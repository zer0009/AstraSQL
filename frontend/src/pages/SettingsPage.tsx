import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "../components/PageHeader";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Select,
  Spinner,
} from "../components/ui";
import { cn } from "../lib/utils";
import { useUserPrefs } from "../hooks/useUserPrefs";
import {
  deleteSession,
  getPublicSettings,
  listConnections,
  listSessions,
} from "../services/api";
import type { Density } from "../lib/userPrefs";

const CONNECTION_STORAGE_KEY = "astrasql.selectedConnectionId";

const MEMORY_PRESETS = [
  { label: "Focused", turns: 1 },
  { label: "Balanced", turns: 3 },
  { label: "Extended", turns: 7 },
] as const;

const DB_TYPE_LABELS: Record<string, string> = {
  postgresql: "PostgreSQL",
  mysql: "MySQL",
  mssql: "Microsoft SQL Server",
};

function formatDbType(value: string): string {
  return DB_TYPE_LABELS[value] ?? value;
}

function SettingRow({
  label,
  description,
  children,
}: {
  label: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1 border-b border-zinc-100 py-3 last:border-0 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
      <div className="min-w-0 sm:max-w-[55%]">
        <dt className="text-sm font-medium text-zinc-800">{label}</dt>
        {description ? (
          <p className="mt-0.5 text-xs text-zinc-500">{description}</p>
        ) : null}
      </div>
      <dd className="shrink-0 text-sm text-zinc-900 sm:text-right">
        {children}
      </dd>
    </div>
  );
}

