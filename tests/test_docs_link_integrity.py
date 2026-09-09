from scripts.validate_docs import ROOT, exact_path_exists, repository_source_error


REPOSITORY = "https://github.com/WhitzardAgent/WhitzardOS"
PUBLIC_SOURCE = "f7d4b2d666a156d361da496a41868278f84ffabf"


def test_first_party_source_links_reject_movable_or_private_refs():
    error = repository_source_error(
        f"{REPOSITORY}/tree/codex/v5-r1-b-memory-context/"
        "examples/v5/r1_b_memory_context"
    )

    assert error == "first-party source link must use a full immutable commit SHA"


def test_first_party_source_links_accept_existing_immutable_objects():
    error = repository_source_error(
        f"{REPOSITORY}/tree/{PUBLIC_SOURCE}/examples/v5/r1_b_memory_context"
    )

    assert error is None


def test_first_party_source_links_validate_blob_and_tree_kinds():
    error = repository_source_error(
        f"{REPOSITORY}/blob/{PUBLIC_SOURCE}/examples/v5/r1_b_memory_context"
    )

    assert error == "first-party blob link points to a tree object"


def test_local_link_targets_require_exact_case():
    assert exact_path_exists(ROOT / "README.md")
    assert not exact_path_exists(ROOT / "readme.md")
