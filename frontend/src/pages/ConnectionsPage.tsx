import { useEffect, useMemo, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { Plus, X } from "lucide-react";
import { useState } from "react";
import { PageHeader } from "../components/PageHeader";
import { ConnectionCard } from "../components/connections/ConnectionCard";
import { ConnectionForm } from "../components/connections/ConnectionForm";
import {
  deleteConnection,
  listConnections,
  listScanJobs,
  scanConnection,
  testConnection,
} from "../services/api";
import type { Connection, ScanJobStatus } from "../types/api";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Spinner,
} from "../components/ui";

function getErrorMessage(err: unknown, fallback: string): string {
  if (isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    return err.message || fallback;
  }
  if (err instanceof Error) return err.message;
  return fallback;
}

function isActive(job: ScanJobStatus): boolean {
  return job.status === "pending" || job.status === "running";
}

export default function ConnectionsPage() {
  const queryClient = useQueryClient();
  const [panel, setPanel] = useState<"closed" | "create" | "edit">("closed");
  const [editing, setEditing] = useState<Connection | null>(null);
  const [pageStatus, setPageStatus] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);
  const completedNotified = useRef<Set<string>>(new Set());

  const connectionsQuery = useQuery({
    queryKey: ["connections"],
    queryFn: listConnections,
  });

  const scansQuery = useQuery({
    queryKey: ["connection-scans"],
    queryFn: () => listScanJobs(false),
    refetchInterval: (query) => {
      const jobs = query.state.data ?? [];
      return jobs.some(isActive) ? 1000 : 5000;
    },
  });

  const scanByConnection = useMemo(() => {
    const map = new Map<string, ScanJobStatus>();
    for (const job of scansQuery.data ?? []) {
      const prev = map.get(job.connection_id);
      if (!prev) {
        map.set(job.connection_id, job);
        continue;
      }
      // Prefer active jobs, else newest by started_at
      if (isActive(job) && !isActive(prev)) {
        map.set(job.connection_id, job);
      } else if (!isActive(prev) && (job.started_at ?? "") > (prev.started_at ?? "")) {
        map.set(job.connection_id, job);
      }
    }
    return map;
  }, [scansQuery.data]);

  // When a scan finishes, refresh connections (last_scanned_at) once.
  useEffect(() => {
    for (const job of scansQuery.data ?? []) {
      if (job.status !== "completed" && job.status !== "failed") continue;
      if (completedNotified.current.has(job.job_id)) continue;
      completedNotified.current.add(job.job_id);
      void queryClient.invalidateQueries({ queryKey: ["connections"] });
      if (job.status === "completed") {
        setPageStatus({
          type: "success",
          message: `${job.connection_name}: scan complete (${job.tables_done} tables).`,
        });
      } else {
        setPageStatus({
          type: "error",
          message: `${job.connection_name}: scan failed — ${job.error ?? job.message}`,
        });
      }
    }
  }, [scansQuery.data, queryClient]);

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteConnection(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["connections"] });
      setPageStatus({ type: "success", message: "Connection deleted." });
    },
  });

  const openCreate = () => {
    setEditing(null);
    setPanel("create");
    setPageStatus(null);
  };

  const openEdit = (connection: Connection) => {
    setEditing(connection);
    setPanel("edit");
    setPageStatus(null);
  };

  const closePanel = () => {
    setPanel("closed");
    setEditing(null);
  };

  const handleFormSuccess = (saved: Connection) => {
    void queryClient.invalidateQueries({ queryKey: ["connections"] });
    setPageStatus({
      type: "success",
      message: panel === "edit" ? "Connection updated." : "Connection created.",
    });
    if (panel === "create") {
      setEditing(saved);
      setPanel("edit");
    } else {
      setEditing(saved);
    }
  };

  const connections = connectionsQuery.data ?? [];
  const activeScans = (scansQuery.data ?? []).filter(isActive);

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Connections"
        description="Manage database connections"
      />

      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col overflow-auto p-5">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="min-w-0">
              {pageStatus ? (
                <p
                  className={
                    pageStatus.type === "success"
                      ? "text-xs text-emerald-700"
                      : "text-xs text-red-600"
                  }
                  role="status"
                >
                  {pageStatus.message}
                </p>
              ) : connectionsQuery.isError ? (
                <p className="text-xs text-red-600" role="status">
                  {getErrorMessage(
                    connectionsQuery.error,
                    "Failed to load connections",
                  )}
                </p>
              ) : activeScans.length > 0 ? (
                <p className="text-xs text-amber-700" role="status">
                  {activeScans.length} schema scan
                  {activeScans.length === 1 ? "" : "s"} running in the
                  background — you can leave this page.
                </p>
              ) : (
                <p className="text-xs text-zinc-500">
                  {connectionsQuery.isLoading
                    ? "Loading connections…"
                    : `${connections.length} connection${connections.length === 1 ? "" : "s"}`}
                </p>
              )}
            </div>
            <Button size="sm" onClick={openCreate}>
              <Plus className="h-3.5 w-3.5" strokeWidth={2} />
              Add connection
            </Button>
          </div>

          {connectionsQuery.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-zinc-500">
              <Spinner size="sm" />
              Loading…
            </div>
          ) : connections.length === 0 ? (
            <div className="rounded-lg border border-dashed border-zinc-300 bg-white px-4 py-10 text-center">
              <p className="text-sm font-medium text-zinc-800">
                No connections configured
              </p>
              <p className="mt-1 text-xs text-zinc-500">
                Add a PostgreSQL connection to start querying.
              </p>
              <Button size="sm" className="mt-4" onClick={openCreate}>
                <Plus className="h-3.5 w-3.5" strokeWidth={2} />
                Add connection
              </Button>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {connections.map((connection) => (
                <ConnectionCard
                  key={connection.id}
                  connection={connection}
                  scan={scanByConnection.get(connection.id) ?? null}
                  busy={deleteMutation.isPending}
                  onEdit={openEdit}
                  onTest={(c) => testConnection(c.id)}
                  onScan={async (c) => {
                    const result = await scanConnection(c.id);
                    void queryClient.invalidateQueries({
                      queryKey: ["connection-scans"],
                    });
                    return result;
                  }}
                  onDelete={async (c) => {
                    await deleteMutation.mutateAsync(c.id);
                    if (editing?.id === c.id) closePanel();
                  }}
                />
              ))}
            </div>
          )}
        </div>

        {panel !== "closed" ? (
          <aside className="flex w-full max-w-md shrink-0 flex-col border-l border-zinc-200 bg-white">
            <Card className="flex h-full flex-col rounded-none border-0 shadow-none">
              <CardHeader className="flex flex-row items-center justify-between space-y-0">
                <CardTitle>
                  {panel === "edit" ? "Edit connection" : "Add connection"}
                </CardTitle>
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label="Close"
                  onClick={closePanel}
                >
                  <X className="h-4 w-4" strokeWidth={1.75} />
                </Button>
              </CardHeader>
              <CardContent className="flex-1 overflow-auto">
                <ConnectionForm
                  connection={editing}
                  onSuccess={handleFormSuccess}
                  onCancel={closePanel}
                />
              </CardContent>
            </Card>
          </aside>
        ) : null}
      </div>
    </div>
  );
}
