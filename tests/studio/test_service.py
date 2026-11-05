from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event

import pytest

from qitos.config.loader import AgentConfig, RuntimeConfig, SessionConfig, TrajectoryConfig
from qitos.config.errors import CredentialFileSecurityError
from qitos.studio.registry import AgentSpec
from qitos.studio.service import StudioError, StudioService


@dataclass
class _Identity:
    value: str


class _Session:
    session_id = _Identity("session-1")
    run_id = _Identity("run-1")
    lifecycle = _Identity("completed")

    def __init__(self, gate: Event):
        self.gate = gate

    def run(self):
        self.gate.wait(2)
        return type("Result", (), {"state": type("State", (), {
            "stop_reason": "final", "final_result": "done"
        })()})()


class _Composition:
    def __init__(self, gate: Event):
        self.gate = gate

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def session(self, task):
        assert task.startswith("Inspect this")
        return _Session(self.gate)

    def restore(self, session_id):
        assert session_id == "session-1"
        return _Session(self.gate)


def _service(tmp_path: Path, gate: Event) -> StudioService:
    config_file = tmp_path / "agent.yaml"
    config_file.write_text("schema: qitos.agent", encoding="utf-8")
    config = AgentConfig(
        runtime=RuntimeConfig(
            session=SessionConfig(mode="durable", store="sqlite", path=str(tmp_path / "sessions.db")),
            trajectory=TrajectoryConfig(enabled=True, output=str(tmp_path / "trajectory.journal")),
        )
    )
    return StudioService(
        {"demo": AgentSpec("demo", "Demo", "", config_file)},
        state_path=tmp_path / "studio.db",
        credential_path=tmp_path / "credentials.yaml",
        config_loader=lambda _: config,
        composition_builder=lambda *_: _Composition(gate),
        session_inspector=lambda *_: {
            "lifecycle": "paused", "config_digest": config.digest(),
            "capabilities": ["session.restore"],
        },
    )


def test_start_is_nonblocking_and_reconciles_persisted_session(tmp_path: Path) -> None:
    gate = Event()
    service = _service(tmp_path, gate)
    try:
        launch = service.start("demo", "Inspect this")
        assert launch["status"] in {"queued", "running"}
        assert launch["id"]
        assert service.get_session(launch["id"])["agent_id"] == "demo"
        gate.set()
        service.wait_for_idle()
        assert service.get_session(launch["id"])["status"] == "completed"
        assert service.get_session(launch["id"])["final_result"] == "done"
    finally:
        gate.set()
        service.close()


def test_unregistered_agent_and_live_resume_are_rejected(tmp_path: Path) -> None:
    gate = Event()
    service = _service(tmp_path, gate)
    try:
        with pytest.raises(StudioError, match="agent_not_registered"):
            service.start("missing", "task")
        launch = service.start("demo", "Inspect this")
        with pytest.raises(StudioError, match="session_busy"):
            service.resume(launch["id"])
    finally:
        gate.set()
        service.close()


def test_restart_marks_unobserved_active_launch_unknown(tmp_path: Path) -> None:
    gate = Event()
    service = _service(tmp_path, gate)
    launch = service.start("demo", "Inspect this")
    gate.set()
    service.close()
    # A previous process's activity marker is never authoritative after restart.
    with _service(tmp_path, Event()) as reopened:
        row = reopened.get_session(launch["id"])
        assert row["status"] == "completed"
        reopened._update(launch["id"], status="running", session_id=None, run_id=None)
        assert reopened.get_session(launch["id"])["status"] == "unknown"


def test_manual_resume_reopens_saved_session_in_new_service(tmp_path: Path) -> None:
    gate = Event()
    with _service(tmp_path, gate) as first:
        launch = first.start("demo", "Inspect this")
        gate.set()
        first.wait_for_idle()
    with _service(tmp_path, Event()) as reopened:
        assert reopened.get_session(launch["id"])["can_resume"]
        resumed = reopened.resume(launch["id"])
        assert resumed["status"] in {"queued", "running"}
        reopened.wait_for_idle()
        assert reopened.get_session(launch["id"])["status"] == "completed"


def test_safe_configuration_error_keeps_its_public_code(tmp_path: Path) -> None:
    gate = Event()
    service = _service(tmp_path, gate)

    def fail_build(*_):
        raise CredentialFileSecurityError("private path detail")

    service._build = fail_build
    try:
        launch = service.start("demo", "Inspect this")
        service.wait_for_idle()
        detail = service.get_session(launch["id"])
        assert detail["status"] == "failed"
        assert detail["error_code"] == "credential_file_security_invalid"
        assert "private path detail" not in str(detail)
    finally:
        service.close()


def test_public_session_redacts_task_secret(tmp_path: Path) -> None:
    gate = Event()
    service = _service(tmp_path, gate)
    try:
        launch = service.start("demo", "Inspect this api_key=private-value")
        assert "private-value" not in str(launch)
        gate.set()
        service.wait_for_idle()
        assert "private-value" not in str(service.get_session(launch["id"]))
    finally:
        gate.set()
        service.close()
