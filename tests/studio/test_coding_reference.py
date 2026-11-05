"""An installed-shape coding Agent uses Studio's generic launch contract."""

from __future__ import annotations

from pathlib import Path
import json
import os
from types import SimpleNamespace

from qitos.config import (
    AgentConfig, BudgetConfig, EnvironmentConfig, ModelConfig, RuntimeConfig,
    SessionConfig, TrajectoryConfig, build_agent_composition,
)
from qitos.studio.registry import AgentSpec
from qitos.studio.registry import load_registry
from qitos.studio.service import StudioService
from qitos.core.tool_registry import ToolRegistry


class _CodingModel:
    model = "offline-coding"
    qitos_protocol = "json_decision_multi_v1"
    context_window = 8192
    max_tokens = 1024

    def __init__(self):
        self.stage = 0

    def call_raw(self, messages, **options):
        _ = messages, options
        stage = self.stage
        self.stage += 1
        actions = [
            ("read_file", {"path": "calc.py"}),
            ("edit_file", {"path": "calc.py", "old_text": "a - b", "replacement": "a + b"}),
            ("run_test", {"target": "test_calc.py", "timeout": 20}),
        ]
        if stage >= len(actions):
            return {"choices": [{"message": {"content": "Final Answer: Fixed add and ran test_calc.py."}}]}
        name, arguments = actions[stage]
        return {"choices": [{"message": {"content": None, "tool_calls": [{
            "id": f"coding-{stage}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }]}}]}


def test_coding_reference_runs_without_studio_specific_frontend(tmp_path: Path, monkeypatch) -> None:
    source_root = Path(__file__).resolve().parents[2] / "examples/projects/studio_coding/src"
    monkeypatch.syspath_prepend(str(source_root))
    source = tmp_path / "source"
    source.mkdir()
    (source / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (source / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    config_file = tmp_path / "agent.yaml"
    config_file.write_text("schema: qitos.agent", encoding="utf-8")
    config = AgentConfig(
        name="coding-reference", protocol="json_decision_multi_v1", parser="auto",
        model=ModelConfig(provider="openai-compatible", model="offline-coding"),
        tool_preset="none", tool_options={"native_tool_calls_required": True},
        budgets=BudgetConfig(max_steps=8, max_requests=8, max_runtime_seconds=90),
        runtime=RuntimeConfig(
            environment=EnvironmentConfig(
                workspace=str(source), image=os.environ.get(
                    "QITOS_STUDIO_CODING_TEST_IMAGE", "qitos-s3-g4-qualification:pytest-debian",
                ),
                cpus=.5, memory_mb=256, pids_limit=32,
            ),
            session=SessionConfig(mode="durable", store="sqlite", path=str(tmp_path / "sessions.sqlite3")),
            trajectory=TrajectoryConfig(enabled=True, output=str(tmp_path / "trajectory.journal")),
        ),
    )
    agents = {"coding": AgentSpec(
        "coding", "Coding Agent", "", config_file,
        factory_ref="qitos_studio_coding:make_agent",
        adapter_ref="qitos_studio_coding:StudioCodingAdapter",
    )}

    def builder(spec, loaded, _):
        return build_agent_composition(
            loaded, model_override=_CodingModel(), agent_factory=spec.load_factory(),
        )

    with StudioService(
        agents, state_path=tmp_path / "studio.sqlite3",
        credential_path=tmp_path / "credentials.yaml", config_loader=lambda _: config,
        composition_builder=builder,
    ) as service:
        launch = service.start("coding", "Fix add and verify the test")
        service.wait_for_idle()
        detail = service.get_session(launch["id"])
        assert detail["status"] == "completed", detail
        assert "Fixed add" in detail["final_result"]
        facts = service.events(launch["id"])["records"]
        tool_results = [item for fact in facts if fact["kind"] == "tool_slot"
                        for item in fact["payload"].get("payload", {}).get("action_results", [])]
        assert [item["tool_name"] for item in tool_results if item["tool_name"] != "env"] == [
            "read_file", "edit_file", "run_test",
        ]
        test_result = next(item for item in tool_results if item["tool_name"] == "run_test")
        assert json.loads(test_result["model_output"])["returncode"] == 0
        assert service.agent_capabilities("coding", launch["id"])["operations"]["message"]["available"]


def test_read_only_policy_uses_same_factory_without_mutation_tools(monkeypatch) -> None:
    source_root = Path(__file__).resolve().parents[2] / "examples/projects/studio_coding/src"
    monkeypatch.syspath_prepend(str(source_root))
    from qitos_studio_coding import make_agent, StudioReviewAdapter

    config = AgentConfig(
        name="review", model=ModelConfig(provider="openai-compatible", model="offline"),
        protocol="json_decision_multi_v1", tool_options={"editing": False},
    )
    registry = ToolRegistry()
    make_agent(config=config, model=_CodingModel(), tool_registry=registry,
               protocol=SimpleNamespace(id="json_decision_multi_v1"), parser=None)
    assert set(registry.list_tools()) == {"read_file", "list_files", "grep_file", "run_test"}
    assert StudioReviewAdapter().capabilities()["views"] == ["files"]


def test_reference_registry_exposes_python_review_and_typescript() -> None:
    root = Path(__file__).resolve().parents[2] / "examples/projects/studio_coding"
    agents = load_registry(root / "studio.yaml")
    assert set(agents) == {"coding", "review", "coding_ts"}
    assert all(spec.factory_ref == "qitos_studio_coding:make_agent" for spec in agents.values())
