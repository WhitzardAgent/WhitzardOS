import { useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent as ReactKeyboardEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { eventSummary, eventTitle, sessionState, toolFacts } from "./view";
import type { RecordFact } from "./view";
import "./style.css";

type Agent = { id: string; name: string; description: string };
type Session = {
  id: string;
  conversation_id: string;
  turn_index: number;
  agent_id: string;
  task: string;
  message: string;
  session_id: string | null;
  run_id: string | null;
  status: string;
  can_resume?: boolean;
  final_result: unknown;
  error_code: string | null;
  created_at: string;
  title?: string | null;
  pinned?: number;
  archived?: number;
  latest_status?: string;
};
type Page<T> = {
  items: T[];
  next_before?: string | null;
  next_after_turn?: number | null;
};
type EventPage = {
  records: RecordFact[];
  next_after: number;
  has_more?: boolean;
  unknown?: boolean;
};
type Capabilities = {
  views: string[];
  operations: Record<string, { available: boolean; reason?: string | null }>;
};
type RunRef = { run_id: string; created_at: string };
type Lang = "zh" | "en";
type Tab =
  | "timeline"
  | "tools"
  | "graph"
  | "artifacts"
  | "diagnostics"
  | "files"
  | "diff";

const copy = {
  zh: {
    new: "新建任务",
    search: "搜索会话",
    recent: "最近会话",
    agents: "智能体",
    local: "本地工作台",
    details: "检查",
    close: "关闭",
    welcome: "今天要完成什么？",
    choose: "选择智能体并描述任务，运行过程会保存在会话中。",
    select: "选择智能体",
    placeholder: "描述任务或追加需求…",
    send: "发送",
    sending: "提交中…",
    resume: "恢复已保存的运行",
    loading: "加载中…",
    empty: "还没有会话",
    offline: "与本地服务断开连接。已加载的记录仍可查看。",
    reconnect: "重新连接",
    unavailable: "没有可显示的已保存事实",
    noResult: "未保存可显示的结果",
    result: "结果",
    process: "执行过程",
    facts: "条已保存事实",
    more: "加载更多",
    rename: "重命名",
    pin: "置顶",
    unpin: "取消置顶",
    archive: "归档",
    archived: "已归档",
    all: "所有会话",
    noAgent: "本地清单中没有智能体",
    newTurn: "继续此会话",
    unsupported: "此智能体未提供后续输入能力",
    busy: "当前运行尚未结束",
    run: "运行",
    timeMissing: "时间未知",
    noFacts: "运行时未保存该视图的事实",
    theme: "切换主题",
    language: "切换语言",
    overview: "概览",
    timeline: "时间线",
    tools: "工具",
    graph: "工作图",
    artifacts: "产出",
    diagnostics: "诊断",
    files: "文件",
    diff: "差异",
    copy: "复制代码",
    unknown: "状态未知",
    error: "操作失败",
    updated: "已更新",
    drafts: "草稿只保存在此浏览器",
    inspectTurn: "检查此轮",
    stopUnavailable: "当前执行器没有可确认的停止能力",
    history: "历史",
    noTurn: "会话记录缺失",
    recovery: "运行事实可查看，进程状态暂无法确认。",
  },
  en: {
    new: "New task",
    search: "Search conversations",
    recent: "Recent",
    agents: "Agents",
    local: "Local workspace",
    details: "Inspect",
    close: "Close",
    welcome: "What would you like to work on?",
    choose: "Choose an agent and describe a task. Its progress is saved here.",
    select: "Choose an agent",
    placeholder: "Describe a task or follow-up…",
    send: "Send",
    sending: "Sending…",
    resume: "Resume saved run",
    loading: "Loading…",
    empty: "No conversations yet",
    offline: "Disconnected from the local service. Saved facts remain visible.",
    reconnect: "Reconnect",
    unavailable: "No saved facts are available",
    noResult: "No displayable result was saved",
    result: "Result",
    process: "Process",
    facts: "saved facts",
    more: "Load more",
    rename: "Rename",
    pin: "Pin",
    unpin: "Unpin",
    archive: "Archive",
    archived: "Archived",
    all: "All conversations",
    noAgent: "No agents in the local registry",
    newTurn: "Continue conversation",
    unsupported: "This agent does not support follow-up input",
    busy: "This run has not ended",
    run: "Run",
    timeMissing: "Time unknown",
    noFacts: "No facts were saved for this view",
    theme: "Switch theme",
    language: "Switch language",
    overview: "Overview",
    timeline: "Timeline",
    tools: "Tools",
    graph: "Work graph",
    artifacts: "Artifacts",
    diagnostics: "Diagnostics",
    files: "Files",
    diff: "Diff",
    copy: "Copy code",
    unknown: "Status unknown",
    error: "Action failed",
    updated: "Updated",
    drafts: "Drafts are saved only in this browser",
    inspectTurn: "Inspect turn",
    stopUnavailable: "This executor has no confirmed stop capability",
    history: "History",
    noTurn: "Conversation record unavailable",
    recovery: "Saved facts are available; process state is unconfirmed.",
  },
} as const;

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
  if (response.status === 403 && !sessionStorage.getItem("studio-reloaded")) {
    sessionStorage.setItem("studio-reloaded", "1");
    window.location.reload();
  }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error_code ?? "request_failed");
  sessionStorage.removeItem("studio-reloaded");
  return data as T;
}

