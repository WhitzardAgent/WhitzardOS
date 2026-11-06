"""Structured engine events for streaming and observability."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import threading
from typing import Any, AsyncIterator, Dict, List, Optional

from .states import RuntimePhase


class EngineEventType(str, Enum):
    STEP_START = "step_start"
    STEP_END = "step_end"
    PHASE_START = "phase_start"
    PHASE_END = "phase_end"
    DECIDE = "decide"
    ACT = "act"
    REDUCE = "reduce"
    CRITIC = "critic"
    CHECK_STOP = "check_stop"
    HANDOFF = "handoff"
    DELEGATE = "delegate"
    FANOUT = "fanout"
    ERROR = "error"
    INTERRUPT = "interrupt"
    RUN_START = "run_start"
    RUN_END = "run_end"
    STEP_STREAM = "step_stream"  # Token-level streaming chunk


@dataclass
class EngineEvent:
    """Structured event emitted by Engine/AsyncEngine during execution."""

    event_type: EngineEventType
    step_id: int = 0
    agent_id: Optional[str] = None
    phase: Optional[RuntimePhase] = None
    ok: bool = True
    payload: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    ts: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "event_type": self.event_type.value,
            "step_id": self.step_id,
            "ok": self.ok,
            "ts": self.ts,
        }
        if self.agent_id is not None:
            d["agent_id"] = self.agent_id
        if self.phase is not None:
            d["phase"] = self.phase.value
        if self.payload:
            d["payload"] = self.payload
        if self.error is not None:
            d["error"] = self.error
        return d


class _ClosingQueue(asyncio.Queue[Optional[EngineEvent]]):
    """Bounded cross-thread ingress with a close signal outside queue capacity."""

    def __init__(self, maxsize: int) -> None:
        super().__init__(maxsize=maxsize)
        self._pending: deque[Optional[EngineEvent]] = deque()
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._scheduled = False
        self._closed = False

    def put_nowait(self, item: Optional[EngineEvent]) -> None:
        with self._lock:
            if self._closed:
                raise asyncio.QueueFull
            if self.qsize() + len(self._pending) >= self.maxsize:
                raise asyncio.QueueFull
            if self._loop is None:
                super().put_nowait(item)
                return
            self._pending.append(item)
            self._schedule_locked()

    def _schedule_locked(self) -> None:
        if self._loop is not None and not self._scheduled:
            self._scheduled = True
            self._loop.call_soon_threadsafe(self._flush)

    def _flush(self) -> None:
        with self._lock:
            self._scheduled = False
            while self._pending and not self.full():
                super().put_nowait(self._pending.popleft())
            if self._closed and self.empty() and not self._pending:
                super().put_nowait(None)

    async def get(self) -> Optional[EngineEvent]:
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._loop is None:
                self._loop = loop
            elif self._loop is not loop:
                raise RuntimeError("event queue belongs to another event loop")
            self._schedule_locked()
        if self._closed and self.empty() and not self._pending:
            return None
        item = await super().get()
        self._flush()
        return item

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._loop is None:
                if self.empty():
                    super().put_nowait(None)
            else:
                self._schedule_locked()


class EventStream:
    """Async-compatible event stream for consuming engine events.

    Usage::

        stream = EventStream()
        engine = Engine(agent, ...)
        # Subscribe before starting
        async for event in stream:
            print(event)

        # Producer side (engine):
        stream.emit(EngineEvent(event_type=EngineEventType.STEP_START, ...))
    """

    def __init__(self) -> None:
        self._queue: _ClosingQueue = _ClosingQueue(maxsize=4096)
        self._subscribers: List[_ClosingQueue] = []
        self._closed = False

    def emit(self, event: EngineEvent) -> None:
        """Emit an event to all subscribers (thread-safe for sync callers)."""
        if self._closed:
            return
        for q in tuple(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    def emit_sync(self, event: EngineEvent) -> None:
        """Emit from a sync context (safe to call from Engine.run)."""
        self.emit(event)

    def close(self) -> None:
        """Signal end of stream."""
        self._closed = True
        for q in tuple(self._subscribers):
            q.close()
        self._queue.close()

    async def __aiter__(self) -> AsyncIterator[EngineEvent]:
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield event

    def subscribe(self) -> asyncio.Queue[Optional[EngineEvent]]:
        """Create a new subscriber queue for fan-out consumption."""
        q = _ClosingQueue(maxsize=1024)
        if self._closed:
            q.close()
        else:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, queue: asyncio.Queue[Optional[EngineEvent]]) -> None:
        if isinstance(queue, _ClosingQueue) and queue in self._subscribers:
            self._subscribers.remove(queue)
            queue.close()


__all__ = ["EngineEvent", "EngineEventType", "EventStream"]
