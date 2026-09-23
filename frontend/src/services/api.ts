import axios from "axios";
import type {
  BusinessRule,
  BusinessRuleCreate,
  BusinessRuleUpdate,
  ChatSession,
  ChatSessionDetail,
  Connection,
  ConnectionCreate,
  ConnectionScanResult,
  ConnectionTestResult,
  ConnectionUpdate,
  Enrichment,
  EnrichmentCreate,
  EnrichmentUpdate,
  ExecuteSqlRequest,
  ExecuteSqlResult,
  ExportRequest,
  FeedbackRequest,
  FeedbackResult,
  GoldenRecord,
  GoldenRecordCreate,
  HistoryStats,
  AuthStatus,
  AuthUser,
  PublicSettings,
  QueryHistoryItem,
  QueryRequest,
  ScanJobStatus,
  StreamQueryEvent,
} from "../types/api";

const api = axios.create({
  baseURL: "",
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
});

type AuthRedirectHandler = (to: "/login" | "/change-password") => void;
let authRedirectHandler: AuthRedirectHandler | null = null;

export function setAuthRedirectHandler(handler: AuthRedirectHandler | null): void {
  authRedirectHandler = handler;
}

function redirectAuth(to: "/login" | "/change-password"): void {
  if (authRedirectHandler) {
    authRedirectHandler(to);
    return;
  }
  if (window.location.pathname !== to) {
    window.location.assign(to);
  }
}

function isPublicAuthUrl(url: string | undefined): boolean {
  if (!url) return false;
  return url.includes("/api/auth/login") || url.includes("/api/auth/status");
}

api.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    const err = error as {
      response?: { status?: number; data?: { code?: string } };
      config?: { url?: string };
    };
    const url = err.config?.url;
    const status = err.response?.status;
    const code = err.response?.data?.code;
    if (!isPublicAuthUrl(url)) {
      if (status === 401) {
        redirectAuth("/login");
      } else if (status === 403 && code === "PASSWORD_CHANGE_REQUIRED") {
        redirectAuth("/change-password");
      }
    }
    return Promise.reject(error);
  },
);

function redirectFromFetchStatus(status: number, body: unknown): void {
  const code =
    body && typeof body === "object" && "code" in body
      ? (body as { code?: string }).code
      : undefined;
  if (status === 401) {
    redirectAuth("/login");
  } else if (status === 403 && code === "PASSWORD_CHANGE_REQUIRED") {
    redirectAuth("/change-password");
  }
}

// --- Auth ---

export async function getAuthStatus(): Promise<AuthStatus> {
  const { data } = await api.get<AuthStatus>("/api/auth/status");
  return data;
}

export async function getMe(): Promise<AuthUser> {
  const { data } = await api.get<AuthUser>("/api/auth/me");
  return data;
}

export async function login(body: {
  username: string;
  password: string;
}): Promise<AuthUser> {
  const { data } = await api.post<AuthUser>("/api/auth/login", body);
  return data;
}

export async function logout(): Promise<void> {
  await api.post("/api/auth/logout");
}

export async function changePassword(body: {
  current_password: string;
  new_password: string;
}): Promise<AuthUser> {
  const { data } = await api.post<AuthUser>("/api/auth/change-password", body);
  return data;
}

// --- Connections ---

export async function listConnections(): Promise<Connection[]> {
  const { data } = await api.get<Connection[]>("/api/connections");
  return data;
}

export async function getConnection(id: string): Promise<Connection> {
  const { data } = await api.get<Connection>(`/api/connections/${id}`);
  return data;
}

export async function createConnection(
  body: ConnectionCreate,
): Promise<Connection> {
  const { data } = await api.post<Connection>("/api/connections", body);
  return data;
}

export async function updateConnection(
  id: string,
  body: ConnectionUpdate,
): Promise<Connection> {
  const { data } = await api.put<Connection>(`/api/connections/${id}`, body);
  return data;
}

