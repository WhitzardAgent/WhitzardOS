from pathlib import Path

import pytest

from qitos.studio.registry import RegistryError, load_registry


def test_registry_resolves_only_locally_registered_agents(tmp_path: Path) -> None:
    config = tmp_path / "agent.yaml"
    config.write_text("schema: qitos.agent\n", encoding="utf-8")
    registry = tmp_path / "studio.yaml"
    registry.write_text(
        "agents:\n  - id: demo\n    name: Demo\n    description: A sample\n    config: agent.yaml\n"
        "  - id: custom\n    name: Custom\n    config: agent.yaml\n    factory: example_agents:make_agent\n",
        encoding="utf-8",
    )

    agents = load_registry(registry)
    assert tuple(agents) == ("demo", "custom")
    assert agents["demo"].config_path == config.resolve()
    assert agents["custom"].factory_ref == "example_agents:make_agent"
    assert agents["demo"].public_dict() == {
        "id": "demo", "name": "Demo", "description": "A sample",
    }


def test_registry_rejects_duplicate_id_and_unknown_fields(tmp_path: Path) -> None:
    (tmp_path / "agent.yaml").write_text("schema: qitos.agent\n", encoding="utf-8")
    registry = tmp_path / "studio.yaml"
    registry.write_text(
        "agents:\n  - {id: demo, name: Demo, config: agent.yaml}\n"
        "  - {id: demo, name: Other, config: agent.yaml}\n",
        encoding="utf-8",
    )
    with pytest.raises(RegistryError, match="duplicate_agent_id"):
        load_registry(registry)
    registry.write_text(
        "agents:\n  - {id: demo, name: Demo, config: agent.yaml, import: os}\n",
        encoding="utf-8",
    )
    with pytest.raises(RegistryError, match="unknown_agent_field"):
        load_registry(registry)
