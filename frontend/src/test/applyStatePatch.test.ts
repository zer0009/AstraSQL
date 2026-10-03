import { describe, expect, it } from "vitest";
import { applyStatePatch } from "../hooks/useStreamQuery";
import {
  ambiguousDone,
  assumedDone,
  clearDone,
  truncatedDone,
} from "./fixtures/sseEvents";
import { formatConfidence } from "../lib/confidence";
import { stepLabel } from "../lib/stepLabels";
import { parseAmbiguity } from "../lib/ambiguity";

describe("formatConfidence", () => {
  it("uses 0.85 as HIGH threshold", () => {
    expect(formatConfidence(0.85)).toBe("HIGH");
    expect(formatConfidence(0.84)).toBe("MEDIUM");
    expect(formatConfidence(0.39)).toBe("LOW");
  });
});

describe("stepLabel", () => {
  it("humanizes known and unknown steps", () => {
    expect(stepLabel("ambiguity_gate")).toBe("Checked answer consistency");
    expect(stepLabel("schema_link")).toBe("Schema Link");
  });
});

describe("applyStatePatch", () => {
  const base = {
    id: "a1",
    role: "assistant" as const,
    content: "",
  };

  it("parses clear done payload", () => {
    const next = applyStatePatch(base, clearDone.data as Record<string, unknown>);
    expect(next.sql).toContain("COUNT");
    expect(next.ambiguity?.status).toBe("clear");
    expect(next.usedGolden).toBe(false);
    expect(next.historyId).toBe("hist-clear-1");
  });

  it("parses assumed status and assumption", () => {
    const next = applyStatePatch(
      base,
      assumedDone.data as Record<string, unknown>,
    );
    expect(next.ambiguity?.status).toBe("assumed");
    expect(next.assumption).toMatch(/revenue/i);
  });

  it("parses ambiguous clarification options from ambiguity object", () => {
    const data = { ...(ambiguousDone.data as Record<string, unknown>) };
    delete data.clarification_options;
    const next = applyStatePatch(base, data);
    expect(next.clarificationOptions).toEqual(["By revenue", "By order count"]);
    expect(next.trustLevel).toBe("clarifying");
  });

  it("flags truncated results", () => {
    const next = applyStatePatch(
      base,
      truncatedDone.data as Record<string, unknown>,
    );
    expect(next.results?.truncated).toBe(true);
    expect(next.results?.row_count).toBe(2500);
  });
});

describe("parseAmbiguity", () => {
  it("returns undefined for non-objects", () => {
    expect(parseAmbiguity(null)).toBeUndefined();
    expect(parseAmbiguity("x")).toBeUndefined();
  });
});
