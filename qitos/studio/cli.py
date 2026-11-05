"""Local Studio launcher."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .http import serve
from .registry import RegistryError, load_registry
from .service import StudioService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qit studio", description="Start the local QitOS Studio")
    parser.add_argument("--registry", required=True, help="Local studio.yaml agent allowlist")
    parser.add_argument("--state", help="Studio launch index path")
    parser.add_argument("--credentials", default="~/.config/qitos/credentials.yaml")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-open", action="store_true", help="Do not open a browser")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    if args.port < 0 or args.port > 65535:
        parser.error("port must be in 0..65535")
    try:
        registry = Path(args.registry).expanduser().resolve()
        agents = load_registry(registry)
    except RegistryError as exc:
        print(f"qit studio: {exc}", file=sys.stderr)
        return 2
    state = Path(args.state).expanduser() if args.state else registry.parent / ".qitos" / "studio.sqlite3"
    static_root = Path(__file__).parent / "static"
    if not (static_root / "index.html").is_file():
        print("qit studio: studio_assets_missing; build studio-web before starting", file=sys.stderr)
        return 2
    with StudioService(agents, state_path=state, credential_path=args.credentials) as service:
        serve(service, static_root, port=args.port, open_browser=not args.no_open)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
