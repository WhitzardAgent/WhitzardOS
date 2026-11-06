#!/usr/bin/env python3
"""Measure QitOS critical-path cost outside deterministic model/tool calls.

Examples::

    python -m scripts.benchmark_engine_overhead --steps 20 --samples 3
    python -m scripts.benchmark_engine_overhead --steps 1000 --samples 1 --sessions 1,4,16
    python -m scripts.benchmark_engine_overhead --steps 20 --batch-width 4 --delay-ms 2

The report is descriptive, not a release threshold. Each run subtracts the
union of its recorded call intervals, so overlapping tools are not subtracted
more than once from the wall-clock critical path.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import math
import resource
import statistics
import threading
import time
import tracemalloc
from typing import Any

from qitos.checkpoint import InMemoryCheckpointStore
from qitos.core.action import Action, ActionExecutionPolicy
from qitos.core.agent_module import AgentModule
from qitos.core.decision import Decision
from qitos.core.state import StateSchema
from qitos.core.tool import tool
from qitos.core.tool_registry import ToolRegistry
from qitos.engine import Engine, RuntimeBudget
from qitos.engine.runtime import RuntimeComposition


class CallSpans:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.intervals: list[tuple[int, int]] = []
        self.cpu_ns = 0

    def record(self, start: int, end: int, cpu_ns: int) -> None:
        with self._lock:
            self.intervals.append((start, end))
            self.cpu_ns += cpu_ns

    def covered_wall_ns(self) -> int:
        covered = 0
        end = 0
        for start, stop in sorted(self.intervals):
            if start >= end:
                covered += stop - start
                end = stop
            elif stop > end:
                covered += stop - end
                end = stop
        return covered


class CountingStore(InMemoryCheckpointStore):
    def __init__(self) -> None:
        super().__init__()
        self.commits = 0
        self.payload_bytes = 0

    def commit_session_snapshot(self, request: Any) -> Any:
        self.commits += 1
        self.payload_bytes += len(json.dumps(request.payload).encode("utf-8"))
        return super().commit_session_snapshot(request)


@dataclass
class BenchState(StateSchema):
    completed: int = 0


class BenchAgent(AgentModule[BenchState, dict[str, Any], Action]):
    def __init__(self, steps: int, width: int, delay_s: float, spans: CallSpans) -> None:
        registry = ToolRegistry()

        @tool(name="bench_noop", concurrency_safe=True)
        def bench_noop() -> str:
            start = time.perf_counter_ns()
            cpu_start = time.thread_time_ns()
            if delay_s:
                time.sleep(delay_s)
            spans.record(start, time.perf_counter_ns(), time.thread_time_ns() - cpu_start)
            return "ok"

        registry.register(bench_noop)
        super().__init__(tool_registry=registry)
        self.steps = steps
        self.width = width
        self.spans = spans

    def init_state(self, task: str, **kwargs: Any) -> BenchState:
        return BenchState(task=task, max_steps=self.steps + 1)

    def decide(self, state: BenchState, observation: dict[str, Any]) -> Decision[Action]:
        start = time.perf_counter_ns()
        cpu_start = time.thread_time_ns()
        decision = (
            Decision.act([Action(name="bench_noop") for _ in range(self.width)])
            if state.current_step < self.steps
            else Decision.final("done")
        )
        self.spans.record(start, time.perf_counter_ns(), time.thread_time_ns() - cpu_start)
        return decision

    def reduce(
        self, state: BenchState, observation: dict[str, Any], decision: Decision[Action]
    ) -> BenchState:
        if decision.mode == "act":
            state.completed += 1
        else:
            state.final_result = decision.final_answer
        return state


def one_run(mode: str, steps: int, width: int, delay_s: float) -> dict[str, int]:
    spans = CallSpans()
    agent = BenchAgent(steps, width, delay_s, spans)
    start = time.perf_counter_ns()
    store = CountingStore() if mode == "session" else None
    if mode == "direct":
        state = agent.init_state("benchmark")
        tool_impl = agent.tool_registry.get("bench_noop")
        for step in range(steps + 1):
            state.current_step = step
            decision = agent.decide(state, {})
            for action in decision.actions:
                tool_impl.execute(action.args, None)
            state = agent.reduce(state, {}, decision)
    else:
        policy = ActionExecutionPolicy(
            mode="parallel" if width > 1 else "serial",
            max_concurrency=width,
        )
        runtime = RuntimeComposition(
            checkpoint_store=store
        )
        engine = Engine(
            agent, runtime=runtime, budget=RuntimeBudget(max_steps=steps + 1),
            action_execution_policy=policy,
        )
        if mode == "session":
            result = engine.session("benchmark").run()
        else:
            result = engine.run("benchmark")
        state = result.state
        runtime.close_tool_worker_pool()
    elapsed = time.perf_counter_ns() - start
    if state.final_result != "done" or state.completed != steps:
        raise RuntimeError(f"incomplete benchmark run: {mode}, {state.completed}/{steps}")
    call_wall = spans.covered_wall_ns()
    return {
        "wall_ns": elapsed,
        "call_wall_union_ns": call_wall,
        "non_call_wall_ns": max(0, elapsed - call_wall),
        "call_cpu_ns": spans.cpu_ns,
        "call_count": len(spans.intervals),
        "checkpoint_commits": store.commits if store is not None else 0,
        "checkpoint_payload_bytes": store.payload_bytes if store is not None else 0,
    }


def percentile(values: list[int], fraction: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def cohort(
    mode: str, count: int, steps: int, width: int, delay_s: float,
    trace_memory: bool,
) -> dict[str, Any]:
    cpu_start = time.process_time_ns()
    if trace_memory:
        tracemalloc.start()
    monitor_stop = threading.Event()
    peak_threads = threading.active_count()

    def monitor_threads() -> None:
        nonlocal peak_threads
        while not monitor_stop.wait(0.002):
            peak_threads = max(peak_threads, threading.active_count() - 1)

    monitor = threading.Thread(target=monitor_threads, daemon=True)
    monitor.start()
    start = time.perf_counter_ns()
    try:
        if count == 1:
            runs = [one_run(mode, steps, width, delay_s)]
        else:
            with ThreadPoolExecutor(max_workers=count) as pool:
                runs = list(pool.map(
                    lambda _: one_run(mode, steps, width, delay_s), range(count)
                ))
    finally:
        monitor_stop.set()
        monitor.join()
    wall_ns = time.perf_counter_ns() - start
    if trace_memory:
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    else:
        peak_bytes = None
    cpu_ns = time.process_time_ns() - cpu_start
    overheads = [run["non_call_wall_ns"] for run in runs]
    return {
        "mode": mode,
        "sessions": count,
        "steps_per_run": steps,
        "batch_width": width,
        "wall_ms": round(wall_ns / 1e6, 3),
        "non_call_wall_p50_ms": round(statistics.median(overheads) / 1e6, 3),
        "non_call_wall_p95_ms": round(percentile(overheads, 0.95) / 1e6, 3),
        "non_call_cpu_ms": round(max(0, cpu_ns - sum(run["call_cpu_ns"] for run in runs)) / 1e6, 3),
        "peak_tracemalloc_bytes": peak_bytes,
        "memory_tracing": trace_memory,
        "peak_threads": peak_threads,
        "process_peak_rss_native_units": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "call_count": sum(run["call_count"] for run in runs),
        "checkpoint_commits": sum(run["checkpoint_commits"] for run in runs),
        "checkpoint_payload_bytes": sum(run["checkpoint_payload_bytes"] for run in runs),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--sessions", default="1,4,16")
    parser.add_argument("--batch-width", type=int, default=1)
    parser.add_argument("--delay-ms", type=float, default=0.0)
    parser.add_argument("--no-trace-memory", action="store_true")
    args = parser.parse_args()
    if args.steps < 1 or args.samples < 1 or args.batch_width < 1 or args.delay_ms < 0:
        parser.error("steps, samples and batch-width must be positive; delay-ms nonnegative")
    counts = [int(value) for value in args.sessions.split(",")]
    if not counts or any(value < 1 for value in counts):
        parser.error("sessions must be comma-separated positive integers")
    rows = []
    for mode in ("direct", "engine", "session"):
        # Exclude one-time imports and provider/registry initialization from
        # the steady-state per-step comparison.
        one_run(mode, min(args.steps, 2), args.batch_width, args.delay_ms / 1000)
        for count in counts:
            samples = [cohort(
                mode, count, args.steps, args.batch_width, args.delay_ms / 1000,
                not args.no_trace_memory,
            ) for _ in range(args.samples)]
            row = dict(samples[-1])
            for key in ("wall_ms", "non_call_wall_p50_ms", "non_call_wall_p95_ms", "non_call_cpu_ms"):
                row[key] = round(statistics.median(sample[key] for sample in samples), 3)
            row["samples"] = args.samples
            rows.append(row)
    print(json.dumps({"schema": "qitos.engine_overhead.v1", "results": rows}, indent=2))


if __name__ == "__main__":
    main()
