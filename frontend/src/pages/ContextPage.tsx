import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { PageHeader } from "../components/PageHeader";
import { EnrichmentEditor } from "../components/context/EnrichmentEditor";
import { GoldenRecordForm } from "../components/context/GoldenRecordForm";
import {
  createRule,
  deleteRule,
  exportContextPack,
  importContextPack,
  listConnections,
  listRules,
} from "../services/api";
import type { ContextPackDocument } from "../types/api";
import {
  Button,
  Select,
  Spinner,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
} from "../components/ui";

function PackPanel({ connectionId }: { connectionId: string }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  const exportMutation = useMutation({
    mutationFn: () => exportContextPack(connectionId),
    onSuccess: (pack) => {
      const blob = new Blob([JSON.stringify(pack, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "astra-pack.json";
      link.click();
      URL.revokeObjectURL(url);
      setStatus({ type: "success", message: "Pack downloaded" });
    },
    onError: (err) => {
      setStatus({
        type: "error",
        message: getErrorMessage(err, "Export failed"),
      });
    },
  });

  const importMutation = useMutation({
    mutationFn: (pack: ContextPackDocument) =>
      importContextPack(connectionId, pack),
    onSuccess: (counts) => {
      queryClient.invalidateQueries({ queryKey: ["enrichments", connectionId] });
      queryClient.invalidateQueries({ queryKey: ["golden-records", connectionId] });
      queryClient.invalidateQueries({ queryKey: ["business-rules", connectionId] });
      setStatus({
        type: "success",
        message: `Imported ${counts.enrichments} enrichments, ${counts.rules} rules, ${counts.goldens} goldens`,
      });
    },
    onError: (err) => {
      setStatus({
        type: "error",
        message: getErrorMessage(err, "Import failed"),
      });
    },
  });

  const onFile = (file: File | undefined) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result)) as ContextPackDocument;
        importMutation.mutate(parsed);
      } catch {
        setStatus({ type: "error", message: "File is not valid JSON" });
      }
    };
    reader.readAsText(file);
  };

  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 py-2">
      <p className="mr-2 text-xs text-zinc-600">
        Astra Pack — export or merge this project&apos;s language
      </p>
      <Button
        type="button"
        size="sm"
        variant="secondary"
        disabled={exportMutation.isPending}
        onClick={() => exportMutation.mutate()}
      >
        Export
      </Button>
      <label className="inline-flex cursor-pointer items-center">
        <span className="sr-only">Import pack</span>
        <input
          type="file"
          accept="application/json,.json"
          className="hidden"
          onChange={(e) => {
            onFile(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={importMutation.isPending}
          onClick={(e) => {
            const input = (e.currentTarget.parentElement?.querySelector(
              "input[type=file]",
            ) ?? null) as HTMLInputElement | null;
            input?.click();
          }}
        >
          Import
        </Button>
      </label>
      {status ? (
        <span
          className={
            status.type === "error" ? "text-xs text-red-600" : "text-xs text-emerald-700"
          }
        >
          {status.message}
        </span>
      ) : null}
    </div>
  );
}

function getErrorMessage(err: unknown, fallback: string): string {
  if (isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    return err.message || fallback;
  }
  if (err instanceof Error) return err.message;
  return fallback;
}

function BusinessRulesPanel({ connectionId }: { connectionId: string }) {
  const queryClient = useQueryClient();
  const [content, setContent] = useState("");
  const [status, setStatus] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  const queryKey = ["business-rules", connectionId] as const;

  const listQuery = useQuery({
    queryKey,
    queryFn: () => listRules(connectionId),
    enabled: Boolean(connectionId),
  });

  useEffect(() => {
    setContent("");
    setStatus(null);
  }, [connectionId]);

  const createMutation = useMutation({
    mutationFn: () => {
      const text = content.trim();
      if (!text) throw new Error("Rule content is required");
      return createRule({ connection_id: connectionId, content: text });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey });
      setContent("");
      setStatus({ type: "success", message: "Business rule added." });
    },
    onError: (err) => {
      setStatus({
        type: "error",
        message: getErrorMessage(err, "Failed to add rule"),
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteRule(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey });
      setStatus({ type: "success", message: "Business rule deleted." });
    },
    onError: (err) => {
      setStatus({
        type: "error",
        message: getErrorMessage(err, "Failed to delete rule"),
      });
    },
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    setStatus(null);
    createMutation.mutate();
  };

  const items = listQuery.data ?? [];

  return (
    <div className="space-y-4">
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="space-y-1">
          <label
            htmlFor="rule-content"
            className="block text-xs font-medium text-zinc-600"
          >
            New business rule
          </label>
          <Textarea
            id="rule-content"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Revenue excludes cancelled orders. Fiscal year starts in April."
            rows={4}
            required
          />
        </div>

        {status ? (
          <p
            className={
              status.type === "success"
                ? "text-xs text-emerald-700"
                : "text-xs text-red-600"
            }
            role="status"
          >
            {status.message}
          </p>
        ) : null}

        <Button type="submit" size="sm" disabled={createMutation.isPending}>
          {createMutation.isPending ? <Spinner size="sm" /> : null}
          Add rule
        </Button>
      </form>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Rules
          </h3>
          {listQuery.isFetching ? <Spinner size="sm" /> : null}
        </div>

        {listQuery.isError ? (
          <p className="text-xs text-red-600">
            {getErrorMessage(listQuery.error, "Failed to load rules")}
          </p>
        ) : listQuery.isLoading ? (
          <div className="flex items-center gap-2 text-sm text-zinc-500">
            <Spinner size="sm" />
            Loading…
          </div>
        ) : items.length === 0 ? (
          <p className="text-sm text-zinc-500">No business rules yet.</p>
        ) : (
          <ul className="divide-y divide-zinc-200 rounded-lg border border-zinc-200 bg-white">
            {items.map((item) => (
              <li
                key={item.id}
                className="flex items-start justify-between gap-3 px-3 py-2.5"
              >
                <p className="whitespace-pre-wrap text-sm text-zinc-800">
                  {item.content}
                </p>
                <Button
                  size="sm"
                  variant="ghost"
                  className="shrink-0 text-red-600 hover:bg-red-50 hover:text-red-700"
                  disabled={deleteMutation.isPending}
                  onClick={() => deleteMutation.mutate(item.id)}
                >
                  Delete
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default function ContextPage() {
  const [connectionId, setConnectionId] = useState("");

  const connectionsQuery = useQuery({
    queryKey: ["connections"],
    queryFn: listConnections,
  });

  const connections = connectionsQuery.data ?? [];

  useEffect(() => {
    if (!connectionId && connections.length === 1) {
      setConnectionId(connections[0].id);
    }
    if (
      connectionId &&
      connections.length > 0 &&
      !connections.some((c) => c.id === connectionId)
    ) {
      setConnectionId("");
    }
  }, [connections, connectionId]);

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Context"
        description="Schema enrichments, golden records, business rules, and a portable pack"
      />

      <div className="flex-1 overflow-auto p-5">
        <div className="mb-4 max-w-md space-y-1">
          <label
            htmlFor="context-connection"
            className="block text-xs font-medium text-zinc-600"
          >
            Connection
          </label>
          <Select
            id="context-connection"
            value={connectionId}
            onChange={(e) => setConnectionId(e.target.value)}
            disabled={connectionsQuery.isLoading}
          >
            <option value="">
              {connectionsQuery.isLoading
                ? "Loading connections…"
                : "Select a connection…"}
            </option>
            {connections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.db_type})
              </option>
            ))}
          </Select>
          {connectionsQuery.isError ? (
            <p className="text-xs text-red-600">
              {getErrorMessage(
                connectionsQuery.error,
                "Failed to load connections",
              )}
            </p>
          ) : null}
        </div>

        {!connectionId ? (
          <div className="rounded-lg border border-dashed border-zinc-300 bg-white px-4 py-10 text-center">
            <p className="text-sm font-medium text-zinc-800">
              No connection selected
            </p>
            <p className="mt-1 text-xs text-zinc-500">
              Choose a connection above to manage enrichments, golden records,
              and business rules.
            </p>
          </div>
        ) : (
          <>
          <PackPanel connectionId={connectionId} />
          <Tabs defaultValue="enrichments" className="max-w-3xl">
            <TabsList>
              <TabsTrigger value="enrichments">Enrichments</TabsTrigger>
              <TabsTrigger value="golden">Golden Records</TabsTrigger>
              <TabsTrigger value="rules">Business Rules</TabsTrigger>
            </TabsList>
            <TabsContent value="enrichments">
              <EnrichmentEditor connectionId={connectionId} />
            </TabsContent>
            <TabsContent value="golden">
              <GoldenRecordForm connectionId={connectionId} />
            </TabsContent>
            <TabsContent value="rules">
              <BusinessRulesPanel connectionId={connectionId} />
            </TabsContent>
          </Tabs>
          </>
        )}
      </div>
    </div>
  );
}
