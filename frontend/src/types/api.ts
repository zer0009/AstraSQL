export interface Connection {
  id: string;
  name: string;
  db_type: string;
  host: string;
  port: number;
  database: string;
  username: string;
  ssl_enabled: boolean;
  password_set: boolean;
  last_scanned_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConnectionCreate {
  name: string;
  db_type: string;
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
  ssl_enabled: boolean;
}

export interface ConnectionUpdate {
  name?: string;
  db_type?: string;
  host?: string;
  port?: number;
  database?: string;
  username?: string;
  password?: string;
  ssl_enabled?: boolean;
}

export interface ConnectionTestResult {
  ok: boolean;
  message: string;
}

export interface ConnectionScanResult {
  job_id: string;
  connection_id: string;
  status: string;
  message: string;
}

export interface ScanJobStatus {
  job_id: string;
  connection_id: string;
  connection_name: string;
  status: "pending" | "running" | "completed" | "failed" | string;
  phase: string;
  message: string;
  current_table: string | null;
  tables_total: number;
  tables_done: number;
  tables_cached: string[];
  percent: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  last_scanned_at: string | null;
}

export interface Enrichment {
  id: string;
  connection_id: string;
  table_name: string;
  column_name: string | null;
  description: string | null;
  alias: string | null;
  example_values: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface EnrichmentCreate {
  connection_id: string;
  table_name: string;
  column_name?: string | null;
  description?: string | null;
  alias?: string | null;
  example_values?: unknown;
}

export interface EnrichmentUpdate {
  table_name?: string;
  column_name?: string | null;
  description?: string | null;
  alias?: string | null;
  example_values?: unknown;
}

export interface GoldenRecord {
  id: string;
  connection_id: string;
  question: string;
  sql: string;
  created_at: string;
  updated_at?: string;
}

export interface GoldenRecordCreate {
  connection_id: string;
  question: string;
  sql: string;
}

export interface BusinessRule {
  id: string;
  connection_id: string;
  content: string;
  created_at: string;
  updated_at?: string;
}

export interface BusinessRuleCreate {
  connection_id: string;
  content: string;
}

export interface BusinessRuleUpdate {
  content: string;
}

export type AmbiguityStatus =
  | "clear"
  | "assumed"
  | "ambiguous"
  | "unanswerable"
  | "not_a_data_question"
  | "failed_open";

export interface DecisionPoint {
  key: string;
  question?: string;
  options?: string[];
}

export interface Ambiguity {
  status?: AmbiguityStatus;
  should_clarify?: boolean;
  reason?: string;
  options?: string[];
  decision_why?: string;
  assumption?: string;
  decision_points?: DecisionPoint[];
  needs_execution_gate?: boolean;
  gate?: Record<string, unknown>;
  clusters?: unknown[];
}

export interface UsageStageSummary {
  stage: string;
  latency_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  cost_usd?: number;
}

export interface UsageSummary {
  total_prompt_tokens?: number;
  total_completion_tokens?: number;
  total_cost_usd?: number;
  total_latency_ms?: number;
  stages?: UsageStageSummary[];
  [key: string]: unknown;
}

export interface QueryHistoryItem {
  id: string;
  connection_id: string;
  session_id?: string | null;
  turn_index?: number | null;
  question: string;
  sql: string;
  result_row_count: number | null;
  confidence: number | null;
  trust_level?: string | null;
  user_rating: number | null;
  explanation: string | null;
  follow_ups: string | null;
  ambiguity_json?: string | null;
  created_at: string;
}

export interface ChatSession {
  id: string;
  connection_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatSessionDetail extends ChatSession {
  queries: QueryHistoryItem[];
}

export interface FeedbackRequest {
  rating: 1 | -1;
  corrected_sql?: string;
  new_rule?: string;
}

export interface FeedbackResult {
  id: string;
  user_rating: number;
  golden_record_id: string | null;
  rule_id?: string | null;
}

export interface ContextPackDocument {
  version: number;
  enrichments: Record<string, unknown>[];
  rules: Record<string, unknown>[];
  goldens: Record<string, unknown>[];
}

export interface ContextPackImportResult {
  enrichments: number;
  rules: number;
  goldens: number;
}

export interface HistoryStats {
  total: number;
  high_confidence: number;
  medium_confidence: number;
  low_confidence: number;
  unknown_confidence: number;
  error_count: number;
  negative_rated: number;
  positive_rated: number;
  unrated: number;
}

export interface AgentStep {
  name: string;
  detail: string;
  /** Tables linked during context retrieval (present on context_retrieved). */
  tables?: string[];
  status?: string;
  cluster_count?: number;
  generation?: Record<string, unknown>;
}

export interface QueryResult {
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  /** True when the SSE payload capped rows (backend sends at most 100). */
  truncated?: boolean;
}

export interface ConversationHistoryTurn {
  question: string;
  sql?: string;
  answer?: string;
  trust_level?: string;
}

export interface QueryRequest {
  connection_id: string;
  question: string;
  conversation_history?: ConversationHistoryTurn[];
  session_id?: string;
  /** Optional schema/business hint injected into retrieval (BIRD-style evidence). */
  evidence?: string;
}

export interface ExecuteSqlRequest {
  connection_id: string;
  sql: string;
}

export interface ExecuteSqlResult {
  sql: string;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
}

export interface ExportRequest {
  columns: string[];
  rows: Record<string, unknown>[] | unknown[][];
  format: "csv" | "xlsx" | "json";
  filename?: string;
}

export interface AuthUser {
  id: string;
  username: string;
  is_admin: boolean;
  must_change_password: boolean;
}

export interface AuthStatus {
  setup_complete: boolean;
}

export interface PublicSettings {
  llm_provider: string;
  openai_model: string;
  max_result_rows: number;
  database_types: string[];
  app_name?: string;
  execution_evidence_gate?: boolean;
  merge_interpret_generate?: boolean;
  ambiguity_policy?: string;
  relationship_discovery_enabled?: boolean;
  relationship_auto_approve?: boolean;
  learning_loop_enabled?: boolean;
  sse_row_preview_limit?: number;
}

export type StreamEventName =
  | "start"
  | "node"
  | "step"
  | "done"
  | "result"
  | "error"
  | string;

export interface StreamQueryEvent {
  event: StreamEventName;
  data: unknown;
}

export interface SemanticRelationship {
  from_table: string;
  from_col: string;
  to_table: string;
  to_col: string;
  status: "approved" | "proposed" | "rejected" | string;
  score?: number;
  evidence?: string;
  [key: string]: unknown;
}

export interface SemanticLayerOut {
  connection_id: string;
  relationships: SemanticRelationship[];
  conventions?: string[];
  reviewed_queries?: unknown[];
  repair_memory?: unknown[];
  join_paths?: string[];
  raw?: Record<string, unknown>;
}

export interface DictionaryImportResult {
  enrichments_created: number;
  enrichments_updated: number;
  rows_parsed: number;
  message?: string;
}
