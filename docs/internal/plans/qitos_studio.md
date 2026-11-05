# QitOS Studio implementation plan

Status: implemented on `codex/qitos-studio`. Approved design: the QitOS Studio plan in the 2026-11-05 conversation.

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
