"""Local launch supervisor and redacted, durable Studio read model."""

from __future__ import annotations

from collections import OrderedDict
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

from .adapter import StudioTurn
from .registry import AgentSpec, RegistryError


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
        max_pending: int = 32,
        max_readers: int = 4,
    ) -> None:
        if max_pending < 1 or max_readers < 1:
            raise ValueError("studio_limits_invalid")
        self._max_pending = max_pending
        self._max_readers = max_readers
        self._closed = False
        self._reader_lock = RLock()
        self._readers: OrderedDict[Path, Any] = OrderedDict()
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
            columns = {row[1] for row in db.execute("PRAGMA table_info(launches)")}
            for name, definition in (
                ("conversation_id", "TEXT"), ("turn_index", "INTEGER"),
                ("title", "TEXT"), ("pinned", "INTEGER NOT NULL DEFAULT 0"),
                ("archived", "INTEGER NOT NULL DEFAULT 0"),
                ("message", "TEXT"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE launches ADD COLUMN {name} {definition}")
            db.execute("""CREATE TABLE IF NOT EXISTS launch_runs (
                launch_id TEXT NOT NULL, run_id TEXT NOT NULL,
                created_at TEXT NOT NULL, PRIMARY KEY (launch_id, run_id))""")
            db.execute("CREATE INDEX IF NOT EXISTS launches_conversation ON launches(conversation_id, turn_index)")
            db.execute("CREATE INDEX IF NOT EXISTS launches_sidebar "
                       "ON launches(turn_index, archived, pinned DESC, created_at DESC, id DESC)")
            # Legacy launches are one-turn conversations. Missing historical run
            # identities remain unknown rather than being fabricated.
            db.execute("UPDATE launches SET conversation_id = id, turn_index = 0 WHERE conversation_id IS NULL")
            db.execute("""INSERT OR IGNORE INTO launch_runs (launch_id, run_id, created_at)
                SELECT id, run_id, created_at FROM launches WHERE run_id IS NOT NULL""")

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

    def start(self, agent_id: str, task: str, *, conversation_id: str | None = None,
              message: str | None = None) -> dict[str, Any]:
        spec = self.agents.get(agent_id)
        if spec is None:
            raise StudioError("agent_not_registered")
        if not isinstance(task, str) or not task.strip() or len(task) > 16_000:
            raise StudioError("task_invalid")
        config = self._config(spec)
        launch_id = str(uuid.uuid4())
        timestamp = _now()
        with self._lock, self._db() as db:
            self._check_admission()
            turn_index = 0
            if conversation_id is not None:
                last = db.execute(
                    "SELECT MAX(turn_index) FROM launches WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()[0]
                if last is None:
                    raise StudioError("session_not_found")
                turn_index = last + 1
            db.execute(
                "INSERT INTO launches (id, agent_id, task, status, created_at, updated_at, "
                "conversation_id, turn_index, message) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?)",
                (launch_id, agent_id, task.strip(), timestamp, timestamp,
                 conversation_id or launch_id, turn_index, message or task.strip()),
            )
            # The worker opens an independent connection; publish its launch
            # before scheduling so a fast composition cannot observe no row.
            db.commit()
            self._submit(launch_id, spec, config, task.strip(), False)
        return self.get_session(launch_id)

    def submit_message(self, conversation_id: str, message: str) -> dict[str, Any]:
        if not isinstance(message, str) or not message.strip() or len(message) > 16_000:
            raise StudioError("task_invalid")
        with self._lock:
            turns = self._conversation_rows(conversation_id)
            if not turns:
                raise StudioError("session_not_found")
            last = self._public_row(turns[-1])
            if last["status"] in {"queued", "running", "unknown"}:
                raise StudioError("session_busy")
            spec = self.agents.get(last["agent_id"])
            if spec is None:
                raise StudioError("agent_not_registered")
            try:
                adapter = spec.load_adapter()
            except RegistryError as exc:
                raise StudioError(str(exc)) from exc
            if adapter is None or not adapter.capabilities().get("continuation"):
                raise StudioError("continuation_unsupported")
            history = [StudioTurn(row["task"], row["session_id"], row["run_id"], row["status"])
                       for row in turns]
            task = adapter.continuation_task(history, message.strip())
            if not isinstance(task, str) or not task.strip() or len(task) > 16_000:
                raise StudioError("continuation_invalid")
            return self.start(spec.id, task, conversation_id=conversation_id,
                              message=message.strip())

    def resume(self, launch_id: str) -> dict[str, Any]:
        with self._lock:
            self._check_admission()
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
            self._submit(launch_id, spec, config, row["task"], True)
        return self.get_session(launch_id)

    def _check_admission(self) -> None:
        if self._closed:
            raise StudioError("studio_closed")
        if len(self._futures) >= self._max_pending:
            raise StudioError("studio_queue_full")

    def _submit(self, launch_id: str, spec: AgentSpec, config: Any, task: str, resume: bool) -> None:
        future = self._pool.submit(self._execute, launch_id, spec, config, task, resume)
        self._futures[launch_id] = future

        def release(done: Future[Any]) -> None:
            with self._lock:
                if self._futures.get(launch_id) is done:
                    del self._futures[launch_id]

        future.add_done_callback(release)

    def _execute(self, launch_id: str, spec: AgentSpec, config: Any, task: str, resume: bool) -> None:
        try:
            with self._build(spec, config, None) as composition:
                session_id = self._row(launch_id)["session_id"]
                session = composition.restore(session_id) if resume else composition.session(task)
                self._update(
                    launch_id, session_id=session.session_id.value,
                    run_id=session.run_id.value, status="running",
                )
                with self._db() as db:
                    db.execute("INSERT OR IGNORE INTO launch_runs VALUES (?, ?, ?)",
                               (launch_id, session.run_id.value, _now()))
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

    def _public_row(self, row: sqlite3.Row, *, inspect_runtime: bool = True) -> dict[str, Any]:
        result = {key: row[key] for key in (
            "id", "agent_id", "task", "session_id", "run_id", "status",
            "error_code", "created_at", "updated_at", "conversation_id", "turn_index",
            "title", "pinned", "archived", "message",
        )}
        result["task"] = project_data(
            row["task"], view=PrivacyView.REDACTED_PUBLIC,
        ).data
        result["message"] = project_data(
            row["message"] or row["task"], view=PrivacyView.REDACTED_PUBLIC,
        ).data
        if result["title"]:
            result["title"] = project_data(
                result["title"], view=PrivacyView.REDACTED_PUBLIC,
            ).data
        result["final_result"] = json.loads(row["final_result"]) if row["final_result"] else None
        active = row["id"] in self._futures and not self._futures[row["id"]].done()
        if row["status"] in {"queued", "running"} and not active:
            result["status"] = "unknown"
            result["error_code"] = "process_not_observed"
        if inspect_runtime and row["session_id"]:
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
        if row["turn_index"] == 0:
            with self._db() as db:
                latest = db.execute(
                    "SELECT * FROM launches WHERE conversation_id = ? ORDER BY turn_index DESC LIMIT 1",
                    (row["id"],),
                ).fetchone()
            if latest is not None and latest["id"] != row["id"]:
                result["latest_status"] = self._public_row(latest, inspect_runtime=inspect_runtime)["status"]
            else:
                result["latest_status"] = result["status"]
        return result

    def agent_capabilities(self, agent_id: str, launch_id: str | None = None) -> dict[str, Any]:
        spec = self.agents.get(agent_id)
        if spec is None:
            raise StudioError("agent_not_registered")
        try:
            adapter = spec.load_adapter()
        except RegistryError as exc:
            raise StudioError(str(exc)) from exc
        declared = adapter.capabilities() if adapter else {}
        if not isinstance(declared, dict):
            raise StudioError("studio_adapter_invalid")
        allowed = {"continuation", "views", "inputs", "description"}
        if set(declared) - allowed:
            raise StudioError("studio_adapter_invalid")
        result: dict[str, Any] = {
            "agent_id": agent_id,
            "inputs": ["text"], "views": ["timeline", "tools", "graph", "artifacts", "diagnostics"],
            "operations": {"start": {"available": True}},
        }
        if isinstance(declared.get("views"), list):
            declared_views = declared["views"]
            assert isinstance(declared_views, list)
            result["views"] = sorted(set(result["views"] + [
                view for view in declared_views if isinstance(view, str)
                and view in {"files", "diff"}
            ]))
        if launch_id is not None:
            row = self._row(launch_id)
            if row["agent_id"] != agent_id:
                raise StudioError("agent_mismatch")
            with self._db() as db:
                latest = db.execute(
                    "SELECT * FROM launches WHERE conversation_id = ? ORDER BY turn_index DESC LIMIT 1",
                    (row["conversation_id"],),
                ).fetchone()
            current = self._public_row(latest)
            terminal = current["status"] not in {"queued", "running", "unknown"}
            result["operations"]["message"] = {
                "available": bool(adapter and declared.get("continuation") and terminal),
                "reason": None if adapter and declared.get("continuation") and terminal
                else ("session_busy" if not terminal else "continuation_unsupported"),
            }
            result["operations"]["resume"] = {
                "available": bool(current.get("can_resume")),
                "reason": None if current.get("can_resume") else "session_not_resumable",
            }
        return result

    def get_session(self, launch_id: str) -> dict[str, Any]:
        return self._public_row(self._row(launch_id))

    def list_sessions(self) -> list[dict[str, Any]]:
        return self.list_sessions_page()["items"]

    def list_sessions_page(self, *, before: str | None = None, limit: int = 50,
                           include_archived: bool = False,
                           search: str = "", summary: bool = False) -> dict[str, Any]:
        if limit < 1 or limit > 100:
            raise StudioError("page_limit_invalid")
        if before is not None and (len(before) > 80 or not before):
            raise StudioError("page_cursor_invalid")
        if not isinstance(search, str) or len(search) > 120:
            raise StudioError("search_invalid")
        with self._db() as db:
            where = "turn_index = 0 AND archived = ?"
            args: list[Any] = [int(include_archived)]
            if search:
                escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                where += " AND (title LIKE ? ESCAPE '\\' OR message LIKE ? ESCAPE '\\' OR agent_id LIKE ? ESCAPE '\\')"
                args.extend([f"%{escaped}%"] * 3)
            if before is not None:
                cursor = db.execute("SELECT pinned, created_at, id FROM launches WHERE id = ? AND turn_index = 0",
                                    (before,)).fetchone()
                if cursor is None:
                    raise StudioError("page_cursor_invalid")
                where += " AND (pinned < ? OR (pinned = ? AND "
                where += "(created_at < ? OR (created_at = ? AND id < ?))))"
                args.extend([cursor["pinned"], cursor["pinned"],
                             cursor["created_at"], cursor["created_at"], cursor["id"]])
            rows = db.execute(f"SELECT * FROM launches WHERE {where} "
                              "ORDER BY pinned DESC, created_at DESC, id DESC LIMIT ?",
                              (*args, limit + 1)).fetchall()
        items = [self._public_row(row, inspect_runtime=not summary) for row in rows[:limit]]
        return {"items": items, "next_before": items[-1]["id"] if len(rows) > limit else None}

    def _conversation_rows(self, conversation_id: str) -> list[sqlite3.Row]:
        with self._db() as db:
            return db.execute("SELECT * FROM launches WHERE conversation_id = ? ORDER BY turn_index",
                              (conversation_id,)).fetchall()

    def conversation(self, conversation_id: str, *, after_turn: int = -1,
                     limit: int = 50) -> dict[str, Any]:
        if after_turn < -1 or limit < 1 or limit > 100:
            raise StudioError("page_cursor_invalid")
        root = self._row(conversation_id)
        if root["turn_index"] != 0:
            raise StudioError("session_not_found")
        with self._db() as db:
            rows = db.execute("SELECT * FROM launches WHERE conversation_id = ? AND turn_index > ? "
                              "ORDER BY turn_index LIMIT ?", (conversation_id, after_turn, limit + 1)).fetchall()
        items = [self._public_row(row) for row in rows[:limit]]
        return {"items": items, "next_after_turn": items[-1]["turn_index"] if len(rows) > limit else None}

    def update_conversation(self, conversation_id: str, *, title: str | None = None,
                            pinned: bool | None = None, archived: bool | None = None) -> dict[str, Any]:
        root = self._row(conversation_id)
        if root["turn_index"] != 0:
            raise StudioError("session_not_found")
        fields: dict[str, Any] = {}
        if title is not None:
            if not isinstance(title, str) or not title.strip() or len(title) > 120:
                raise StudioError("title_invalid")
            fields["title"] = title.strip()
        if pinned is not None:
            if not isinstance(pinned, bool):
                raise StudioError("metadata_invalid")
            fields["pinned"] = int(pinned)
        if archived is not None:
            if not isinstance(archived, bool):
                raise StudioError("metadata_invalid")
            fields["archived"] = int(archived)
        if not fields:
            raise StudioError("metadata_invalid")
        self._update(conversation_id, **fields)
        return self.get_session(conversation_id)

    def runs(self, launch_id: str) -> list[dict[str, str]]:
        self._row(launch_id)
        with self._db() as db:
            rows = db.execute("SELECT run_id, created_at FROM launch_runs WHERE launch_id = ? "
                              "ORDER BY created_at, run_id", (launch_id,)).fetchall()
        return [dict(row) for row in rows]

    def events(self, launch_id: str, *, after: int = 0, limit: int = 100,
               run_id: str | None = None) -> dict[str, Any]:
        if after < 0 or limit < 1 or limit > 256:
            raise StudioError("event_cursor_invalid")
        row = self._row(launch_id)
        if run_id is not None and run_id not in {run["run_id"] for run in self.runs(launch_id)}:
            raise StudioError("run_not_found")
        selected_run = run_id or row["run_id"]
        if not selected_run:
            return {"records": [], "next_after": after, "unknown": True}
        spec = self.agents.get(row["agent_id"])
        if spec is None:
            raise StudioError("agent_not_registered")
        config = self._config(spec)
        source = (Path(config.runtime.trajectory.output).expanduser().resolve()
                  if config.runtime.trajectory.output else _session_store_path(config).parent)
        try:
            with self._trajectory_reader(source) as reader:
                page = read_page(
                    reader, TrajectoryQuery(run_id=selected_run, after_sequence=after, limit=limit),
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

    @contextmanager
    def _trajectory_reader(self, source: Path) -> Iterator[Any]:
        # Journal readers revalidate bytes on every page; JSON readers are
        # materialized snapshots and must never be reused across requests.
        with self._reader_lock:
            if self._closed:
                raise StudioError("studio_closed")
            if ((source.is_file() and source.suffix != ".journal")
                    or (source.is_dir() and not (source / "trajectory.journal").is_file()
                        and (source / "trajectory.json").is_file())):
                # The JSON adapter materializes the entire file before reporting
                # bounded_read=False. Reject before allocating that snapshot.
                raise BoundedReadUnsupported("historical_bounded_read_unsupported")
            cacheable = ((source.suffix == ".journal" and source.is_file())
                         or (source.is_dir() and (source / "trajectory.journal").is_file()))
            reader = self._readers.pop(source, None) if cacheable else None
            if reader is None:
                reader = default_reader(source)
            if cacheable:
                self._readers[source] = reader
                while len(self._readers) > self._max_readers:
                    _, evicted = self._readers.popitem(last=False)
                    evicted.close()
            try:
                yield reader
            except BaseException:
                if cacheable:
                    self._readers.pop(source, None)
                    reader.close()
                raise
            finally:
                if not cacheable:
                    close = getattr(reader, "close", None)
                    if callable(close):
                        close()

    def wait_for_idle(self) -> None:
        while True:
            with self._lock:
                pending = list(self._futures.values())
            if not pending:
                return
            for future in pending:
                future.result()

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._pool.shutdown(wait=True)
        with self._reader_lock:
            for reader in self._readers.values():
                reader.close()
            self._readers.clear()
