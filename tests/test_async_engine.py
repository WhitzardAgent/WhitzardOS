"""Tests for AsyncEngine, EventStream, and async model adapters."""

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any

import pytest

from qitos import (
    AsyncEngine,
    AgentModule,
    Decision,
    Action,
    Engine,
    EngineEvent,
    EngineEventType,
    EventStream,
    StateSchema,
    ToolRegistry,
    tool,
)
from qitos.engine import RuntimeBudget
from qitos.checkpoint import CheckpointConfig, CheckpointId
from qitos.engine.states import RuntimePhase


# --- Minimal test fixtures ---


@dataclass
class DemoState(StateSchema):
    logs: list[str] = field(default_factory=list)


class DemoAgent(AgentModule[DemoState, dict[str, Any], Action]):
    def __init__(self, answer: str = "42"):
        registry = ToolRegistry()

        @tool(name="add")
        def add(a: int, b: int) -> int:
            return a + b

        registry.register(add)
        self._answer = answer
        super().__init__(tool_registry=registry)

    def init_state(self, task: str, **kwargs: Any) -> DemoState:
        return DemoState(task=task, max_steps=3)

    def decide(self, state: DemoState, observation: dict[str, Any]) -> Decision[Action]:
        if state.current_step == 0:
            return Decision.act(
                actions=[Action(name="add", args={"a": 1, "b": 2})],
                rationale="use tool",
            )
        return Decision.final(self._answer)

    def reduce(
        self,
        state: DemoState,
        observation: dict[str, Any],
        decision: Decision[Action],
    ) -> DemoState:
        return state


def test_engine_rejects_overlapping_run_before_reset(monkeypatch):
    engine = Engine(DemoAgent())
    entered = threading.Event()
    release = threading.Event()

    def blocked(task, **kwargs):
        entered.set()
        assert release.wait(timeout=3)

    monkeypatch.setattr(engine, "_run_impl", blocked)
    worker = threading.Thread(target=engine.run, args=("first",))
    worker.start()
    try:
        assert entered.wait(timeout=3)
        with pytest.raises(RuntimeError, match="active run"):
            engine.run("second")
        with pytest.raises(RuntimeError, match="active run"):
            engine.resume_from_checkpoint(CheckpointConfig(
                thread_id="old", checkpoint_id=CheckpointId("missing"),
            ))
    finally:
        release.set()
        worker.join(timeout=3)
    assert not worker.is_alive()


# --- EventStream tests ---


class TestEventStream:
    def test_full_queue_closes_after_drain(self):
        async def consume():
            stream = EventStream()
            event = EngineEvent(event_type=EngineEventType.STEP_START)
            for _ in range(4096):
                stream.emit(event)
            stream.close()
            seen = 0
            async for _ in stream:
                seen += 1
            assert seen == 4096

        asyncio.run(asyncio.wait_for(consume(), timeout=3))

    def test_worker_thread_emission_wakes_waiting_consumer(self):
        async def consume():
            stream = EventStream()
            async def read():
                return [event async for event in stream]
            reader = asyncio.create_task(read())
            await asyncio.sleep(0)
            def produce():
                stream.emit_sync(EngineEvent(event_type=EngineEventType.RUN_START))
                stream.close()
            await asyncio.to_thread(produce)
            assert len(await reader) == 1

        asyncio.run(asyncio.wait_for(consume(), timeout=3))

    def test_emit_and_iterate(self):
        stream = EventStream()
        events = []

        async def _consume():
            async for event in stream:
                events.append(event)

        loop = asyncio.new_event_loop()
        consume_task = loop.create_task(_consume())

        stream.emit(EngineEvent(event_type=EngineEventType.RUN_START, payload={"task": "test"}))
        stream.emit(EngineEvent(event_type=EngineEventType.STEP_START, step_id=0))
        stream.close()

        loop.run_until_complete(consume_task)
        loop.close()

        assert len(events) == 2
        assert events[0].event_type == EngineEventType.RUN_START
        assert events[1].step_id == 0

    def test_to_dict(self):
        event = EngineEvent(
            event_type=EngineEventType.DECIDE,
            step_id=1,
            agent_id="coder",
            phase=RuntimePhase.DECIDE,
            payload={"mode": "act"},
        )
        d = event.to_dict()
        assert d["event_type"] == "decide"
        assert d["step_id"] == 1
        assert d["agent_id"] == "coder"
        assert d["phase"] == "DECIDE"
        assert d["payload"]["mode"] == "act"

    def test_subscribe_fanout(self):
        stream = EventStream()
        q1 = stream.subscribe()
        q2 = stream.subscribe()

        stream.emit(EngineEvent(event_type=EngineEventType.RUN_START))
        stream.close()

        # Both queues should receive the event + close sentinel
        loop = asyncio.new_event_loop()
        e1 = loop.run_until_complete(q1.get())
        e2 = loop.run_until_complete(q2.get())
        loop.close()

        assert e1.event_type == EngineEventType.RUN_START
        assert e2.event_type == EngineEventType.RUN_START

    def test_close_signal(self):
        stream = EventStream()
        events = []

        async def _consume():
            async for event in stream:
                events.append(event)

        loop = asyncio.new_event_loop()
        task = loop.create_task(_consume())
        stream.close()
        loop.run_until_complete(task)
        loop.close()
        assert events == []


