import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { ChevronLeft, ChevronRight, Copy, Download, RotateCcw } from "lucide-react";
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
} from "../components/ui";
import { listConnections, listHistory } from "../services/api";
import type { QueryHistoryItem } from "../types/api";
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

export default function HistoryPage() {
  const navigate = useNavigate();
  const [connectionId, setConnectionId] = useState<string>("");
  const [ratingFilter, setRatingFilter] = useState<RatingFilter>("all");
  const [offset, setOffset] = useState(0);

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

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="History"
        description="Past queries and feedback"
      />
      <div className="flex-1 space-y-4 overflow-auto p-5">
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
                    <TableHead className="w-[160px]">Actions</TableHead>
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
          if the chat input is empty.
        </p>
      </div>
    </div>
  );
}
