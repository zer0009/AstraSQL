import { useCallback, useEffect, useRef, useState } from "react";
import {
  createSession,
  deleteSession,
  executeSql,
  getSession,
  renameSession,
} from "../services/api";
import type { ChatSession, QueryHistoryItem } from "../types/api";
import {
  readCurrentSessionId,
  writeCurrentSessionId,
} from "../lib/userPrefs";
import { useUserPrefs } from "./useUserPrefs";
import {
  type ChatMessage,
  useStreamQuery,
} from "./useStreamQuery";

function parseFollowUps(raw: string | null | undefined): string[] | undefined {
  if (!raw) return undefined;
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return undefined;
    return parsed.map(String).filter(Boolean);
  } catch {
    return undefined;
  }
}

function extractApiError(err: unknown): string {
  if (err && typeof err === "object" && "response" in err) {
    const response = (err as { response?: { data?: unknown } }).response;
    const data = response?.data;
    if (data && typeof data === "object" && data !== null && "detail" in data) {
      const detail = (data as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
    }
  }
  if (err instanceof Error) return err.message;
  return "Failed to execute SQL";
}

/** Rebuild chat bubbles from persisted query history (no result rows). */
export function reconstructMessages(
  queries: QueryHistoryItem[],
): ChatMessage[] {
  return queries.flatMap((q) => [
    {
      id: `${q.id}-user`,
      role: "user" as const,
      content: q.question,
    },
    {
      id: q.id,
      role: "assistant" as const,
      content: q.explanation ?? "Query completed.",
      sql: q.sql,
      historyId: q.id,
      confidence: q.confidence ?? undefined,
      followUps: parseFollowUps(q.follow_ups),
      // results intentionally omitted — re-run executes saved SQL directly
    },
  ]);
}

export function useChatSession(connectionId: string | null) {
  const { prefs } = useUserPrefs();
  const [session, setSession] = useState<ChatSession | null>(null);
  const [isLoadingSession, setIsLoadingSession] = useState(false);
  const [rerunningMessageId, setRerunningMessageId] = useState<string | null>(
    null,
  );
  /** When set, the next load effect prefers this session id over localStorage. */
  const pendingSessionIdRef = useRef<string | null>(null);
  /** Bumped by switchTo / connection changes to re-run the load effect. */
  const [loadKey, setLoadKey] = useState(0);
  const sessionIdRef = useRef<string | null>(null);
  const connectionRef = useRef(connectionId);
  connectionRef.current = connectionId;

  const {
    messages,
    send: streamSend,
    isStreaming,
    reset,
    updateMessage,
    lastResult,
  } = useStreamQuery(connectionId, {
    conversationTurns: prefs.conversationTurns,
    sessionId: session?.id ?? null,
  });

  // Keep ref in sync for ensureSession / clear without stale closures.
  sessionIdRef.current = session?.id ?? null;

  // Load persisted or requested session when connection / loadKey changes.
  useEffect(() => {
    const key = connectionId ?? null;
    let cancelled = false;

    // Clear immediately so we never show another connection's transcript.
    setSession(null);
    sessionIdRef.current = null;
    reset([]);

    async function load() {
      if (!key) return;

      const targetId =
        pendingSessionIdRef.current ?? readCurrentSessionId(key);
      pendingSessionIdRef.current = null;
      if (!targetId) return;

      if (!cancelled) setIsLoadingSession(true);
      try {
        const detail = await getSession(targetId);
        if (cancelled) return;
        if (detail.connection_id !== key) {
          writeCurrentSessionId(key, null);
          return;
        }
        setSession({
          id: detail.id,
          connection_id: detail.connection_id,
          title: detail.title,
          created_at: detail.created_at,
          updated_at: detail.updated_at,
        });
        sessionIdRef.current = detail.id;
        writeCurrentSessionId(key, detail.id);
        reset(reconstructMessages(detail.queries ?? []));
      } catch {
        if (cancelled) return;
        writeCurrentSessionId(key, null);
      } finally {
        if (!cancelled) setIsLoadingSession(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [connectionId, loadKey, reset]);

  const ensureSession = useCallback(
    async (firstQuestion: string): Promise<string | null> => {
      if (!connectionId) return null;
      if (sessionIdRef.current) return sessionIdRef.current;

      const title = firstQuestion.trim().slice(0, 60) || undefined;
      const created = await createSession({
        connection_id: connectionId,
        title,
      });
      sessionIdRef.current = created.id;
      setSession(created);
      writeCurrentSessionId(connectionId, created.id);
      return created.id;
    },
    [connectionId],
  );

  const send = useCallback(
    async (question: string) => {
      const trimmed = question.trim();
      if (!trimmed || !connectionId || isStreaming) return;

      let activeSessionId: string | null = sessionIdRef.current;
      try {
        activeSessionId = await ensureSession(trimmed);
      } catch (err) {
        console.error("Failed to create chat session", err);
      }
      await streamSend(trimmed, { sessionId: activeSessionId });
    },
    [connectionId, ensureSession, isStreaming, streamSend],
  );

  /**
   * Re-execute the saved SQL for a message — no LLM, updates results in place.
   */
  const rerunSql = useCallback(
    async (messageId: string, sqlOverride?: string) => {
      if (!connectionId || isStreaming || rerunningMessageId) return;
      const target = messages.find((m) => m.id === messageId);
      const sql = (sqlOverride ?? target?.sql ?? "").trim();
      if (!target || target.role !== "assistant" || !sql) return;

      setRerunningMessageId(messageId);
      updateMessage(messageId, (msg) => ({
        ...msg,
        sql,
        error: undefined,
      }));

      try {
        const result = await executeSql({
          connection_id: connectionId,
          sql,
        });
        updateMessage(messageId, (msg) => ({
          ...msg,
          sql: result.sql || msg.sql,
          results: {
            columns: result.columns,
            rows: result.rows,
            row_count: result.row_count,
          },
          error: undefined,
        }));
      } catch (err) {
        updateMessage(messageId, (msg) => ({
          ...msg,
          error: extractApiError(err),
        }));
      } finally {
        setRerunningMessageId(null);
      }
    },
    [connectionId, isStreaming, messages, rerunningMessageId, updateMessage],
  );

  const resetSession = useCallback(() => {
    const conn = connectionRef.current;
    reset([]);
    setSession(null);
    sessionIdRef.current = null;
    if (conn) writeCurrentSessionId(conn, null);
  }, [reset]);

  const clear = useCallback(async () => {
    const id = sessionIdRef.current;
    resetSession();
    if (id) {
      try {
        await deleteSession(id);
      } catch {
        // Session may already be gone — ignore
      }
    }
  }, [resetSession]);

  const newChat = useCallback(async () => {
    // Start a fresh local transcript without deleting the previous session
    // from history — user can still find it via sessions list later.
    resetSession();
  }, [resetSession]);

  const switchTo = useCallback(
    (sessionId: string) => {
      if (!connectionId || !sessionId) return;
      if (sessionIdRef.current === sessionId) return;
      writeCurrentSessionId(connectionId, sessionId);
      pendingSessionIdRef.current = sessionId;
      setLoadKey((k) => k + 1);
    },
    [connectionId],
  );

  /**
   * Delete a session from the backend. If it is the active session, reset
   * local state without a second delete (resetSession only clears UI).
   */
  const deleteSessionById = useCallback(
    async (sessionId: string) => {
      const wasActive = sessionIdRef.current === sessionId;
      try {
        await deleteSession(sessionId);
      } catch {
        // May already be gone
      }
      if (wasActive) {
        resetSession();
      }
    },
    [resetSession],
  );

  const rename = useCallback(async (title: string) => {
    const id = sessionIdRef.current;
    if (!id) return;
    const trimmed = title.trim();
    if (!trimmed) return;
    const updated = await renameSession(id, trimmed);
    setSession(updated);
  }, []);

  return {
    messages,
    send,
    rerunSql,
    isStreaming,
    rerunningMessageId,
    clear,
    newChat,
    rename,
    switchTo,
    resetSession,
    deleteSessionById,
    session,
    isLoadingSession,
    lastResult,
  };
}
