import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
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
    if (!q || !connectionId || isStreaming || isLoadingSession) return;
    pendingRerun.current = null;
    setDraft("");
    void send(q);
  }, [connectionId, isStreaming, isLoadingSession, send]);

  useEffect(() => {
    setTitleDraft(session?.title ?? "");
    setEditingTitle(false);
  }, [session?.id, session?.title]);

  // Keep sidebar session list in sync when sessions are created / renamed.
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
        <header className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-zinc-200 bg-white px-5">
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
                  className="truncate text-sm font-medium text-zinc-800 hover:text-zinc-950"
                  title="Click to rename"
                  onClick={() => setEditingTitle(true)}
                >
                  {session.title || "Untitled chat"}
                </button>
              )
            ) : (
              <h1 className="text-sm font-semibold text-zinc-900">New chat</h1>
            )}
          </div>

          <div className="flex shrink-0 items-center gap-1">
            {messages.length > 0 ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => void clear()}
                disabled={isStreaming}
              >
                Clear chat
              </Button>
            ) : null}
          </div>
        </header>

        {!hasConnection ? (
          <div className="flex flex-1 items-center justify-center p-6">
            <p className="text-sm text-zinc-500">
              {connections.length === 0
                ? "Add a connection under Connections to start querying."
                : "Select a connection in the sidebar to start querying."}
            </p>
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
            />
            <ChatInput
              value={draft}
              onChange={setDraft}
              onSend={(q) => void send(q)}
              disabled={
                !hasConnection || isStreaming || Boolean(rerunningMessageId)
              }
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
