import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import {
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  GraduationCap,
  RotateCcw,
} from "lucide-react";
import { PageHeader } from "../components/PageHeader";
import {
  Badge,
  Button,
  Select,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Textarea,
} from "../components/ui";
import { getHistoryStats, listConnections, listHistory, submitFeedback } from "../services/api";
import type { HistoryStats, QueryHistoryItem } from "../types/api";
import { cn } from "../lib/utils";

const PAGE_SIZE = 25;

type RatingFilter = "all" | "positive" | "negative";
type ConfidenceLevel = "HIGH" | "MEDIUM" | "LOW" | null;

function truncate(text: string, max: number): string {
  const t = text.replace(/\s+/g, " ").trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max)}…`;
}

function confidenceLevel(value: number | null): ConfidenceLevel {
  if (value == null || Number.isNaN(value)) return null;
  if (value >= 0.85) return "HIGH";
  if (value >= 0.4) return "MEDIUM";
  return "LOW";
}

function ConfidenceBadge({ value }: { value: number | null }) {
  const level = confidenceLevel(value);
  if (!level) {
    return <span className="text-xs text-zinc-400">—</span>;
  }

  return (
    <Badge
      className={cn(
        level === "HIGH" && "border-zinc-300 bg-zinc-100 text-zinc-800",
        level === "MEDIUM" && "border-amber-200 bg-amber-50 text-amber-800",
        level === "LOW" && "border-red-200 bg-red-50 text-red-700",
      )}
    >
      {level}
    </Badge>
  );
}

function RatingCell({ rating }: { rating: number | null }) {
  if (rating === 1) {
    return <Badge variant="success">Positive</Badge>;
  }
  if (rating === -1) {
    return (
      <Badge className="border-red-200 bg-red-50 text-red-700">Negative</Badge>
    );
  }
  return <span className="text-xs text-zinc-400">—</span>;
}

function formatDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function downloadHistoryJson(item: QueryHistoryItem) {
  const blob = new Blob([JSON.stringify(item, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `astrasql-history-${item.id}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

function pct(part: number, total: number): string {
  if (total <= 0) return "0%";
  return `${Math.round((100 * part) / total)}%`;
}

function StatsStrip({
  stats,
  loading,
}: {
  stats?: HistoryStats;
  loading: boolean;
}) {
  if (loading && !stats) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-zinc-200 bg-white px-4 py-3 text-sm text-zinc-500">
        <Spinner size="sm" />
        Loading stats…
      </div>
    );
  }
  if (!stats) return null;

  const cards = [
    { label: "Total queries", value: String(stats.total) },
    {
      label: "HIGH confidence",
      value: `${stats.high_confidence} (${pct(stats.high_confidence, stats.total)})`,
    },
    {
      label: "Errors / failed",
      value: `${stats.error_count} (${pct(stats.error_count, stats.total)})`,
    },
    {
      label: "Negative rated",
      value: `${stats.negative_rated} (${pct(stats.negative_rated, stats.total)})`,
    },
  ];

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map((card) => (
        <div
          key={card.label}
          className="rounded-lg border border-zinc-200 bg-white px-4 py-3"
        >
          <p className="text-[11px] font-medium uppercase tracking-wide text-zinc-400">
            {card.label}
          </p>
          <p className="mt-1 text-lg font-semibold tabular-nums text-zinc-900">
            {card.value}
          </p>
        </div>
      ))}
    </div>
  );
}

