import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { eventSummary, eventTitle, sessionState } from "./view";
import type { RecordFact } from "./view";
import "./style.css";

type Agent = { id: string; name: string; description: string };
type Session = {
  id: string;
  agent_id: string;
  task: string;
  session_id: string | null;
  run_id: string | null;
  status: string;
  lifecycle?: string;
  can_resume?: boolean;
  final_result: unknown;
  error_code: string | null;
  created_at: string;
};
type EventPage = {
  records: RecordFact[];
  next_after: number;
  has_more?: boolean;
  unknown?: boolean;
};
type Tab = "timeline" | "tools" | "graph" | "artifacts" | "diagnostics";

async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const csrf =
    document.querySelector<HTMLMetaElement>('meta[name="studio-csrf"]')
      ?.content ?? "";
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers:
      method === "GET"
        ? {}
        : { "Content-Type": "application/json", "X-Studio-CSRF": csrf },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error_code ?? "request_failed");
  return data as T;
}

export function StatusBadge({ status }: { status: string }) {
  const state = sessionState(status);
  return (
    <span className={`status status-${state.tone}`}>
      <span className="status-dot" />
      {state.label}
    </span>
  );
}

export function AgentCard({
  agent,
  onSelect,
}: {
  agent: Agent;
  onSelect: () => void;
}) {
  return (
    <button className="agent-card" onClick={onSelect} type="button">
      <span className="agent-mark" aria-hidden="true">
        {agent.name.slice(0, 1).toUpperCase()}
      </span>
      <span className="agent-card-copy">
        <strong>{agent.name}</strong>
        <span>{agent.description || "A QitOS agent ready for a task."}</span>
      </span>
      <span className="agent-card-action">
        Start a task <span aria-hidden="true">↗</span>
      </span>
    </button>
  );
}

function FactCard({ record }: { record: RecordFact }) {
  return (
    <details className="fact-card">
      <summary>
        <span className="fact-kind">{eventTitle(record)}</span>
        <span className="fact-summary">{eventSummary(record)}</span>
        <span className="fact-time">
          {record.occurred_at
            ? new Date(record.occurred_at).toLocaleTimeString()
            : "Time unavailable"}
        </span>
      </summary>
      <pre>{JSON.stringify(record.payload ?? {}, null, 2)}</pre>
    </details>
  );
}

