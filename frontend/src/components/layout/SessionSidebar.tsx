import type { MouseEvent } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  MessageSquare,
  Plus,
  Trash2,
} from "lucide-react";
import { Button, Select, Spinner } from "../ui";
import { AstraLogo } from "../brand";
import { UserMenu } from "./UserMenu";
import { CHAT_FOOTER_NAV } from "./navItems";
import { deleteSession, listSessions } from "../../services/api";
import type { Connection } from "../../types/api";
import { useUserPrefs } from "../../hooks/useUserPrefs";
import { cn } from "../../lib/utils";

export interface SessionSidebarProps {
  connectionId: string;
  connections: Connection[];
  connectionsLoading?: boolean;
  onConnectionChange: (id: string) => void;
  activeSessionId: string | undefined;
  onNewChat: () => void;
  onSwitchSession: (id: string) => void;
  /** Called after a successful delete; parent should reset if active was deleted. */
  onDeleteSession: (id: string) => void;
  disabled?: boolean;
}

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diffSec = Math.round((Date.now() - then) / 1000);
  if (diffSec < 60) return "just now";
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay < 7) return `${diffDay}d ago`;
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

export function SessionSidebar({
  connectionId,
  connections,
  connectionsLoading = false,
  onConnectionChange,
  activeSessionId,
  onNewChat,
  onSwitchSession,
  onDeleteSession,
  disabled = false,
}: SessionSidebarProps) {
  const { prefs, update } = useUserPrefs();
  const open = prefs.sidebarOpen;
  const queryClient = useQueryClient();

  const sessionsQuery = useQuery({
    queryKey: ["sessions", connectionId],
    queryFn: () => listSessions({ connection_id: connectionId, limit: 100 }),
    enabled: Boolean(connectionId),
  });

  const sessions = sessionsQuery.data ?? [];

  const setOpen = (next: boolean) => {
    update({ sidebarOpen: next });
  };

  const handleDelete = async (sessionId: string, e: MouseEvent) => {
    e.stopPropagation();
    try {
      await deleteSession(sessionId);
    } catch {
      // already gone
    }
    await queryClient.invalidateQueries({
      queryKey: ["sessions", connectionId],
    });
    onDeleteSession(sessionId);
  };

  if (!open) {
    return (
      <aside
        className="flex w-12 shrink-0 flex-col items-center gap-2 border-r border-[var(--border)] bg-[var(--surface-raised)] py-3"
        aria-label="Chat sessions"
      >
        <button
          type="button"
          title="AstraSQL"
          className="flex h-8 w-8 items-center justify-center rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
          onClick={() => setOpen(true)}
        >
          <AstraLogo variant="mark" size={28} />
        </button>
        <button
          type="button"
          title="New chat"
          disabled={disabled || !connectionId}
          onClick={onNewChat}
          className="flex h-8 w-8 items-center justify-center rounded-md text-zinc-600 hover:bg-[var(--surface-muted)] disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
        >
          <Plus className="h-4 w-4" strokeWidth={1.75} />
        </button>
        <div className="flex min-h-0 flex-1 flex-col items-center gap-1 overflow-y-auto py-1">
          {sessions.slice(0, 8).map((s) => (
            <button
              key={s.id}
              type="button"
              title={s.title || "Untitled chat"}
              disabled={disabled}
              onClick={() => onSwitchSession(s.id)}
              className={cn(
                "flex h-8 w-8 items-center justify-center rounded-md text-zinc-500 hover:bg-[var(--surface-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
                activeSessionId === s.id && "bg-[var(--surface-muted)] text-zinc-900",
              )}
            >
              <MessageSquare className="h-3.5 w-3.5" strokeWidth={1.75} />
            </button>
          ))}
        </div>
        <div className="flex flex-col items-center gap-1 border-t border-[var(--border)] pt-2">
          {CHAT_FOOTER_NAV.map(({ to, label, icon: Icon }) => (
            <Link
              key={to}
              to={to}
              title={label}
              className="flex h-8 w-8 items-center justify-center rounded-md text-zinc-500 hover:bg-[var(--surface-muted)] hover:text-zinc-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
            >
              <Icon className="h-3.5 w-3.5" strokeWidth={1.75} />
            </Link>
          ))}
          <UserMenu compact />
        </div>
        <button
          type="button"
          title="Expand sidebar"
          onClick={() => setOpen(true)}
          className="flex h-8 w-8 items-center justify-center rounded-md text-zinc-500 hover:bg-[var(--surface-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
        >
          <ChevronRight className="h-4 w-4" strokeWidth={1.75} />
        </button>
      </aside>
    );
  }

  return (
    <aside
      className="flex w-60 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-raised)]"
      aria-label="Chat sessions"
    >
      <div className="flex h-12 shrink-0 items-center border-b border-[var(--border)] px-4">
        <AstraLogo size={22} />
      </div>

      <div className="space-y-2 border-b border-[var(--border)] p-3">
        <label
          htmlFor="sidebar-connection"
          className="text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)]"
        >
          Connection
        </label>
        {connectionsLoading ? (
          <div className="flex h-8 items-center">
            <Spinner size="sm" />
          </div>
        ) : (
          <Select
            id="sidebar-connection"
            className="h-8 w-full"
            value={connectionId}
            onChange={(e) => onConnectionChange(e.target.value)}
            disabled={connections.length === 0 || disabled}
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
        <Button
          type="button"
          variant="secondary"
          size="sm"
          className="w-full justify-start"
          disabled={disabled || !connectionId}
          onClick={onNewChat}
        >
          <Plus className="h-3.5 w-3.5" strokeWidth={1.75} />
          New Chat
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {!connectionId ? (
          <p className="px-2 py-6 text-center text-xs text-zinc-500">
            Select a connection to see chats.
          </p>
        ) : sessionsQuery.isLoading ? (
          <div className="flex items-center justify-center gap-2 py-6 text-xs text-zinc-500">
            <Spinner size="sm" />
            Loading…
          </div>
        ) : sessions.length === 0 ? (
          <p className="px-2 py-6 text-center text-xs text-zinc-500">
            No chats yet. Ask a question to start.
          </p>
        ) : (
          <ul className="space-y-0.5">
            {sessions.map((s) => {
              const active = activeSessionId === s.id;
              const title = s.title || "Untitled chat";
              return (
                <li key={s.id} className="group flex items-stretch gap-0.5">
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => onSwitchSession(s.id)}
                    className={cn(
                      "min-w-0 flex-1 rounded-md px-2 py-1.5 text-left hover:bg-[var(--surface-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
                      active && "bg-[var(--surface-muted)]",
                      disabled && "opacity-50",
                    )}
                  >
                    <p
                      className={cn(
                        "truncate text-xs font-medium text-zinc-800",
                        active && "text-zinc-900",
                      )}
                    >
                      {title}
                    </p>
                    <p className="text-[10px] text-[var(--text-muted)]">
                      {formatRelative(s.updated_at)}
                    </p>
                  </button>
                  <button
                    type="button"
                    title={`Delete ${title}`}
                    aria-label={`Delete ${title}`}
                    disabled={disabled}
                    className="mt-0.5 shrink-0 rounded p-1.5 text-zinc-400 opacity-0 hover:bg-zinc-200 hover:text-red-600 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] group-hover:opacity-100 group-focus-within:opacity-100"
                    onClick={(e) => void handleDelete(s.id, e)}
                  >
                    <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="shrink-0 border-t border-[var(--border)] p-2">
        <nav
          className="mb-1 flex items-center justify-around gap-0.5"
          aria-label="App sections"
        >
          {CHAT_FOOTER_NAV.map(({ to, label, icon: Icon }) => (
            <Link
              key={to}
              to={to}
              title={label}
              className="flex h-8 w-8 items-center justify-center rounded-md text-zinc-500 hover:bg-[var(--surface-muted)] hover:text-zinc-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
            >
              <Icon className="h-3.5 w-3.5" strokeWidth={1.75} />
            </Link>
          ))}
        </nav>
        <UserMenu className="mb-1 justify-between px-1" />
        <p className="mb-1 px-1 text-center text-[10px] text-[var(--text-muted)]">
          Self-hosted NL2SQL
        </p>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs text-zinc-500 hover:bg-[var(--surface-muted)] hover:text-zinc-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
        >
          <ChevronLeft className="h-3.5 w-3.5" strokeWidth={1.75} />
          Collapse
        </button>
      </div>
    </aside>
  );
}
