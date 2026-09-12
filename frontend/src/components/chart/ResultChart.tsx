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

/** Compact axis ticks: 1.2k, 3.4M, etc. */
function formatCompactNumber(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return String(value);
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000) {
    return `${(n / 1_000_000_000).toFixed(abs >= 10_000_000_000 ? 0 : 1)}B`;
  }
  if (abs >= 1_000_000) {
    return `${(n / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}M`;
  }
  if (abs >= 10_000) {
    return `${(n / 1_000).toFixed(abs >= 100_000 ? 0 : 1)}k`;
  }
  if (abs >= 1_000) {
    return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  }
  if (Number.isInteger(n)) return String(n);
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/** Full precision for tooltips / KPI card. */
function formatFullNumber(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "—";
    if (Number.isInteger(value)) {
      return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
    }
    return value.toLocaleString(undefined, {
      maximumFractionDigits: 4,
      minimumFractionDigits: 0,
    });
  }
  const n = Number(value);
  if (!Number.isNaN(n) && Number.isFinite(n)) return formatFullNumber(n);
  return String(value);
}

function humanizeColumn(name: string): string {
  return name
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function truncateLabel(label: string, max = 18): string {
  if (label.length <= max) return label;
  return `${label.slice(0, max - 1)}…`;
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
        const av =
          typeof a[primary] === "number" ? (a[primary] as number) : -Infinity;
        const bv =
          typeof b[primary] === "number" ? (b[primary] as number) : -Infinity;
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

/** Prefer horizontal bars when category labels are long. */
function shouldUseHorizontalBars(
  data: Record<string, string | number | null>[],
  labelKey: string,
): boolean {
  if (data.length === 0) return false;
  const lengths = data.map((d) => String(d[labelKey] ?? "").length);
  const avg = lengths.reduce((a, b) => a + b, 0) / lengths.length;
  const max = Math.max(...lengths);
  return avg >= 12 || max >= 20;
}

const tooltipStyle = {
  fontSize: 12,
  borderRadius: 6,
  border: "1px solid #e4e4e7",
  background: "#fff",
};

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name?: string; value?: unknown; color?: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 shadow-sm">
      {label != null && label !== "" ? (
        <p className="mb-1 text-xs font-medium text-zinc-700">{String(label)}</p>
      ) : null}
      <ul className="space-y-0.5">
        {payload.map((entry) => (
          <li
            key={String(entry.name)}
            className="flex items-center gap-2 text-xs text-zinc-600"
          >
            <span
              className="inline-block h-2 w-2 rounded-sm"
              style={{ background: entry.color }}
            />
            <span>{humanizeColumn(String(entry.name ?? ""))}</span>
            <span className="ml-auto font-medium tabular-nums text-zinc-900">
              {formatFullNumber(entry.value)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
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
          {humanizeColumn(col)}
        </span>
        <span className="text-3xl font-semibold tabular-nums text-zinc-900">
          {formatFullNumber(raw)}
        </span>
      </div>
    );
  }

  const rawData = buildChartData(results, info);
  const { data, capped, total } = prepareDisplayData(rawData, info);
  const labelKey = info.labelColumn!;
  const horizontal =
    (info.shape === "bar" || info.shape === "groupedBar") &&
    shouldUseHorizontalBars(data, labelKey);

  const chartHeight = horizontal
    ? Math.max(240, Math.min(420, 36 * data.length + 48))
    : 240;

  const valueAxisProps = {
    tick: { fontSize: 11, fill: "#71717a" },
    tickLine: false as const,
    tickFormatter: formatCompactNumber,
    width: 52,
  };

  const categoryAxisProps = {
    dataKey: labelKey,
    tick: { fontSize: 11, fill: "#71717a" },
    tickLine: false as const,
    tickFormatter: (v: string) => truncateLabel(String(v)),
    interval: 0 as const,
  };

  return (
    <div className="space-y-1">
      <div
        className="rounded-md border border-zinc-200 bg-white p-2"
        style={{ height: chartHeight }}
      >
        <ResponsiveContainer width="100%" height="100%">
          {info.shape === "timeSeries" ? (
            <LineChart
              data={data}
              margin={{ top: 8, right: 12, left: 4, bottom: 4 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" />
              <XAxis
                {...categoryAxisProps}
                label={{
                  value: humanizeColumn(labelKey),
                  position: "insideBottom",
                  offset: -2,
                  style: { fontSize: 10, fill: "#a1a1aa" },
                }}
              />
              <YAxis
                {...valueAxisProps}
                label={{
                  value:
                    info.valueColumns.length === 1
                      ? humanizeColumn(info.valueColumns[0])
                      : "Value",
                  angle: -90,
                  position: "insideLeft",
                  style: { fontSize: 10, fill: "#a1a1aa" },
                }}
              />
              <Tooltip content={<ChartTooltip />} contentStyle={tooltipStyle} />
              {info.valueColumns.length > 1 ? (
                <Legend
                  wrapperStyle={{ fontSize: 11 }}
                  formatter={(value) => humanizeColumn(String(value))}
                />
              ) : null}
              {info.valueColumns.map((col, i) => (
                <Line
                  key={col}
                  type="monotone"
                  dataKey={col}
                  name={col}
                  stroke={PALETTE[i % PALETTE.length]}
                  strokeWidth={2}
                  dot={data.length <= 20}
                  activeDot={{ r: 4 }}
                />
              ))}
            </LineChart>
          ) : horizontal ? (
            <BarChart
              layout="vertical"
              data={data}
              margin={{ top: 8, right: 16, left: 8, bottom: 4 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" horizontal={false} />
              <XAxis
                type="number"
                {...valueAxisProps}
                width={undefined}
                label={{
                  value:
                    info.valueColumns.length === 1
                      ? humanizeColumn(info.valueColumns[0])
                      : "Value",
                  position: "insideBottom",
                  offset: -2,
                  style: { fontSize: 10, fill: "#a1a1aa" },
                }}
              />
              <YAxis
                type="category"
                {...categoryAxisProps}
                width={100}
                label={{
                  value: humanizeColumn(labelKey),
                  angle: -90,
                  position: "insideLeft",
                  style: { fontSize: 10, fill: "#a1a1aa" },
                }}
              />
              <Tooltip content={<ChartTooltip />} contentStyle={tooltipStyle} />
              {info.valueColumns.length > 1 ? (
                <Legend
                  wrapperStyle={{ fontSize: 11 }}
                  formatter={(value) => humanizeColumn(String(value))}
                />
              ) : null}
              {info.valueColumns.map((col, i) => (
                <Bar
                  key={col}
                  dataKey={col}
                  name={col}
                  fill={PALETTE[i % PALETTE.length]}
                  radius={[0, 3, 3, 0]}
                />
              ))}
            </BarChart>
          ) : (
            <BarChart
              data={data}
              margin={{ top: 8, right: 12, left: 4, bottom: 4 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" />
              <XAxis
                {...categoryAxisProps}
                label={{
                  value: humanizeColumn(labelKey),
                  position: "insideBottom",
                  offset: -2,
                  style: { fontSize: 10, fill: "#a1a1aa" },
                }}
              />
              <YAxis
                {...valueAxisProps}
                label={{
                  value:
                    info.valueColumns.length === 1
                      ? humanizeColumn(info.valueColumns[0])
                      : "Value",
                  angle: -90,
                  position: "insideLeft",
                  style: { fontSize: 10, fill: "#a1a1aa" },
                }}
              />
              <Tooltip content={<ChartTooltip />} contentStyle={tooltipStyle} />
              {info.valueColumns.length > 1 ? (
                <Legend
                  wrapperStyle={{ fontSize: 11 }}
                  formatter={(value) => humanizeColumn(String(value))}
                />
              ) : null}
              {info.valueColumns.map((col, i) => (
                <Bar
                  key={col}
                  dataKey={col}
                  name={col}
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
