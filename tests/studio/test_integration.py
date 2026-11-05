"""Two installed-shape agents run through one Studio service and real Session store."""

from pathlib import Path

from qitos.config.builder import ConfiguredAgent, build_agent_composition
from qitos.config.loader import (
    AgentConfig, EnvironmentConfig, ModelConfig, RuntimeConfig, SessionConfig,
    TrajectoryConfig,
)
from qitos.studio.registry import AgentSpec
from qitos.studio.service import StudioService
from qitos.core.action import Action
from qitos.core.decision import Decision
from qitos.core.tool import tool
from qitos.engine.runtime import LifecyclePolicy


class _FinalModel:
    model = "offline-final"
    context_window = 8192
    max_tokens = 128
    qitos_harness_metadata = {"protocol": "react_text_v1", "parser": "ReActTextParser"}

    def call_raw(self, messages, **options):
        _ = messages, options
        return {"choices": [{"message": {"content": "Final Answer: finished"}}]}


def test_declarative_and_custom_factory_share_studio_flow(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples" / "studio"))
    config_file = tmp_path / "agent.yaml"
    config_file.write_text("schema: qitos.agent", encoding="utf-8")
    config = AgentConfig(
        name="offline",
        max_steps=2,
        model=ModelConfig(provider="openai-compatible", model="offline-final"),
        protocol="react_text_v1", parser="auto",
        runtime=RuntimeConfig(
            environment=EnvironmentConfig(type="unsafe_host", workspace=str(tmp_path)),
            session=SessionConfig(mode="durable", store="sqlite", path=str(tmp_path / "sessions.sqlite3")),
            trajectory=TrajectoryConfig(enabled=True, output=str(tmp_path / "trajectory.journal")),
        ),
    )
    agents = {
        "default": AgentSpec("default", "Default", "", config_file),
        "custom": AgentSpec("custom", "Custom", "", config_file, "studio_agents:make_agent"),
    }

    def builder(spec, loaded, _):
        return build_agent_composition(
            loaded, model_override=_FinalModel(),
            agent_factory=spec.load_factory(),
        )

    with StudioService(
        agents, state_path=tmp_path / "studio.sqlite3",
        credential_path=tmp_path / "credentials.yaml",
        config_loader=lambda _: config,
        composition_builder=builder,
    ) as service:
        first = service.start("default", "Explain this")
        second = service.start("custom", "Review that")
        service.wait_for_idle()
        for launch in (first, second):
            detail = service.get_session(launch["id"])
            assert detail["status"] == "completed", detail
            assert detail["final_result"] == "finished"
            page = service.events(launch["id"])
            assert page["records"]
            assert all(record["run_id"] == detail["run_id"] for record in page["records"])


class _PauseFirst(LifecyclePolicy):
    policy_id = "studio.test.pause_first"

    def should_pause(self, context):
        return context.step_id == 0


class _TwoStepAgent(ConfiguredAgent):
    def decide(self, state, observation):
        if state.current_step == 0:
            return Decision.act([Action(name="noop", args={})])
        return Decision.final("restored")


def _two_step_factory(*, config, model, tool_registry, protocol, parser):
    @tool(name="noop")
    def noop() -> str:
        return "done"

    tool_registry.register(noop)
    return _TwoStepAgent(
        name=config.name, llm=model, tool_registry=tool_registry,
        protocol=protocol.id, parser=parser, tool_use_policy="auto",
        native_tool_calls_required=False, config_digest=config.digest(),
    )


def test_manual_restore_uses_real_persisted_session_and_new_run(tmp_path: Path) -> None:
    config_file = tmp_path / "agent.yaml"
    config_file.write_text("schema: qitos.agent", encoding="utf-8")
    config = AgentConfig(
        name="pausable", max_steps=3,
        model=ModelConfig(provider="openai-compatible", model="offline-final"),
        protocol="react_text_v1", parser="auto", lifecycle={"policy": "pause_first"},
        runtime=RuntimeConfig(
            environment=EnvironmentConfig(type="unsafe_host", workspace=str(tmp_path)),
            session=SessionConfig(mode="durable", store="sqlite", path=str(tmp_path / "sessions.sqlite3")),
            trajectory=TrajectoryConfig(enabled=True, output=str(tmp_path / "trajectory.journal")),
        ),
    )

    def builder(spec, loaded, _):
        return build_agent_composition(
            loaded, model_override=_FinalModel(), extensions={"pause_first": _PauseFirst},
            agent_factory=_two_step_factory,
        )

    agents = {"pausable": AgentSpec("pausable", "Pausable", "", config_file)}
    kwargs = dict(
        state_path=tmp_path / "studio.sqlite3", credential_path=tmp_path / "credentials.yaml",
        config_loader=lambda _: config, composition_builder=builder,
    )
    with StudioService(agents, **kwargs) as service:
        launched = service.start("pausable", "Resume me")
        service.wait_for_idle()
        paused = service.get_session(launched["id"])
        assert paused["status"] == "paused", paused
        assert paused["can_resume"]
        first_run = paused["run_id"]
    with StudioService(agents, **kwargs) as reopened:
        reopened._update(launched["id"], status="running")
        assert reopened.get_session(launched["id"])["status"] == "paused"
        resumed = reopened.resume(launched["id"])
        assert resumed["status"] in {"queued", "running"}
        reopened.wait_for_idle()
        completed = reopened.get_session(launched["id"])
        assert completed["status"] == "completed", completed
        assert completed["run_id"] != first_run
        assert completed["final_result"] == "restored"
