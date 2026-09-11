import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { QueryResult } from "../../types/api";
import {
  CHART_ROW_CAP,
  type ChartShapeInfo,
  detectChartShape,
} from "./detectChartShape";

const PALETTE = [
  "#3b82f6", // blue-500
  "#10b981", // emerald-500
  "#f59e0b", // amber-500
  "#8b5cf6", // violet-500
  "#ef4444", // red-500
];

function cellValue(
  row: Record<string, unknown> | unknown[],
  column: string,
  columnIndex: number,
): unknown {
  if (Array.isArray(row)) return row[columnIndex];
  return (row as Record<string, unknown>)[column];
}

function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const n = Number(value);
  return Number.isNaN(n) ? null : n;
}

function formatSingleValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  return String(value);
}

function buildChartData(
  results: QueryResult,
  info: ChartShapeInfo,
): Record<string, string | number | null>[] {
  if (!info.labelColumn) return [];
  const labelIdx = results.columns.indexOf(info.labelColumn);
  const valueIndexes = info.valueColumns.map((c) => results.columns.indexOf(c));

  return results.rows.map((row) => {
    const point: Record<string, string | number | null> = {
      [info.labelColumn!]: String(
        cellValue(row, info.labelColumn!, labelIdx) ?? "",
      ),
    };
    info.valueColumns.forEach((col, i) => {
      point[col] = toNumber(cellValue(row, col, valueIndexes[i]));
    });
    return point;
  });
}

/**
 * Sort categorical charts by primary measure desc and cap at CHART_ROW_CAP.
 * Time series keeps chronological order (no sort) but still caps.
 */
function prepareDisplayData(
  data: Record<string, string | number | null>[],
  info: ChartShapeInfo,
): { data: Record<string, string | number | null>[]; capped: boolean; total: number } {
  const total = data.length;
  let working = [...data];

  if (info.shape === "bar" || info.shape === "groupedBar") {
    const primary = info.valueColumns[0];
    if (primary) {
      working.sort((a, b) => {
        const av = typeof a[primary] === "number" ? (a[primary] as number) : -Infinity;
        const bv = typeof b[primary] === "number" ? (b[primary] as number) : -Infinity;
        return bv - av;
      });
    }
  }

  const capped = working.length > CHART_ROW_CAP;
  if (capped) {
    working = working.slice(0, CHART_ROW_CAP);
  }

  return { data: working, capped, total };
}

export interface ResultChartProps {
  results: QueryResult;
  /** Pre-computed shape; if omitted, detected internally. */
  shapeInfo?: ChartShapeInfo;
}

export function ResultChart({ results, shapeInfo }: ResultChartProps) {
  const info = shapeInfo ?? detectChartShape(results);

  if (info.shape === "none") return null;

  if (info.shape === "singleValue") {
    const col = info.valueColumns[0] ?? results.columns[0];
    const colIdx = results.columns.indexOf(col);
    const raw = cellValue(results.rows[0], col, colIdx);
    return (
      <div className="flex flex-col items-center justify-center gap-1 rounded-md border border-zinc-200 bg-zinc-50 px-4 py-8">
        <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          {col}
        </span>
        <span className="text-3xl font-semibold tabular-nums text-zinc-900">
          {formatSingleValue(raw)}
        </span>
      </div>
    );
  }

  const rawData = buildChartData(results, info);
  const { data, capped, total } = prepareDisplayData(rawData, info);
  const labelKey = info.labelColumn!;

  return (
    <div className="space-y-1">
      <div
        className="rounded-md border border-zinc-200 bg-white p-2"
        style={{ height: 240 }}
      >
        <ResponsiveContainer width="100%" height="100%">
          {info.shape === "timeSeries" ? (
            <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" />
              <XAxis
                dataKey={labelKey}
                tick={{ fontSize: 11, fill: "#71717a" }}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 11, fill: "#71717a" }}
                tickLine={false}
                width={48}
              />
              <Tooltip
                contentStyle={{
                  fontSize: 12,
                  borderRadius: 6,
                  border: "1px solid #e4e4e7",
                }}
              />
              {info.valueColumns.length > 1 ? (
                <Legend wrapperStyle={{ fontSize: 11 }} />
              ) : null}
              {info.valueColumns.map((col, i) => (
                <Line
                  key={col}
                  type="monotone"
                  dataKey={col}
                  stroke={PALETTE[i % PALETTE.length]}
                  strokeWidth={2}
                  dot={data.length <= 20}
                  activeDot={{ r: 4 }}
                />
              ))}
            </LineChart>
          ) : (
            <BarChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" />
              <XAxis
                dataKey={labelKey}
                tick={{ fontSize: 11, fill: "#71717a" }}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 11, fill: "#71717a" }}
                tickLine={false}
                width={48}
              />
              <Tooltip
                contentStyle={{
                  fontSize: 12,
                  borderRadius: 6,
                  border: "1px solid #e4e4e7",
                }}
              />
              {info.valueColumns.length > 1 ? (
                <Legend wrapperStyle={{ fontSize: 11 }} />
              ) : null}
              {info.valueColumns.map((col, i) => (
                <Bar
                  key={col}
                  dataKey={col}
                  fill={PALETTE[i % PALETTE.length]}
                  radius={[3, 3, 0, 0]}
                />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
      {capped ? (
        <p className="px-1 text-[11px] text-zinc-500">
          Showing top {CHART_ROW_CAP} of {total} — see Table tab for all rows
        </p>
      ) : null}
    </div>
  );
}