export async function deleteConnection(id: string): Promise<void> {
  await api.delete(`/api/connections/${id}`);
}

export async function testConnection(
  id: string,
): Promise<ConnectionTestResult> {
  const { data } = await api.post<ConnectionTestResult>(
    `/api/connections/${id}/test`,
  );
  return data;
}

export async function scanConnection(
  id: string,
): Promise<ConnectionScanResult> {
  const { data } = await api.post<ConnectionScanResult>(
    `/api/connections/${id}/scan`,
  );
  return data;
}

export async function getConnectionScanStatus(
  id: string,
): Promise<ScanJobStatus> {
  const { data } = await api.get<ScanJobStatus>(
    `/api/connections/${id}/scan`,
  );
  return data;
}

export async function listScanJobs(
  activeOnly = false,
): Promise<ScanJobStatus[]> {
  const { data } = await api.get<ScanJobStatus[]>("/api/connections/scans", {
    params: { active_only: activeOnly },
  });
  return data;
}

// --- Context: enrichments ---

export async function listEnrichments(
  connectionId: string,
): Promise<Enrichment[]> {
  const { data } = await api.get<Enrichment[]>("/api/context/enrichments", {
    params: { connection_id: connectionId },
  });
  return data;
}

export async function createEnrichment(
  body: EnrichmentCreate,
): Promise<Enrichment> {
  const { data } = await api.post<Enrichment>("/api/context/enrichments", body);
  return data;
}

export async function updateEnrichment(
  id: string,
  body: EnrichmentUpdate,
): Promise<Enrichment> {
  const { data } = await api.put<Enrichment>(
    `/api/context/enrichments/${id}`,
    body,
  );
  return data;
}

export async function deleteEnrichment(id: string): Promise<void> {
  await api.delete(`/api/context/enrichments/${id}`);
}

// --- Context: golden records ---

export async function listGoldenRecords(
  connectionId: string,
): Promise<GoldenRecord[]> {
  const { data } = await api.get<GoldenRecord[]>(
    "/api/context/golden-records",
    { params: { connection_id: connectionId } },
  );
  return data;
}

export async function createGoldenRecord(
  body: GoldenRecordCreate,
): Promise<GoldenRecord> {
  const { data } = await api.post<GoldenRecord>(
    "/api/context/golden-records",
    body,
  );
  return data;
}

export async function deleteGoldenRecord(id: string): Promise<void> {
  await api.delete(`/api/context/golden-records/${id}`);
}

// --- Context: business rules ---

export async function listRules(connectionId: string): Promise<BusinessRule[]> {
  const { data } = await api.get<BusinessRule[]>("/api/context/rules", {
    params: { connection_id: connectionId },
  });
  return data;
}

export async function createRule(
  body: BusinessRuleCreate,
): Promise<BusinessRule> {
  const { data } = await api.post<BusinessRule>("/api/context/rules", body);
  return data;
}

export async function updateRule(
  id: string,
  body: BusinessRuleUpdate,
): Promise<BusinessRule> {
  const { data } = await api.put<BusinessRule>(`/api/context/rules/${id}`, body);
  return data;
}

export async function deleteRule(id: string): Promise<void> {
  await api.delete(`/api/context/rules/${id}`);
}

// --- History ---

export interface HistoryListParams {
  connection_id?: string;
  rating?: number;
  limit?: number;
  offset?: number;
}

export async function listHistory(
  params: HistoryListParams = {},
): Promise<QueryHistoryItem[]> {
  const { data } = await api.get<QueryHistoryItem[]>("/api/history", {
    params,
  });
  return data;
}

export async function getHistory(id: string): Promise<QueryHistoryItem> {
  const { data } = await api.get<QueryHistoryItem>(`/api/history/${id}`);
  return data;
}

