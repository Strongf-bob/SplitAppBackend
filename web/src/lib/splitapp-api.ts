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

export type UserProfile = {
  id: string;
  name: string;
  phone_number?: string;
  email?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  avatar_url?: string | null;
};

export type EventSummary = {
  id: string;
  title: string;
  name?: string;
  status?: string;
  is_closed?: boolean;
  total_kopecks?: number;
  participants_count?: number;
  participants?: Array<unknown>;
  token?: string;
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

export type SplitikMessageResponse = {
  session_id: string;
  message_id: string;
  assistant_message: string;
  questions?: Array<{ id: string; text: string }>;
  suggested_actions?: Array<{ type: string; label: string }>;
};

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function loadTokens(): SplitAppTokens | null {
  if (typeof window === "undefined") return null;
  try {
    return JSON.parse(window.localStorage.getItem(tokenKey) || "null") as SplitAppTokens | null;
  } catch {
    return null;
  }
}

export function saveTokens(tokens: SplitAppTokens) {
  window.localStorage.setItem(tokenKey, JSON.stringify(tokens));
}

export function clearTokens() {
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
  window.history.replaceState({}, document.title, window.location.pathname);

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

export async function api<T>(path: string, tokens: SplitAppTokens | null, init: RequestInit = {}): Promise<T> {
  const response = await fetchWithAuth(path, tokens, init);
  if (response.ok) return (await response.json()) as T;

  if (response.status === 401 && tokens?.refresh_token) {
    const refreshedTokens = await refreshAccessToken(tokens.refresh_token);
    saveTokens({ ...tokens, ...refreshedTokens });
    const retry = await fetchWithAuth(path, { ...tokens, ...refreshedTokens }, init);
    if (retry.ok) return (await retry.json()) as T;
    throw new ApiError(retry.status, await responseErrorMessage(retry));
  }

  throw new ApiError(response.status, await responseErrorMessage(response));
}

async function fetchWithAuth(path: string, tokens: SplitAppTokens | null, init: RequestInit) {
  const headers = new Headers(init.headers);
  if (tokens?.access_token) headers.set("Authorization", `Bearer ${tokens.access_token}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  return fetch(path, { ...init, headers });
}

async function refreshAccessToken(refreshToken: string): Promise<RefreshTokensResponse> {
  const response = await fetch("/api/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken })
  });
  if (!response.ok) throw new ApiError(response.status, await responseErrorMessage(response));
  return (await response.json()) as RefreshTokensResponse;
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
  return new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB" }).format(kopecks / 100);
}
