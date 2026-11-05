import assert from "node:assert/strict";
import test from "node:test";
import { summarize } from "../src/summary.ts";

test("formats names for a summary", () => {
  assert.equal(summarize([" Ada ", "Lin"]), "ADA, LIN");
});
