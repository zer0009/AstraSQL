import type { StreamQueryEvent } from "../../types/api";

/** Recorded SSE shapes matching backend stream_query compact_state. */
export const clearDone: StreamQueryEvent = {
  event: "done",
  data: {
    question: "How many customers?",
    sql: "SELECT COUNT(*) AS n FROM customers",
    results: {
      columns: ["n"],
      rows: [{ n: 42 }],
      row_count: 1,
    },
    confidence: 0.9,
    trust_level: "guessed",
    answer: "There are 42 customers.",
    follow_ups: ["List top customers by revenue"],
    clarification_options: [],
    used_golden: false,
    ambiguity: { status: "clear", should_clarify: false },
    history_id: "hist-clear-1",
  },
};

export const assumedDone: StreamQueryEvent = {
  event: "done",
  data: {
    question: "Top customers",
    sql: "SELECT name FROM customers ORDER BY revenue DESC LIMIT 10",
    results: {
      columns: ["name"],
      rows: [{ name: "Acme" }],
      row_count: 1,
    },
    confidence: 0.7,
    trust_level: "guessed",
    answer: "Here are the top customers by revenue.",
    assumption: "Ranked by revenue descending",
    clarification_options: [],
    used_golden: false,
    ambiguity: {
      status: "assumed",
      should_clarify: false,
      assumption: "Ranked by revenue descending",
      decision_why: "dominant_cluster;candidates=3",
    },
    history_id: "hist-assumed-1",
  },
};

export const ambiguousDone: StreamQueryEvent = {
  event: "done",
  data: {
    question: "Top customers",
    sql: "",
    results: null,
    confidence: null,
    trust_level: "clarifying",
    answer: "Do you mean by revenue or by order count?",
    clarification_options: ["By revenue", "By order count"],
    used_golden: false,
    ambiguity: {
      status: "ambiguous",
      should_clarify: true,
      reason: "Split result clusters",
      options: ["By revenue", "By order count"],
      decision_why: "split_clusters;k=3",
    },
    history_id: "hist-ambig-1",
  },
};

export const unanswerableDone: StreamQueryEvent = {
  event: "done",
  data: {
    question: "What is the weather tomorrow?",
    sql: "",
    trust_level: "failed",
    answer: "This database has no weather data.",
    clarification_options: [],
    ambiguity: {
      status: "unanswerable",
      should_clarify: true,
      reason: "No matching tables",
    },
    history_id: "hist-unans-1",
  },
};

export const notDataDone: StreamQueryEvent = {
  event: "done",
  data: {
    question: "Hello!",
    sql: "",
    trust_level: "guessed",
    answer: "Hi — ask me a question about your data.",
    ambiguity: {
      status: "not_a_data_question",
      should_clarify: false,
    },
    history_id: "hist-chitchat-1",
  },
};

export const truncatedDone: StreamQueryEvent = {
  event: "done",
  data: {
    question: "All orders",
    sql: "SELECT * FROM orders",
    results: {
      columns: ["id"],
      rows: Array.from({ length: 100 }, (_, i) => ({ id: i + 1 })),
      row_count: 2500,
      truncated: true,
    },
    confidence: 0.88,
    trust_level: "guessed",
    answer: "Showing a preview of orders.",
    ambiguity: { status: "clear" },
    history_id: "hist-trunc-1",
  },
};

export const gateSteps: StreamQueryEvent[] = [
  {
    event: "step",
    data: {
      node: "context_retriever",
      step: {
        name: "context_retrieved",
        detail: "Retrieved schema context",
        tables: ["customers", "orders"],
      },
    },
  },
  {
    event: "step",
    data: {
      node: "query_generator",
      step: {
        name: "sql_generated",
        detail: "Generated SQL (merged)",
        generation: { merged: true },
      },
    },
  },
  {
    event: "step",
    data: {
      node: "ambiguity_gate",
      step: {
        name: "ambiguity_gate",
        detail: "Sampled 3 candidates; 1 dominant cluster",
        cluster_count: 1,
        status: "assumed",
      },
    },
  },
];

/** Replay a sequence of SSE events through a handler (no network). */
export async function replayFixtures(
  events: StreamQueryEvent[],
  onEvent: (e: StreamQueryEvent) => void,
): Promise<void> {
  for (const event of events) {
    onEvent(event);
  }
}
