# Coding Agent exercise projects

These tiny projects contain intentional failures. They are fixtures, not
completed Agent results. The Python project uses `python -m pytest -q`; the
TypeScript project uses Node.js 24+ built-in TypeScript type stripping and
`npm test` with no external dependencies.

Exercise sequence for each project:

1. Ask the coding Agent to inspect the project and fix the failing test.
2. Ask it to add a related cross-file feature and tests.
3. Introduce a new failing requirement, then ask it to investigate and repair.
4. Continue the Studio conversation with one more requirement, verifying the
   new turn has a distinct runtime Session and saved run/trace identities.

Set each project's workspace and an appropriate Docker image in the Agent's
`agent.yaml`; these are application decisions. The checked-in reference config
uses a Python image and cannot run the TypeScript project unchanged. Actual
model success and all failures/retries must be recorded separately; these
fixtures do not imply that live acceptance has passed.
