import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { AgentCard, StatusBadge } from "./App";

describe("Studio UI", () => {
  it("presents an agent as a task launch choice", () => {
    const html = renderToStaticMarkup(
      <AgentCard
        agent={{
          id: "research",
          name: "Research Agent",
          description: "Find evidence",
        }}
        onSelect={() => {}}
      />,
    );
    expect(html).toContain("Research Agent");
    expect(html).toContain("Find evidence");
    expect(html).toContain("Start a task");
  });

  it("uses a textual state alongside status color", () => {
    const html = renderToStaticMarkup(<StatusBadge status="unknown" />);
    expect(html).toContain("Status unknown");
  });
});
