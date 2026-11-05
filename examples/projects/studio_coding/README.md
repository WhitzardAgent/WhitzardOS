# Studio coding reference application

This is an independently installable `AgentModule` application. Studio loads
its factory and optional adapter from the operator's local registry. Its
workspace, Docker image, model, budget and permission policy live in
`agent.yaml`, not in the Studio UI. The checked-in model endpoint is a
placeholder; supply an explicit model configuration and `CredentialRef` before
running a live task. The adapter creates a linked new Session for follow-up
requests; it does not reopen a completed runtime Session.
The registry exposes two application policies through the same GUI: `coding`
can edit and run commands, while `review` registers only read/search/test tools.
Both are configured in local YAML; Studio does not inspect their IDs to decide
which controls to show. Neither policy provides a durable approval workflow.
Small intentionally failing [Python and TypeScript exercise projects](demo/README.md)
are included for live task evaluation; their presence is not a model success
claim.

```bash
docker build -f docker/Dockerfile.python -t qitos-studio-coding-python:local .
sh docker/build_node.sh
python -m pip install -e .
qit studio --registry studio.yaml --credentials /path/to/credentials.yaml
```

Start Studio from this directory so relative workspace and persistence paths
resolve here. `coding` and `review` point to `demo/python` and the separately
built Python test image. `coding_ts` points to `demo/typescript` and uses
the separately built Node 24.11.0 image for Node's built-in TypeScript type
stripping. The build script downloads the official Node distribution and its
Dockerfile checks the architecture-specific SHA-256 digest before installation.
After installing this package,
`python demo/offline_typescript_check.py` runs a deterministic failure/fix,
feature addition, and second failure/fix sequence through Studio and real
Docker tools. It does not evaluate a live model. The default
configuration has no browser approval surface: durable approval recovery is
not supported by the current Session runtime. Do not treat this reference as
a validated Codex-equivalent coding agent; live model and Docker qualification
are separate acceptance gates.
