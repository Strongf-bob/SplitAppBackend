const tokenKey = "splitapp.tokens";
const yandexOAuthStateKey = "splitapp.yandexOAuthState";
const yandexOAuthClientId = "6c5725f5868c4604adaea1e4b892c14d";
const productionYandexRedirectUri = "https://split-app.ru/app";

export type SplitAppTokens = {
  access_token: string;
  refresh_token?: string;
  user?: UserProfile;
};

type RefreshTokensResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
};

let refreshInFlight: Promise<SplitAppTokens> | null = null;

export type UserProfile = {
  id: string;
  name: string;
  phone_number?: string;
  email?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  avatar_url?: string | null;
  public_handle?: string | null;
  discovery_enabled?: boolean;
};

export type UserPage = {
  items: UserProfile[];
  total: number;
};

export type Friendship = {
  id: string;
  requester_id: string;
  addressee_id: string;
  status: string;
  peer?: UserProfile | null;
};

export type FriendshipPage = {
  items: Friendship[];
  total: number;
};

export type EventParticipant = {
  user_id: string;
  role: string;
  status: string;
};

export type EventSummary = {
  id: string;
  title: string;
  name?: string;
  status?: string;
  is_closed?: boolean;
  total_kopecks?: number;
  participants_count?: number;
  participants?: EventParticipant[];
  token?: string;
};

export type EventInvite = {
  id: string;
  event_id: string;
  token: string;
  status: string;
  expires_at?: string;
};

export type EventInvitePreview = {
  event_id: string;
  event_name: string;
  creator_id: string;
  expires_at: string;
  participant_count: number;
  actor_decision?: string | null;
};

export type HomeSummary = {
  confirmed?: { owed_kopecks?: number; receivable_kopecks?: number };
  pending?: { owed_kopecks?: number; receivable_kopecks?: number };
  disputed?: { owed_kopecks?: number; receivable_kopecks?: number };
};

export type EventPage = {
  items: EventSummary[];
  total: number;
};

export type ReceiptSummary = {
  id: string;
  title?: string;
  category?: string | null;
  total_amount_kopecks?: number;
  status?: string;
  created_at?: string;
};

export type ReceiptPage = {
  items: ReceiptSummary[];
  total: number;
};

export type BalanceContribution = {
  source_type: string;
  source_id: string;
  amount_kopecks: number;
};

export type EventBalanceExplanation = {
  event_id: string;
  debitor_id: string;
  creditor_id: string;
  amount_kopecks: number;
  contributions: BalanceContribution[];
};

export type SettlementNetPosition = {
  user_id: string;
  direction: "owes" | "receives";
  amount_kopecks: number;
};

export type SettlementTransfer = {
  debtor_id: string;
  creditor_id: string;
  amount_kopecks: number;
};

export type SettlementPreview = {
  event_id: string;
  raw_debts: EventBalanceExplanation[];
  net_positions: SettlementNetPosition[];
  recommended_transfers: SettlementTransfer[];
  source_participant_ids: string[];
  original_transfer_count: number;
  recommended_transfer_count: number;
  original_gross_kopecks: number;
  recommended_total_kopecks: number;
  transfer_count_reduced: boolean;
};

export type SettlementPlanStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "stale"
  | "expired"
  | "executing"
  | "partially_settled"
  | "completed";

export type SettlementPlanEdge = {
  edge_id: string;
  debtor_id: string;
  creditor_id: string;
  amount_kopecks: number;
  payment_request_id?: string | null;
  status?: string | null;
};

export type SettlementPlanApproval = {
  user_id: string;
  approved_at: string;
};

export type SettlementPlan = {
  id: string;
  event_id: string;
  status: SettlementPlanStatus;
  algorithm_version: "greedy-net-v1";
  preview: SettlementPreview;
  edges: SettlementPlanEdge[];
  required_approver_ids: string[];
  approvals: SettlementPlanApproval[];
  created_by: string;
  expires_at: string;
  created_at: string;
  updated_at: string;
  rejected_by?: string | null;
  rejection_reason?: string | null;
  rejected_at?: string | null;
};

export type SettlementPlanPage = {
  items: SettlementPlan[];
  limit: number;
  offset: number;
  total: number;
};

export type PaymentRequest = {
  id: string;
  event_id: string;
  debtor_id: string;
  creditor_id: string;
  amount_kopecks: number;
  note?: string;
  status: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  payment_id?: string | null;
  deadline_at?: string | null;
  acknowledged_at?: string | null;
  cancelled_at?: string | null;
  disputed_at?: string | null;
  extension_requested_at?: string | null;
  origin?: string | null;
  settlement_plan_id?: string | null;
  settlement_edge_id?: string | null;
};

