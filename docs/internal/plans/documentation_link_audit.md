# Documentation link integrity audit

Audit date: 2026-09-09
Source baseline: `2789b97feb0ed637b2c68d281bfede4f80f286d2`

## Scope and result

The deterministic inventory covers 358 repository, public-doc, example and
bundled-agent-skill Markdown/MDX files containing 1,415 link occurrences:

- 981 local or documentation-route links;
- 220 unique HTTP(S) targets;
- 328 occurrences of first-party GitHub `blob` or `tree` source links.

All 170 routes declared by `docs/docs.json` and all 134 unique internal routes
linked from MDX returned a real page title from the deployed Mintlify site. The
union contains 176 routes; no confirmed HTTP or soft 404 was found. HTTP probing
of the 220 Markdown targets found no other confirmed external 404 after excluding
the intentional local qita URL `http://127.0.0.1:8765`. A bot-limited response is
not treated as proof that third-party content exists.

## Findings closed

1. The EN/zh memory guide linked its installed consumer to the unpublished
   `codex/v5-r1-b-memory-context` branch. GitHub returned **File not found**.
   Both pages now use the public immutable implementation commit.
2. Ten EN/zh tutorial source links used the old movable `main` branch. The branch
   exists but is not the canonical `master`; links now use the exact public source
   commit so the lesson cannot silently drift.
3. Five Chinese tutorial cards linked to English routes. They now retain `/zh/`
   across function-tool, MCP, hook and multi-agent navigation.
4. The generated security-report contents linked `ATT&CK` to a misspelled anchor
   and advertised a `Raw Data` section that was never emitted. The generator,
   checked-in example and regression test now agree.
5. The two bundled playwright-cli skill documents advertised nine missing
   `references/*.md` files each. The dead list is replaced with truthful CLI help
   guidance.
6. Five MDX pages lacked complete title/description frontmatter. EN/zh benchmark,
   contribution and advanced multi-agent pages now have renderable metadata.

## Permanent prevention

`scripts/validate_docs.py` now scans root Markdown, all `docs` Markdown/MDX,
example READMEs and the two bundled skill trees. In addition to navigation,
bilingual parity, local targets and anchors, it enforces:

- Chinese/English route locality;
- required title and description frontmatter on every MDX page;
- exact-case local targets, including on case-insensitive developer hosts;
- full 40-character immutable refs for first-party `blob`/`tree` links;
- existence and correct blob/tree type of each referenced Git object.

The docs workflow runs this validator and its focused regression tests. Network
probing remains a release/audit check rather than a required CI gate because
third-party rate limits and bot protection are not deterministic. Deployed-route
soft-404 inspection likewise remains a post-deployment check.

## Validation

```bash
python scripts/validate_docs.py
python -m pytest -q tests/test_docs_link_integrity.py tests/test_predefined_atomic_tools.py
python scripts/sync_tutorial_docs.py --check
python scripts/sync_api_reference.py --check
node scripts/validate_docs_mdx.mjs
git diff --check
```

The exact source-link replacement was also opened in a real browser; its GitHub
title identifies `examples/v5/r1_b_memory_context` at the pinned commit rather
than `File not found`.
