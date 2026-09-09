"""Deterministic public navigation, parity and repository-link validation."""
import json
from functools import lru_cache
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
REPOSITORY_SOURCE_PREFIX = "/WhitzardAgent/WhitzardOS/"
IMMUTABLE_REF = re.compile(r"[0-9a-f]{40}")


def public_markdown_files():
    """Return user-facing, repository and bundled-skill documentation."""

    roots = [
        *(ROOT.glob("*.md")),
        *(DOCS.rglob("*.md")),
        *(DOCS.rglob("*.mdx")),
        *((ROOT / "examples").rglob("README*.md")),
        *((ROOT / ".agents" / "skills").rglob("*.md")),
        *((ROOT / ".claude" / "skills").rglob("*.md")),
    ]
    return sorted({path for path in roots if path.is_file()})


def markdown_links(text):
    """Extract Markdown/MDX links without treating fenced examples as links."""

    text = re.sub(r"```[^\n]*\n.*?```", "", text, flags=re.S)
    inline = re.findall(
        r'\]\((?:<([^>]+)>|([^\s)]+))(?:\s+[^)]*)?\)|'
        r'(?:href|src)=["\']([^"\']+)["\']',
        text,
    )
    links = [next(value for value in match if value) for match in inline]
    references = re.findall(
        r'^\s*\[[^]]+\]:\s*(?:<([^>]+)>|(\S+))', text, flags=re.M
    )
    links.extend(next(value for value in match if value) for match in references)
    return links


@lru_cache(maxsize=None)
def repository_source_error(link):
    """Reject movable/private first-party source links and missing Git objects."""

    parsed = urlsplit(link)
    if parsed.netloc != "github.com" or not parsed.path.startswith(
        REPOSITORY_SOURCE_PREFIX
    ):
        return None
    relative = parsed.path[len(REPOSITORY_SOURCE_PREFIX):]
    parts = relative.split("/", 2)
    if len(parts) != 3 or parts[0] not in {"blob", "tree"}:
        return None
    mode, ref, object_path = parts
    if IMMUTABLE_REF.fullmatch(ref) is None:
        return "first-party source link must use a full immutable commit SHA"
    result = subprocess.run(
        ["git", "cat-file", "-t", f"{ref}:{unquote(object_path)}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return "first-party source link points to a missing Git object"
    object_type = result.stdout.strip()
    expected = "blob" if mode == "blob" else "tree"
    if object_type != expected:
        return f"first-party {mode} link points to a {object_type or 'missing'} object"
    return None


def exact_path_exists(path):
    """Check existence without hiding case errors on case-insensitive hosts."""

    try:
        relative = path.resolve(strict=False).relative_to(ROOT.resolve())
    except ValueError:
        return path.exists()
    current = ROOT
    for part in relative.parts:
        if not current.is_dir() or part not in {item.name for item in current.iterdir()}:
            return False
        current = current / part
    return current.exists()


def pages(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "pages":
                yield from (x for x in item if isinstance(x, str))
            else:
                yield from pages(item)
    elif isinstance(value, list):
        for item in value:
            yield from pages(item)


def validate():
    errors = []
    config = json.loads((DOCS / "docs.json").read_text())
    languages = config["navigation"]["languages"]
    en = list(pages(languages[0]))
    zh = [p.removeprefix("zh/") for p in pages(languages[1])]
    if en != zh:
        errors.append("docs.json: language navigation order differs")
    for name in en:
        for prefix in ("", "zh/"):
            if not (DOCS / f"{prefix}{name}.mdx").is_file():
                errors.append(f"docs.json: missing {prefix}{name}")
    for page in sorted(DOCS.rglob("*.mdx")):
        text = page.read_text()
        frontmatter = re.match(r"^---\n(.*?)\n---\n", text, flags=re.S)
        if frontmatter is None:
            errors.append(f"{page.relative_to(ROOT)}: missing frontmatter")
            continue
        metadata = frontmatter.group(1)
        for field in ("title", "description"):
            if re.search(rf"^{field}:\s*\S", metadata, flags=re.M) is None:
                errors.append(f"{page.relative_to(ROOT)}: missing {field}")
    for page in public_markdown_files():
        text = page.read_text()
        for link in markdown_links(text):
            parsed = urlsplit(link)
            source_error = repository_source_error(link)
            if source_error:
                errors.append(f"{page.relative_to(ROOT)}: {source_error}: {link}")
            if parsed.scheme or link.startswith("//"):
                continue
            target = unquote(parsed.path)
            if (
                page.is_relative_to(DOCS / "zh")
                and target.startswith("/")
                and target != "/"
                and not target.startswith("/zh/")
            ):
                errors.append(
                    f"{page.relative_to(ROOT)}: Chinese page links to English route {link}"
                )
            if (
                page.suffix == ".mdx"
                and page.is_relative_to(DOCS)
                and not page.is_relative_to(DOCS / "zh")
                and target.startswith("/zh/")
            ):
                errors.append(
                    f"{page.relative_to(ROOT)}: English page links to Chinese route {link}"
                )
            if target.startswith("/") and page.is_relative_to(DOCS):
                base = DOCS / target.lstrip("/")
            elif target.startswith("/"):
                base = ROOT / target.lstrip("/")
            else:
                base = page.parent / target
            if not target:
                base = page
            choices = [
                base,
                base.with_suffix(".mdx"),
                base.with_suffix(".md"),
                base / "index.mdx",
                base / "README.md",
            ]
            found = next((p for p in choices if exact_path_exists(p)), None)
            if found is None:
                errors.append(f"{page.relative_to(ROOT)}: missing link {link}")
            elif (
                parsed.fragment
                and found.is_file()
                and found.suffix in (".mdx", ".md")
            ):
                content = found.read_text()
                headings = re.findall(r"^#{1,6}\s+(.+)$", content, re.M)
                slugs = {re.sub(r"[^\w\- ]", "", h.lower()).replace(" ", "-") for h in headings}
                slugs.update(re.findall(r'id=["\']([^"\']+)', content))
                if unquote(parsed.fragment) not in slugs:
                    errors.append(f"{page.relative_to(ROOT)}: missing anchor {link}")
    return sorted(set(errors))


if __name__ == "__main__":
    errors = validate()
    print(
        "\n".join(errors)
        if errors
        else (
            "Public navigation, frontmatter, bilingual parity, local and "
            "repository links passed."
        )
    )
    sys.exit(bool(errors))