function SegmentedDensity({
  value,
  onChange,
}: {
  value: Density;
  onChange: (next: Density) => void;
}) {
  const options: { value: Density; label: string }[] = [
    { value: "comfortable", label: "Comfortable" },
    { value: "compact", label: "Compact" },
  ];

  return (
    <div
      role="group"
      aria-label="Theme density"
      className="inline-flex rounded-md border border-zinc-200 bg-zinc-50 p-0.5"
    >
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={cn(
            "rounded px-3 py-1.5 text-xs font-medium transition-colors",
            value === opt.value
              ? "bg-white text-zinc-900 shadow-sm"
              : "text-zinc-500 hover:text-zinc-800",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

export default function SettingsPage() {
  const { prefs, update, reset } = useUserPrefs();
  const queryClient = useQueryClient();

  const [connectionId, setConnectionId] = useState(() => {
    try {
      return localStorage.getItem(CONNECTION_STORAGE_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [clearMessage, setClearMessage] = useState<string | null>(null);
  const [resetMessage, setResetMessage] = useState<string | null>(null);

  const settingsQuery = useQuery({
    queryKey: ["settings", "public"],
    queryFn: getPublicSettings,
  });

  const connectionsQuery = useQuery({
    queryKey: ["connections"],
    queryFn: listConnections,
  });

  const connections = connectionsQuery.data ?? [];
  const effectiveConnectionId = useMemo(() => {
    if (connectionId && connections.some((c) => c.id === connectionId)) {
      return connectionId;
    }
    return connections[0]?.id ?? "";
  }, [connectionId, connections]);

  const sessionsQuery = useQuery({
    queryKey: ["sessions", effectiveConnectionId],
    queryFn: () =>
      listSessions({ connection_id: effectiveConnectionId, limit: 200 }),
    enabled: Boolean(effectiveConnectionId),
  });

  const clearSessionsMutation = useMutation({
    mutationFn: async () => {
      const sessions = sessionsQuery.data ?? [];
      for (const s of sessions) {
        await deleteSession(s.id);
      }
      return sessions.length;
    },
    onSuccess: (count) => {
      void queryClient.invalidateQueries({
        queryKey: ["sessions", effectiveConnectionId],
      });
      try {
        if (effectiveConnectionId) {
          localStorage.removeItem(
            `astrasql.currentSessionId.${effectiveConnectionId}`,
          );
        }
      } catch {
        // ignore
      }
      setClearMessage(
        count === 0
          ? "No sessions to clear."
          : `Cleared ${count} session${count === 1 ? "" : "s"}.`,
      );
    },
    onError: () => {
      setClearMessage("Failed to clear sessions.");
    },
  });

  const settings = settingsQuery.data;
  const sessionCount = sessionsQuery.data?.length ?? 0;
  const selectedConnectionName =
    connections.find((c) => c.id === effectiveConnectionId)?.name ?? null;

  const handleConnectionChange = (id: string) => {
    setConnectionId(id);
    setClearMessage(null);
    try {
      if (id) localStorage.setItem(CONNECTION_STORAGE_KEY, id);
      else localStorage.removeItem(CONNECTION_STORAGE_KEY);
    } catch {
      // ignore
    }
  };

  const handleResetPrefs = () => {
    if (
      !window.confirm(
        "Reset appearance and chat preferences to defaults? Chat sessions are not deleted.",
      )
    ) {
      return;
    }
    reset();
    setResetMessage("Preferences reset to defaults.");
    setClearMessage(null);
  };

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Settings"
        description="Preferences for this browser. Server options are set in your environment file."
      />
      <div className="flex-1 space-y-4 overflow-auto p-5">
        {/* Appearance */}
        <Card>
          <CardHeader>
            <CardTitle>Appearance</CardTitle>
            <CardDescription>
              How the interface looks in this browser.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <SettingRow
              label="Density"
              description="Compact tightens spacing in tables and page padding."
            >
              <SegmentedDensity
                value={prefs.density}
                onChange={(density) => update({ density })}
              />
            </SettingRow>
          </CardContent>
        </Card>

        {/* Chat behavior */}
        <Card>
          <CardHeader>
            <CardTitle>Chat behavior</CardTitle>
            <CardDescription>
              How much recent conversation is sent with each new question.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-sm font-medium text-zinc-800">
                    Conversation memory
                  </p>
                  <p className="mt-0.5 text-xs text-zinc-500">
                    How many recent Q&amp;A pairs are sent with each new
                    question. Higher uses more tokens.
                  </p>
                </div>
                <Badge variant="secondary">
                  {prefs.conversationTurns} turn
                  {prefs.conversationTurns === 1 ? "" : "s"}
                </Badge>
              </div>

              <div className="flex flex-wrap gap-1.5">
                {MEMORY_PRESETS.map((preset) => (
                  <button
                    key={preset.turns}
                    type="button"
                    onClick={() =>
                      update({ conversationTurns: preset.turns })
                    }
                    className={cn(
                      "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
                      prefs.conversationTurns === preset.turns
                        ? "border-zinc-900 bg-zinc-900 text-white"
                        : "border-zinc-200 bg-white text-zinc-600 hover:border-zinc-300 hover:bg-zinc-50",
                    )}
                  >
                    {preset.label} ({preset.turns})
                  </button>
                ))}
              </div>

              <input
                id="conversation-turns"
                type="range"
                min={1}
                max={10}
                step={1}
                value={prefs.conversationTurns}
                onChange={(e) =>
                  update({ conversationTurns: Number(e.target.value) })
                }
                aria-label="Conversation memory depth"
                className="w-full accent-zinc-900"
              />
              <div className="flex justify-between text-[11px] text-zinc-400">
                <span>1 — less context</span>
                <span>10 — more context</span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Chat sessions */}
        <Card>
          <CardHeader>
            <CardTitle>Chat sessions</CardTitle>
            <CardDescription>
              Manage saved chat threads for a database connection. Query history
              is kept; only chat session threads are deleted.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <label className="flex max-w-sm flex-col gap-1.5">
              <span className="text-sm font-medium text-zinc-800">
                Connection
              </span>
              {connectionsQuery.isLoading ? (
                <div className="flex items-center gap-2 text-sm text-zinc-500">
                  <Spinner size="sm" />
                  Loading connections…
                </div>
              ) : (
                <Select
                  value={effectiveConnectionId}
                  onChange={(e) => handleConnectionChange(e.target.value)}
                  disabled={connections.length === 0}
                >
                  {connections.length === 0 ? (
                    <option value="">No connections yet</option>
                  ) : (
                    connections.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))
                  )}
                </Select>
              )}
            </label>

            <p className="text-sm text-zinc-600">
              {sessionsQuery.isLoading ? (
                <span className="inline-flex items-center gap-2 text-zinc-500">
                  <Spinner size="sm" />
                  Loading sessions…
                </span>
              ) : effectiveConnectionId ? (
                <>
                  <span className="font-medium text-zinc-900">
                    {sessionCount}
                  </span>{" "}
                  saved session{sessionCount === 1 ? "" : "s"}
                  {selectedConnectionName
                    ? ` for ${selectedConnectionName}`
                    : ""}
                  .
                </>
              ) : (
                "Add a connection to manage chat sessions."
              )}
            </p>

            <div className="rounded-md border border-red-100 bg-red-50/60 px-3 py-3">
              <p className="text-xs font-medium text-red-800">Danger zone</p>
              <p className="mt-0.5 text-xs text-red-700/80">
                Clears chat threads for the selected connection. Past queries in
                History remain available.
              </p>
              <Button
                type="button"
                variant="danger"
                size="sm"
                className="mt-3"
                disabled={
                  !effectiveConnectionId ||
                  clearSessionsMutation.isPending ||
                  sessionsQuery.isLoading ||
                  sessionCount === 0
                }
                onClick={() => {
                  if (
                    !window.confirm(
                      `Delete all ${sessionCount} chat session${sessionCount === 1 ? "" : "s"} for this connection? Query history rows are kept.`,
                    )
                  ) {
                    return;
                  }
                  setClearMessage(null);
                  clearSessionsMutation.mutate();
                }}
              >
                {clearSessionsMutation.isPending
                  ? "Clearing…"
                  : "Clear sessions"}
              </Button>
              {clearMessage ? (
                <p
                  className={cn(
                    "mt-2 text-xs",
                    clearMessage.startsWith("Failed")
                      ? "text-red-700"
                      : "text-emerald-700",
                  )}
                  role="status"
                >
                  {clearMessage}
                </p>
              ) : null}
            </div>
          </CardContent>
        </Card>

        {/* About / server */}
        <Card>
          <CardHeader>
            <CardTitle>About this server</CardTitle>
            <CardDescription>
              Read-only details from the running AstraSQL backend.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {settingsQuery.isLoading ? (
              <div className="flex items-center gap-2 py-6 text-sm text-zinc-500">
                <Spinner size="sm" />
                Loading server details…
              </div>
            ) : settingsQuery.isError ? (
              <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                Could not load server details. Is the API running?
              </p>
            ) : settings ? (
              <dl>
                {settings.app_name ? (
                  <SettingRow label="App">{settings.app_name}</SettingRow>
                ) : null}
                <SettingRow label="AI provider">
                  <span className="font-medium capitalize">
                    {settings.llm_provider}
                  </span>
                </SettingRow>
                <SettingRow label="Model">
                  <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs">
                    {settings.openai_model}
                  </code>
                </SettingRow>
                <SettingRow
                  label="Result limit"
                  description="Maximum rows returned per query."
                >
                  {settings.max_result_rows.toLocaleString()}
                </SettingRow>
                <SettingRow label="Databases">
                  <div className="flex flex-wrap justify-end gap-1">
                    {settings.database_types.length === 0 ? (
                      <span className="text-zinc-400">None available</span>
                    ) : (
                      settings.database_types.map((t) => (
                        <Badge key={t} variant="secondary">
                          {formatDbType(t)}
                        </Badge>
                      ))
                    )}
                  </div>
                </SettingRow>
              </dl>
            ) : null}

            <p className="mt-4 rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2 text-xs text-zinc-600">
              Change these with environment variables on the server (see{" "}
              <code className="rounded bg-white px-1 py-0.5">.env.example</code>
              ).
            </p>
          </CardContent>
        </Card>

        {/* Reset local prefs */}
        <Card>
          <CardHeader>
            <CardTitle>Local preferences</CardTitle>
            <CardDescription>
              Reset appearance and chat memory for this browser. Does not delete
              sessions or server data.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleResetPrefs}
            >
              Reset local preferences
            </Button>
            {resetMessage ? (
              <p className="text-xs text-emerald-700" role="status">
                {resetMessage}
              </p>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
