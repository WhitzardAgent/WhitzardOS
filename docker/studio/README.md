# Local Studio image

Build from a source checkout after `cd studio-web && npm ci && npm run build`:

```bash
docker build -f docker/studio/Dockerfile -t qitos-studio:local .
```

On Linux, use host networking so Studio's loopback-only listener remains local:

```bash
docker run --rm --network host \
  -v /absolute/agent/project:/workspace \
  -v /absolute/private/config:/private:ro \
  qitos-studio:local --registry /workspace/studio.yaml \
  --credentials /private/credentials.yaml --no-open
```

Open `http://127.0.0.1:8766/` on the host. Docker Desktop host networking
requires the corresponding Docker Desktop setting. Do not publish the Studio
port from a bridge network: Studio intentionally listens on loopback inside
its network namespace. The mounted application must be installed in the image
through a downstream Dockerfile (`FROM qitos-studio:local; RUN pip install ...`),
or the registry must contain only declarative Agents. The application's own
Docker Env requires an available Docker daemon and explicit configuration;
the Studio image does not silently supply one.

## Repository qualification fixture

The full QitOS test suite uses the owned sandbox fixture in
`.github/ci/Dockerfile.sandbox`. Its three local aliases are defined by the
CI workflow; they are fixture names, not claims that historical release image
digests were recovered. When the default Debian endpoint is unavailable, set
the mirror explicitly during the same build:

```bash
docker build --build-arg DEBIAN_MIRROR=mirrors.tuna.tsinghua.edu.cn \
  -f .github/ci/Dockerfile.sandbox -t qitos-ci-sandbox .github/ci
docker tag qitos-ci-sandbox qitos-g5-qualification:20260904
docker tag qitos-ci-sandbox qitos-s3-g4-qualification:pytest-debian
docker tag qitos-ci-sandbox openclaw:staged
pytest -q
```

Run Docker tests serially or with explicitly bounded concurrency, and only
remove containers/images created by this task.
