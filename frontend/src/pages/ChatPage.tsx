import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ChatInput, MessageList } from "../components/chat";
import { SessionSidebar } from "../components/layout/SessionSidebar";
import { Button, Input, Spinner } from "../components/ui";
import { useChatSession } from "../hooks/useChatSession";
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
  const queryClient = useQueryClient();
  const pendingRerun = useRef<string | null>(null);

  const [connectionId, setConnectionId] = useState<string>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [draft, setDraft] = useState("");
  const [evidence, setEvidence] = useState("");
  const [showEvidence, setShowEvidence] = useState(false);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");

  const connectionsQuery = useQuery({
    queryKey: ["connections"],
    queryFn: listConnections,
  });

  const {
    messages,
    send,
    rerunSql,
    isStreaming,
    rerunningMessageId,
    clear,
    newChat,
    cancel,
    rename,
    switchTo,
    resetSession,
    session,
    isLoadingSession,
  } = useChatSession(connectionId || null);

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
    if (!q || !connectionId || isStreaming || isLoadingSession) return;
    pendingRerun.current = null;
    setDraft("");
    void send(q);
  }, [connectionId, isStreaming, isLoadingSession, send]);

  useEffect(() => {
    setTitleDraft(session?.title ?? "");
    setEditingTitle(false);
  }, [session?.id, session?.title]);

  useEffect(() => {
    if (!connectionId || !session?.id) return;
    void queryClient.invalidateQueries({
      queryKey: ["sessions", connectionId],
    });
  }, [connectionId, session?.id, session?.title, session?.updated_at, queryClient]);

  const hasConnection = Boolean(connectionId);
  const connections = connectionsQuery.data ?? [];

  const commitTitle = async () => {
    const next = titleDraft.trim();
    setEditingTitle(false);
    if (!session || !next || next === (session.title ?? "")) return;
    try {
      await rename(next);
    } catch {
      setTitleDraft(session.title ?? "");
    }
  };

  const handleSidebarDelete = (id: string) => {
    if (session?.id === id) {
      resetSession();
    }
  };

  const handleSend = (q: string) => {
    const note = evidence.trim();
    setEvidence("");
    void send(q, note || undefined);
  };

  return (
    <div className="flex h-full min-h-0">
      <SessionSidebar
        connectionId={connectionId}
        connections={connections}
        connectionsLoading={connectionsQuery.isLoading}
        onConnectionChange={setConnectionId}
        activeSessionId={session?.id}
        onNewChat={() => void newChat()}
        onSwitchSession={switchTo}
        onDeleteSession={handleSidebarDelete}
        disabled={isStreaming || Boolean(rerunningMessageId)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--surface-raised)] px-5">
          <div className="flex min-w-0 items-center gap-2">
            {session ? (
              editingTitle ? (
                <Input
                  className="h-8 w-56 max-w-full"
                  value={titleDraft}
                  autoFocus
                  onChange={(e) => setTitleDraft(e.target.value)}
                  onBlur={() => void commitTitle()}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void commitTitle();
                    }
                    if (e.key === "Escape") {
                      setTitleDraft(session.title ?? "");
                      setEditingTitle(false);
                    }
                  }}
                />
              ) : (
                <button
                  type="button"
                  className="truncate text-sm font-medium text-zinc-800 hover:text-zinc-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] rounded"
                  title="Click to rename"
                  onClick={() => setEditingTitle(true)}
                >
                  {session.title || "Untitled chat"}
                </button>
              )
            ) : (
              <h1 className="text-sm font-semibold text-[var(--text)]">
                New chat
              </h1>
            )}
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {isStreaming ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => cancel()}
              >
                Cancel
              </Button>
            ) : null}
            {messages.length > 0 ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  if (
                    window.confirm(
                      "Delete this chat session? Query history rows are kept.",
                    )
                  ) {
                    void clear();
                  }
                }}
                disabled={isStreaming}
              >
                Delete chat
              </Button>
            ) : null}
          </div>
        </header>

        {!hasConnection ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6">
            <p className="text-sm text-[var(--text-muted)]">
              {connections.length === 0
                ? "Add a connection to start querying."
                : "Select a connection in the sidebar to start querying."}
            </p>
            {connections.length === 0 ? (
              <Link
                to="/connections"
                className="inline-flex h-8 items-center justify-center rounded-md bg-zinc-900 px-3 text-xs font-medium text-white hover:bg-zinc-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
              >
                Add connection
              </Link>
            ) : null}
          </div>
        ) : isLoadingSession ? (
          <div className="flex flex-1 items-center justify-center gap-2 p-6 text-sm text-zinc-500">
            <Spinner size="sm" />
            Loading chat session…
          </div>
        ) : (
          <>
            <MessageList
              messages={messages}
              isStreaming={isStreaming}
              rerunningMessageId={rerunningMessageId}
              onFollowUp={(q) => void send(q)}
              onAskAgain={(q) => void send(q)}
              onRerunSql={(id, sql) => void rerunSql(id, sql)}
              onRetry={(q) => void send(q)}
            />
            <ChatInput
              value={draft}
              onChange={setDraft}
              onSend={handleSend}
              disabled={
                !hasConnection || isStreaming || Boolean(rerunningMessageId)
              }
              evidence={evidence}
              onEvidenceChange={setEvidence}
              showEvidence={showEvidence}
              onToggleEvidence={() => setShowEvidence((v) => !v)}
              placeholder={
                isStreaming
                  ? "Waiting for response…"
                  : rerunningMessageId
                    ? "Executing SQL…"
                    : "Ask a question about your data…"
              }
            />
          </>
        )}
      </div>
    </div>
  );
}
