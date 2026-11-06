from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event

import pytest

from qitos.config.loader import AgentConfig, RuntimeConfig, SessionConfig, TrajectoryConfig
from qitos.config.errors import CredentialFileSecurityError
from qitos.studio.registry import AgentSpec
from qitos.studio.service import StudioError, StudioService
from qitos.studio.adapter import StudioTurn


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


class DemoAdapter:
    def capabilities(self):
        return {"continuation": True, "views": ["files", "diff"]}

    def continuation_task(self, turns: list[StudioTurn], message: str) -> str:
        return f"Inspect this follow-up.\nPrevious request: {turns[-1].task}\nFollow-up: {message}"


def test_linked_turns_keep_distinct_sessions_and_messages(tmp_path: Path) -> None:
    gate = Event()
    gate.set()
    with _service(tmp_path, gate) as service:
        spec = service.agents["demo"]
        service.agents["demo"] = AgentSpec(
            spec.id, spec.name, spec.description, spec.config_path,
            adapter_ref=f"{__name__}:DemoAdapter",
        )
        first = service.start("demo", "Inspect this project")
        service.wait_for_idle()
        second = service.submit_message(first["id"], "Inspect this change")
        service.wait_for_idle()
        assert second["conversation_id"] == first["id"]
        assert second["turn_index"] == 1
        assert service.get_session(second["id"])["session_id"] == "session-1"  # Test composition identity.
        assert second["message"] == "Inspect this change"
        assert "Follow-up: Inspect this change" in service._row(second["id"])["task"]
        assert [turn["id"] for turn in service.conversation(first["id"])["items"]] == [first["id"], second["id"]]
        assert service.agent_capabilities("demo", first["id"])["operations"]["message"]["available"]
        assert service.get_session(first["id"])["latest_status"] == "completed"
        assert service.runs(first["id"])[0]["run_id"] == "run-1"
        with pytest.raises(StudioError, match="run_not_found"):
            service.events(first["id"], run_id="other-run")


def test_default_agent_has_no_follow_up_and_pages_history(tmp_path: Path) -> None:
    gate = Event()
    gate.set()
    with _service(tmp_path, gate) as service:
        ids = []
        for index in range(4):
            ids.append(service.start("demo", f"Inspect this {index}")["id"])
        service.wait_for_idle()
        with pytest.raises(StudioError, match="continuation_unsupported"):
            service.submit_message(ids[-1], "more")
        first = service.list_sessions_page(limit=2)
        second = service.list_sessions_page(limit=2, before=first["next_before"])
        assert len(first["items"]) == len(second["items"]) == 2
        assert {item["id"] for item in first["items"]}.isdisjoint(
            {item["id"] for item in second["items"]}
        )
        service.update_conversation(ids[0], title="A title", pinned=True, archived=True)
        assert service.get_session(ids[0])["title"] == "A title"
        assert all(item["id"] != ids[0] for item in service.list_sessions_page()["items"])
        assert [item["id"] for item in service.list_sessions_page(include_archived=True)["items"]] == [ids[0]]
        assert [item["id"] for item in service.list_sessions_page(search="Inspect this 2")["items"]] == [ids[2]]


def test_old_launch_rows_migrate_without_inventing_missing_runs(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "studio.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE launches (id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, task TEXT NOT NULL, "
                   "session_id TEXT, run_id TEXT, status TEXT NOT NULL, error_code TEXT, final_result TEXT, "
                   "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
        db.execute("INSERT INTO launches VALUES ('legacy', 'demo', 'Inspect this', NULL, NULL, "
                   "'completed', NULL, NULL, '2026-01-01', '2026-01-01')")
    with _service(tmp_path, Event()) as service:
        assert service.get_session("legacy")["conversation_id"] == "legacy"
        assert service.get_session("legacy")["turn_index"] == 0
        assert service.runs("legacy") == []


def test_admission_is_bounded_and_completed_handles_are_released(tmp_path):
    gate = Event()
    service = _service(tmp_path, gate)
    service._max_pending = 1
    try:
        service.start("demo", "Inspect this")
        with pytest.raises(StudioError, match="studio_queue_full"):
            service.start("demo", "Inspect this overflow")
        assert len(service.list_sessions()) == 1
        gate.set()
        service.wait_for_idle()
        assert service._futures == {}
        service.start("demo", "Inspect this next")
        service.wait_for_idle()
    finally:
        gate.set()
        service.close()
    with pytest.raises(StudioError, match="studio_closed"):
        service.start("demo", "Inspect this after shutdown")


def test_reader_cache_reuses_bounds_evicts_and_closes(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import qitos.studio.service as module

    opened, closed = [], []

    def factory(path):
        opened.append(path)
        return SimpleNamespace(close=lambda: closed.append(path))

    monkeypatch.setattr(module, "default_reader", factory)
    service = _service(tmp_path, Event())
    service._max_readers = 2
    paths = [tmp_path / f"{i}.journal" for i in range(3)]
    for path in paths:
        path.touch()
    with service._trajectory_reader(paths[0]) as first:
        pass
    with service._trajectory_reader(paths[0]) as again:
        assert again is first
    for path in paths[1:]:
        with service._trajectory_reader(path):
            pass
    assert opened == paths
    assert closed == paths[:1]
    service.close()
    assert closed == paths


def test_capabilities_do_not_materialize_conversation_history(tmp_path, monkeypatch):
    gate = Event()
    gate.set()
    with _service(tmp_path, gate) as service:
        launch = service.start("demo", "Inspect this")
        service.wait_for_idle()
        monkeypatch.setattr(service, "_conversation_rows", lambda *_: pytest.fail("unbounded history read"))
        assert service.agent_capabilities("demo", launch["id"])["operations"]["start"]["available"]


def test_sidebar_summary_does_not_decode_checkpoint_or_grant_restore(tmp_path, monkeypatch):
    gate = Event()
    gate.set()
    with _service(tmp_path, gate) as service:
        launch = service.start("demo", "Inspect this")
        service.wait_for_idle()
        monkeypatch.setattr(service, "_inspect", lambda *_: pytest.fail("checkpoint decode"))
        row = service.list_sessions_page(summary=True)["items"][0]
        assert row["status"] == "completed"
        assert "can_resume" not in row
        service._update(launch["id"], status="running")
        assert service.list_sessions_page(summary=True)["items"][0]["status"] == "unknown"


@pytest.mark.parametrize("directory", [False, True])
def test_unbounded_json_source_is_rejected_before_materialization(tmp_path, monkeypatch, directory):
    import qitos.studio.service as module
    from qitos.tracing.paging import BoundedReadUnsupported

    source = tmp_path / "trajectory.json"
    source.write_text('{"records":[]}')
    monkeypatch.setattr(module, "default_reader", lambda *_: pytest.fail("materialized JSON"))
    with _service(tmp_path, Event()) as service:
        with pytest.raises(BoundedReadUnsupported):
            with service._trajectory_reader(tmp_path if directory else source):
                pytest.fail("unsupported source yielded")


def test_launch_commits_before_worker_submission(tmp_path, monkeypatch):
    gate = Event()
    with _service(tmp_path, gate) as service:
        def submitted(launch_id, *_):
            assert service._row(launch_id)["status"] == "queued"
        monkeypatch.setattr(service, "_submit", submitted)
        service.start("demo", "Inspect this")
