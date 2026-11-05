"""Local launch supervisor and redacted, durable Studio read model."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Callable, Iterator, Mapping
import uuid

from qitos.config import LocalCredentialFileResolver, build_agent_composition, load_agent_config
from qitos.config.builder import _inspect_persisted_session, _session_store_path
from qitos.qita.reader import default_reader
from qitos.tracing.paging import BoundedReadUnsupported, read_page
from qitos.tracing.privacy import project_data
from qitos.tracing.trajectory import PrivacyView, TrajectoryQuery

from .registry import AgentSpec


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StudioError(ValueError):
    """A typed user-visible Studio error without private payloads."""


class StudioService:
    """A process-local supervisor; SQLite holds only Studio launch references."""

    def __init__(
        self,
        agents: Mapping[str, AgentSpec],
        *,
        state_path: str | Path,
        credential_path: str | Path,
        config_loader: Callable[[Path], Any] = load_agent_config,
        composition_builder: Callable[[AgentSpec, Any, Any], Any] | None = None,
        session_inspector: Callable[[Any, str], dict[str, Any]] = _inspect_persisted_session,
        max_workers: int = 1,
    ) -> None:
        self.agents = dict(agents)
        self.state_path = Path(state_path).expanduser().resolve()
        self.credential_path = Path(credential_path).expanduser().resolve()
        self._load_config = config_loader
        self._build = composition_builder or self._build_composition
        self._inspect = session_inspector
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="qitos-studio")
        self._lock = RLock()
        self._futures: dict[str, Future[Any]] = {}
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS launches (
                id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, task TEXT NOT NULL,
                session_id TEXT, run_id TEXT, status TEXT NOT NULL,
                error_code TEXT, final_result TEXT, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL)""")

    def __enter__(self) -> "StudioService":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.state_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def _build_composition(self, spec: AgentSpec, config: Any, _: Any) -> Any:
        resolver = LocalCredentialFileResolver(
            self.credential_path, repository_root=spec.config_path.parent,
        )
        return build_agent_composition(
            config, credential_resolver=resolver, agent_factory=spec.load_factory(),
        )

    def _config(self, spec: AgentSpec) -> Any:
        config = self._load_config(spec.config_path)
        if (config.runtime.session.mode != "durable"
                or config.runtime.session.store != "sqlite"
                or not config.runtime.trajectory.enabled):
            raise StudioError("durable_trajectory_required")
        _session_store_path(config)  # A launch must have a stable persistence target.
        return config

    def start(self, agent_id: str, task: str) -> dict[str, Any]:
        spec = self.agents.get(agent_id)
        if spec is None:
            raise StudioError("agent_not_registered")
        if not isinstance(task, str) or not task.strip() or len(task) > 16_000:
            raise StudioError("task_invalid")
        config = self._config(spec)
        launch_id = str(uuid.uuid4())
        timestamp = _now()
        with self._lock, self._db() as db:
            db.execute(
                "INSERT INTO launches (id, agent_id, task, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'queued', ?, ?)",
                (launch_id, agent_id, task.strip(), timestamp, timestamp),
            )
            self._futures[launch_id] = self._pool.submit(
                self._execute, launch_id, spec, config, task.strip(), False,
            )
        return self.get_session(launch_id)

    def resume(self, launch_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._row(launch_id)
            if launch_id in self._futures and not self._futures[launch_id].done():
                raise StudioError("session_busy")
            if not row["session_id"]:
                raise StudioError("session_not_persisted")
            spec = self.agents.get(row["agent_id"])
            if spec is None:
                raise StudioError("agent_not_registered")
            config = self._config(spec)
            inspected = self._inspect(config, row["session_id"])
            if inspected.get("config_digest") != config.digest():
                raise StudioError("session_config_changed")
            if "session.restore" not in inspected.get("capabilities", []):
                raise StudioError("session_restore_unsupported")
            if inspected.get("lifecycle") not in {"paused", "waiting_input"}:
                raise StudioError("session_not_resumable")
            self._update(launch_id, status="queued", error_code=None)
            self._futures[launch_id] = self._pool.submit(
                self._execute, launch_id, spec, config, row["task"], True,
            )
        return self.get_session(launch_id)

    def _execute(self, launch_id: str, spec: AgentSpec, config: Any, task: str, resume: bool) -> None:
        try:
            with self._build(spec, config, None) as composition:
                session_id = self._row(launch_id)["session_id"]
                session = composition.restore(session_id) if resume else composition.session(task)
                self._update(
                    launch_id, session_id=session.session_id.value,
                    run_id=session.run_id.value, status="running",
                )
                result = session.run()
                final = project_data(
                    result.state.final_result, view=PrivacyView.REDACTED_PUBLIC,
                ).data
                self._update(
                    launch_id, status=session.lifecycle.value,
                    final_result=json.dumps(final, ensure_ascii=False),
                )
        except Exception as exc:
            code = getattr(exc, "error_code", None) or getattr(exc, "code", None)
            code = getattr(code, "value", code)
            self._update(
                launch_id, status="failed",
                error_code=str(code) if isinstance(code, str) and len(code) < 80 else "execution_failed",
            )

    def _row(self, launch_id: str) -> sqlite3.Row:
        with self._db() as db:
            row = db.execute("SELECT * FROM launches WHERE id = ?", (launch_id,)).fetchone()
        if row is None:
            raise StudioError("session_not_found")
        return row

    def _update(self, launch_id: str, **fields: Any) -> None:
        fields["updated_at"] = _now()
        values = list(fields.values())
        with self._db() as db:
            db.execute(
                "UPDATE launches SET " + ", ".join(f"{key} = ?" for key in fields) + " WHERE id = ?",
                (*values, launch_id),
            )

    def _public_row(self, row: sqlite3.Row) -> dict[str, Any]:
        result = {key: row[key] for key in (
            "id", "agent_id", "task", "session_id", "run_id", "status",
            "error_code", "created_at", "updated_at",
        )}
        result["task"] = project_data(
            row["task"], view=PrivacyView.REDACTED_PUBLIC,
        ).data
        result["final_result"] = json.loads(row["final_result"]) if row["final_result"] else None
        active = row["id"] in self._futures and not self._futures[row["id"]].done()
        if row["status"] in {"queued", "running"} and not active:
            result["status"] = "unknown"
            result["error_code"] = "process_not_observed"
        if row["session_id"]:
            spec = self.agents.get(row["agent_id"])
            if spec is not None:
                try:
                    config = self._config(spec)
                    inspected = self._inspect(config, row["session_id"])
                    result["lifecycle"] = inspected.get("lifecycle", "unknown")
                    result["capabilities"] = inspected.get("capabilities", [])
                    if not active and row["status"] in {"queued", "running"}:
                        lifecycle = inspected.get("lifecycle")
                        if lifecycle in {"completed", "failed", "paused", "waiting_input"}:
                            result["status"] = lifecycle
                            result["error_code"] = None
                    result["can_resume"] = (
                        not active and inspected.get("config_digest") == config.digest()
                        and "session.restore" in inspected.get("capabilities", [])
                        and inspected.get("lifecycle") in {"paused", "waiting_input"}
                    )
                except Exception:
                    result["lifecycle"] = "unknown"
                    result["capabilities"] = []
                    result["can_resume"] = False
        return result

    def get_session(self, launch_id: str) -> dict[str, Any]:
        return self._public_row(self._row(launch_id))

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM launches ORDER BY created_at DESC LIMIT 100").fetchall()
        return [self._public_row(row) for row in rows]

    def events(self, launch_id: str, *, after: int = 0, limit: int = 100) -> dict[str, Any]:
        if after < 0 or limit < 1 or limit > 256:
            raise StudioError("event_cursor_invalid")
        row = self._row(launch_id)
        if not row["run_id"]:
            return {"records": [], "next_after": after, "unknown": True}
        spec = self.agents.get(row["agent_id"])
        if spec is None:
            raise StudioError("agent_not_registered")
        config = self._config(spec)
        source = (Path(config.runtime.trajectory.output).expanduser().resolve()
                  if config.runtime.trajectory.output else _session_store_path(config).parent)
        reader = None
        try:
            reader = default_reader(source)
            page = read_page(
                reader, TrajectoryQuery(run_id=row["run_id"], after_sequence=after, limit=limit),
                view=PrivacyView.REDACTED_PUBLIC,
            )
            records = [project_data(record.to_dict(), view=PrivacyView.SAFE_DIAGNOSTIC).data
                       for record in page.records]
            next_after = max((record.sequence or 0 for record in page.records), default=after)
            return {"records": records, "next_after": next_after,
                    "unknown": after == 0 and not bool(records),
                    "has_more": page.next_cursor is not None}
        except (OSError, ValueError, BoundedReadUnsupported) as exc:
            raise StudioError("trajectory_unavailable") from exc
        finally:
            close = getattr(reader, "close", None)
            if callable(close):
                close()

    def wait_for_idle(self) -> None:
        for future in list(self._futures.values()):
            future.result()

    def close(self) -> None:
        self._pool.shutdown(wait=True)
