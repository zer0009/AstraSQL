import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, Download } from "lucide-react";
import {
  Button,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../ui";
import { exportData } from "../../services/api";
import type { QueryResult } from "../../types/api";
import { cn } from "../../lib/utils";

const PAGE_SIZE = 25;

export interface ResultsTableProps {
  results: QueryResult;
}

type SortDir = "asc" | "desc" | null;

function cellValue(row: Record<string, unknown> | unknown[], column: string, columnIndex: number): unknown {
  if (Array.isArray(row)) return row[columnIndex];
  return row[column];
}

function compareValues(a: unknown, b: unknown): number {
  if (a == null && b == null) return 0;
  if (a == null) return -1;
  if (b == null) return 1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, {
    numeric: true,
    sensitivity: "base",
  });
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function ResultsTable({ results }: ResultsTableProps) {
  const { columns, rows } = results;
  const [page, setPage] = useState(0);
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState(false);

  const sortedRows = useMemo(() => {
    if (!sortCol || !sortDir) return rows;
    const colIndex = columns.indexOf(sortCol);
    const copy = [...rows];
    copy.sort((a, b) => {
      const cmp = compareValues(
        cellValue(a, sortCol, colIndex),
        cellValue(b, sortCol, colIndex),
      );
      return sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [rows, columns, sortCol, sortDir]);

  const pageCount = Math.max(1, Math.ceil(sortedRows.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const pageRows = sortedRows.slice(
    safePage * PAGE_SIZE,
    safePage * PAGE_SIZE + PAGE_SIZE,
  );

  const toggleSort = (column: string) => {
    if (sortCol !== column) {
      setSortCol(column);
      setSortDir("asc");
      setPage(0);
      return;
    }
    if (sortDir === "asc") setSortDir("desc");
    else if (sortDir === "desc") {
      setSortCol(null);
      setSortDir(null);
    } else setSortDir("asc");
    setPage(0);
  };

  const handleExport = async (format: "csv" | "json" | "xlsx") => {
    setExportOpen(false);
    setExporting(true);
    try {
      const blob = await exportData({
        columns,
        rows: sortedRows,
        format,
        filename: `astrasql-results.${format}`,
      });
      downloadBlob(blob, `astrasql-results.${format}`);
    } catch {
      // export failures are non-fatal in UI
    } finally {
      setExporting(false);
    }
  };

  if (columns.length === 0) {
    return (
      <p className="text-xs text-zinc-500">No columns returned.</p>
    );
  }

  return (
    <div className="overflow-hidden rounded-md border border-zinc-200">
      <div className="flex items-center justify-between gap-2 border-b border-zinc-200 bg-zinc-50 px-3 py-1.5">
        <span className="text-xs text-zinc-500">
          {results.row_count} row{results.row_count === 1 ? "" : "s"}
        </span>
        <div className="relative">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={exporting || rows.length === 0}
            onClick={() => setExportOpen((v) => !v)}
          >
            <Download className="h-3 w-3" strokeWidth={1.75} />
            Export
          </Button>
          {exportOpen ? (
            <>
              <button
                type="button"
                className="fixed inset-0 z-10 cursor-default"
                aria-label="Close export menu"
                onClick={() => setExportOpen(false)}
              />
              <div className="absolute right-0 z-20 mt-1 w-28 rounded-md border border-zinc-200 bg-white py-1 shadow-sm">
                {(["csv", "json", "xlsx"] as const).map((fmt) => (
                  <button
                    key={fmt}
                    type="button"
                    className="block w-full px-3 py-1.5 text-left text-xs text-zinc-700 hover:bg-zinc-50"
                    onClick={() => handleExport(fmt)}
                  >
                    {fmt.toUpperCase()}
                  </button>
                ))}
              </div>
            </>
          ) : null}
        </div>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            {columns.map((col) => {
              const active = sortCol === col;
              return (
                <TableHead key={col}>
                  <button
                    type="button"
                    onClick={() => toggleSort(col)}
                    className={cn(
                      "inline-flex items-center gap-1 hover:text-zinc-800",
                      active && "text-zinc-900",
                    )}
                  >
                    {col}
                    {active && sortDir === "asc" ? (
                      <ArrowUp className="h-3 w-3" strokeWidth={1.75} />
                    ) : active && sortDir === "desc" ? (
                      <ArrowDown className="h-3 w-3" strokeWidth={1.75} />
                    ) : (
                      <ArrowUpDown className="h-3 w-3 opacity-40" strokeWidth={1.75} />
                    )}
                  </button>
                </TableHead>
              );
            })}
          </TableRow>
        </TableHeader>
        <TableBody>
          {pageRows.length === 0 ? (
            <TableRow>
              <TableCell
                colSpan={columns.length}
                className="text-center text-zinc-500"
              >
                No rows
              </TableCell>
            </TableRow>
          ) : (
            pageRows.map((row, rowIndex) => (
              <TableRow key={safePage * PAGE_SIZE + rowIndex}>
                {columns.map((col, colIndex) => (
                  <TableCell
                    key={col}
                    className="max-w-[240px] truncate font-mono text-xs"
                    title={formatCell(cellValue(row, col, colIndex))}
                  >
                    {formatCell(cellValue(row, col, colIndex))}
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>

      {pageCount > 1 ? (
        <div className="flex items-center justify-between border-t border-zinc-200 bg-zinc-50 px-3 py-1.5">
          <span className="text-xs text-zinc-500">
            Page {safePage + 1} of {pageCount}
          </span>
          <div className="flex gap-1">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={safePage === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              Prev
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={safePage >= pageCount - 1}
              onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
            >
              Next
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
