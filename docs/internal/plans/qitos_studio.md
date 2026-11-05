# QitOS Studio implementation plan

Status: V1 implemented; the Codex-oriented V2 is partially implemented on
`codex/qitos-studio`. Runtime control, approval, resource-body, and live-model
qualification gates remain open. Approved design: the QitOS Studio plans in
the 2026-11-05 and 2026-11-06 conversations.

## Boundaries

- Studio is a local, optional edge client. `Engine`, `Session`, the canonical Trajectory, and qita retain their existing ownership.
- A registry file explicitly names launchable agents. Web requests choose an ID and task, never a config path or Python import.
- A browser disconnect does not end a run. Restart may inspect persisted sessions and manually restore paused sessions; it does not automatically resume an in-flight run.
- Default reads are redacted. The first release does not expose live pause, steering, approval, fork, remote binding, or arbitrary artifact bodies.

## Deliverables

- [x] Root `DESIGN.md` with QitOS-specific tokens, page states, and responsive layout.
- [x] Registry loader and local service for launch, history, Session inspection, bounded Trajectory pages, SSE, and manual restore.
- [x] Loopback-only HTTP entrypoint with cookie token and Origin protection for mutation.
- [x] TypeScript/React app: agent home, task composer, session view, inspector, responsive states.
- [x] Wheel asset packaging; installed declarative and custom-agent consumers; Python/JS/browser checks; EN/zh docs, README, CHANGELOG.

## Verification record

- Studio, architecture, qita, and config-Trajectory regressions: 50 passed.
- Frontend component tests: 4 passed; production TypeScript/Vite build passed.
- Studio flake8 and mypy passed; required kernel flake8 and mypy passed.
- Wheel and sdist built, both passed `twine check`; a clean virtualenv imported the packaged assets and executed two installed Agent shapes, reopened their history, and read both Trajectories.
- A real persisted paused Session was manually restored by a new StudioService and received a new run ID. Browser checks covered task creation and failure, real completed Sessions, inspector, desktop/mobile layouts, themes, drawer interaction, focus return, and disconnected state.
- The prescribed unfiltered `pytest -q` was attempted. Unavailable local Docker qualification images caused existing Docker tests to fail and stall; the run was interrupted after 1,811 passes and 54 skips. A second run excluding e2e and the owned-Docker file reached 1,839 passes and 4 skips before two more Docker sandbox tests failed for the same missing images. No Studio failure remained.

## Review focus

1. Registry path traversal or browser-supplied imports must not execute.
2. A stale worker may not claim a completed Session can be resumed.
3. SSE reconnect must backfill from durable Trajectory sequence.
4. A missing or historical trace must show `unknown`, not a fabricated empty success.
5. Shutdown and failed composition must release owned resources and record a typed outcome.

## V2 implementation ledger (2026-11-06)

Target: the approved Codex-oriented general Agent GUI plan. The existing V1
implementation is the base. Public execution semantics remain in Session and
Trajectory; Studio stores presentation links and local metadata only.

- [x] Read existing runtime/UI and fixed the principal limitation: one launch is
  one turn, and an optional application adapter may make a later turn as a
  **linked new Session**. Legacy launches migrate to one-turn conversations.
- [x] Added operator-only adapter loading, bounded conversation/history pages,
  run identity history, metadata controls, and capability discovery.
- [x] Add tests for migration, continuation, pagination, and retained HTTP authorization.
- [x] Implement conversation-first bilingual UI and browser checks for task failure,
  desktop/narrow layout, and language switch. Screenshots retained beside this plan.
- [x] Add standalone installable coding reference; existing declarative and
  non-coding factory examples continue through the same registry/GUI.
- [x] Build the Docker qualification fixture, Python coding image, and pinned
  Node 24 image; run the full test suite, both offline coding tool chains, and
  a clean wheel install.

### V2 verification and remaining gates

- `pytest -q`: **3926 passed, 52 skipped**. The CI-defined qualification
  aliases were built from `.github/ci/Dockerfile.sandbox` using the documented
  HTTPS mirror, then used by the existing Docker tests. This is a local fixture
  build, not a claim that an older published image was recovered.
- Python coding reference: its dedicated image
  `qitos-studio-coding-python:local` passed the real Docker tool-chain test
  (`read_file`, `edit_file`, and `run_test`), including persisted Trajectory.
- TypeScript coding reference: the Node 24.11.0 image was built from the
  official checksum-pinned distribution. A deterministic Studio run read the
  project, repaired its existing test failure, added a cross-file feature and
  test, then repaired the new test failure. Its four `npm test` return codes
  were `[1, 0, 1, 0]`; the persisted Session completed. This checks the tool
  and trace chain, not model judgment.
- Frontend: five component tests and Vite production build passed. Desktop and
  narrow-screen browser checks covered Chinese/English, dark/light, failure,
  inspector, navigation, and reconnect. Fixed screenshots are in
  `studio_visual/`.
- Kernel/Studio flake8 and mypy passed. A clean-source wheel passed `twine
  check`, installed into a fresh virtual environment, and contained only the
  current versioned CSS and JS assets. The Studio container image served HTTP
  200 and contained those same assets.
- Runtime V5-05 durable control and approval receipts are still absent.
  Consequently the Studio API and GUI do not claim working pause, cancel,
  approval, or rejection. Authorized file and diff body APIs are also absent;
  no file or diff contents are guessed from tool text.
- No real-model coding task was qualified: this checkout has no explicit model
  endpoint and credential reference for that gate. The Python Docker test is a
  deterministic tool-chain check, not a model-quality evaluation.

Ruling: a terminal Session is not steered or silently reopened. The adapter
creates a linked Session with an explicit continuation task; runtime identities
stay distinct. This provides honest conversation semantics while the V5-05
durable control/approval channel is unfinished. Live pause, cancel, and approval
must not appear as enabled operations until that channel can prove receipts and
authorization across process loss.

Ruling: the CI sandbox Dockerfile is the reproducible local fixture source.
Its alias tags are defined by CI; they are not claimed as historical release
image identities. The standalone `tests/fixtures/s4/g5/Dockerfile.qualification`
has a `node` user dependency not supplied by the CI fixture and is not used
for this local test fixture.
