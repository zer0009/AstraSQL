import { test, expect } from "@playwright/test";
import {
  ambiguousDone,
  assumedDone,
  clearDone,
  gateSteps,
} from "../src/test/fixtures/sseEvents";
import { applyStatePatch } from "../src/hooks/useStreamQuery";

/**
 * Playwright smoke against recorded SSE fixtures (no live backend / tokens).
 */
test.describe("SSE fixture smoke", () => {
  test("clear / assumed / ambiguous patches produce UI-ready state", () => {
    const base = { id: "a", role: "assistant" as const, content: "" };

    const clear = applyStatePatch(
      base,
      clearDone.data as Record<string, unknown>,
    );
    expect(clear.ambiguity?.status).toBe("clear");
    expect(clear.sql).toBeTruthy();

    const assumed = applyStatePatch(
      base,
      assumedDone.data as Record<string, unknown>,
    );
    expect(assumed.assumption).toBeTruthy();

    const amb = applyStatePatch(
      base,
      ambiguousDone.data as Record<string, unknown>,
    );
    expect(amb.clarificationOptions?.length).toBeGreaterThan(0);
    expect(amb.trustLevel).toBe("clarifying");

    expect(gateSteps.length).toBeGreaterThan(0);
  });
});
