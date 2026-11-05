# Build from a checkout containing the committed Studio Web assets.
FROM python:3.12-slim-bookworm
WORKDIR /opt/qitos
COPY pyproject.toml setup.py README.md MANIFEST.in LICENSE ./
COPY qitos ./qitos
RUN python -m pip install --no-cache-dir .
RUN useradd --uid 10001 --create-home studio
USER studio
WORKDIR /workspace
ENTRYPOINT ["qit", "studio"]
CMD ["--registry", "/workspace/studio.yaml", "--no-open"]
