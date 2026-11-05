#!/bin/sh
set -eu

case "$(docker info --format '{{.Architecture}}')" in
    aarch64|arm64) node_arch=arm64 ;;
    x86_64|amd64) node_arch=x64 ;;
    *) echo 'Unsupported Docker architecture' >&2; exit 1 ;;
esac

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_dir=$(dirname "$script_dir")
download_dir=$(mktemp -d)
trap 'rm -rf "$download_dir"' EXIT HUP INT TERM
curl --fail --location --silent --show-error --retry 3 \
    "https://nodejs.org/dist/v24.11.0/node-v24.11.0-linux-${node_arch}.tar.xz" \
    --output "$download_dir/node.tar.xz"
docker build --build-context "node-dist=$download_dir" \
    -f "$script_dir/Dockerfile.node" -t qitos-studio-coding-node:local "$project_dir"