function Inspector({
  records,
  tab,
  unavailable,
  onTab,
  onClose,
}: {
  records: RecordFact[];
  tab: Tab;
  unavailable: boolean;
  onTab: (tab: Tab) => void;
  onClose: () => void;
}) {
  const tabs: { id: Tab; label: string }[] = [
    { id: "timeline", label: "Timeline" },
    { id: "tools", label: "Tools" },
    { id: "graph", label: "Work graph" },
    { id: "artifacts", label: "Artifacts" },
    { id: "diagnostics", label: "Diagnostics" },
  ];
  const kinds: Record<Tab, string[] | null> = {
    timeline: null,
    tools: ["tool_batch", "tool_slot", "tool_result"],
    graph: ["work_graph", "ownership"],
    artifacts: ["artifact"],
    diagnostics: ["error", "loss", "budget", "sandbox", "lifecycle"],
  };
  const visible = records.filter(
    (record) => !kinds[tab] || kinds[tab]?.includes(record.kind),
  );
  return (
    <aside className="inspector" aria-label="Run inspector">
      <header className="inspector-header">
        <div>
          <span className="eyebrow">OBSERVE</span>
          <h2>Run details</h2>
        </div>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label="Close inspector"
        >
          ×
        </button>
      </header>
      <div className="tab-list" role="tablist" aria-label="Inspector views">
        {tabs.map((item) => (
          <button
            key={item.id}
            role="tab"
            aria-selected={tab === item.id}
            className={tab === item.id ? "tab active" : "tab"}
            onClick={() => onTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="inspector-body" role="tabpanel">
        {visible.length ? (
          visible.map((record, index) => (
            <FactCard
              key={`${record.sequence ?? "unknown"}-${index}`}
              record={record}
            />
          ))
        ) : (
          <div className="empty-inspector">
            <span className="empty-symbol">◇</span>
            <strong>
              {unavailable
                ? "Recorded facts unavailable"
                : `No ${tabs.find((item) => item.id === tab)?.label.toLowerCase()} facts yet`}
            </strong>
            <p>
              QitOS only shows facts the runtime recorded. Missing data is not
              treated as success.
            </p>
          </div>
        )}
      </div>
    </aside>
  );
}

function initialSessionId() {
  const match = /^\/sessions\/([0-9a-f-]{36})$/.exec(window.location.pathname);
  return match?.[1] ?? null;
}

export default function App() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(initialSessionId);
  const [agentId, setAgentId] = useState<string | null>(null);
  const [task, setTask] = useState("");
  const [records, setRecords] = useState<RecordFact[]>([]);
  const [factUnavailable, setFactUnavailable] = useState(false);
  const [followEpoch, setFollowEpoch] = useState(0);
  const [tab, setTab] = useState<Tab>("timeline");
  const [inspectorOpen, setInspectorOpen] = useState(
    () => !window.matchMedia("(max-width: 1180px)").matches,
  );
  const [navOpen, setNavOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [disconnected, setDisconnected] = useState(false);
  const [theme, setTheme] = useState(() =>
    localStorage.getItem("studio-theme") === "light" ? "light" : "dark",
  );
  const cursor = useRef(0);
  const navButton = useRef<HTMLButtonElement>(null);
  const detailButton = useRef<HTMLButtonElement>(null);

  function closeNavigation() {
    setNavOpen(false);
    navButton.current?.focus();
  }

  function closeDetails() {
    setInspectorOpen(false);
    detailButton.current?.focus();
  }

  function navigate(id: string | null) {
    setSelectedId(id);
    setAgentId(null);
    if (navOpen) closeNavigation();
    history.pushState({}, "", id ? `/sessions/${id}` : "/");
  }

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("studio-theme", theme);
  }, [theme]);

  useEffect(() => {
    const onPop = () => setSelectedId(initialSessionId());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (navOpen) closeNavigation();
        else if (inspectorOpen) closeDetails();
      }
    };
    window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, [navOpen, inspectorOpen]);

  useEffect(() => {
    let alive = true;
    async function refresh() {
      try {
        const [nextAgents, nextSessions] = await Promise.all([
          request<Agent[]>("/api/agents"),
          request<Session[]>("/api/sessions"),
        ]);
        if (alive) {
          setAgents(nextAgents);
          setSessions(nextSessions);
          setError(null);
          setDisconnected(false);
        }
      } catch (cause) {
        if (alive) {
          setError((cause as Error).message);
          setDisconnected(true);
        }
      } finally {
        if (alive) setLoading(false);
      }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setRecords([]);
      setFactUnavailable(false);
      return;
    }
    let disposed = false;
    let stream: EventSource | null = null;
    let reconnect: number | undefined;
    cursor.current = 0;
    setRecords([]);
    setFactUnavailable(false);
    const append = (batch: RecordFact[]) => {
      if (disposed) return;
      setRecords((previous) => {
        const seen = new Set(previous.map((item) => item.sequence));
        return [
          ...previous,
          ...batch.filter((item) => !seen.has(item.sequence)),
        ];
      });
      for (const item of batch)
        cursor.current = Math.max(cursor.current, item.sequence ?? 0);
    };
    async function follow() {
      try {
        let more = true;
        while (more && !disposed) {
          const page = await request<EventPage>(
            `/api/sessions/${selectedId}/events?after=${cursor.current}&limit=100`,
          );
          append(page.records);
          if (page.records.length) setFactUnavailable(false);
          else if (page.unknown && cursor.current === 0)
            setFactUnavailable(true);
          more = Boolean(page.has_more && page.records.length);
        }
        if (disposed) return;
        const detail = await request<Session>(`/api/sessions/${selectedId}`);
        if (disposed) return;
        setSessions((previous) =>
          previous.map((item) => (item.id === detail.id ? detail : item)),
        );
        if (!["queued", "running"].includes(detail.status)) return;
        stream = new EventSource(
          `/api/sessions/${selectedId}/stream?after=${cursor.current}`,
        );
        stream.onmessage = (event) => {
          try {
            append([JSON.parse(event.data) as RecordFact]);
          } catch {
            setError("event_decode_failed");
          }
        };
        stream.onerror = () => {
          stream?.close();
          stream = null;
          if (!disposed)
            reconnect = window.setTimeout(() => void follow(), 2500);
        };
      } catch (cause) {
        if (!disposed) {
          setError((cause as Error).message);
          setFactUnavailable(true);
          reconnect = window.setTimeout(() => void follow(), 4000);
        }
      }
    }
    void follow();
    return () => {
      disposed = true;
      stream?.close();
      window.clearTimeout(reconnect);
    };
  }, [selectedId, followEpoch]);

  const selected = sessions.find((item) => item.id === selectedId);
  const chosenAgent = agents.find((item) => item.id === agentId);
  const activityRecords = records.filter((item) =>
    ["step", "tool_result", "model_response", "error", "stop", "run"].includes(
      item.kind,
    ),
  );

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!agentId || !task.trim() || pending || disconnected) return;
    setPending(true);
    setError(null);
    try {
      const session = await request<Session>("/api/sessions", "POST", {
        agent_id: agentId,
        task: task.trim(),
      });
      setSessions((previous) => [session, ...previous]);
      setTask("");
      navigate(session.id);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setPending(false);
    }
  }

  async function resume() {
    if (!selected || pending) return;
    setPending(true);
    setError(null);
    try {
      const next = await request<Session>(
        `/api/sessions/${selected.id}/resume`,
        "POST",
      );
      setSessions((previous) =>
        previous.map((item) => (item.id === next.id ? next : item)),
      );
      setFollowEpoch((previous) => previous + 1);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setPending(false);
    }
  }

  return (
    <div
      className={`app-shell ${inspectorOpen && selectedId ? "with-inspector" : ""}`}
    >
      <nav
        className={`sidebar ${navOpen ? "sidebar-open" : ""}`}
        aria-label="Studio navigation"
      >
        <div className="brand">
          <span className="brand-mark">Q</span>
          <span>
            <strong>QitOS</strong>
            <small>STUDIO</small>
          </span>
        </div>
        <button className="new-task" onClick={() => navigate(null)}>
          ＋ <span>New task</span>
        </button>
        <div className="nav-heading">
          WORKSPACE <span>{sessions.length}</span>
        </div>
        <div className="session-list">
          {sessions.length ? (
            sessions.map((item) => (
              <button
                key={item.id}
                className={`session-link ${selectedId === item.id ? "selected" : ""}`}
                onClick={() => navigate(item.id)}
              >
                <span className="session-link-title">{item.task}</span>
                <span className="session-link-meta">
                  <span>
                    {agents.find((agent) => agent.id === item.agent_id)?.name ??
                      item.agent_id}
                  </span>
                  <StatusBadge status={item.status} />
                </span>
              </button>
            ))
          ) : (
            <p className="nav-empty">Your sessions will appear here.</p>
          )}
        </div>
        <div className="sidebar-footer">
          <span className="connection-dot" /> Local workspace{" "}
          <button
            className="theme-button"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          >
            {theme === "dark" ? "☼" : "◐"}
          </button>
        </div>
      </nav>
      {navOpen && (
        <button
          className="drawer-scrim"
          aria-label="Close navigation"
          onClick={closeNavigation}
        />
      )}
      <main className="main-panel">
        <header className="topbar">
          <div className="topbar-left">
            <button
              ref={navButton}
              className="icon-button mobile-menu"
              onClick={() => setNavOpen(true)}
              aria-label="Open navigation"
              aria-expanded={navOpen}
            >
              ☰
            </button>
            <span className="breadcrumb">
              Workspace <span>/</span> {selected ? "Session" : "Overview"}
            </span>
          </div>
          <div className="topbar-actions">
            {selected && (
              <button
                ref={detailButton}
                className="text-button"
                onClick={() => setInspectorOpen(!inspectorOpen)}
                aria-expanded={inspectorOpen}
              >
                {inspectorOpen ? "Hide details" : "Show details"}
              </button>
            )}
            <span className="topbar-version">LOCAL</span>
          </div>
        </header>
        {error && (
          <div className="error-banner" role="alert">
            <strong>Something needs attention</strong>
            <span>{error.replaceAll("_", " ")}</span>
            <button onClick={() => setError(null)} aria-label="Dismiss error">
              ×
            </button>
          </div>
        )}
        {disconnected && (
          <div className="notice connection-notice">
            Connection lost. Reconnecting to the local Studio service…
          </div>
        )}
        {selectedId ? (
          <div className="content session-content">
            {selected ? (
              <>
                <div className="session-heading">
                  <span className="eyebrow">
                    AGENT SESSION ·{" "}
                    {agents.find((agent) => agent.id === selected.agent_id)
                      ?.name ?? selected.agent_id}
                  </span>
                  <h1>{selected.task}</h1>
                  <div className="session-meta">
                    <StatusBadge status={selected.status} />
                    <span>
                      {selected.created_at
                        ? new Date(selected.created_at).toLocaleString()
                        : "Time unavailable"}
                    </span>
                    {selected.run_id && (
                      <code>Run {selected.run_id.slice(0, 8)}</code>
                    )}
                  </div>
                </div>
                {selected.status === "unknown" && (
                  <div className="notice">
                    This process is no longer observed. The saved Session and
                    trajectory remain available when present.
                  </div>
                )}
                <section className="activity">
                  <h2>
                    Activity <span>{records.length} recorded facts</span>
                  </h2>
                  {activityRecords.length ? (
                    activityRecords.map((item, index) => (
                      <FactCard
                        key={`${item.sequence}-${index}`}
                        record={item}
                      />
                    ))
                  ) : (
                    <div className="activity-empty">
                      {["queued", "running"].includes(selected.status) && (
                        <div className="pulse" />
                      )}
                      <strong>
                        {selected.status === "running" ||
                        selected.status === "queued"
                          ? "Waiting for recorded activity"
                          : factUnavailable
                            ? "Recorded activity unavailable"
                            : "No activity facts available"}
                      </strong>
                      <p>Events appear here after the runtime persists them.</p>
                    </div>
                  )}
                </section>
                {(selected.final_result !== null ||
                  selected.status === "completed") && (
                  <section className="result-card">
                    <span className="eyebrow">FINAL RESULT</span>
                    {selected.final_result === null ? (
                      <p>No displayable result was saved.</p>
                    ) : (
                      <pre>
                        {typeof selected.final_result === "string"
                          ? selected.final_result
                          : JSON.stringify(selected.final_result, null, 2)}
                      </pre>
                    )}
                  </section>
                )}
                {selected.error_code && (
                  <div className="notice notice-error">
                    Execution ended with <code>{selected.error_code}</code>.
                    Inspect recorded facts for details.
                  </div>
                )}
                {selected.can_resume && (
                  <button
                    className="primary-button resume-button"
                    onClick={() => void resume()}
                    disabled={pending}
                  >
                    {pending ? "Resuming…" : "Resume saved session"}
                  </button>
                )}
              </>
            ) : (
              <div className="page-empty">
                {loading
                  ? "Loading session…"
                  : disconnected
                    ? "Session unavailable while disconnected."
                    : "Session not found in this workspace."}
              </div>
            )}
          </div>
        ) : (
          <div className="content home-content">
            <div className="hero">
              <span className="eyebrow">QITOS / AGENT WORKBENCH</span>
              <h1>
                Build agents.
                <br />
                <em>See what they do.</em>
              </h1>
              <p>
                Start a task with any registered QitOS agent, then follow its
                decisions, tools, and results in one place.
              </p>
            </div>
            <section className="agents-section">
              <div className="section-heading">
                <div>
                  <span className="eyebrow">YOUR AGENTS</span>
                  <h2>Choose an agent</h2>
                </div>
                <span className="section-count">{agents.length} available</span>
              </div>
              {loading ? (
                <div className="page-empty">Loading agents…</div>
              ) : agents.length ? (
                <div className="agent-grid">
                  {agents.map((agent) => (
                    <AgentCard
                      key={agent.id}
                      agent={agent}
                      onSelect={() => setAgentId(agent.id)}
                    />
                  ))}
                </div>
              ) : (
                <div className="page-empty">
                  {disconnected
                    ? "Agents unavailable while disconnected."
                    : "No agents are registered. Add one to the local Studio registry."}
                </div>
              )}
            </section>
            {chosenAgent && (
              <form
                className="task-composer"
                onSubmit={(event) => void submit(event)}
              >
                <div className="composer-heading">
                  <span className="agent-mark small">
                    {chosenAgent.name[0].toUpperCase()}
                  </span>
                  <div>
                    <span className="eyebrow">NEW TASK</span>
                    <strong>{chosenAgent.name}</strong>
                  </div>
                  <button
                    type="button"
                    className="icon-button"
                    onClick={() => setAgentId(null)}
                    aria-label="Close composer"
                  >
                    ×
                  </button>
                </div>
                <label htmlFor="task-input">What should this agent do?</label>
                <textarea
                  id="task-input"
                  value={task}
                  onChange={(event) => setTask(event.target.value)}
                  placeholder="Describe the task and expected outcome…"
                  rows={4}
                  maxLength={16000}
                  autoFocus
                />
                <div className="composer-footer">
                  <span>
                    {disconnected
                      ? "Reconnect to start a task."
                      : "Each submission starts a new Session."}
                  </span>
                  <button
                    className="primary-button"
                    disabled={pending || disconnected || !task.trim()}
                  >
                    {pending ? "Starting…" : "Start task →"}
                  </button>
                </div>
              </form>
            )}
            <section className="recent-section">
              <div className="section-heading">
                <div>
                  <span className="eyebrow">CONTINUE EXPLORING</span>
                  <h2>Recent sessions</h2>
                </div>
              </div>
              {sessions.length ? (
                sessions.slice(0, 5).map((item) => (
                  <button
                    className="recent-row"
                    key={item.id}
                    onClick={() => navigate(item.id)}
                  >
                    <span>{item.task}</span>
                    <StatusBadge status={item.status} />
                    <span aria-hidden="true">↗</span>
                  </button>
                ))
              ) : (
                <p className="muted-copy">
                  Start a task to see its history here.
                </p>
              )}
            </section>
          </div>
        )}
      </main>
      {selectedId && inspectorOpen && (
        <Inspector
          records={records}
          tab={tab}
          unavailable={factUnavailable}
          onTab={setTab}
          onClose={closeDetails}
        />
      )}
    </div>
  );
}