export function StatusBadge({
  status,
  lang = "en",
}: {
  status: string;
  lang?: Lang;
}) {
  const state = sessionState(status);
  const labels: Record<string, string> = {
    queued: "排队中",
    running: "运行中",
    paused: "已暂停",
    waiting_input: "等待输入",
    completed: "已完成",
    failed: "失败",
    unknown: "状态未知",
  };
  return (
    <span className={`status status-${state.tone}`}>
      <span className="status-dot" />
      {lang === "zh" ? (labels[status] ?? status) : state.label}
    </span>
  );
}

export function AgentCard({
  agent,
  onSelect,
  lang = "en",
}: {
  agent: Agent;
  onSelect: () => void;
  lang?: Lang;
}) {
  return (
    <button className="agent-choice" type="button" onClick={onSelect}>
      <span className="agent-mark">{agent.name.slice(0, 1).toUpperCase()}</span>
      <span>
        <strong>{agent.name}</strong>
        <small>{agent.description}</small>
      </span>
      <span className="agent-arrow">
        {lang === "zh" ? "选择" : "Start a task"} ↗
      </span>
    </button>
  );
}

function initialId() {
  return (
    /^\/sessions\/([0-9a-f-]{36})$/.exec(window.location.pathname)?.[1] ?? null
  );
}
function valueText(value: unknown) {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}
function Fact({ record, lang }: { record: RecordFact; lang: Lang }) {
  const tools = toolFacts(record);
  return (
    <details className="fact">
      <summary>
        <span className="fact-icon">
          {record.kind === "tool_result"
            ? "⌘"
            : record.kind === "error"
              ? "!"
              : "·"}
        </span>
        <span>
          <strong>{eventTitle(record, lang)}</strong>
          <small>{eventSummary(record, lang)}</small>
        </span>
        <time>
          {record.occurred_at
            ? new Date(record.occurred_at).toLocaleTimeString(
                lang === "zh" ? "zh-CN" : "en-US",
              )
            : copy[lang].timeMissing}
        </time>
      </summary>
      {tools.length > 0 && (
        <div className="tool-outcomes">
          {tools.map((tool, index) => (
            <div className="tool-outcome" key={`${tool.tool_name}-${index}`}>
              <div>
                <strong>{tool.tool_name}</strong>
                {tool.status && <span>{tool.status}</span>}
                {tool.returncode !== null && (
                  <code>exit {tool.returncode}</code>
                )}
              </div>
              {tool.path && <code>{tool.path}</code>}
              {tool.stdout && <pre>{tool.stdout}</pre>}
              {tool.stderr && <pre className="tool-stderr">{tool.stderr}</pre>}
            </div>
          ))}
        </div>
      )}
      <details className="raw-fact">
        <summary>{lang === "zh" ? "原始事实" : "Raw fact"}</summary>
        <pre>{JSON.stringify(record.payload ?? {}, null, 2)}</pre>
      </details>
    </details>
  );
}

