import { useCallback, useRef, useState } from "react";
import {
  clarificationOptionsFrom,
  parseAmbiguity,
} from "../lib/ambiguity";
import { streamQuery } from "../services/api";
import type {
  AgentStep,
  Ambiguity,
  ConversationHistoryTurn,
  QueryResult,
  StreamQueryEvent,
  UsageSummary,
} from "../types/api";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  steps?: AgentStep[];
  sql?: string;
  results?: QueryResult;
  confidence?: string | number;
  followUps?: string[];
  clarificationOptions?: string[];
  usedGolden?: boolean;
  trustLevel?: string;
  assumption?: string;
  keyFinding?: string;
  historyId?: string;
  error?: string;
  ambiguity?: Ambiguity;
  intent?: string;
  usage?: UsageSummary;
};

export type StreamLastResult = {
  sql?: string;
  results?: QueryResult;
  answer?: string;
  confidence?: string | number;
  followUps?: string[];
  clarificationOptions?: string[];
  usedGolden?: boolean;
  trustLevel?: string;
  assumption?: string;
  keyFinding?: string;
  historyId?: string;
  error?: string;
  steps?: AgentStep[];
  ambiguity?: Ambiguity;
  intent?: string;
  usage?: UsageSummary;
};

/**
 * Pair completed user/assistant turns into a compact history payload.
 * Only turns with a non-empty assistant answer and no error are included.
 */
function buildTurnHistory(
  messages: ChatMessage[],
  maxTurns: number,
): ConversationHistoryTurn[] {
  const turns: ConversationHistoryTurn[] = [];
  for (let i = 0; i + 1 < messages.length; i++) {
    const user = messages[i];
    const assistant = messages[i + 1];
    if (
      user.role === "user" &&
      assistant.role === "assistant" &&
      assistant.content &&
      !assistant.error
    ) {
      turns.push({
        question: user.content,
        sql: assistant.sql,
        answer: assistant.content,
        trust_level: assistant.trustLevel,
      });
      i++; // skip the assistant message on next iteration
    }
  }
  return turns.slice(-Math.max(1, maxTurns));
}

export function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function parseResults(value: unknown): QueryResult | undefined {
  const obj = asRecord(value);
  if (!obj) return undefined;
  const columns = Array.isArray(obj.columns)
    ? obj.columns.map(String)
    : undefined;
  const rawRows = Array.isArray(obj.rows) ? obj.rows : undefined;
  if (!columns || !rawRows) return undefined;
  const rows = rawRows.map((row) => {
    if (row && typeof row === "object" && !Array.isArray(row)) {
      return row as Record<string, unknown>;
    }
    if (Array.isArray(row)) {
      const out: Record<string, unknown> = {};
      columns.forEach((col, i) => {
        out[col] = row[i];
      });
      return out;
    }
    return {} as Record<string, unknown>;
  });
  const rowCount =
    typeof obj.row_count === "number" ? obj.row_count : rows.length;
  return {
    columns,
    rows,
    row_count: rowCount,
    truncated: Boolean(obj.truncated),
  };
}

function parseStepTables(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const tables = value.map(String).filter(Boolean);
  return tables.length > 0 ? tables : undefined;
}

function parseSteps(value: unknown): AgentStep[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return value
    .map((item) => {
      const obj = asRecord(item);
      if (!obj || typeof obj.name !== "string") return null;
      const tables = parseStepTables(obj.tables);
      return {
        name: obj.name,
        detail:
          typeof obj.detail === "string"
            ? obj.detail
            : String(obj.detail ?? ""),
        ...(tables ? { tables } : {}),
        ...(typeof obj.status === "string" ? { status: obj.status } : {}),
        ...(typeof obj.cluster_count === "number"
          ? { cluster_count: obj.cluster_count }
          : {}),
        ...(obj.generation && typeof obj.generation === "object"
          ? { generation: obj.generation as Record<string, unknown> }
          : {}),
      } satisfies AgentStep;
    })
    .filter((s): s is AgentStep => s !== null);
}

function parseFollowUps(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return value.map(String).filter(Boolean);
}

function parseUsage(value: unknown): UsageSummary | undefined {
  const obj = asRecord(value);
  if (!obj) return undefined;
  return obj as UsageSummary;
}

