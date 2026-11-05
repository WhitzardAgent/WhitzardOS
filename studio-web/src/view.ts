export type RecordFact = {
  sequence?: number | null;
  kind: string;
  phase?: string | null;
  occurred_at?: string;
  payload?: Record<string, unknown>;
};

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

export function eventTitle(event: RecordFact): string {
  const label = names[event.kind] ?? event.kind.replaceAll("_", " ");
  const tool = event.payload?.tool_name;
  return typeof tool === "string" && tool ? `${label} · ${tool}` : label;
}

export function eventSummary(event: RecordFact): string {
  const payload = event.payload ?? {};
  for (const key of ["summary", "status", "stop_reason", "message"]) {
    const value = payload[key];
    if (typeof value === "string" && value) return value.slice(0, 260);
  }
  return event.phase
    ? `Phase ${event.phase}`
    : `Recorded ${event.kind.replaceAll("_", " ")}`;
}