function MarkdownResult({ value, lang }: { value: unknown; lang: Lang }) {
  if (typeof value !== "string") return <pre>{valueText(value)}</pre>;
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children }) => <span>{children}</span>,
          img: ({ alt }) => <span>{alt}</span>,
          code: ({ children, className }) => (
            <code className={className}>{children}</code>
          ),
          pre: ({ children }) => (
            <div className="code-wrap">
              <button
                type="button"
                onClick={(event) => {
                  const code =
                    event.currentTarget.nextElementSibling?.textContent ?? "";
                  void navigator.clipboard.writeText(code);
                }}
                aria-label={copy[lang].copy}
              >
                {copy[lang].copy}
              </button>
              <pre>{children}</pre>
            </div>
          ),
        }}
      >
        {value}
      </ReactMarkdown>
    </div>
  );
}

export default function App() {
  const [lang, setLang] = useState<Lang>(() =>
    localStorage.getItem("studio-lang") === "en" ? "en" : "zh",
  );
  const t = copy[lang];
  const [theme, setTheme] = useState(() =>
    localStorage.getItem("studio-theme") === "light" ? "light" : "dark",
  );
  const [agents, setAgents] = useState<Agent[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [nextBefore, setNextBefore] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(initialId);
  const [turns, setTurns] = useState<Session[]>([]);
  const [nextTurn, setNextTurn] = useState<number | null>(null);
  const [selectedTurnId, setSelectedTurnId] = useState<string | null>(null);
  const [runs, setRuns] = useState<RunRef[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [agentId, setAgentId] = useState<string>("");
  const [task, setTask] = useState("");
  const [records, setRecords] = useState<RecordFact[]>([]);
  const [factUnavailable, setFactUnavailable] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("timeline");
  const [search, setSearch] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [disconnected, setDisconnected] = useState(false);
  const composer = useRef<HTMLTextAreaElement>(null);
  const navButton = useRef<HTMLButtonElement>(null);
  const inspectorButton = useRef<HTMLButtonElement>(null);
  const cursor = useRef(0);
  const selected = sessions.find((item) => item.id === selectedId);
  const currentTurn =
    turns.find((item) => item.id === selectedTurnId) ?? turns[turns.length - 1];
  const currentAgent = agents.find(
    (item) => item.id === (selected?.agent_id ?? agentId),
  );
  const canMessage = selectedId
    ? capabilities?.operations.message?.available === true
    : Boolean(agentId);
  const draftKey = `studio-draft:${selectedId ?? "new"}`;

  function sessionPage(before: string | null): Promise<Page<Session>> {
    const query = search.trim();
    if (query)
      return request<Page<Session>>("/api/sessions/search", "POST", {
        query,
        limit: 50,
        before,
        archived: showArchived,
      });
    return request<Page<Session>>(
      `/api/sessions?page=1&limit=50${before ? `&before=${before}` : ""}${showArchived ? "&archived=1" : ""}`,
    );
  }

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("studio-theme", theme);
  }, [theme]);
  useEffect(() => {
    document.documentElement.lang = lang;
    localStorage.setItem("studio-lang", lang);
  }, [lang]);
  useEffect(() => {
    setTask(localStorage.getItem(draftKey) ?? "");
  }, [draftKey]);
  useEffect(() => {
    localStorage.setItem(draftKey, task);
  }, [draftKey, task]);
  useEffect(() => {
    const handler = () => setSelectedId(initialId());
    window.addEventListener("popstate", handler);
    return () => window.removeEventListener("popstate", handler);
  }, []);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        document.getElementById("conversation-search")?.focus();
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "n") {
        event.preventDefault();
        navigate(null);
        composer.current?.focus();
      }
      if (event.key === "Escape") {
        if (navOpen) {
          setNavOpen(false);
          navButton.current?.focus();
        } else if (inspectorOpen) {
          setInspectorOpen(false);
          inspectorButton.current?.focus();
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [navOpen, inspectorOpen]);

  useEffect(() => {
    let alive = true;
    setSessions([]);
    setNextBefore(null);
    async function refresh() {
      try {
        const [nextAgents, page] = await Promise.all([
          request<Agent[]>("/api/agents"),
          sessionPage(null),
        ]);
        if (!alive) return;
        setAgents(nextAgents);
        setSessions((previous) => [
          ...page.items,
          ...previous.filter(
            (item) => !page.items.some((fresh) => fresh.id === item.id),
          ),
        ]);
        setNextBefore((previous) => previous ?? page.next_before ?? null);
        setDisconnected(false);
        setError(null);
        if (nextAgents.length)
          setAgentId((previous) => previous || nextAgents[0].id);
      } catch (cause) {
        if (alive) {
          setDisconnected(true);
          setError((cause as Error).message);
        }
      } finally {
        if (alive) setLoading(false);
      }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 6000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [showArchived, search]);
  useEffect(() => {
    if (!selectedId) {
      setTurns([]);
      setCapabilities(null);
      return;
    }
    let alive = true;
    async function load() {
      try {
        const [page, root] = await Promise.all([
          request<Page<Session>>(`/api/sessions/${selectedId}/turns?limit=50`),
          request<Session>(`/api/sessions/${selectedId}`),
        ]);
        if (!alive) return;
        setTurns(page.items);
        setNextTurn(page.next_after_turn ?? null);
        setSelectedTurnId((previous) =>
          previous && page.items.some((item) => item.id === previous)
            ? previous
            : (page.items[page.items.length - 1]?.id ?? null),
        );
        setSessions((previous) =>
          previous.some((item) => item.id === root.id)
            ? previous.map((item) => (item.id === root.id ? root : item))
            : [root, ...previous],
        );
        const caps = await request<Capabilities>(
          `/api/sessions/${selectedId}/capabilities`,
        );
        if (alive) setCapabilities(caps);
      } catch (cause) {
        if (alive) setError((cause as Error).message);
      }
    }
    void load();
    const timer = window.setInterval(() => void load(), 4000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [selectedId]);
  useEffect(() => {
    if (!currentTurn?.id) {
      setRuns([]);
      setSelectedRunId(null);
      return;
    }
    let alive = true;
    setSelectedRunId(currentTurn.run_id);
    void request<RunRef[]>(`/api/sessions/${currentTurn.id}/runs`)
      .then((items) => {
        if (alive) setRuns(items);
      })
      .catch((cause) => {
        if (alive) setError((cause as Error).message);
      });
    return () => {
      alive = false;
    };
  }, [currentTurn?.id, currentTurn?.run_id]);
  useEffect(() => {
    if (!currentTurn?.run_id) {
      setRecords([]);
      setFactUnavailable(false);
      return;
    }
    let alive = true;
    let stream: EventSource | null = null;
    let reconnect: number | undefined;
    const turnId = currentTurn.id,
      runId = selectedRunId ?? currentTurn.run_id;
    cursor.current = 0;
    setRecords([]);
    setFactUnavailable(false);
    const append = (batch: RecordFact[]) => {
      if (!alive) return;
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
        while (more && alive) {
          const page = await request<EventPage>(
            `/api/sessions/${turnId}/events?run_id=${encodeURIComponent(runId!)}&after=${cursor.current}&limit=100`,
          );
          append(page.records);
          if (page.records.length) setFactUnavailable(false);
          else if (page.unknown && cursor.current === 0)
            setFactUnavailable(true);
          more = Boolean(page.has_more && page.records.length);
        }
        if (
          !alive ||
          currentTurn?.status !== "running" ||
          runId !== currentTurn.run_id
        )
          return;
        stream = new EventSource(
          `/api/sessions/${turnId}/stream?run_id=${encodeURIComponent(runId!)}&after=${cursor.current}`,
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
          if (alive) reconnect = window.setTimeout(() => void follow(), 2500);
        };
      } catch (cause) {
        if (alive) {
          setError((cause as Error).message);
          reconnect = window.setTimeout(() => void follow(), 4000);
        }
      }
    }
    void follow();
    return () => {
      alive = false;
      stream?.close();
      clearTimeout(reconnect);
    };
  }, [
    currentTurn?.id,
    currentTurn?.run_id,
    currentTurn?.status,
    selectedRunId,
  ]);

  function navigate(id: string | null) {
    setSelectedId(id);
    setSelectedTurnId(null);
    setSelectedRunId(null);
    setNavOpen(false);
    history.pushState({}, "", id ? `/sessions/${id}` : "/");
  }
  async function loadMoreSessions() {
    if (!nextBefore) return;
    try {
      const page = await sessionPage(nextBefore);
      setSessions((previous) => [
        ...previous,
        ...page.items.filter((item) => !previous.some((p) => p.id === item.id)),
      ]);
      setNextBefore(page.next_before ?? null);
    } catch (cause) {
      setError((cause as Error).message);
    }
  }
  async function loadMoreTurns() {
    if (!selectedId || nextTurn === null) return;
    try {
      const page = await request<Page<Session>>(
        `/api/sessions/${selectedId}/turns?after=${nextTurn}&limit=50`,
      );
      setTurns((previous) => [...previous, ...page.items]);
      setNextTurn(page.next_after_turn ?? null);
    } catch (cause) {
      setError((cause as Error).message);
    }
  }
  async function updateMeta(body: object) {
    if (!selectedId) return;
    try {
      const next = await request<Session>(
        `/api/sessions/${selectedId}`,
        "PATCH",
        body,
      );
      setSessions((previous) =>
        previous.map((item) => (item.id === next.id ? next : item)),
      );
    } catch (cause) {
      setError((cause as Error).message);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!task.trim() || pending || disconnected || !canMessage) return;
    setPending(true);
    setError(null);
    try {
      const next = selectedId
        ? await request<Session>(
            `/api/sessions/${selectedId}/messages`,
            "POST",
            { message: task.trim() },
          )
        : await request<Session>("/api/sessions", "POST", {
            agent_id: agentId,
            task: task.trim(),
          });
      localStorage.removeItem(draftKey);
      setTask("");
      if (!selectedId) {
        setSessions((previous) => [next, ...previous]);
        navigate(next.id);
      } else {
        setTurns((previous) => [...previous, next]);
        setSelectedTurnId(next.id);
      }
      composer.current?.focus();
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setPending(false);
    }
  }
  async function resume() {
    if (!currentTurn || pending) return;
    setPending(true);
    try {
      const next = await request<Session>(
        `/api/sessions/${currentTurn.id}/resume`,
        "POST",
      );
      setTurns((previous) =>
        previous.map((item) => (item.id === next.id ? next : item)),
      );
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setPending(false);
    }
  }
  function composerKey(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }
  const visibleSessions = sessions.filter(
    (item) =>
      (showArchived ? Boolean(item.archived) : !item.archived) &&
      `${item.title ?? item.task} ${item.agent_id}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const tabNames: Tab[] = [
    "timeline",
    "tools",
    "graph",
    "artifacts",
    "diagnostics",
    ...(capabilities?.views.includes("files") ? ["files" as Tab] : []),
    ...(capabilities?.views.includes("diff") ? ["diff" as Tab] : []),
  ];
  const kinds: Record<Tab, string[] | null> = {
    timeline: null,
    tools: ["tool_batch", "tool_slot", "tool_result"],
    graph: ["work_graph", "ownership"],
    artifacts: ["artifact"],
    diagnostics: ["error", "loss", "budget", "sandbox", "lifecycle"],
    files: ["file"],
    diff: ["diff"],
  };
  const inspection = records.filter((item) =>
    tab === "files"
      ? item.kind === "file" ||
        toolFacts(item).some((tool) => tool.path !== null)
      : !kinds[tab] || kinds[tab]?.includes(item.kind),
  );
  return (
    <div className={`app-shell ${inspectorOpen ? "with-inspector" : ""}`}>
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
        <button
          className="new-task"
          onClick={() => {
            navigate(null);
            composer.current?.focus();
          }}
        >
          ＋ <span>{t.new}</span>
          <kbd>⌘ N</kbd>
        </button>
        <label className="search-box">
          <span>⌕</span>
          <input
            id="conversation-search"
            type="search"
            placeholder={t.search}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            aria-label={t.search}
          />
          <kbd>⌘ K</kbd>
        </label>
        <div className="nav-heading">
          <span>{showArchived ? t.archived : t.recent}</span>
          <button onClick={() => setShowArchived(!showArchived)}>
            {showArchived ? t.all : t.archived}
          </button>
        </div>
        <div className="session-list">
          {visibleSessions.length ? (
            visibleSessions.map((item) => (
              <button
                key={item.id}
                className={`session-link ${selectedId === item.id ? "selected" : ""}`}
                onClick={() => navigate(item.id)}
              >
                <span className="session-link-title">
                  {item.pinned ? "◆ " : ""}
                  {item.title ?? item.message ?? item.task}
                </span>
                <span className="session-link-meta">
                  <span>
                    {agents.find((agent) => agent.id === item.agent_id)?.name ??
                      item.agent_id}
                  </span>
                  <StatusBadge
                    status={item.latest_status ?? item.status}
                    lang={lang}
                  />
                </span>
              </button>
            ))
          ) : (
            <p className="nav-empty">{loading ? t.loading : t.empty}</p>
          )}
          {nextBefore && (
            <button
              className="load-more"
              onClick={() => void loadMoreSessions()}
            >
              {t.more}
            </button>
          )}
        </div>
        <div className="sidebar-footer">
          <span className={`connection-dot ${disconnected ? "lost" : ""}`} />
          {t.local}
          <div className="footer-actions">
            <button
              onClick={() => setLang(lang === "zh" ? "en" : "zh")}
              aria-label={t.language}
            >
              {lang === "zh" ? "EN" : "中"}
            </button>
            <button
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              aria-label={t.theme}
            >
              {theme === "dark" ? "☼" : "◐"}
            </button>
          </div>
        </div>
      </nav>
      {navOpen && (
        <button
          className="drawer-scrim"
          onClick={() => {
            setNavOpen(false);
            navButton.current?.focus();
          }}
          aria-label={t.close}
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
            >
              ☰
            </button>
            <span className="breadcrumb">
              {currentAgent?.name ?? "QitOS Studio"}
              {selectedId && (
                <>
                  <span> / </span>
                  {selected?.title ??
                    selected?.message ??
                    selected?.task ??
                    t.history}
                </>
              )}
            </span>
          </div>
          <div className="topbar-actions">
            {selectedId && (
              <>
                <button
                  className="icon-button"
                  onClick={() => {
                    const title = window.prompt(
                      t.rename,
                      selected?.title ?? selected?.message ?? "",
                    );
                    if (title) void updateMeta({ title });
                  }}
                  aria-label={t.rename}
                >
                  ✎
                </button>
                <button
                  className="icon-button"
                  onClick={() => void updateMeta({ pinned: !selected?.pinned })}
                  aria-label={selected?.pinned ? t.unpin : t.pin}
                >
                  ◆
                </button>
                <button
                  className="icon-button"
                  onClick={() => void updateMeta({ archived: true })}
                  aria-label={t.archive}
                >
                  ▣
                </button>
                <button
                  ref={inspectorButton}
                  className="text-button"
                  onClick={() => setInspectorOpen(!inspectorOpen)}
                  aria-expanded={inspectorOpen}
                >
                  {t.details} ▧
                </button>
              </>
            )}
          </div>
        </header>
        {error && (
          <div className="error-banner" role="alert">
            <strong>{t.error}</strong>
            <span>{error.replaceAll("_", " ")}</span>
            <button onClick={() => setError(null)} aria-label={t.close}>
              ×
            </button>
          </div>
        )}
        {disconnected && (
          <div className="connection-notice" role="status">
            {t.offline}
            <button
              onClick={() => {
                window.location.reload();
              }}
            >
              {t.reconnect}
            </button>
          </div>
        )}
        <div className="conversation-scroll" key={selectedId ?? "new"}>
          <div className="conversation">
            {!selectedId ? (
              <div className="welcome">
                <div className="welcome-symbol">Q</div>
                <h1>{t.welcome}</h1>
                <p>{t.choose}</p>
                {agents.length ? (
                  <div className="agent-grid">
                    {agents.map((agent) => (
                      <AgentCard
                        key={agent.id}
                        agent={agent}
                        lang={lang}
                        onSelect={() => {
                          setAgentId(agent.id);
                          composer.current?.focus();
                        }}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="empty-state">
                    {loading ? t.loading : t.noAgent}
                  </div>
                )}
              </div>
            ) : turns.length ? (
              <div className="turns">
                {turns.map((turn) => (
                  <section className="turn" key={turn.id}>
                    <div className="user-message">
                      <span className="message-label">
                        {agents.find((agent) => agent.id === turn.agent_id)
                          ?.name ?? turn.agent_id}{" "}
                        ·{" "}
                        {new Date(turn.created_at).toLocaleString(
                          lang === "zh" ? "zh-CN" : "en-US",
                        )}
                      </span>
                      <div className="message-bubble">
                        {turn.message ?? turn.task}
                      </div>
                    </div>
                    <div className="agent-message">
                      <div className="agent-message-head">
                        <span className="agent-mark small">
                          {currentAgent?.name.slice(0, 1) ?? "Q"}
                        </span>
                        <strong>{currentAgent?.name ?? turn.agent_id}</strong>
                        <StatusBadge status={turn.status} lang={lang} />
                        <button
                          className="quiet-link"
                          onClick={() => {
                            setSelectedTurnId(turn.id);
                            setSelectedRunId(null);
                            setInspectorOpen(true);
                          }}
                        >
                          {t.inspectTurn}
                        </button>
                      </div>
                      {turn.status === "unknown" && (
                        <div className="inline-notice">{t.recovery}</div>
                      )}
                      {turn.final_result !== null ? (
                        <MarkdownResult value={turn.final_result} lang={lang} />
                      ) : (
                        <div className="muted-line">
                          {["queued", "running"].includes(turn.status)
                            ? `${t.process}…`
                            : turn.error_code
                              ? `${t.error}: ${turn.error_code}`
                              : t.noResult}
                        </div>
                      )}
                      {turn.id === currentTurn?.id && records.length > 0 && (
                        <details className="process-block">
                          <summary>
                            {t.process} · {records.length} {t.facts}
                          </summary>
                          <div>
                            {records.slice(-30).map((record, index) => (
                              <Fact
                                record={record}
                                lang={lang}
                                key={`${record.sequence}-${index}`}
                              />
                            ))}
                          </div>
                        </details>
                      )}
                      {turn.can_resume && (
                        <button
                          className="secondary-button"
                          onClick={() => void resume()}
                          disabled={pending}
                        >
                          {t.resume}
                        </button>
                      )}
                    </div>
                  </section>
                ))}
                {nextTurn !== null && (
                  <button
                    className="load-more"
                    onClick={() => void loadMoreTurns()}
                  >
                    {t.more}
                  </button>
                )}
              </div>
            ) : (
              <div className="empty-state">
                {loading ? t.loading : t.noTurn}
              </div>
            )}
          </div>
        </div>
        <div className="composer-dock">
          <form className="composer" onSubmit={(event) => void submit(event)}>
            <textarea
              ref={composer}
              value={task}
              onChange={(event) => setTask(event.target.value)}
              onKeyDown={composerKey}
              placeholder={
                selectedId && !canMessage ? t.unsupported : t.placeholder
              }
              disabled={
                selectedId
                  ? !canMessage || disconnected
                  : disconnected || agents.length === 0
              }
              maxLength={16000}
              rows={2}
              aria-label={t.placeholder}
            />
            <div className="composer-bottom">
              <div className="composer-agent">
                {!selectedId && (
                  <select
                    value={agentId}
                    onChange={(event) => setAgentId(event.target.value)}
                    aria-label={t.select}
                  >
                    {agents.map((agent) => (
                      <option key={agent.id} value={agent.id}>
                        {agent.name}
                      </option>
                    ))}
                  </select>
                )}
                {selectedId && (
                  <span>
                    {canMessage
                      ? t.newTurn
                      : capabilities?.operations.message?.reason ===
                          "session_busy"
                        ? t.busy
                        : t.unsupported}
                  </span>
                )}
              </div>
              <span className="draft-note">{t.drafts}</span>
              <button
                className="send-button"
                type="submit"
                disabled={
                  pending || !task.trim() || !canMessage || disconnected
                }
                aria-label={t.send}
              >
                {pending ? "…" : "↑"}
              </button>
            </div>
          </form>
        </div>
      </main>
      {inspectorOpen && (
        <aside className="inspector" aria-label="Run inspector">
          <header className="inspector-header">
            <div>
              <span className="eyebrow">QITOS / {t.run.toUpperCase()}</span>
              <h2>{t.details}</h2>
            </div>
            <button
              className="icon-button"
              onClick={() => {
                setInspectorOpen(false);
                inspectorButton.current?.focus();
              }}
              aria-label={t.close}
            >
              ×
            </button>
          </header>
          <div className="run-identity">
            {runs.length > 1 ? (
              <select
                value={selectedRunId ?? currentTurn?.run_id ?? ""}
                onChange={(event) => setSelectedRunId(event.target.value)}
                aria-label={t.run}
              >
                {runs.map((run) => (
                  <option key={run.run_id} value={run.run_id}>
                    {t.run} {run.run_id.slice(0, 12)}
                  </option>
                ))}
              </select>
            ) : currentTurn?.run_id ? (
              `${t.run} ${currentTurn.run_id.slice(0, 12)}`
            ) : (
              t.unavailable
            )}
          </div>
          <div className="tab-list" role="tablist">
            {tabNames.map((name) => (
              <button
                key={name}
                role="tab"
                aria-selected={tab === name}
                className={tab === name ? "tab active" : "tab"}
                onClick={() => setTab(name)}
              >
                {t[name]}
              </button>
            ))}
          </div>
          <div className="inspector-body" role="tabpanel">
            {inspection.length ? (
              inspection.map((record, index) => (
                <Fact
                  record={record}
                  lang={lang}
                  key={`${record.sequence}-${index}`}
                />
              ))
            ) : (
              <div className="empty-inspector">
                <span>◇</span>
                <strong>{factUnavailable ? t.unavailable : t.noFacts}</strong>
              </div>
            )}
          </div>
        </aside>
      )}
    </div>
  );
}