/** Apply a compact agent-state patch onto a chat message. Exported for tests. */
export function applyStatePatch(
  message: ChatMessage,
  patch: Record<string, unknown>,
): ChatMessage {
  const next: ChatMessage = { ...message };

  if (typeof patch.answer === "string") {
    next.content = patch.answer;
  } else if (typeof patch.explanation === "string" && !next.content) {
    next.content = patch.explanation;
  }

  const sql =
    (typeof patch.corrected_sql === "string" && patch.corrected_sql) ||
    (typeof patch.sql === "string" && patch.sql) ||
    undefined;
  if (sql) next.sql = sql;

  const results = parseResults(patch.results);
  if (results) next.results = results;

  if (
    typeof patch.confidence === "string" ||
    typeof patch.confidence === "number"
  ) {
    next.confidence = patch.confidence;
  }

  const followUps = parseFollowUps(patch.follow_ups);
  if (followUps) next.followUps = followUps;

  const clarificationOptions = parseFollowUps(patch.clarification_options);
  if (clarificationOptions) next.clarificationOptions = clarificationOptions;

  if (typeof patch.used_golden === "boolean") {
    next.usedGolden = patch.used_golden;
  }

  if (typeof patch.trust_level === "string" && patch.trust_level) {
    next.trustLevel = patch.trust_level;
  }
  if (typeof patch.assumption === "string" && patch.assumption) {
    next.assumption = patch.assumption;
  }
  if (typeof patch.key_finding === "string" && patch.key_finding) {
    next.keyFinding = patch.key_finding;
  }

  const ambiguity = parseAmbiguity(patch.ambiguity);
  if (ambiguity) {
    next.ambiguity = ambiguity;
    if (!next.assumption && ambiguity.assumption) {
      next.assumption = ambiguity.assumption;
    }
    const fromAmbiguity = clarificationOptionsFrom(
      next.clarificationOptions,
      ambiguity,
    );
    if (fromAmbiguity) next.clarificationOptions = fromAmbiguity;
    if (
      ambiguity.should_clarify &&
      (!next.trustLevel || next.trustLevel === "guessed")
    ) {
      next.trustLevel = "clarifying";
    }
  }

  if (typeof patch.intent === "string" && patch.intent) {
    next.intent = patch.intent;
  }

  const usage = parseUsage(patch.usage_summary ?? patch.usage);
  if (usage) next.usage = usage;

  const steps = parseSteps(patch.steps);
  if (steps) next.steps = steps;

  if (typeof patch.history_id === "string") {
    next.historyId = patch.history_id;
  }

  if (typeof patch.error === "string" && patch.error) {
    next.error = patch.error;
  }

  return next;
}

function extractErrorMessage(data: unknown): string {
  const obj = asRecord(data);
  if (obj) {
    if (typeof obj.message === "string") return obj.message;
    if (typeof obj.error === "string") return obj.error;
  }
  if (typeof data === "string" && data) return data;
  return "Query failed";
}

function toLastResult(msg: ChatMessage): StreamLastResult {
  return {
    sql: msg.sql,
    results: msg.results,
    answer: msg.content,
    confidence: msg.confidence,
    followUps: msg.followUps,
    clarificationOptions: msg.clarificationOptions,
    usedGolden: msg.usedGolden,
    trustLevel: msg.trustLevel,
    assumption: msg.assumption,
    keyFinding: msg.keyFinding,
    historyId: msg.historyId,
    error: msg.error,
    steps: msg.steps,
    ambiguity: msg.ambiguity,
    intent: msg.intent,
    usage: msg.usage,
  };
}

function newId(): string {
  return crypto.randomUUID();
}

export type UseStreamQueryOptions = {
  initialMessages?: ChatMessage[];
  conversationTurns?: number;
  sessionId?: string | null;
};

