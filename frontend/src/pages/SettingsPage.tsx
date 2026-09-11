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
import { useUserPrefs } from "../hooks/useUserPrefs";
import {
  deleteSession,
  getPublicSettings,
  listConnections,
  listSessions,
} from "../services/api";

const CONNECTION_STORAGE_KEY = "astrasql.selectedConnectionId";

function SettingRow({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-0.5 border-b border-zinc-100 py-3 last:border-0 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <dt className="text-xs font-medium text-zinc-500">{label}</dt>
      <dd className="text-sm text-zinc-900 sm:text-right">{children}</dd>
    </div>
  );
}

export default function SettingsPage() {
  const { prefs, update } = useUserPrefs();
  const queryClient = useQueryClient();

  const [connectionId, setConnectionId] = useState(() => {
    try {
      return localStorage.getItem(CONNECTION_STORAGE_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [clearMessage, setClearMessage] = useState<string | null>(null);

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

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Settings"
        description="Application configuration"
      />
      <div className="flex-1 space-y-4 overflow-auto p-5">
        <Card>
          <CardHeader>
            <CardTitle>Server configuration</CardTitle>
            <CardDescription>
              Read-only values from{" "}
              <code className="rounded bg-zinc-100 px-1 py-0.5 text-[11px]">
                GET /api/settings/public
              </code>
            </CardDescription>
          </CardHeader>
          <CardContent>
            {settingsQuery.isLoading ? (
              <div className="flex items-center gap-2 py-6 text-sm text-zinc-500">
                <Spinner size="sm" />
                Loading settings…
              </div>
            ) : settingsQuery.isError ? (
              <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                Failed to load public settings.
              </p>
            ) : settings ? (
              <dl>
                {settings.app_name ? (
                  <SettingRow label="App name">{settings.app_name}</SettingRow>
                ) : null}
                <SettingRow label="LLM provider">
                  <span className="font-medium">{settings.llm_provider}</span>
                </SettingRow>
                <SettingRow label="Model">
                  <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs">
                    {settings.openai_model}
                  </code>
                </SettingRow>
                <SettingRow label="Max result rows">
                  {settings.max_result_rows}
                </SettingRow>
                <SettingRow label="Available database types">
                  <div className="flex flex-wrap justify-end gap-1">
                    {settings.database_types.length === 0 ? (
                      <span className="text-zinc-400">None registered</span>
                    ) : (
                      settings.database_types.map((t) => (
                        <Badge key={t} variant="secondary">
                          {t}
                        </Badge>
                      ))
                    )}
                  </div>
                </SettingRow>
              </dl>
            ) : null}

            <p className="mt-4 rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2 text-xs text-zinc-600">
              Configure via environment variables (
              <code className="rounded bg-white px-1 py-0.5">.env</code>) on
              the server.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Local preferences</CardTitle>
            <CardDescription>
              Stored in this browser only (
              <code className="rounded bg-zinc-100 px-1 py-0.5 text-[11px]">
                localStorage
              </code>
              )
            </CardDescription>
          </CardHeader>
          <CardContent>
            <label className="flex max-w-xs flex-col gap-1">
              <span className="text-xs font-medium text-zinc-500">
                Theme density
              </span>
              <Select
                value={prefs.density}
                onChange={(e) =>
                  update({
                    density: e.target.value as "comfortable" | "compact",
                  })
                }
              >
                <option value="comfortable">Comfortable</option>
                <option value="compact">Compact</option>
              </Select>
            </label>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Chat & Memory</CardTitle>
            <CardDescription>
              Controls multi-turn context and persisted chat sessions on the
              server
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="max-w-md space-y-2">
              <div className="flex items-center justify-between gap-3">
                <label
                  htmlFor="conversation-turns"
                  className="text-xs font-medium text-zinc-500"
                >
                  Conversation memory depth
                </label>
                <span className="text-xs text-zinc-600">
                  Last {prefs.conversationTurns} turn
                  {prefs.conversationTurns === 1 ? "" : "s"} sent as context
                </span>
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
                className="w-full accent-zinc-900"
              />
            </div>

            <div className="space-y-2 border-t border-zinc-100 pt-4">
              <label className="flex max-w-xs flex-col gap-1">
                <span className="text-xs font-medium text-zinc-500">
                  Connection
                </span>
                {connectionsQuery.isLoading ? (
                  <Spinner size="sm" />
                ) : (
                  <Select
                    value={effectiveConnectionId}
                    onChange={(e) => {
                      setConnectionId(e.target.value);
                      setClearMessage(null);
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
              </label>

              <p className="text-xs text-zinc-500">
                {sessionsQuery.isLoading
                  ? "Loading sessions…"
                  : `${sessionCount} saved session${sessionCount === 1 ? "" : "s"} for this connection.`}
              </p>

              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={
                  !effectiveConnectionId ||
                  clearSessionsMutation.isPending ||
                  sessionsQuery.isLoading
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
                  : "Clear all sessions for this connection"}
              </Button>

              {clearMessage ? (
                <p className="text-xs text-zinc-600">{clearMessage}</p>
              ) : null}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
