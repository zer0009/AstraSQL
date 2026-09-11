import type { QueryResult } from "../../types/api";

export type ChartShape =
  | "singleValue"
  | "timeSeries"
  | "bar"
  | "groupedBar"
  | "none";

export interface ChartShapeInfo {
  shape: ChartShape;
  labelColumn: string | null;
  valueColumns: string[];
}

const DATE_NAME_RE = /date|time|year|month|day/i;
const DATE_VALUE_RE =
  /^\d{4}(-\d{2}(-\d{2}(T[\d:.]+Z?)?)?)?$|^\d{4}\/\d{1,2}\/\d{1,2}$/;
/** Matches `id`, `customer_id`, `order_id`, etc. — never treat as a chart measure. */
const ID_NAME_RE = /(^id$)|(_id$)/i;
const LABEL_NAME_RE = /name|title|label|category/i;

/** Max rows shown on bar/grouped charts before capping. */
export const CHART_ROW_CAP = 15;

function cellValue(
  row: Record<string, unknown> | unknown[],
  column: string,
  columnIndex: number,
): unknown {
  if (Array.isArray(row)) return row[columnIndex];
  return (row as Record<string, unknown>)[column];
}

function isNumericValue(value: unknown): boolean {
  if (value === null || value === undefined || value === "") return false;
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value === "boolean") return false;
  const n = Number(value);
  return !Number.isNaN(n) && Number.isFinite(n);
}

function isNumericColumn(
  rows: QueryResult["rows"],
  column: string,
  columnIndex: number,
): boolean {
  const sample = rows.slice(0, 5);
  if (sample.length === 0) return false;
  let numericCount = 0;
  let nonNullCount = 0;
  for (const row of sample) {
    const v = cellValue(row, column, columnIndex);
    if (v === null || v === undefined || v === "") continue;
    nonNullCount += 1;
    if (isNumericValue(v)) numericCount += 1;
  }
  return nonNullCount > 0 && numericCount === nonNullCount;
}

function looksLikeDate(
  columnName: string,
  rows: QueryResult["rows"],
  columnIndex: number,
): boolean {
  if (DATE_NAME_RE.test(columnName)) return true;
  for (const row of rows.slice(0, 5)) {
    const v = cellValue(row, columnName, columnIndex);
    if (v === null || v === undefined || v === "") continue;
    if (v instanceof Date) return true;
    if (typeof v === "string" && DATE_VALUE_RE.test(v.trim())) return true;
    if (typeof v === "number" && v >= 1900 && v <= 2100) return true;
  }
  return false;
}

function isIdColumn(columnName: string): boolean {
  return ID_NAME_RE.test(columnName);
}

/**
 * Pick the best label (dimension) column by scanning all columns.
 * Priority: named label text → any text → date → ID numeric fallback.
 */
function pickLabelColumn(
  columns: string[],
  rows: QueryResult["rows"],
  numericFlags: boolean[],
): { label: string; isDate: boolean } | null {
  const nonIdText: string[] = [];
  const namedLabels: string[] = [];
  const dateCols: string[] = [];
  const idNumeric: string[] = [];

  columns.forEach((col, i) => {
    const idLike = isIdColumn(col);
    const numeric = numericFlags[i];
    const dateLike = looksLikeDate(col, rows, i);

    if (dateLike && !idLike) {
      dateCols.push(col);
    }
    if (!numeric && !idLike) {
      nonIdText.push(col);
      if (LABEL_NAME_RE.test(col)) namedLabels.push(col);
    }
    if (idLike && numeric) {
      idNumeric.push(col);
    }
  });

  if (namedLabels.length > 0) {
    return { label: namedLabels[0], isDate: false };
  }
  if (nonIdText.length > 0) {
    return { label: nonIdText[0], isDate: false };
  }
  if (dateCols.length > 0) {
    return { label: dateCols[0], isDate: true };
  }
  // Last resort: numeric ID as dimension (Metabase-style)
  if (idNumeric.length > 0) {
    return { label: idNumeric[0], isDate: false };
  }
  return null;
}

/**
 * Infer the best chart shape for a SQL result set.
 * Pure heuristics — no LLM.
 *
 * Example: customer_id, customer_name, total_sales, order_count
 * → label: customer_name, values: total_sales + order_count → groupedBar
 */
export function detectChartShape(results: QueryResult): ChartShapeInfo {
  const { columns, rows } = results;

  if (columns.length === 0 || rows.length === 0) {
    return { shape: "none", labelColumn: null, valueColumns: [] };
  }

  // KPI card: single cell
  if (columns.length === 1 && rows.length === 1) {
    return {
      shape: "singleValue",
      labelColumn: columns[0],
      valueColumns: [columns[0]],
    };
  }

  const numericFlags = columns.map((col, i) => isNumericColumn(rows, col, i));

  const picked = pickLabelColumn(columns, rows, numericFlags);
  if (!picked) {
    return { shape: "none", labelColumn: null, valueColumns: [] };
  }

  const { label: labelColumn, isDate: labelIsDate } = picked;

  // Measures = numeric columns that are not IDs and not the label itself
  const valueColumns = columns.filter((col, i) => {
    if (!numericFlags[i]) return false;
    if (col === labelColumn) return false;
    if (isIdColumn(col)) return false;
    return true;
  });

  if (valueColumns.length === 0) {
    return { shape: "none", labelColumn: null, valueColumns: [] };
  }

  // Time series
  if (labelIsDate) {
    return { shape: "timeSeries", labelColumn, valueColumns };
  }

  // Categorical bar / grouped bar — allow up to a reasonable row count;
  // ResultChart applies a display cap of CHART_ROW_CAP.
  if (rows.length > 100) {
    return { shape: "none", labelColumn: null, valueColumns: [] };
  }

  if (valueColumns.length === 1) {
    return { shape: "bar", labelColumn, valueColumns };
  }
  if (valueColumns.length >= 2 && valueColumns.length <= 4) {
    return { shape: "groupedBar", labelColumn, valueColumns };
  }

  // Too many measures — chart the first measure only as a simple bar
  return {
    shape: "bar",
    labelColumn,
    valueColumns: [valueColumns[0]],
  };
}