export type PaymentRequestPage = {
  items: PaymentRequest[];
  limit: number;
  offset: number;
  total: number;
};

export type Payment = {
  id: string;
  event_id: string;
  sender_id: string;
  receiver_id: string;
  amount_kopecks: number;
  status: string;
  confirmed: boolean;
  created_at: string;
  payment_request_id?: string | null;
  rejected_at?: string | null;
};

export type SplitikDraft = {
  id: string;
  type: string;
  status: string;
  payload: Record<string, unknown>;
  event_id?: string | null;
  session_id?: string | null;
  version?: number;
  source?: string;
  attachment_ids?: string[];
  questions?: Array<{ id: string; text: string; required?: boolean }>;
};

export type SplitikMessageResponse = {
  session_id: string;
  message_id: string;
  assistant_message: string;
  drafts?: SplitikDraft[];
  questions?: Array<{ id: string; text: string }>;
  suggested_actions?: Array<{ type: string; label: string; draft_id?: string | null }>;
};

export type SplitikAttachment = {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
};

export type ClientReportScreen =
  | "home"
  | "events"
  | "people"
  | "notifications"
  | "profile"
  | "splitik"
  | "receipts"
  | "payments"
  | "unknown";

export type ClientReportPayload = {
  kind: "automatic_error" | "manual_feedback";
  severity?: "info" | "warning" | "error" | "critical";
  screen?: ClientReportScreen;
  message: string;
  user_description?: string;
  request_id?: string;
  client_trace_id?: string;
  app_version?: string;
  url_path?: string;
  user_agent?: string;
  online?: boolean;
  contact_allowed?: boolean;
  contact?: string;
  metadata?: Record<string, unknown>;
};

export type ClientReportResponse = {
  id: string;
  status: string;
  friendly_message: string;
};

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly requestId?: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function loadTokens(): SplitAppTokens | null {
  if (typeof window === "undefined") return null;
  const sessionTokens = parseStoredTokens(window.sessionStorage.getItem(tokenKey));
  if (sessionTokens) return sessionTokens;
  const persistedTokens = parseStoredTokens(window.localStorage.getItem(tokenKey));
  if (persistedTokens) window.sessionStorage.setItem(tokenKey, JSON.stringify(persistedTokens));
  return persistedTokens;
}

export function saveTokens(tokens: SplitAppTokens) {
  window.sessionStorage.setItem(tokenKey, JSON.stringify(tokens));
  window.localStorage.setItem(tokenKey, JSON.stringify(tokens));
}

export function clearTokens() {
  window.sessionStorage.removeItem(tokenKey);
  window.localStorage.removeItem(tokenKey);
}

export function yandexRedirectUri() {
  return productionYandexRedirectUri;
}

export function startYandexLogin() {
  const state = crypto.randomUUID();
  window.sessionStorage.setItem(yandexOAuthStateKey, state);
  const search = new URLSearchParams({
    response_type: "token",
    client_id: yandexOAuthClientId,
    redirect_uri: yandexRedirectUri(),
    state
  });
  window.location.href = `https://oauth.yandex.ru/authorize?${search.toString()}`;
}

export async function handleYandexOAuthCallback(): Promise<SplitAppTokens | null> {
  if (typeof window === "undefined" || !window.location.hash.includes("access_token")) return null;
  const params = new URLSearchParams(window.location.hash.slice(1));
  const accessToken = params.get("access_token");
  const returnedState = params.get("state");
  const expectedState = window.sessionStorage.getItem(yandexOAuthStateKey);
  window.history.replaceState({}, document.title, window.location.pathname + window.location.search);

  if (!accessToken || !expectedState || returnedState !== expectedState) return null;
  window.sessionStorage.removeItem(yandexOAuthStateKey);

  const response = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ yandex_token: accessToken })
  });

  if (!response.ok) throw new Error("Не удалось войти через Яндекс.");
  const tokens = (await response.json()) as SplitAppTokens;
  saveTokens(tokens);
  return tokens;
}

