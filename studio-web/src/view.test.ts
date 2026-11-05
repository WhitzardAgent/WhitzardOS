import { describe, expect, it } from "vitest";
import { eventTitle, sessionState } from "./view";

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
});
