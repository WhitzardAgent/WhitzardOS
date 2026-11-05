export type RecordFact = {
  sequence?: number | null;
  kind: string;
  phase?: string | null;
  occurred_at?: string;
  payload?: Record<string, unknown>;
};

export type ToolFact = {
  tool_name: string;
  status: string | null;
  returncode: number | null;
  stdout: string | null;
  stderr: string | null;
  path: string | null;
};

export function toolFacts(event: RecordFact): ToolFact[] {
  if (event.kind !== "tool_slot") return [];
  const nested = event.payload?.payload;
  if (!nested || typeof nested !== "object") return [];
  const results = (nested as Record<string, unknown>).action_results;
  if (!Array.isArray(results)) return [];
  return results.flatMap((raw) => {
    if (!raw || typeof raw !== "object") return [];
    const item = raw as Record<string, unknown>;
    if (typeof item.tool_name !== "string" || item.tool_name === "env")
      return [];
    let output: Record<string, unknown> = {};
    try {
      if (typeof item.model_output === "string") {
        const decoded: unknown = JSON.parse(item.model_output);
        if (decoded && typeof decoded === "object" && !Array.isArray(decoded))
          output = decoded as Record<string, unknown>;
      }
    } catch {
      // The saved model projection is optional; the structural tool fact remains.
    }
    return [
      {
        tool_name: item.tool_name,
        status:
          typeof output.status === "string"
            ? output.status
            : typeof item.status === "string"
              ? item.status
              : null,
        returncode:
          typeof output.returncode === "number" ? output.returncode : null,
        stdout: typeof output.stdout === "string" ? output.stdout : null,
        stderr: typeof output.stderr === "string" ? output.stderr : null,
        path: typeof output.path === "string" ? output.path : null,
      },
    ];
  });
}

export function sessionState(status: string): { label: string; tone: string } {
  const states: Record<string, { label: string; tone: string }> = {
    queued: { label: "Queued", tone: "muted" },
    running: { label: "Running", tone: "accent" },
    paused: { label: "Paused", tone: "warning" },
    waiting_input: { label: "Waiting for input", tone: "warning" },
    completed: { label: "Completed", tone: "success" },
    failed: { label: "Failed", tone: "danger" },
    unknown: { label: "Status unknown", tone: "warning" },
  };
  return (
    states[status] ?? { label: status.replaceAll("_", " "), tone: "muted" }
  );
}

const names: Record<string, string> = {
  run: "Run",
  session: "Session",
  model_request: "Model request",
  model_response: "Model response",
  tool_batch: "Tool batch",
  tool_slot: "Tool call",
  tool_result: "Tool result",
  lifecycle: "Lifecycle",
  work_graph: "Work graph",
  artifact: "Artifact",
  loss: "Data loss",
  error: "Error",
  budget: "Budget",
  snapshot: "Snapshot",
  stop: "Stop",
  reasoning: "Reasoning",
  context: "Context",
  step: "Step",
};

const namesZh: Record<string, string> = {
  run: "运行",
  session: "会话",
  model_request: "模型请求",
  model_response: "模型响应",
  tool_batch: "工具批次",
  tool_slot: "工具调用",
  tool_result: "工具结果",
  lifecycle: "生命周期",
  work_graph: "工作图",
  artifact: "产出",
  loss: "数据缺失",
  error: "错误",
  budget: "预算",
  snapshot: "快照",
  stop: "停止",
  reasoning: "推理",
  context: "上下文",
  step: "步骤",
};

export function eventTitle(
  event: RecordFact,
  lang: "zh" | "en" = "en",
): string {
  const label =
    (lang === "zh" ? namesZh : names)[event.kind] ??
    event.kind.replaceAll("_", " ");
  const tool = toolFacts(event)[0]?.tool_name ?? event.payload?.tool_name;
  return typeof tool === "string" && tool ? `${label} · ${tool}` : label;
}

export function eventSummary(
  event: RecordFact,
  lang: "zh" | "en" = "en",
): string {
  const tools = toolFacts(event);
  if (tools.length) {
    const first = tools[0];
    return (
      [
        first.path,
        first.status,
        first.returncode === null
          ? null
          : `${lang === "zh" ? "退出码" : "exit"} ${first.returncode}`,
      ]
        .filter(Boolean)
        .join(" · ") ||
      `${tools.length} tool result${tools.length > 1 ? "s" : ""}`
    );
  }
  const payload = event.payload ?? {};
  const nested = payload.payload;
  if (nested && typeof nested === "object") {
    const inner = nested as Record<string, unknown>;
    for (const key of [
      "summary",
      "status",
      "stage",
      "stop_reason",
      "message",
    ]) {
      const value = inner[key];
      if (typeof value === "string" && value) return value.slice(0, 260);
    }
  }
  for (const key of ["summary", "status", "stop_reason", "message"]) {
    const value = payload[key];
    if (typeof value === "string" && value) return value.slice(0, 260);
  }
  return event.phase
    ? `${lang === "zh" ? "阶段" : "Phase"} ${event.phase}`
    : `${lang === "zh" ? "已记录" : "Recorded"} ${event.kind.replaceAll("_", " ")}`;
}
