const tokenKey = "splitapp.tokens";
const yandexOAuthStateKey = "splitapp.yandexOAuthState";
const yandexOAuthClientId = "6c5725f5868c4604adaea1e4b892c14d";
const productionYandexRedirectUri = "https://split-app.ru/app";

export type SplitAppTokens = {
  access_token: string;
  refresh_token?: string;
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
  const headers = new Headers();
  if (tokens?.access_token) headers.set("Authorization", `Bearer ${tokens.access_token}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return (await response.json()) as T;
}

export function money(kopecks = 0) {
  return new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB" }).format(kopecks / 100);
}
