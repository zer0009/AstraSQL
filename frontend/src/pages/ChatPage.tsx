import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { ChatInput, MessageList } from "../components/chat";
import { Button, Select, Spinner } from "../components/ui";
import { useStreamQuery } from "../hooks/useStreamQuery";
import { listConnections } from "../services/api";

const STORAGE_KEY = "astrasql.selectedConnectionId";

type RerunLocationState = {
  question?: string;
  connection_id?: string;
  history_id?: string;
};

export default function ChatPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const pendingRerun = useRef<string | null>(null);

  const [connectionId, setConnectionId] = useState<string>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [draft, setDraft] = useState("");

  const connectionsQuery = useQuery({
    queryKey: ["connections"],
    queryFn: listConnections,
  });

  const { messages, send, isStreaming, clear } = useStreamQuery(
    connectionId || null,
  );

  useEffect(() => {
    try {
      if (connectionId) localStorage.setItem(STORAGE_KEY, connectionId);
      else localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore storage errors
    }
  }, [connectionId]);

  useEffect(() => {
    const list = connectionsQuery.data;
    if (!list || list.length === 0) return;
    if (connectionId && list.some((c) => c.id === connectionId)) return;
    setConnectionId(list[0].id);
  }, [connectionsQuery.data, connectionId]);

  // Prefill + auto-send from History "Re-run"
  useEffect(() => {
    const state = location.state as RerunLocationState | null;
    if (!state?.question) return;
    if (state.connection_id) setConnectionId(state.connection_id);
    pendingRerun.current = state.question;
    setDraft(state.question);
    navigate(location.pathname, { replace: true, state: null });
  }, [location.state, location.pathname, navigate]);

  useEffect(() => {
    const q = pendingRerun.current;
    if (!q || !connectionId || isStreaming) return;
    pendingRerun.current = null;
    setDraft("");
    void send(q);
  }, [connectionId, isStreaming, send]);

  const hasConnection = Boolean(connectionId);
  const connections = connectionsQuery.data ?? [];

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-zinc-200 bg-white px-5">
        <div className="flex min-w-0 items-center gap-3">
          <h1 className="shrink-0 text-sm font-semibold text-zinc-900">
            Query
          </h1>
          <div className="flex min-w-0 items-center gap-2">
            <label
              htmlFor="chat-connection"
              className="shrink-0 text-xs text-zinc-500"
            >
              Connection
            </label>
            {connectionsQuery.isLoading ? (
              <Spinner size="sm" />
            ) : (
              <Select
                id="chat-connection"
                className="h-8 w-52 max-w-full"
                value={connectionId}
                onChange={(e) => {
                  setConnectionId(e.target.value);
                  clear();
                }}
                disabled={connections.length === 0}
              >
                {connections.length === 0 ? (
                  <option value="">No connections</option>
                ) : (
                  connections.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))
                )}
              </Select>
            )}
          </div>
        </div>
        {messages.length > 0 ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={clear}
            disabled={isStreaming}
          >
            Clear
          </Button>
        ) : null}
      </header>

      {!hasConnection ? (
        <div className="flex flex-1 items-center justify-center p-6">
          <p className="text-sm text-zinc-500">
            Select a connection to start querying, or add one under Connections.
          </p>
        </div>
      ) : (
        <>
          <MessageList
            messages={messages}
            isStreaming={isStreaming}
            onFollowUp={(q) => void send(q)}
            onAskAgain={(q) => void send(q)}
          />
          <ChatInput
            value={draft}
            onChange={setDraft}
            onSend={(q) => void send(q)}
            disabled={!hasConnection || isStreaming}
            placeholder={
              isStreaming
                ? "Waiting for response…"
                : "Ask a question about your data…"
            }
          />
        </>
      )}
    </div>
  );
}
