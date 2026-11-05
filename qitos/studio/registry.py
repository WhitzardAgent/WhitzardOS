"""Explicit local allowlist of launchable agents."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Callable, cast

import yaml

from qitos.core.agent_module import AgentModule
from qitos.tracing.privacy import project_data
from qitos.tracing.trajectory import PrivacyView


_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_FACTORY = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*$")


class RegistryError(ValueError):
    """A local registry is invalid. Messages never contain user content."""


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str
    description: str
    config_path: Path
    factory_ref: str | None = None

    def public_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": project_data(self.name, view=PrivacyView.REDACTED_PUBLIC).data,
            "description": project_data(self.description, view=PrivacyView.REDACTED_PUBLIC).data,
        }

    def load_factory(self) -> Callable[..., AgentModule[Any, Any, Any]] | None:
        if self.factory_ref is None:
            return None
        module_name, attribute = self.factory_ref.split(":", 1)
        try:
            candidate = getattr(importlib.import_module(module_name), attribute)
        except (ImportError, AttributeError) as exc:
            raise RegistryError("agent_factory_unavailable") from exc
        if not callable(candidate):
            raise RegistryError("agent_factory_not_callable")
        return cast(Callable[..., AgentModule[Any, Any, Any]], candidate)


def load_registry(path: str | Path) -> dict[str, AgentSpec]:
    source = Path(path).expanduser().resolve()
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise RegistryError("registry_unreadable") from exc
    if not isinstance(raw, dict) or set(raw) != {"agents"} or not isinstance(raw["agents"], list):
        raise RegistryError("registry_shape_invalid")
    agents: dict[str, AgentSpec] = {}
    for item in raw["agents"]:
        if not isinstance(item, dict):
            raise RegistryError("agent_shape_invalid")
        if set(item) - {"id", "name", "description", "config", "factory"}:
            raise RegistryError("unknown_agent_field")
        if not {"id", "name", "config"}.issubset(item):
            raise RegistryError("agent_required_field_missing")
        agent_id, name = item["id"], item["name"]
        if not isinstance(agent_id, str) or not _ID.fullmatch(agent_id):
            raise RegistryError("agent_id_invalid")
        if agent_id in agents:
            raise RegistryError("duplicate_agent_id")
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise RegistryError("agent_name_invalid")
        description = item.get("description", "")
        if not isinstance(description, str) or len(description) > 500:
            raise RegistryError("agent_description_invalid")
        config = item["config"]
        if not isinstance(config, str) or not config.strip():
            raise RegistryError("agent_config_invalid")
        config_path = (source.parent / config).expanduser().resolve()
        if not config_path.is_file():
            raise RegistryError("agent_config_unavailable")
        factory_ref = item.get("factory")
        if factory_ref is not None and (
            not isinstance(factory_ref, str) or not _FACTORY.fullmatch(factory_ref)
        ):
            raise RegistryError("agent_factory_invalid")
        agents[agent_id] = AgentSpec(
            id=agent_id, name=name.strip(), description=description.strip(),
            config_path=config_path, factory_ref=factory_ref,
        )
    if not agents:
        raise RegistryError("registry_empty")
    return agents
