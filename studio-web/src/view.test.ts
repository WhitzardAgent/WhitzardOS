import { describe, expect, it } from "vitest";
import { eventTitle, eventSummary, sessionState, toolFacts } from "./view";

describe("observation copy", () => {
  it("shows unknown facts honestly", () => {
    expect(sessionState("unknown").label).toBe("Status unknown");
    expect(sessionState("paused").label).toBe("Paused");
  });

  it("makes structural events readable without hiding their kind", () => {
    expect(
      eventTitle({ kind: "tool_result", payload: { tool_name: "read_file" } }),
    ).toBe("Tool result · read_file");
    expect(eventTitle({ kind: "work_graph", payload: {} })).toBe("Work graph");
  });

  it("reads structured saved tool outcomes without guessing from tool names", () => {
    const fact = {
      kind: "tool_slot",
      payload: {
        payload: {
          action_results: [
            {
              tool_name: "run_test",
              model_output: JSON.stringify({
                status: "success",
                returncode: 0,
                stdout: "1 passed",
              }),
            },
          ],
        },
      },
    };
    expect(toolFacts(fact)[0].returncode).toBe(0);
    expect(eventTitle(fact)).toBe("Tool call · run_test");
    expect(eventSummary(fact)).toContain("exit 0");
    expect(eventTitle(fact, "zh")).toBe("工具调用 · run_test");
  });
});