export function useStreamQuery(
  connectionId: string | null,
  options: UseStreamQueryOptions = {},
) {
  const {
    initialMessages = [],
    conversationTurns = 3,
    sessionId = null,
  } = options;

  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [isStreaming, setIsStreaming] = useState(false);
  const [lastResult, setLastResult] = useState<StreamLastResult | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const assistantIdRef = useRef<string | null>(null);
  const messagesRef = useRef<ChatMessage[]>(initialMessages);
  const conversationTurnsRef = useRef(conversationTurns);
  const sessionIdRef = useRef(sessionId);

  conversationTurnsRef.current = conversationTurns;
  sessionIdRef.current = sessionId;
  messagesRef.current = messages;

  const reset = useCallback((next: ChatMessage[] = []) => {
    abortRef.current?.abort();
    abortRef.current = null;
    assistantIdRef.current = null;
    messagesRef.current = next;
    setMessages(next);
    setIsStreaming(false);
    setLastResult(null);
  }, []);

  const clear = useCallback(() => {
    reset([]);
  }, [reset]);

  const updateAssistant = useCallback(
    (updater: (msg: ChatMessage) => ChatMessage): ChatMessage | null => {
      const id = assistantIdRef.current;
      if (!id) return null;
      const current = messagesRef.current.find((m) => m.id === id);
      if (!current) return null;
      const updated = updater(current);
      const next = messagesRef.current.map((m) =>
        m.id === id ? updated : m,
      );
      messagesRef.current = next;
      setMessages(next);
      return updated;
    },
    [],
  );

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
    updateAssistant((msg) => ({
      ...msg,
      error: msg.error || "Cancelled",
      content: msg.content || "Query cancelled.",
    }));
  }, [updateAssistant]);

  const updateMessage = useCallback(
    (
      messageId: string,
      updater: (msg: ChatMessage) => ChatMessage,
    ): ChatMessage | null => {
      const current = messagesRef.current.find((m) => m.id === messageId);
      if (!current) return null;
      const updated = updater(current);
      const next = messagesRef.current.map((m) =>
        m.id === messageId ? updated : m,
      );
      messagesRef.current = next;
      setMessages(next);
      return updated;
    },
    [],
  );

  const handleEvent = useCallback(
    (event: StreamQueryEvent) => {
      const name = event.event;
      const data = event.data;

      if (name === "start") {
        return;
      }

      if (name === "step") {
        const payload = asRecord(data);
        const stepRaw = payload?.step ?? payload;
        const stepObj = asRecord(stepRaw);
        if (!stepObj || typeof stepObj.name !== "string") return;
        const tables = parseStepTables(stepObj.tables);
        const step: AgentStep = {
          name: stepObj.name,
          detail:
            typeof stepObj.detail === "string"
              ? stepObj.detail
              : String(stepObj.detail ?? ""),
          ...(tables ? { tables } : {}),
          ...(typeof stepObj.status === "string"
            ? { status: stepObj.status }
            : {}),
          ...(typeof stepObj.cluster_count === "number"
            ? { cluster_count: stepObj.cluster_count }
            : {}),
          ...(stepObj.generation && typeof stepObj.generation === "object"
            ? {
                generation: stepObj.generation as Record<string, unknown>,
              }
            : {}),
        };
        updateAssistant((msg) => ({
          ...msg,
          steps: [...(msg.steps ?? []), step],
        }));
        return;
      }

      if (name === "node") {
        const patch = asRecord(data);
        if (!patch) return;
        updateAssistant((msg) => applyStatePatch(msg, patch));
        return;
      }

      if (name === "done" || name === "result") {
        const patch = asRecord(data) ?? {};
        const updated = updateAssistant((msg) => {
          const next = applyStatePatch(msg, patch);
          if (!next.sql && typeof patch.sql === "string") {
            next.sql = patch.sql;
          }
          if (!next.content && !next.error) {
            const status = next.ambiguity?.status;
            if (status === "ambiguous" || next.clarificationOptions?.length) {
              next.content =
                next.ambiguity?.reason ||
                "I need a bit more detail to answer accurately.";
            } else if (status === "unanswerable") {
              next.content =
                next.ambiguity?.reason ||
                "I could not find data that answers this question.";
            } else if (status === "not_a_data_question") {
              next.content =
                next.content ||
                "That does not look like a question about your data.";
            } else {
              next.content = next.sql ? "Query completed." : "Done.";
            }
          }
          return next;
        });
        if (updated) setLastResult(toLastResult(updated));
        return;
      }

      if (name === "error") {
        const message = extractErrorMessage(data);
        const patch = asRecord(data);
        const updated = updateAssistant((msg) => {
          const next = patch ? applyStatePatch(msg, patch) : { ...msg };
          next.error = message;
          if (!next.content) next.content = "";
          return next;
        });
        if (updated) setLastResult(toLastResult(updated));
      }
    },
    [updateAssistant],
  );

  const send = useCallback(
    async (
      question: string,
      overrides?: { sessionId?: string | null; evidence?: string },
    ) => {
      const trimmed = question.trim();
      if (!trimmed || !connectionId || isStreaming) return;

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      const conversation_history = buildTurnHistory(
        messagesRef.current,
        conversationTurnsRef.current,
      );

      const userMsg: ChatMessage = {
        id: newId(),
        role: "user",
        content: trimmed,
      };
      const assistantMsg: ChatMessage = {
        id: newId(),
        role: "assistant",
        content: "",
        steps: [],
      };
      assistantIdRef.current = assistantMsg.id;

      setMessages((prev) => {
        const next = [...prev, userMsg, assistantMsg];
        messagesRef.current = next;
        return next;
      });
      setIsStreaming(true);
      setLastResult(null);

      const activeSessionId =
        overrides?.sessionId !== undefined
          ? overrides.sessionId
          : sessionIdRef.current;

      try {
        await streamQuery(
          {
            connection_id: connectionId,
            question: trimmed,
            conversation_history,
            session_id: activeSessionId || undefined,
            evidence: overrides?.evidence?.trim() || undefined,
          },
          handleEvent,
          controller.signal,
        );
      } catch (err) {
        if (controller.signal.aborted) {
          updateAssistant((msg) => ({
            ...msg,
            error: msg.error || "Cancelled",
            content: msg.content || "Query cancelled.",
          }));
          return;
        }
        const message = err instanceof Error ? err.message : "Query failed";
        const updated = updateAssistant((msg) => ({ ...msg, error: message }));
        if (updated) setLastResult(toLastResult(updated));
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
          setIsStreaming(false);
        }
      }
    },
    [connectionId, handleEvent, isStreaming, updateAssistant],
  );

  return {
    messages,
    send,
    isStreaming,
    clear,
    reset,
    cancel,
    updateMessage,
    lastResult,
  };
}