# --- EngineEventType tests ---


class TestEngineEventType:
    def test_all_types(self):
        expected = {
            "step_start", "step_end", "phase_start", "phase_end",
            "decide", "act", "reduce", "critic", "check_stop",
            "handoff", "delegate", "fanout", "error",
            "run_start", "run_end", "step_stream",
            "interrupt",
        }
        actual = {t.value for t in EngineEventType}
        assert actual == expected


# --- AsyncEngine tests ---


class TestAsyncEngine:
    def test_token_stream_overlap_does_not_replace_active_callback(self, monkeypatch):
        async def check():
            engine = AsyncEngine(DemoAgent())
            entered = threading.Event()
            release = threading.Event()

            def blocked(task, **kwargs):
                entered.set()
                assert release.wait(timeout=3)

            monkeypatch.setattr(engine.engine, "_run_impl", blocked)
            first = engine.arun_stream("first")
            first_read = asyncio.create_task(first.__anext__())
            assert await asyncio.to_thread(entered.wait, 3)
            active_callback = engine.engine.stream_callback
            second = engine.arun_stream_tokens("second")
            try:
                with pytest.raises(RuntimeError, match="active run"):
                    await second.__anext__()
                with pytest.raises(RuntimeError, match="active run"):
                    engine.run("second")
                assert engine.engine.stream_callback is active_callback
            finally:
                release.set()
                await second.aclose()
                with pytest.raises(StopAsyncIteration):
                    await first_read
                await first.aclose()

        asyncio.run(check())

    def test_arun_returns_result(self):
        agent = DemoAgent(answer="hello world")
        engine = AsyncEngine(agent=agent, budget=RuntimeBudget(max_steps=5))
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(engine.arun("test task"))
        loop.close()

        assert result.step_count >= 1
        assert result.state.final_result == "hello world"

    def test_arun_stream_yields_events(self):
        agent = DemoAgent(answer="stream test")
        engine = AsyncEngine(agent=agent, budget=RuntimeBudget(max_steps=5))
        events = []

        async def _run():
            async for event in engine.arun_stream("test task"):
                events.append(event)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(_run())
        loop.close()

        types = [e.event_type for e in events]
        assert EngineEventType.RUN_START in types
        assert EngineEventType.RUN_END in types
        assert EngineEventType.STEP_START in types or EngineEventType.STEP_END in types

    def test_sync_run_delegates(self):
        agent = DemoAgent(answer="sync test")
        engine = AsyncEngine(agent=agent, budget=RuntimeBudget(max_steps=5))
        result = engine.run("test task")
        assert result.state.final_result == "sync test"

    def test_engine_property(self):
        agent = DemoAgent()
        engine = AsyncEngine(agent=agent, budget=RuntimeBudget(max_steps=5))
        assert isinstance(engine.engine, Engine)
        assert engine.agent is engine.engine.agent


# --- Async model tests ---


class TestAsyncOpenAICompatibleModel:
    def test_import(self):
        from qitos.models import AsyncOpenAICompatibleModel, AsyncOpenAIModel
        assert AsyncOpenAICompatibleModel is not None
        assert AsyncOpenAIModel is not None

    def test_factory_registration(self):
        from qitos.models import ModelFactory
        assert "async-openai-compatible" in ModelFactory._providers
        assert "async-openai" in ModelFactory._providers

    def test_async_model_base(self):
        from qitos.models import AsyncModel

        class _TestAsyncModel(AsyncModel):
            async def _acall_api(self, messages):
                return "async response"

        model = _TestAsyncModel(model="test")
        # Sync call should work via asyncio.run fallback
        result = model([{"role": "user", "content": "test"}])
        assert result == "async response"

        # Async call
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(model.acall([{"role": "user", "content": "test"}]))
        loop.close()
        assert result == "async response"
