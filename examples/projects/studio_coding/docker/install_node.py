"""Install a checksum-pinned official Node distribution in the demo image."""

from hashlib import sha256
from pathlib import Path
import platform
import tarfile


VERSION = "24.11.0"
CHECKSUMS = {
    "aarch64": ("arm64", "33a6673b2c7bffeae9deec7f9f8b31aad9119b08f13d49b2ca3ee3bebfe8260f"),
    "x86_64": ("x64", "46da9a098973ab7ba4fca76945581ecb2eaf468de347173897044382f10e0a0a"),
}
arch, expected = CHECKSUMS[platform.machine()]
filename = f"node-v{VERSION}-linux-{arch}.tar.xz"
archive = Path("/tmp/node.tar.xz")
payload = archive.read_bytes()
if sha256(payload).hexdigest() != expected:
    raise RuntimeError("Node distribution checksum mismatch")
with tarfile.open(archive, "r:xz") as tar:
    tar.extractall("/opt", filter="data")
(Path("/opt") / filename.removesuffix(".tar.xz")).rename("/opt/node")
