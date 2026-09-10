import { useState } from "react";
import { isAxiosError } from "axios";
import type {
  Connection,
  ConnectionScanResult,
  ConnectionTestResult,
  ScanJobStatus,
} from "../../types/api";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
  Spinner,
} from "../ui";

const STALE_MS = 7 * 24 * 60 * 60 * 1000;

function getErrorMessage(err: unknown, fallback: string): string {
  if (isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    return err.message || fallback;
  }
  if (err instanceof Error) return err.message;
  return fallback;
}

function formatScanDate(iso: string | null): string {
  if (!iso) return "Never scanned";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function isScanStale(lastScannedAt: string | null): boolean {
  if (!lastScannedAt) return true;
  const t = new Date(lastScannedAt).getTime();
  if (Number.isNaN(t)) return true;
  return Date.now() - t > STALE_MS;
}

function isScanActive(scan?: ScanJobStatus | null): boolean {
  return Boolean(scan && (scan.status === "pending" || scan.status === "running"));
}

export interface ConnectionCardProps {
  connection: Connection;
  scan?: ScanJobStatus | null;
  busy?: boolean;
  onEdit: (connection: Connection) => void;
  onTest: (connection: Connection) => Promise<ConnectionTestResult>;
  onScan: (connection: Connection) => Promise<ConnectionScanResult>;
  onDelete: (connection: Connection) => Promise<void>;
}

export function ConnectionCard({
  connection,
  scan = null,
  busy = false,
  onEdit,
  onTest,
  onScan,
  onDelete,
}: ConnectionCardProps) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [action, setAction] = useState<"test" | "scan" | "delete" | null>(
    null,
  );
  const [status, setStatus] = useState<{
    type: "success" | "error" | "warning";
    message: string;
  } | null>(null);

  const scanning = isScanActive(scan);
  const stale = isScanStale(connection.last_scanned_at);
  const endpoint = `${connection.host}:${connection.port}/${connection.database}`;

  const run = async (
    kind: "test" | "scan" | "delete",
    fn: () => Promise<void>,
  ) => {
    setStatus(null);
    setAction(kind);
    try {
      await fn();
    } catch (err) {
      setStatus({
        type: "error",
        message: getErrorMessage(err, `Failed to ${kind} connection`),
      });
    } finally {
      setAction(null);
    }
  };

  const handleTest = () =>
    run("test", async () => {
      const result = await onTest(connection);
      setStatus({
        type: result.ok ? "success" : "error",
        message: result.message,
      });
    });

  const handleScan = () =>
    run("scan", async () => {
      const result = await onScan(connection);
      setStatus({
        type: "success",
        message: result.message || "Schema scan started in the background.",
      });
    });

  const handleDelete = () =>
    run("delete", async () => {
      await onDelete(connection);
      setConfirmDelete(false);
    });

  return (
    <Card className="flex flex-col">
      <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0">
        <div className="min-w-0">
          <CardTitle className="truncate">{connection.name}</CardTitle>
          <p className="mt-1 truncate font-mono text-xs text-zinc-500">
            {endpoint}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <Badge variant="secondary" className="uppercase">
            {connection.db_type}
          </Badge>
          {scanning ? (
            <Badge variant="warning">Scanning</Badge>
          ) : scan?.status === "completed" ? (
            <Badge variant="success">Scan OK</Badge>
          ) : scan?.status === "failed" ? (
            <Badge variant="danger">Scan failed</Badge>
          ) : null}
        </div>
      </CardHeader>

      <CardContent className="space-y-2">
        <div className="flex items-center gap-2 text-xs">
          <span className="text-zinc-500">Last scanned</span>
          <span className={stale ? "text-amber-700" : "text-zinc-700"}>
            {formatScanDate(
              scan?.last_scanned_at ?? connection.last_scanned_at,
            )}
          </span>
          {stale && !scanning ? (
            <Badge variant="warning">
              {connection.last_scanned_at ? "Stale (>7d)" : "Not scanned"}
            </Badge>
          ) : null}
        </div>

        {scan && (scanning || scan.status === "failed" || scan.status === "completed") ? (
          <div className="rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2">
            <div className="flex items-center justify-between gap-2 text-xs">
              <span className="font-medium text-zinc-800">
                {scanning ? "Schema scan in progress" : scan.status === "failed" ? "Schema scan failed" : "Schema scan finished"}
              </span>
              <span className="tabular-nums text-zinc-500">{scan.percent}%</span>
            </div>
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-zinc-200">
              <div
                className={
                  scan.status === "failed"
                    ? "h-full rounded-full bg-red-500 transition-all"
                    : scan.status === "completed"
                      ? "h-full rounded-full bg-emerald-600 transition-all"
                      : "h-full rounded-full bg-zinc-800 transition-all"
                }
                style={{ width: `${Math.max(scan.percent, scanning ? 4 : 0)}%` }}
              />
            </div>
            <p className="mt-1.5 text-xs text-zinc-600" role="status">
              {scan.message}
              {scan.current_table ? (
                <span className="text-zinc-500">
                  {" "}
                  · <span className="font-mono">{scan.current_table}</span>
                </span>
              ) : null}
            </p>
            {scan.tables_total > 0 ? (
              <p className="mt-0.5 text-[11px] text-zinc-500">
                {scan.tables_done}/{scan.tables_total} tables
                {scan.phase ? ` · phase: ${scan.phase}` : ""}
              </p>
            ) : null}
            {scan.error ? (
              <p className="mt-1 text-xs text-red-600">{scan.error}</p>
            ) : null}
            {scan.tables_cached.length > 0 && scanning ? (
              <p className="mt-1 truncate text-[11px] text-zinc-400">
                Recent: {scan.tables_cached.slice(-5).join(", ")}
              </p>
            ) : null}
          </div>
        ) : null}

        {status && !scanning ? (
          <p
            className={
              status.type === "success"
                ? "text-xs text-emerald-700"
                : status.type === "warning"
                  ? "text-xs text-amber-700"
                  : "text-xs text-red-600"
            }
            role="status"
          >
            {status.message}
          </p>
        ) : null}

        {confirmDelete ? (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
            <p className="font-medium">Delete this connection?</p>
            <p className="mt-1 text-red-700">
              This will permanently remove the connection and cascade-delete
              related enrichments, golden records, business rules, schema cache,
              and query history.
            </p>
            <div className="mt-2 flex items-center gap-2">
              <Button
                size="sm"
                variant="danger"
                disabled={action === "delete" || busy || scanning}
                onClick={handleDelete}
              >
                {action === "delete" ? <Spinner size="sm" /> : null}
                Confirm delete
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={action === "delete"}
                onClick={() => setConfirmDelete(false)}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : null}
      </CardContent>

      <CardFooter className="mt-auto flex-wrap">
        <Button
          size="sm"
          variant="outline"
          disabled={busy || action !== null || scanning}
          onClick={() => onEdit(connection)}
        >
          Edit
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={busy || action !== null || scanning}
          onClick={handleTest}
        >
          {action === "test" ? <Spinner size="sm" /> : null}
          Test
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={busy || action !== null || scanning}
          onClick={handleScan}
        >
          {action === "scan" || scanning ? <Spinner size="sm" /> : null}
          {scanning ? "Scanning…" : "Scan schema"}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="text-red-600 hover:bg-red-50 hover:text-red-700"
          disabled={busy || action !== null || scanning}
          onClick={() => {
            setConfirmDelete(true);
            setStatus(null);
          }}
        >
          Delete
        </Button>
      </CardFooter>
    </Card>
  );
}
