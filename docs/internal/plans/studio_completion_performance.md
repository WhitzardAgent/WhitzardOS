# Studio completion and performance implementation plan

Goal: complete the approved Studio product through runtime-owned interaction,
authorized resources, bounded observation, and measured coding qualification.
Architecture: Session remains mutation authority; Trajectory remains fact authority.
Studio owns presentation and admission limits only. Python, SQLite, React/TypeScript.
Spec: `qitos_studio.md`, `../../v5/05-interactive-session-and-sandbox.md`.

## Execution order and acceptance

1. Observation cost (implemented, validation running): `qitos/tracing/paging.py` must extend its
   disposable index after validating the old prefix, decoding only appended
   frames and selected page frames. Preserve full byte verification, cursor
   binding, rollback on partial append, and replacement/truncation rejection.
   Studio owns a bounded reader cache, closes eviction/shutdown resources,
   and limits accepted outstanding tasks. Tests count work, not wall time.
2. History cost (implemented for sidebar and capability lookup): capability queries select the latest turn with indexed LIMIT 1.
   Added an index for sidebar ordering and checkpoint-free HTTP sidebar summaries. Avoid full history materialization for
   operations that need only one row. Keep continuation history semantics.
3. Interaction runtime: define operation/request identity, exact args digest,
   permission scope, expiry, owner generation, and durable receipts in existing
   core/Session/checkpoint contracts. Integrate permission validation after
   interception. Test duplicate, stale owner, changed args, process loss before
   and after commit before wiring HTTP controls. This is implementation work,
   not a reason to defer the approved user requirement indefinitely.
4. Authorized resources: application supplies opaque resource references tied
   to Session/run and privacy view. Read byte ranges through runtime-owned
   artifact access; reject path/link escape and stale references. Coding app
   supplies retained workspace and diff resources; Studio renders by type.
5. Product polish: preserve loaded turns during refresh; latest-turn entry,
   virtualized histories, explicit event pagination, bounded browser retention,
   debounce search, abort obsolete requests, restore scroll/focus, localize
   errors. Browser tests cover long conversations and reconnect after restart.
6. Qualification: both coding policies plus a non-coding approval consumer;
   deterministic failure/fix and restart tests, then live model Python/TS tasks
   with explicit credential references. No endpoint or secret is inferred.

## Audit findings and risks

- Confirmed: Studio creates an entire disposable journal index per event page;
  append refresh also decodes all old frames. This amplifies JSON decoding and
  SQLite index writes with history length. Fix first; hashing remains O(bytes)
  by contract and must be reported separately from decoding work.
- Confirmed: every sidebar row invokes full checkpoint JSON load and integrity
  verification; polling repeats this. A future head-only read model needs a
  verified association with immutable snapshot metadata, not a TTL that grants
  stale restore/control authority. Measure before changing checkpoint schema.
- Confirmed: completed Future objects remain in the supervisor forever, and
  ThreadPoolExecutor has an unbounded queue. Remove completed handles and reject
  overload before inserting a launch row.
- Confirmed: capability discovery loads every turn just to inspect the latest.
- Confirmed: React auto-drains all event pages and accumulates all records;
  the four-second turn refresh discards manually loaded older pages. These are
  open product/performance defects; virtualizing DOM alone does not bound data.
- Checkpoint concern (not benchmarked): complete conversation/state snapshots
  plus previous-snapshot reads on commits can produce cumulative quadratic
  bytes over a long run. Preserve atomic head/generation and integrity; evaluate
  content-addressed immutable components and explicit retention before redesign.
- SSE currently owns one thread per connection and repeatedly hashes history.
  Evaluate shared per-source fan-out with durable cursor backfill after fixing
  reader ownership; ephemeral notifications must never replace persisted facts.

## Review gates

Corrupt prefix plus valid append; incomplete suffix rollback; eviction during
read; service shutdown racing HTTP; task rejection leaves no launch row; stale
owner never gains authority from cached UI state. Full pytest, kernel/changed
static checks, frontend build/tests and clean wheel validation remain required.

## Measured regression evidence

A 259-record journal followed by one appended record previously decoded 261
records on the next one-record page. The regression now requires exactly two
decodes (index new frame, read selected frame) and six new index entries. The
existing 10,000/100,000-record workload and integrity/export tests pass. This is
a work-count result, not a wall-clock speedup claim. Sidebar summary tests require
zero checkpoint inspections; detail and resume retain their current checks.

Coding continuation review: the adapter links task context but cannot itself transfer a private staged workspace. Qualify retained-workspace transfer or explicit publication before promising that later turns see prior edits. This is a correctness gate, independent of model quality.

## Interaction contract design to implement next

Use existing Session snapshot components and tool-slot terminal receipts. A
request contains operation_id, session_id, run_id, work-item owner generation,
request kind, created/expiry time, and authenticated controller authority. CAS
against the checkpoint head guards persistence; head snapshot generation is
not interchangeable with the work item's owner generation (the former changes
at normal checkpoints). Acceptance must record the owner binding explicitly.

Approval additionally binds call/attempt ID, final validated argument digest,
tool specification digest and permission scope. Store the request before
returning waiting_input. Decision states are pending, approved, denied, expired
or superseded; execution state is recorded separately by existing tool slots.
A durable decision authorizes only the exact validated attempt. A committed
terminal slot cannot execute again; process loss with an uncertain external
effect must remain unknown, not be retried under the old approval.

Implementation seams:
- `qitos/core`: serializable request/receipt and snapshot component definitions;
  no UI or transport imports.
- `qitos/checkpoint`: atomic request/decision updates under existing Session
  ownership and snapshot integrity, without a parallel Studio permission DB.
- `qitos/engine/action_executor.py`: resolve approval after final validation and
  before invocation; recheck exact binding after any interceptor transformation.
- `qitos/engine/session_runtime.py`: inspect pending requests, resolve a decision,
  and restore interrupted attempts through the same executor; preserve committed
  slots. Pause/cancel receipt distinguishes requested from quiescent/terminal.
- `qitos/studio`: authenticate local transport, forward commands, read receipts;
  enable buttons only from runtime responses. Browser close has no cancel effect.

Required executable gate before GUI exposure: two-process approval restore,
duplicate decisions, expiry, denial, changed arguments/spec/scope, stale owner,
and crash after effect commit. Add a non-coding tool requiring approval to prove
that the contract and cards do not depend on coding tool names.

Workspace continuation is a separate gate: carry an authorized retained
workspace artifact into the application's next Session or fork strategy.
Do not silently publish files back to the host to simulate continuity. Diff
views compare explicit source/output versions and expose application-approved
paths only; symlink/hardlink/traversal tests precede resource endpoints.