export default function HistoryPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [connectionId, setConnectionId] = useState<string>("");
  const [ratingFilter, setRatingFilter] = useState<RatingFilter>("all");
  const [offset, setOffset] = useState(0);
  const [teachId, setTeachId] = useState<string | null>(null);
  const [teachSql, setTeachSql] = useState("");
  const [teachMessage, setTeachMessage] = useState<string | null>(null);

  const connectionsQuery = useQuery({
    queryKey: ["connections"],
    queryFn: listConnections,
  });

  const historyParams = useMemo(() => {
    const params: {
      connection_id?: string;
      rating?: number;
      limit: number;
      offset: number;
    } = {
      limit: PAGE_SIZE,
      offset,
    };
    if (connectionId) params.connection_id = connectionId;
    if (ratingFilter === "positive") params.rating = 1;
    if (ratingFilter === "negative") params.rating = -1;
    return params;
  }, [connectionId, ratingFilter, offset]);

  const historyQuery = useQuery({
    queryKey: ["history", historyParams],
    queryFn: () => listHistory(historyParams),
  });

  const statsQuery = useQuery({
    queryKey: ["history-stats", connectionId || "all"],
    queryFn: () =>
      getHistoryStats(connectionId ? { connection_id: connectionId } : {}),
  });

  const teachMutation = useMutation({
    mutationFn: ({
      historyId,
      corrected_sql,
    }: {
      historyId: string;
      corrected_sql: string;
    }) =>
      submitFeedback(historyId, {
        rating: -1,
        corrected_sql,
      }),
    onSuccess: () => {
      setTeachMessage("Saved as golden record");
      setTeachId(null);
      setTeachSql("");
      void queryClient.invalidateQueries({ queryKey: ["history"] });
      void queryClient.invalidateQueries({ queryKey: ["history-stats"] });
      window.setTimeout(() => setTeachMessage(null), 2500);
    },
  });

  const items = historyQuery.data ?? [];
  const hasNext = items.length >= PAGE_SIZE;
  const hasPrev = offset > 0;
  const page = Math.floor(offset / PAGE_SIZE) + 1;

  const connectionName = (id: string) =>
    connectionsQuery.data?.find((c) => c.id === id)?.name ?? id.slice(0, 8);

  async function handleRerun(item: QueryHistoryItem) {
    try {
      await navigator.clipboard.writeText(item.question);
    } catch {
      // clipboard may be unavailable; still navigate with state
    }
    navigate("/", {
      state: {
        question: item.question,
        connection_id: item.connection_id,
        history_id: item.id,
      },
    });
  }

  function resetPage() {
    setOffset(0);
  }

  function openTeach(item: QueryHistoryItem) {
    setTeachId(item.id);
    setTeachSql(item.sql);
    setTeachMessage(null);
  }

  function submitTeach() {
    if (!teachId) return;
    const trimmed = teachSql.trim();
    if (!trimmed) return;
    teachMutation.mutate({ historyId: teachId, corrected_sql: trimmed });
  }

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="History"
        description="Past queries and feedback"
      />
      <div className="flex-1 space-y-4 overflow-auto p-5">
        <StatsStrip stats={statsQuery.data} loading={statsQuery.isLoading} />

        <div className="flex flex-wrap items-end gap-3">
          <label className="flex min-w-[180px] flex-col gap-1">
            <span className="text-xs font-medium text-zinc-500">Connection</span>
            <Select
              value={connectionId}
              onChange={(e) => {
                setConnectionId(e.target.value);
                resetPage();
              }}
            >
              <option value="">All</option>
              {(connectionsQuery.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </label>

          <label className="flex min-w-[140px] flex-col gap-1">
            <span className="text-xs font-medium text-zinc-500">Rating</span>
            <Select
              value={ratingFilter}
              onChange={(e) => {
                setRatingFilter(e.target.value as RatingFilter);
                resetPage();
              }}
            >
              <option value="all">All</option>
              <option value="positive">Positive</option>
              <option value="negative">Negative</option>
            </Select>
          </label>

          <div className="ml-auto flex items-center gap-2 text-xs text-zinc-500">
            {historyQuery.isFetching ? <Spinner size="sm" /> : null}
            <span>Page {page}</span>
          </div>
        </div>

        {teachMessage ? (
          <p className="text-xs text-emerald-700" role="status">
            {teachMessage}
          </p>
        ) : null}

        {historyQuery.isLoading ? (
          <div className="flex items-center justify-center gap-2 py-16 text-sm text-zinc-500">
            <Spinner />
            Loading history…
          </div>
        ) : historyQuery.isError ? (
          <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            Failed to load history. Check that the API is running.
          </p>
        ) : items.length === 0 ? (
          <p className="text-sm text-zinc-500">No query history yet.</p>
        ) : (
          <>
            <div className="rounded-lg border border-zinc-200 bg-white">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[140px]">Created</TableHead>
                    <TableHead>Question</TableHead>
                    <TableHead>SQL</TableHead>
                    <TableHead className="w-[90px]">Confidence</TableHead>
                    <TableHead className="w-[90px]">Rating</TableHead>
                    <TableHead className="w-[200px]">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell className="whitespace-nowrap text-xs text-zinc-600">
                        <div>{formatDate(item.created_at)}</div>
                        <div className="mt-0.5 text-[11px] text-zinc-400">
                          {connectionName(item.connection_id)}
                        </div>
                      </TableCell>
                      <TableCell
                        className="max-w-[220px] text-sm"
                        title={item.question}
                      >
                        {truncate(item.question, 80)}
                      </TableCell>
                      <TableCell
                        className="max-w-[260px] font-mono text-xs text-zinc-600"
                        title={item.sql}
                      >
                        {truncate(item.sql, 72)}
                      </TableCell>
                      <TableCell>
                        <ConfidenceBadge value={item.confidence} />
                      </TableCell>
                      <TableCell>
                        <RatingCell rating={item.user_rating} />
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          <Button
                            variant="outline"
                            size="sm"
                            title="Copy question and open Chat"
                            onClick={() => void handleRerun(item)}
                          >
                            <RotateCcw className="h-3.5 w-3.5" />
                            Re-run
                          </Button>
                          {item.user_rating === -1 ? (
                            <Button
                              variant="secondary"
                              size="sm"
                              title="Promote a corrected SQL as a golden record"
                              onClick={() => openTeach(item)}
                            >
                              <GraduationCap className="h-3.5 w-3.5" />
                              Teach
                            </Button>
                          ) : null}
                          <Button
                            variant="ghost"
                            size="sm"
                            title="Export history row as JSON"
                            onClick={() => downloadHistoryJson(item)}
                          >
                            <Download className="h-3.5 w-3.5" />
                            Export
                          </Button>
                        </div>
                        {teachId === item.id ? (
                          <div className="mt-2 space-y-2 rounded-md border border-zinc-200 bg-zinc-50 p-2.5">
                            <p className="text-xs text-zinc-600">
                              Edit the correct SQL. Saving stores it as a golden
                              record for this question.
                            </p>
                            <Textarea
                              value={teachSql}
                              onChange={(e) => setTeachSql(e.target.value)}
                              className="max-h-40 min-h-[5rem] resize-y font-mono text-xs"
                              spellCheck={false}
                              aria-label="Corrected SQL to teach"
                            />
                            <div className="flex justify-end gap-2">
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={teachMutation.isPending}
                                onClick={() => {
                                  setTeachId(null);
                                  setTeachSql("");
                                }}
                              >
                                Cancel
                              </Button>
                              <Button
                                variant="secondary"
                                size="sm"
                                disabled={
                                  teachMutation.isPending || !teachSql.trim()
                                }
                                onClick={submitTeach}
                              >
                                {teachMutation.isPending ? (
                                  <Spinner size="sm" />
                                ) : null}
                                Save golden
                              </Button>
                            </div>
                            {teachMutation.isError ? (
                              <p className="text-xs text-red-600">
                                Could not save correction
                              </p>
                            ) : null}
                          </div>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            <div className="flex items-center justify-between">
              <p className="text-xs text-zinc-500">
                Showing {items.length} row{items.length === 1 ? "" : "s"}
                {offset > 0 ? ` (offset ${offset})` : ""}
              </p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!hasPrev || historyQuery.isFetching}
                  onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!hasNext || historyQuery.isFetching}
                  onClick={() => setOffset((o) => o + PAGE_SIZE)}
                >
                  Next
                  <ChevronRight className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          </>
        )}

        <p className="text-xs text-zinc-400">
          Tip: Re-run copies the question to the clipboard and opens{" "}
          <Link to="/" className="underline hover:text-zinc-600">
            Chat
          </Link>
          . Use{" "}
          <span className="inline-flex items-center gap-0.5">
            <Copy className="inline h-3 w-3" /> paste
          </span>{" "}
          if the chat input is empty. Teach promotes corrected SQL into golden
          records.
        </p>
      </div>
    </div>
  );
}
