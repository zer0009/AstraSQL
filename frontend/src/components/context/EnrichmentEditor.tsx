import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import {
  createEnrichment,
  deleteEnrichment,
  listEnrichments,
  updateEnrichment,
} from "../../services/api";
import type { Enrichment } from "../../types/api";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Spinner,
  Textarea,
} from "../ui";

function getErrorMessage(err: unknown, fallback: string): string {
  if (isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    return err.message || fallback;
  }
  if (err instanceof Error) return err.message;
  return fallback;
}

interface FormState {
  table_name: string;
  column_name: string;
  description: string;
  alias: string;
  example_values: string;
}

const emptyForm: FormState = {
  table_name: "",
  column_name: "",
  description: "",
  alias: "",
  example_values: "",
};

function enrichmentToForm(item: Enrichment): FormState {
  return {
    table_name: item.table_name,
    column_name: item.column_name ?? "",
    description: item.description ?? "",
    alias: item.alias ?? "",
    example_values: item.example_values ?? "",
  };
}

export interface EnrichmentEditorProps {
  connectionId: string;
}

export function EnrichmentEditor({ connectionId }: EnrichmentEditorProps) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<FormState>(emptyForm);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [status, setStatus] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  const queryKey = ["enrichments", connectionId] as const;

  const listQuery = useQuery({
    queryKey,
    queryFn: () => listEnrichments(connectionId),
    enabled: Boolean(connectionId),
  });

  useEffect(() => {
    setForm(emptyForm);
    setEditingId(null);
    setStatus(null);
  }, [connectionId]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const table_name = form.table_name.trim();
      if (!table_name) throw new Error("Table name is required");

      const payload = {
        table_name,
        column_name: form.column_name.trim() || null,
        description: form.description.trim() || null,
        alias: form.alias.trim() || null,
        example_values: form.example_values.trim() || null,
      };

      if (editingId) {
        return updateEnrichment(editingId, payload);
      }
      return createEnrichment({ connection_id: connectionId, ...payload });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey });
      setForm(emptyForm);
      setEditingId(null);
      setStatus({
        type: "success",
        message: editingId ? "Enrichment updated." : "Enrichment created.",
      });
    },
    onError: (err) => {
      setStatus({
        type: "error",
        message: getErrorMessage(err, "Failed to save enrichment"),
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteEnrichment(id),
    onSuccess: (_, id) => {
      void queryClient.invalidateQueries({ queryKey });
      if (editingId === id) {
        setEditingId(null);
        setForm(emptyForm);
      }
      setStatus({ type: "success", message: "Enrichment deleted." });
    },
    onError: (err) => {
      setStatus({
        type: "error",
        message: getErrorMessage(err, "Failed to delete enrichment"),
      });
    },
  });

  const setField = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const startEdit = (item: Enrichment) => {
    setEditingId(item.id);
    setForm(enrichmentToForm(item));
    setStatus(null);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setForm(emptyForm);
    setStatus(null);
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    setStatus(null);
    saveMutation.mutate();
  };

  const items = listQuery.data ?? [];
  const labelClass = "block text-xs font-medium text-zinc-600";

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>
            {editingId ? "Edit enrichment" : "Add enrichment"}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label htmlFor="enrich-table" className={labelClass}>
                  Table name
                </label>
                <Input
                  id="enrich-table"
                  value={form.table_name}
                  onChange={(e) => setField("table_name", e.target.value)}
                  placeholder="orders"
                  required
                />
              </div>
              <div className="space-y-1">
                <label htmlFor="enrich-column" className={labelClass}>
                  Column name{" "}
                  <span className="font-normal text-zinc-400">(optional)</span>
                </label>
                <Input
                  id="enrich-column"
                  value={form.column_name}
                  onChange={(e) => setField("column_name", e.target.value)}
                  placeholder="status"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label htmlFor="enrich-alias" className={labelClass}>
                  Alias
                </label>
                <Input
                  id="enrich-alias"
                  value={form.alias}
                  onChange={(e) => setField("alias", e.target.value)}
                  placeholder="Order status"
                />
              </div>
              <div className="space-y-1">
                <label htmlFor="enrich-examples" className={labelClass}>
                  Example values
                </label>
                <Input
                  id="enrich-examples"
                  value={form.example_values}
                  onChange={(e) => setField("example_values", e.target.value)}
                  placeholder='["pending","shipped"]'
                />
              </div>
            </div>

            <div className="space-y-1">
              <label htmlFor="enrich-description" className={labelClass}>
                Description
              </label>
              <Textarea
                id="enrich-description"
                value={form.description}
                onChange={(e) => setField("description", e.target.value)}
                placeholder="Business meaning of this table or column"
                rows={3}
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

            <div className="flex items-center gap-2">
              <Button
                type="submit"
                size="sm"
                disabled={saveMutation.isPending}
              >
                {saveMutation.isPending ? <Spinner size="sm" /> : null}
                {editingId ? "Update" : "Add"}
              </Button>
              {editingId ? (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={cancelEdit}
                  disabled={saveMutation.isPending}
                >
                  Cancel
                </Button>
              ) : null}
            </div>
          </form>
        </CardContent>
      </Card>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Existing enrichments
          </h3>
          {listQuery.isFetching ? <Spinner size="sm" /> : null}
        </div>

        {listQuery.isError ? (
          <p className="text-xs text-red-600">
            {getErrorMessage(listQuery.error, "Failed to load enrichments")}
          </p>
        ) : listQuery.isLoading ? (
          <div className="flex items-center gap-2 text-sm text-zinc-500">
            <Spinner size="sm" />
            Loading…
          </div>
        ) : items.length === 0 ? (
          <p className="text-sm text-zinc-500">No enrichments yet.</p>
        ) : (
          <ul className="divide-y divide-zinc-200 rounded-lg border border-zinc-200 bg-white">
            {items.map((item) => (
              <li
                key={item.id}
                className="flex items-start justify-between gap-3 px-3 py-2.5"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-zinc-900">
                    <span className="font-mono">{item.table_name}</span>
                    {item.column_name ? (
                      <>
                        <span className="text-zinc-400">.</span>
                        <span className="font-mono">{item.column_name}</span>
                      </>
                    ) : (
                      <span className="ml-1 text-xs font-normal text-zinc-400">
                        (table)
                      </span>
                    )}
                    {item.alias ? (
                      <span className="ml-2 text-xs font-normal text-zinc-500">
                        {item.alias}
                      </span>
                    ) : null}
                  </p>
                  {item.description ? (
                    <p className="mt-0.5 line-clamp-2 text-xs text-zinc-500">
                      {item.description}
                    </p>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => startEdit(item)}
                    disabled={deleteMutation.isPending}
                  >
                    Edit
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-red-600 hover:bg-red-50 hover:text-red-700"
                    disabled={deleteMutation.isPending}
                    onClick={() => deleteMutation.mutate(item.id)}
                  >
                    Delete
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
