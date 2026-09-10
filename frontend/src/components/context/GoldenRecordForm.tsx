import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import {
  createGoldenRecord,
  deleteGoldenRecord,
  listGoldenRecords,
} from "../../services/api";
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

export interface GoldenRecordFormProps {
  connectionId: string;
}

export function GoldenRecordForm({ connectionId }: GoldenRecordFormProps) {
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState("");
  const [sql, setSql] = useState("");
  const [status, setStatus] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  const queryKey = ["golden-records", connectionId] as const;

  const listQuery = useQuery({
    queryKey,
    queryFn: () => listGoldenRecords(connectionId),
    enabled: Boolean(connectionId),
  });

  useEffect(() => {
    setQuestion("");
    setSql("");
    setStatus(null);
  }, [connectionId]);

  const createMutation = useMutation({
    mutationFn: () => {
      const q = question.trim();
      const s = sql.trim();
      if (!q) throw new Error("Question is required");
      if (!s) throw new Error("SQL is required");
      return createGoldenRecord({
        connection_id: connectionId,
        question: q,
        sql: s,
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey });
      setQuestion("");
      setSql("");
      setStatus({ type: "success", message: "Golden record added." });
    },
    onError: (err) => {
      setStatus({
        type: "error",
        message: getErrorMessage(err, "Failed to add golden record"),
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteGoldenRecord(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey });
      setStatus({ type: "success", message: "Golden record deleted." });
    },
    onError: (err) => {
      setStatus({
        type: "error",
        message: getErrorMessage(err, "Failed to delete golden record"),
      });
    },
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    setStatus(null);
    createMutation.mutate();
  };

  const items = listQuery.data ?? [];
  const labelClass = "block text-xs font-medium text-zinc-600";

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Add golden record</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-3">
            <div className="space-y-1">
              <label htmlFor="golden-question" className={labelClass}>
                Question
              </label>
              <Input
                id="golden-question"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="How many orders shipped last month?"
                required
              />
            </div>
            <div className="space-y-1">
              <label htmlFor="golden-sql" className={labelClass}>
                SQL
              </label>
              <Textarea
                id="golden-sql"
                value={sql}
                onChange={(e) => setSql(e.target.value)}
                placeholder="SELECT ..."
                rows={5}
                className="font-mono text-xs"
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

            <Button
              type="submit"
              size="sm"
              disabled={createMutation.isPending}
            >
              {createMutation.isPending ? <Spinner size="sm" /> : null}
              Add
            </Button>
          </form>
        </CardContent>
      </Card>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Golden records
          </h3>
          {listQuery.isFetching ? <Spinner size="sm" /> : null}
        </div>

        {listQuery.isError ? (
          <p className="text-xs text-red-600">
            {getErrorMessage(listQuery.error, "Failed to load golden records")}
          </p>
        ) : listQuery.isLoading ? (
          <div className="flex items-center gap-2 text-sm text-zinc-500">
            <Spinner size="sm" />
            Loading…
          </div>
        ) : items.length === 0 ? (
          <p className="text-sm text-zinc-500">No golden records yet.</p>
        ) : (
          <ul className="divide-y divide-zinc-200 rounded-lg border border-zinc-200 bg-white">
            {items.map((item) => (
              <li
                key={item.id}
                className="flex items-start justify-between gap-3 px-3 py-2.5"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-zinc-900">
                    {item.question}
                  </p>
                  <pre className="mt-1 max-h-24 overflow-auto rounded bg-zinc-50 p-2 font-mono text-[11px] leading-relaxed text-zinc-600">
                    {item.sql}
                  </pre>
                </div>
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