export async function api<T>(
  path: string,
  tokens: SplitAppTokens | null,
  init: RequestInit = {},
  onTokensRefreshed?: (tokens: SplitAppTokens) => void
): Promise<T> {
  const activeTokens = resolveStoredTokens(tokens);
  const response = await fetchWithAuth(path, activeTokens, init);
  if (response.ok) return (await response.json()) as T;

  if (response.status === 401 && activeTokens?.refresh_token) {
    const nextTokens = await refreshTokensOnce(activeTokens);
    onTokensRefreshed?.(nextTokens);
    const retry = await fetchWithAuth(path, nextTokens, init);
    if (retry.ok) return (await retry.json()) as T;
    throw new ApiError(retry.status, await responseErrorMessage(retry), retry.headers.get("X-Request-ID") ?? undefined);
  }

  throw new ApiError(response.status, await responseErrorMessage(response), response.headers.get("X-Request-ID") ?? undefined);
}

function resolveStoredTokens(tokens: SplitAppTokens | null) {
  const storedTokens = loadTokens();
  return storedTokens ?? tokens;
}

function parseStoredTokens(raw: string | null): SplitAppTokens | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as SplitAppTokens | null;
    return parsed?.access_token ? parsed : null;
  } catch {
    return null;
  }
}

async function fetchWithAuth(path: string, tokens: SplitAppTokens | null, init: RequestInit) {
  const headers = new Headers(init.headers);
  if (tokens?.access_token) headers.set("Authorization", `Bearer ${tokens.access_token}`);
  if (!headers.has("X-Request-ID")) headers.set("X-Request-ID", crypto.randomUUID());
  const isFormDataBody = typeof FormData !== "undefined" && init.body instanceof FormData;
  if (init.body && !isFormDataBody && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  return fetch(path, { ...init, headers });
}

async function refreshAccessToken(refreshToken: string): Promise<RefreshTokensResponse> {
  const response = await fetch("/api/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken })
  });
  if (!response.ok) throw new ApiError(response.status, await responseErrorMessage(response), response.headers.get("X-Request-ID") ?? undefined);
  return (await response.json()) as RefreshTokensResponse;
}

async function refreshTokensOnce(tokens: SplitAppTokens): Promise<SplitAppTokens> {
  refreshInFlight ??= refreshAccessToken(tokens.refresh_token ?? "")
    .then((refreshedTokens) => {
      const nextTokens = { ...tokens, ...refreshedTokens };
      saveTokens(nextTokens);
      return nextTokens;
    })
    .finally(() => {
      refreshInFlight = null;
    });

  return refreshInFlight;
}

export async function reportClientIssue(
  payload: ClientReportPayload,
  tokens: SplitAppTokens | null
): Promise<ClientReportResponse> {
  const client_trace_id = payload.client_trace_id || crypto.randomUUID();
  const headers = new Headers({ "Content-Type": "application/json", "X-Request-ID": crypto.randomUUID() });
  if (tokens?.access_token) headers.set("Authorization", `Bearer ${tokens.access_token}`);
  const response = await fetch("/api/client-reports", {
    method: "POST",
    headers,
    body: JSON.stringify({
      ...payload,
      client_trace_id,
      url_path: payload.url_path ?? window.location.pathname + window.location.hash,
      user_agent: payload.user_agent ?? navigator.userAgent,
      online: payload.online ?? navigator.onLine,
      metadata: sanitizeReportMetadata(payload.metadata ?? {})
    })
  });
  if (!response.ok) {
    throw new ApiError(response.status, await responseErrorMessage(response), response.headers.get("X-Request-ID") ?? undefined);
  }
  return (await response.json()) as ClientReportResponse;
}

async function responseErrorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail.trim()) return body.detail;
    if (Array.isArray(body.detail)) return formatValidationDetail(body.detail);
  } catch {
    // Fall through to the HTTP status when the backend did not return JSON.
  }
  return `HTTP ${response.status}`;
}

function sanitizeReportMetadata(metadata: Record<string, unknown>) {
  const allowed = new Set(["api_status", "api_path", "component", "screen_label", "action", "error_name", "error_message"]);
  return Object.fromEntries(Object.entries(metadata).filter(([key]) => allowed.has(key)));
}

function formatValidationDetail(items: unknown[]) {
  const messages = items
    .map((item) => {
      if (!item || typeof item !== "object") return "";
      const detail = item as { loc?: unknown; msg?: unknown };
      const location = Array.isArray(detail.loc) ? detail.loc.join(".") : "body";
      const message = typeof detail.msg === "string" ? detail.msg : "Некорректное значение";
      return `${location}: ${message}`;
    })
    .filter(Boolean);
  return messages.length ? messages.join("; ") : "HTTP 422";
}

export function money(kopecks = 0) {
  const rubles = Math.round(kopecks / 100);
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(rubles)} ₽`;
}