export async function getHistoryStats(
  params: { connection_id?: string } = {},
): Promise<HistoryStats> {
  const { data } = await api.get<HistoryStats>("/api/history/stats", {
    params,
  });
  return data;
}

export async function submitFeedback(
  historyId: string,
  body: FeedbackRequest,
): Promise<FeedbackResult> {
  const { data } = await api.post<FeedbackResult>(
    `/api/history/${historyId}/feedback`,
    body,
  );
  return data;
}

// --- Chat sessions ---

export interface SessionListParams {
  connection_id?: string;
  limit?: number;
  offset?: number;
}

export async function createSession(body: {
  connection_id: string;
  title?: string;
}): Promise<ChatSession> {
  const { data } = await api.post<ChatSession>("/api/sessions", body);
  return data;
}

export async function listSessions(
  params: SessionListParams = {},
): Promise<ChatSession[]> {
  const { data } = await api.get<ChatSession[]>("/api/sessions", { params });
  return data;
}

export async function getSession(id: string): Promise<ChatSessionDetail> {
  const { data } = await api.get<ChatSessionDetail>(`/api/sessions/${id}`);
  return data;
}

export async function renameSession(
  id: string,
  title: string,
): Promise<ChatSession> {
  const { data } = await api.patch<ChatSession>(`/api/sessions/${id}`, {
    title,
  });
  return data;
}

export async function deleteSession(id: string): Promise<void> {
  await api.delete(`/api/sessions/${id}`);
}

// --- Export ---

export async function exportData(body: ExportRequest): Promise<Blob> {
  const { data } = await api.post<Blob>("/api/export", body, {
    responseType: "blob",
  });
  return data;
}

// --- Settings ---

interface PublicSettingsRaw {
  app_name: string;
  llm_provider: string;
  model: string;
  max_rows: number;
  database_types: string[];
}

export async function getPublicSettings(): Promise<PublicSettings> {
  const { data } = await api.get<PublicSettingsRaw>("/api/settings/public");
  return {
    app_name: data.app_name,
    llm_provider: data.llm_provider,
    openai_model: data.model,
    max_result_rows: data.max_rows,
    database_types: data.database_types,
  };
}

// --- Query (direct SQL execute — no LLM) ---

export async function executeSql(
  body: ExecuteSqlRequest,
): Promise<ExecuteSqlResult> {
  const { data } = await api.post<ExecuteSqlResult>("/api/query/execute", body);
  return data;
}

// --- Query (SSE stream) ---

function parseSseChunk(
  chunk: string,
  onEvent: (event: StreamQueryEvent) => void,
): void {
  // Normalize CRLF from sse-starlette / proxies
  const normalized = chunk.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const blocks = normalized.split("\n\n");
  for (const block of blocks) {
    const trimmed = block.trim();
    if (!trimmed) continue;

    let eventName = "message";
    const dataLines: string[] = [];

    for (const line of trimmed.split("\n")) {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    }

    if (dataLines.length === 0) continue;

    const raw = dataLines.join("\n");
    let data: unknown = raw;
    try {
      data = JSON.parse(raw);
    } catch {
      // keep raw string
    }

    onEvent({ event: eventName, data });
  }
}

export async function streamQuery(
  body: QueryRequest,
  onEvent: (event: StreamQueryEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/query", {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    let parsed: unknown = text;
    try {
      parsed = JSON.parse(text);
    } catch {
      // keep raw
    }
    redirectFromFetchStatus(response.status, parsed);
    const message =
      parsed && typeof parsed === "object" && "detail" in parsed
        ? String((parsed as { detail: unknown }).detail)
        : text;
    throw new Error(message || `Query failed (${response.status})`);
  }

  if (!response.body) {
    throw new Error("No response body for SSE stream");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";

    for (const part of parts) {
      parseSseChunk(part, onEvent);
    }
  }

  if (buffer.trim()) {
    parseSseChunk(buffer, onEvent);
  }
}

export { api };
