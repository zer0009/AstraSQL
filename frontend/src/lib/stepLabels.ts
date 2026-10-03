/** Human-readable labels for agent pipeline step names. */
const STEP_LABELS: Record<string, string> = {
  context_retrieved: "Found relevant tables",
  schema_coarse: "Scanned schema (coarse)",
  schema_full: "Loaded full schema",
  schema_fine: "Refined table selection",
  schema_column_expand: "Expanded column context",
  schema_join_path_expand: "Expanded join paths",
  sql_generated: "Generated SQL",
  merged_non_sql: "Non-SQL reply",
  ambiguity_gate: "Checked answer consistency",
  ambiguity_gate_skipped: "Skipped consistency check",
  ambiguity_gate_failed_open: "Consistency check unavailable",
  query_validated: "Validated SQL",
  query_executed: "Ran query",
  response_formatted: "Formatted answer",
  direct_response: "Direct reply",
  shape_retry: "Retrying suspicious result",
  suspicious_result: "Suspicious empty/null result",
};

export function stepLabel(name: string): string {
  if (STEP_LABELS[name]) return STEP_LABELS[name];
  // schema_* and other snake_case → Title Case words
  return name
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
