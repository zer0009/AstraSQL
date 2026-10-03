import { useMemo, useState } from "react";
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
  Textarea,
} from "../components/ui";
import {
  getSemanticLayer,
  importDictionary,
  listConnections,
  updateRelationshipStatus,
} from "../services/api";

const STORAGE_KEY = "astrasql.selectedConnectionId";

export default function SemanticLayerPage() {
  const queryClient = useQueryClient();
  const [connectionId, setConnectionId] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [dictFormat, setDictFormat] = useState<"json" | "csv" | "bird_csv">(
    "json",
  );
  const [dictContent, setDictContent] = useState("");
  const [dictTable, setDictTable] = useState("");
  const [importMessage, setImportMessage] = useState<string | null>(null);

  const connectionsQuery = useQuery({
    queryKey: ["connections"],
    queryFn: listConnections,
  });
  const connections = connectionsQuery.data ?? [];
  const effectiveId = useMemo(() => {
    if (connectionId && connections.some((c) => c.id === connectionId)) {
      return connectionId;
    }
    return connections[0]?.id ?? "";
  }, [connectionId, connections]);

  const layerQuery = useQuery({
    queryKey: ["semantic-layer", effectiveId],
    queryFn: () => getSemanticLayer(effectiveId),
    enabled: Boolean(effectiveId),
  });

  const statusMutation = useMutation({
    mutationFn: (args: {
      from_table: string;
      from_col: string;
      to_table: string;
      to_col: string;
      status: "approved" | "proposed" | "rejected";
    }) =>
      updateRelationshipStatus(
        effectiveId,
        args.from_table,
        args.from_col,
        args.to_table,
        args.to_col,
        args.status,
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["semantic-layer", effectiveId],
      });
    },
  });

  const importMutation = useMutation({
    mutationFn: () =>
      importDictionary(effectiveId, {
        format: dictFormat,
        content: dictContent,
        table_name: dictTable || undefined,
      }),
    onSuccess: (result) => {
      setImportMessage(result.message || "Import complete");
      setDictContent("");
      void queryClient.invalidateQueries({ queryKey: ["enrichments"] });
    },
    onError: () => setImportMessage("Import failed"),
  });

  const layer = layerQuery.data;

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Schema & knowledge"
        description="Review discovered table links, learned conventions, and import a data dictionary."
      />
      <div className="flex-1 space-y-4 overflow-auto p-5">
        <label className="flex max-w-sm flex-col gap-1.5">
          <span className="text-sm font-medium text-zinc-800">Connection</span>
          <Select
            value={effectiveId}
            onChange={(e) => {
              setConnectionId(e.target.value);
              try {
                localStorage.setItem(STORAGE_KEY, e.target.value);
              } catch {
                // ignore
              }
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
        </label>

        {!effectiveId ? (
          <p className="text-sm text-zinc-500">Add a connection first.</p>
        ) : layerQuery.isLoading ? (
          <div className="flex items-center gap-2 text-sm text-zinc-500">
            <Spinner size="sm" /> Loading…
          </div>
        ) : (
          <>
            <Card>
              <CardHeader>
                <CardTitle>Table relationships</CardTitle>
                <CardDescription>
                  Approve or reject joins discovered during schema scan.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {(layer?.relationships ?? []).length === 0 ? (
                  <p className="text-sm text-zinc-500">
                    No relationships yet. Scan the schema to discover them.
                  </p>
                ) : (
                  (layer?.relationships ?? []).map((rel) => (
                    <div
                      key={`${rel.from_table}.${rel.from_col}=${rel.to_table}.${rel.to_col}`}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-zinc-200 px-3 py-2"
                    >
                      <div className="min-w-0">
                        <p className="font-mono text-xs text-zinc-800">
                          {rel.from_table}.{rel.from_col} → {rel.to_table}.
                          {rel.to_col}
                        </p>
                        <div className="mt-1 flex items-center gap-2">
                          <Badge
                            variant={
                              rel.status === "approved"
                                ? "success"
                                : rel.status === "rejected"
                                  ? "danger"
                                  : "secondary"
                            }
                          >
                            {rel.status}
                          </Badge>
                          {rel.score != null ? (
                            <span className="text-[11px] text-zinc-400">
                              score {Number(rel.score).toFixed(2)}
                            </span>
                          ) : null}
                        </div>
                      </div>
                      <div className="flex gap-1">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={statusMutation.isPending}
                          onClick={() =>
                            statusMutation.mutate({
                              ...rel,
                              from_table: rel.from_table,
                              from_col: rel.from_col,
                              to_table: rel.to_table,
                              to_col: rel.to_col,
                              status: "approved",
                            })
                          }
                        >
                          Approve
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          disabled={statusMutation.isPending}
                          onClick={() =>
                            statusMutation.mutate({
                              from_table: rel.from_table,
                              from_col: rel.from_col,
                              to_table: rel.to_table,
                              to_col: rel.to_col,
                              status: "rejected",
                            })
                          }
                        >
                          Reject
                        </Button>
                      </div>
                    </div>
                  ))
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Learned conventions</CardTitle>
                <CardDescription>
                  Patterns recorded from feedback (join types, directions).
                </CardDescription>
              </CardHeader>
              <CardContent>
                {(layer?.conventions ?? []).length === 0 ? (
                  <p className="text-sm text-zinc-500">None yet.</p>
                ) : (
                  <ul className="list-disc space-y-1 pl-5 text-sm text-zinc-700">
                    {(layer?.conventions ?? []).map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Import data dictionary</CardTitle>
                <CardDescription>
                  Paste JSON, CSV, or a BIRD-style description CSV to enrich
                  column meanings.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex flex-wrap gap-2">
                  <Select
                    value={dictFormat}
                    onChange={(e) =>
                      setDictFormat(e.target.value as typeof dictFormat)
                    }
                  >
                    <option value="json">JSON</option>
                    <option value="csv">CSV</option>
                    <option value="bird_csv">BIRD CSV</option>
                  </Select>
                  {dictFormat === "bird_csv" ? (
                    <input
                      className="rounded-md border border-zinc-200 px-2 py-1.5 text-sm"
                      placeholder="Table name"
                      value={dictTable}
                      onChange={(e) => setDictTable(e.target.value)}
                    />
                  ) : null}
                </div>
                <Textarea
                  value={dictContent}
                  onChange={(e) => setDictContent(e.target.value)}
                  className="min-h-[140px] font-mono text-xs"
                  placeholder='{"customers":{"status":{"description":"A=active"}}}'
                />
                <Button
                  type="button"
                  size="sm"
                  disabled={!dictContent.trim() || importMutation.isPending}
                  onClick={() => importMutation.mutate()}
                >
                  {importMutation.isPending ? "Importing…" : "Import"}
                </Button>
                {importMessage ? (
                  <p className="text-xs text-emerald-700" role="status">
                    {importMessage}
                  </p>
                ) : null}
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}
