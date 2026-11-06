# Engine execution overhead: implementation and qualification

Status: first local correctness and hot-path changes implemented on
`codex/qitos-studio`; full lifecycle and process-isolation qualification remains
open. This plan keeps the single `AgentModule + Engine` step loop and changes
only the execution resources around it.

## Contract and delivered changes

1. One Engine or AsyncEngine instance admits one active run. Admission happens
   before resetting run state or installing stream hooks and callbacks. A
   cancelled async waiter does not release admission until its sync worker
   actually finishes. Independent Engines may run concurrently.
2. `EventStream` has bounded thread-to-loop ingress. A full data queue cannot
   consume the close signal; accepted events drain before termination. A
   subscriber can be removed with `unsubscribe`.
3. Ordinary `ExchangeLog` appends use a validated-prefix index. Public items
   and persistence input remain isolated and fully checked on construction;
   a normal append validates only its new fact. The last item and its exchange
   ID have narrow readers. Session skips prior-snapshot loading when there is
   no current steering receipt to compare.
4. A parallel tool segment submits at most `max_concurrency` in-flight slots.
   Timed blocking tools share a `ToolWorkerPool` with no waiting queue. A
   timed-out worker retains its capacity until its Future completes. An
   overloaded attempt receives `tool_worker_capacity` with `executed: false`.
   Context variables cross this worker boundary. `RuntimeComposition` can
   inject a host-owned pool or lazily create its own; composition cleanup
   reports workers still running.

## Reproducible cost baseline

Run `python -m scripts.benchmark_engine_overhead --steps 1000 --samples 1
--sessions 1,4,16 --no-trace-memory` for critical-path timing. Omit
`--no-trace-memory` to measure Python allocation peaks separately. Use
`--batch-width 4 --delay-ms 2` for overlapping tool calls. The deterministic
agent has no real model I/O; its `decide` and tool intervals are instrumented.
The non-call wall metric subtracts their interval union **per run**, never the
sum of overlapping calls from the cohort wall time. `non_call_cpu_ms` is
process CPU minus instrumented call CPU and still includes benchmark harness
and coordination. RSS is the process high-water mark in platform-native units,
not a per-run delta. CPU/GIL contention makes 4/16-session wall values
environment-dependent; use same-host before/after comparisons.

2026-11-06 local macOS, Python 3.12, warmed runs, 1000 steps per run, no
`tracemalloc` for the timing table (one sample per cohort):

| Path | Concurrent runs | Non-call wall p50 / p95 | Non-call CPU, cohort | Checkpoint payload bytes |
| --- | ---: | ---: | ---: | ---: |
| Direct hooks/tools | 1 | 3.5 / 3.5 ms | 3.8 ms | 0 |
| Engine | 1 | 306 / 306 ms | 307 ms | 0 |
| Durable Session | 1 | 317 / 317 ms | 318 ms | 84,257 |
| Engine | 4 | 1,142 / 1,270 ms | 1,322 ms | 0 |
| Durable Session | 4 | 1,370 / 1,413 ms | 1,461 ms | 337,044 |
| Engine | 16 | 4,302 / 4,888 ms | 5,499 ms | 0 |
| Durable Session | 16 | 5,197 / 5,847 ms | 5,955 ms | 1,348,128 |

The default Session policy committed nine snapshots per 1000-step run, so
these figures do not represent per-step durable commits. A memory-traced run
reported approximately 17 MiB of peak Python allocations for one Engine run
and 17 MiB for one Session run; 16 concurrent runs reached 265/274 MiB.
`tracemalloc` materially increased measured wall time, so the timing table
uses a separate untraced run. These are baselines, not proof of a speedup.
An append regression asserts exactly 1000 user-item validations for 1000
ordinary messages, replacing the earlier 10,100-call observed pattern.

## Remaining qualification and design gates

- **Run context:** the instance admission guard prevents overlap, but mutable
  hooks and callback fields are still instance scoped. A later public API
  revision should pass a per-run context through hooks, model streaming,
  cancellation and resource handles. Do this with migration tests for all
  execution entry points rather than a second loop.
- **Parallel resource:** segment coordinator pools still exist per segment.
  They now have a bounded submit window, but shared host capacity for all
  parallel coordinators and WorkScheduler child workers is not yet unified.
  A parent waiting on a child must not hold the child's only execution slot.
- **Timeout lifecycle:** a Python thread cannot be forcibly killed. The pool
  reports capacity and late completion, but process-level hard-stop and
  unknown external effect reconciliation remain Env/Session work. An async
  coroutine initiated from an already running event loop uses the same pool;
  native async steps still need the separate AnyIO comparison experiment.
- **Data plane:** full Session snapshot serialization, Docker Base64 workspace
  capture, Trajectory full-byte verification and SSE thread-per-client cost
  remain candidates for measurement before storage/protocol redesign.
- **Release gate:** cross-process restore/fault injection, full `pytest -q`,
  public API source binding, wheel install, Docker capacity tests and
  same-load before/after comparison are required before claiming the whole
  architecture plan complete.

## Verification record

Targeted Engine/core/checkpoint/tracing/architecture tests: 592 passed after
the first implementation slice; later pool and benchmark edits require a fresh
run. The added capacity, close, context-propagation, full-queue and overlap
regressions pass. Stable-surface flake8 and mypy pass. The public API source
binding test rejects uncommitted changes to linked implementation files; it
must be updated to a reviewed source commit and the generated EN/zh reference
pages synchronized before release, not weakened.
