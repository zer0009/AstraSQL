import { describe, expect, it } from "vitest";
import { reconstructMessages } from "../hooks/useChatSession";
import type { QueryHistoryItem } from "../types/api";

describe("reconstructMessages", () => {
  it("restores clarification state from ambiguity_json", () => {
    const queries: QueryHistoryItem[] = [
      {
        id: "h1",
        connection_id: "c1",
        question: "Top customers?",
        sql: "",
        result_row_count: null,
        confidence: null,
        trust_level: "clarifying",
        user_rating: null,
        explanation: "Which measure?",
        follow_ups: null,
        ambiguity_json: JSON.stringify({
          status: "ambiguous",
          should_clarify: true,
          options: ["By revenue", "By orders"],
        }),
        created_at: new Date().toISOString(),
      },
    ];
    const msgs = reconstructMessages(queries);
    expect(msgs).toHaveLength(2);
    const assistant = msgs[1];
    expect(assistant.role).toBe("assistant");
    expect(assistant.clarificationOptions).toEqual([
      "By revenue",
      "By orders",
    ]);
    expect(assistant.trustLevel).toBe("clarifying");
    expect(assistant.ambiguity?.status).toBe("ambiguous");
  });

  it("restores assumed assumption", () => {
    const queries: QueryHistoryItem[] = [
      {
        id: "h2",
        connection_id: "c1",
        question: "Top customers",
        sql: "SELECT 1",
        result_row_count: 1,
        confidence: 0.7,
        trust_level: "guessed",
        user_rating: null,
        explanation: "Done",
        follow_ups: null,
        ambiguity_json: JSON.stringify({
          status: "assumed",
          assumption: "By revenue",
          decision_why: "dominant",
        }),
        created_at: new Date().toISOString(),
      },
    ];
    const msgs = reconstructMessages(queries);
    expect(msgs[1].assumption).toBe("By revenue");
  });
});
