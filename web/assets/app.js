const tokenKey = "splitapp.tokens";
const yandexOAuthStateKey = "splitapp.yandexOAuthState";
const yandexOAuthClientId = "6c5725f5868c4604adaea1e4b892c14d";

const state = {
  tokens: loadTokens(),
  user: null,
  events: [],
  selectedEventId: null,
  selectedReceiptId: null,
  currentView: "home",
  deferredInstallPrompt: null,
  splitikSessionId: null
};

const viewRoot = document.querySelector("#viewRoot");
const workspace = document.querySelector("#workspace");
const authPanel = document.querySelector("#authPanel");
const welcomePanel = document.querySelector("#welcomePanel");
const toast = document.querySelector("#toast");
const installButton = document.querySelector("#installButton");
const welcomeInstallButton = document.querySelector("#welcomeInstallButton");
const logoutButton = document.querySelector("#logoutButton");
const networkStatus = document.querySelector("#networkStatus");
const yandexLoginButton = document.querySelector("#yandexLoginButton");

function loadTokens() {
  try {
    return JSON.parse(localStorage.getItem(tokenKey) || "null");
  } catch {
    return null;
  }
}

function saveTokens(tokens) {
  state.tokens = tokens;
  localStorage.setItem(tokenKey, JSON.stringify(tokens));
}

function clearTokens() {
  state.tokens = null;
  state.user = null;
  state.events = [];
  state.selectedEventId = null;
  state.splitikSessionId = null;
  localStorage.removeItem(tokenKey);
}

function showToast(message) {
  toast.textContent = message;
  toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    toast.hidden = true;
  }, 3600);
}

function money(kopecks = 0) {
  return new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB" }).format(
    Number(kopecks || 0) / 100
  );
}

function rublesToKopecks(value) {
  return Math.round(Number(String(value || "0").replace(",", ".")) * 100);
}

function idempotencyKey(prefix) {
  return `${prefix}-${crypto.randomUUID()}`;
}

function qs(params) {
  const search = new URLSearchParams(params);
  return search.toString();
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (value !== false && value !== null && value !== undefined) node.setAttribute(key, value);
  }
  for (const child of Array.isArray(children) ? children : [children]) {
    if (child === null || child === undefined) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

async function api(path, options = {}, retried = false) {
  const headers = new Headers(options.headers || {});
  if (!(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (state.tokens?.access_token) headers.set("Authorization", `Bearer ${state.tokens.access_token}`);

  const response = await fetch(path, { ...options, headers });
  if (response.status === 401 && state.tokens?.refresh_token && !retried) {
    await refreshTokens();
    return api(path, options, true);
  }
  if (response.status === 204) return null;

  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof body === "object" && body ? body.detail : body;
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return body;
}

async function refreshTokens() {
  const body = await fetch("/api/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: state.tokens.refresh_token })
  });
  if (!body.ok) {
    clearTokens();
    renderAuthState();
    throw new Error("Сессия истекла. Войдите снова.");
  }
  saveTokens(await body.json());
}

async function bootstrap() {
  updateOnlineStatus();
  await registerServiceWorker();
  setupInstall();
  setupNavigation();
  setupAuth();
  await handleYandexOAuthCallback();
  renderAuthState();
  if (state.tokens) {
    await safeLoadInitialData();
  }
}

async function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  try {
    await navigator.serviceWorker.register("/sw.js");
  } catch (error) {
    console.warn("Service worker registration failed", error);
  }
}

function setupInstall() {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    state.deferredInstallPrompt = event;
    installButton.hidden = false;
  });
  const runInstall = async () => {
    if (!state.deferredInstallPrompt) {
      showToast("На iPhone используйте Share -> Add to Home Screen.");
      return;
    }
    state.deferredInstallPrompt.prompt();
    await state.deferredInstallPrompt.userChoice;
    state.deferredInstallPrompt = null;
    installButton.hidden = true;
  };
  installButton.addEventListener("click", runInstall);
  welcomeInstallButton.addEventListener("click", runInstall);
}

function setupNavigation() {
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.view));
  });
  document.querySelector("[data-scroll-login]").addEventListener("click", () => {
    authPanel.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  window.addEventListener("online", updateOnlineStatus);
  window.addEventListener("offline", updateOnlineStatus);
  logoutButton.addEventListener("click", async () => {
    clearTokens();
    if ("caches" in window) {
      const keys = await caches.keys();
      await Promise.all(keys.map((key) => caches.delete(key)));
    }
    renderAuthState();
    showToast("Вы вышли. Локальные данные очищены.");
  });
}

function setupAuth() {
  yandexLoginButton.addEventListener("click", startYandexLogin);
}

function yandexRedirectUri() {
  if (window.location.hostname === "split-app.ru" || window.location.hostname === "www.split-app.ru") {
    return "https://split-app.ru/app";
  }
  return `${window.location.origin}/app`;
}

function startYandexLogin() {
  const oauthState = crypto.randomUUID();
  sessionStorage.setItem(yandexOAuthStateKey, oauthState);

  const params = new URLSearchParams({
    response_type: "token",
    client_id: yandexOAuthClientId,
    redirect_uri: yandexRedirectUri(),
    state: oauthState
  });

  window.location.assign(`https://oauth.yandex.ru/authorize?${params.toString()}`);
}

async function handleYandexOAuthCallback() {
  if (!window.location.hash) return;

  const fragment = new URLSearchParams(window.location.hash.slice(1));
  const yandexToken = fragment.get("access_token");
  const error = fragment.get("error");
  if (!yandexToken && !error) return;

  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);

  if (error) {
    const description = fragment.get("error_description") || "Яндекс не подтвердил вход.";
    showToast(description);
    return;
  }

  const expectedState = sessionStorage.getItem(yandexOAuthStateKey);
  sessionStorage.removeItem(yandexOAuthStateKey);
  if (!expectedState || fragment.get("state") !== expectedState) {
    showToast("Не удалось подтвердить OAuth-сессию. Попробуйте войти снова.");
    return;
  }

  try {
    await loginWithYandexToken(yandexToken);
    showToast("Вход выполнен.");
  } catch (loginError) {
    showToast(loginError.message);
  }
}

async function loginWithYandexToken(yandexToken) {
  const login = await api("/api/login", {
    method: "POST",
    body: JSON.stringify({ yandex_token: yandexToken })
  });
  saveTokens(login);
  state.user = login.user;
}

function updateOnlineStatus() {
  networkStatus.textContent = navigator.onLine ? "online" : "offline";
  networkStatus.style.color = navigator.onLine ? "var(--accent-strong)" : "var(--danger)";
}

function renderAuthState() {
  const loggedIn = Boolean(state.tokens);
  workspace.hidden = !loggedIn;
  authPanel.hidden = loggedIn;
  welcomePanel.hidden = loggedIn;
  logoutButton.hidden = !loggedIn;
  if (loggedIn) renderCurrentView();
}

async function safeLoadInitialData() {
  try {
    await Promise.all([loadEvents(), loadProfile()]);
    renderAuthState();
  } catch (error) {
    showToast(error.message);
    if (String(error.message).includes("Сессия")) renderAuthState();
  }
}

async function loadProfile() {
  const stats = await api("/api/users/me/financial-stats");
  state.stats = stats;
}

async function loadEvents() {
  const page = await api(`/api/events?${qs({ limit: 50, offset: 0 })}`);
  state.events = page.items || [];
  if (!state.selectedEventId && state.events[0]) state.selectedEventId = state.events[0].id;
}

function navigate(view) {
  state.currentView = view;
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  renderCurrentView();
}

function renderCurrentView() {
  if (!state.tokens) return;
  const renderers = {
    home: renderHome,
    events: renderEvents,
    receipts: renderReceipts,
    payments: renderPayments,
    friends: renderFriends,
    profile: renderProfile,
    splitik: renderSplitik
  };
  viewRoot.replaceChildren();
  renderers[state.currentView]?.();
}

function header(title, subtitle) {
  return el("div", { class: "view-header" }, [
    el("div", {}, [el("h1", { text: title }), el("p", { class: "muted", text: subtitle })]),
    el("button", { class: "ghost-button", type: "button", onclick: () => safeLoadInitialData(), text: "Обновить" })
  ]);
}

function renderHome() {
  const stats = state.stats || {};
  viewRoot.append(
    header("Главная", "Быстрый обзор событий, долгов и pending-действий."),
    el("div", { class: "grid" }, [
      metricCard("Открытые события", stats.open_events_count ?? state.events.length),
      metricCard("Я должен", money(stats.outstanding_owed_kopecks || 0)),
      metricCard("Мне должны", money(stats.outstanding_receivable_kopecks || 0)),
      el("div", { class: "card" }, [
        el("h3", { text: "Быстрые действия" }),
        el("div", { class: "row-actions" }, [
          el("button", { class: "primary-button", text: "Создать событие", onclick: () => navigate("events") }),
          el("button", { class: "secondary-button", text: "Добавить чек", onclick: () => navigate("receipts") }),
          el("button", { class: "ghost-button", text: "Открыть Сплитик", onclick: () => navigate("splitik") })
        ])
      ])
    ]),
    eventsList("Последние события", state.events.slice(0, 5))
  );
}

function metricCard(label, value) {
  return el("div", { class: "card" }, [el("span", { class: "eyebrow", text: label }), el("strong", { class: "amount", text: value })]);
}

function eventsList(title, events) {
  const list = el("ul", { class: "list" });
  if (!events.length) list.append(el("li", { class: "empty", text: "Событий пока нет." }));
  events.forEach((event) => {
    list.append(
      el("li", { class: "list-row" }, [
        el("div", {}, [
          el("strong", { text: event.name }),
          el("p", { class: "muted", text: `${event.participants?.length || 0} участников` })
        ]),
        el("button", {
          class: "ghost-button",
          text: "Открыть",
          onclick: () => {
            state.selectedEventId = event.id;
            navigate("events");
          }
        })
      ])
    );
  });
  return el("section", { class: "panel" }, [el("h2", { text: title }), list]);
}

function selectedEvent() {
  return state.events.find((event) => event.id === state.selectedEventId) || state.events[0] || null;
}

function renderEventPicker() {
  const select = el("select", {
    onchange: (event) => {
      state.selectedEventId = event.target.value;
      renderCurrentView();
    }
  });
  state.events.forEach((event) => {
    select.append(el("option", { value: event.id, text: event.name, selected: event.id === state.selectedEventId }));
  });
  return select;
}

function renderEvents() {
  viewRoot.append(header("События", "Создание, участники, invite link и nearby code."));
  const createForm = el("form", { class: "panel form-grid two" }, [
    el("label", {}, ["Название события", el("input", { name: "name", required: true, placeholder: "Поездка в Казань" })]),
    el("button", { class: "primary-button", type: "submit", text: "Создать" })
  ]);
  createForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const form = new FormData(createForm);
      const created = await api("/api/events", { method: "POST", body: JSON.stringify({ name: form.get("name") }) });
      await loadEvents();
      state.selectedEventId = created.id;
      createForm.reset();
      renderEvents();
      showToast("Событие создано.");
    } catch (error) {
      showToast(error.message);
    }
  });
  viewRoot.append(createForm, eventsList("Все события", state.events), renderEventTools());
}

function renderEventTools() {
  const event = selectedEvent();
  if (!event) return el("section", { class: "panel empty", text: "Создайте событие, чтобы управлять участниками." });
  const panel = el("section", { class: "panel" }, [
    el("h2", { text: "Участники и приглашения" }),
    renderEventPicker(),
    el("p", { class: "muted", text: "Добавляйте видимых пользователей или делитесь invite/nearby code." })
  ]);
  const userForm = el("form", { class: "form-grid two" }, [
    el("label", {}, ["User UUID", el("input", { name: "user_id", required: true })]),
    el("button", { class: "primary-button", text: "Добавить участника" })
  ]);
  userForm.addEventListener("submit", async (submit) => {
    submit.preventDefault();
    try {
      const userId = new FormData(userForm).get("user_id");
      await api(`/api/events/${event.id}/participants`, {
        method: "POST",
        body: JSON.stringify({ user_ids: [userId] })
      });
      showToast("Участник добавлен.");
    } catch (error) {
      showToast(error.message);
    }
  });
  const inviteButtons = el("div", { class: "row-actions" }, [
    el("button", {
      class: "secondary-button",
      text: "Создать invite link",
      onclick: async () => {
        try {
          const invite = await api(`/api/events/${event.id}/invites`, {
            method: "POST",
            body: JSON.stringify({ expires_in_seconds: 604800 })
          });
          await navigator.clipboard?.writeText(invite.invite_url);
          showToast(`Invite создан: ${invite.invite_url}`);
        } catch (error) {
          showToast(error.message);
        }
      }
    }),
    el("button", {
      class: "ghost-button",
      text: "Nearby code",
      onclick: async () => {
        try {
          const code = await api(`/api/events/${event.id}/nearby-code`, {
            method: "POST",
            body: JSON.stringify({ expires_in_seconds: 180 })
          });
          showToast(`Код: ${code.code}`);
        } catch (error) {
          showToast(error.message);
        }
      }
    })
  ]);
  panel.append(userForm, inviteButtons);
  return panel;
}

function renderReceipts() {
  viewRoot.append(header("Чеки", "Ручной чек, JPEG, распределение и AI draft review."));
  const event = selectedEvent();
  if (!event) {
    viewRoot.append(el("section", { class: "panel empty", text: "Сначала создайте событие." }));
    return;
  }
  const form = el("form", { class: "panel form-grid three" }, [
    el("label", {}, ["Событие", renderEventPicker()]),
    el("label", {}, ["Payer UUID", el("input", { name: "payer_id", required: true, value: event.creator_id })]),
    el("label", {}, ["Итог, ₽", el("input", { name: "total", required: true, inputmode: "decimal", value: "1000" })]),
    el("label", {}, ["Название", el("input", { name: "title", value: "Новый чек" })]),
    el("label", {}, ["Позиция", el("input", { name: "item", value: "Позиция" })]),
    el("label", {}, ["Участники UUID через запятую", el("input", { name: "shares", required: true, value: (event.participants || []).map((p) => p.user_id).join(",") })]),
    el("button", { class: "primary-button", type: "submit", text: "Создать чек" })
  ]);
  form.addEventListener("submit", async (submit) => {
    submit.preventDefault();
    const data = new FormData(form);
    const shareUsers = String(data.get("shares"))
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    const shareValue = shareUsers.length ? 1 / shareUsers.length : 1;
    try {
      const receipt = await api(`/api/events/${state.selectedEventId}/receipts`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey("receipt") },
        body: JSON.stringify({
          payer_id: data.get("payer_id"),
          title: data.get("title"),
          total_amount_kopecks: rublesToKopecks(data.get("total")),
          items: [
            {
              name: data.get("item"),
              cost_kopecks: rublesToKopecks(data.get("total")),
              split_mode: "custom",
              share_items: shareUsers.map((user_id) => ({ user_id, share_value: shareValue }))
            }
          ]
        })
      });
      state.selectedReceiptId = receipt.id;
      showToast("Чек создан. Подтвердите его отдельно.");
    } catch (error) {
      showToast(error.message);
    }
  });
  viewRoot.append(form, renderAiReceiptDraft(), renderReceiptImageTools());
  loadReceiptsPanel();
}

function renderAiReceiptDraft() {
  const resultBox = el("div", { hidden: true });
  const form = el("form", { class: "panel form-grid" }, [
    el("h2", { text: "AI draft чека" }),
    el("p", {
      class: "muted",
      text: "Модели: MiMo V2 5 Pro -> Qwen 3 7 Max -> Kimi K2 5 при расхождении. Backend вернет draft для ручной проверки, деньги не меняются."
    }),
    el("textarea", { name: "receipt_text", required: true, placeholder: "Вставьте текст чека или заметки по фото..." }),
    el("label", {}, ["Payer UUID", el("input", { name: "payer_id", value: selectedEvent()?.creator_id || "" })]),
    el("button", { class: "secondary-button", text: "Подготовить draft через backend" }),
    resultBox
  ]);
  form.addEventListener("submit", async (submit) => {
    submit.preventDefault();
    const data = new FormData(form);
    try {
      const draft = await api(`/api/events/${state.selectedEventId}/receipt-drafts/ai`, {
        method: "POST",
        body: JSON.stringify({
          source_text: data.get("receipt_text"),
          payer_id: data.get("payer_id") || null,
          locale: "ru-RU",
          timezone: "Europe/Moscow"
        })
      });
      resultBox.hidden = false;
      resultBox.replaceChildren(renderReceiptAIDraftCard(draft));
      showToast("AI draft сохранен на backend. Деньги не изменены.");
    } catch (error) {
      showToast(error.message);
    }
  });
  return form;
}

function renderReceiptAIDraftCard(draft) {
  const payload = draft.draft_payload;
  const card = el("article", { class: "card draft-card" });
  const statusText = draft.disagreements.length
    ? `Есть расхождения: ${draft.disagreements.join(", ")}`
    : "Модели совпали по критичным полям";
  const titleInput = el("input", { value: payload.title || "Черновик чека", "aria-label": "Название чека" });
  const totalInput = el("input", {
    value: String((payload.total_amount_kopecks || 0) / 100),
    inputmode: "decimal",
    "aria-label": "Итоговая сумма"
  });
  const itemList = el("div", { class: "draft-items" });

  (payload.items || []).forEach((item, index) => {
    const itemName = el("input", { value: item.name || `Позиция ${index + 1}`, "aria-label": "Название позиции" });
    const itemCost = el("input", {
      value: String((item.cost_kopecks || 0) / 100),
      inputmode: "decimal",
      "aria-label": "Цена позиции"
    });
    const shares = el(
      "div",
      { class: "draft-shares" },
      (item.share_items || []).map((share) =>
        el("span", {
          class: "chip",
          text: `${share.user_id}: ${Math.round(Number(share.share_value) * 100)}%`
        })
      )
    );
    itemList.append(el("div", { class: "draft-item" }, [itemName, itemCost, shares]));
  });

  const confirmedBanner = el("div", {
    class: "confirm-banner",
    text: "Черновик проверен. Следующий шаг будет созданием обычного draft receipt.",
    hidden: true
  });
  const confirmButton = el("button", {
    class: "primary-button",
    type: "button",
    text: "Черновик правильный, подтверждаю",
    onclick: () => {
      card.classList.add("confirmed");
      confirmedBanner.hidden = false;
      confirmButton.disabled = true;
      confirmButton.textContent = "Подтверждено";
      showToast("Черновик подтвержден в PWA. Чек еще не создан.");
    }
  });

  card.append(
    el("div", { class: "draft-summary" }, [
      el("div", {}, [
        el("span", { class: "eyebrow", text: `AI draft · ${draft.model_status}` }),
        titleInput,
        el("p", { class: "muted", text: statusText })
      ]),
      el("div", { class: "draft-total" }, [
        el("span", { text: "Итого" }),
        el("strong", { text: money(payload.total_amount_kopecks) })
      ])
    ]),
    el("div", { class: "form-grid two" }, [
      el("label", {}, ["Итог, ₽", totalInput]),
      el("label", {}, [
        "Payer UUID",
        el("input", { value: payload.payer_id, "aria-label": "Payer UUID" })
      ])
    ]),
    itemList,
    renderModelStrip(draft),
    confirmedBanner,
    el("div", { class: "row-actions" }, [
      confirmButton,
      el("button", {
        class: "ghost-button",
        type: "button",
        text: "Вернуться к тексту",
        onclick: () => document.querySelector("[name=receipt_text]")?.focus()
      })
    ])
  );
  return card;
}

function renderModelStrip(draft) {
  const models = [
    draft.primary_result,
    draft.verification_result,
    draft.escalation_result
  ].filter(Boolean);
  return el(
    "div",
    { class: "model-strip" },
    models.map((result) =>
      el("div", { class: "model-card" }, [
        el("span", { class: "eyebrow", text: result.model_role }),
        el("strong", { text: result.model_id }),
        el("p", {
          class: "muted",
          text: result.warnings?.length ? result.warnings.join("; ") : "Без предупреждений"
        })
      ])
    )
  );
}

function renderReceiptImageTools() {
  const form = el("form", { class: "panel form-grid two" }, [
    el("label", {}, ["Receipt UUID", el("input", { name: "receipt_id", value: state.selectedReceiptId || "" })]),
    el("label", {}, ["JPEG", el("input", { name: "file", type: "file", accept: "image/jpeg" })]),
    el("button", { class: "primary-button", text: "Загрузить JPEG" }),
    el("button", {
      class: "ghost-button",
      type: "button",
      text: "Получить presigned URL",
      onclick: async () => {
        try {
          const id = form.querySelector("[name=receipt_id]").value;
          const result = await api(`/api/receipts/${id}/image/presigned-url`);
          showToast(result.image_url);
        } catch (error) {
          showToast(error.message);
        }
      }
    })
  ]);
  form.addEventListener("submit", async (submit) => {
    submit.preventDefault();
    const data = new FormData(form);
    const id = data.get("receipt_id");
    const upload = new FormData();
    upload.set("file", data.get("file"));
    try {
      await api(`/api/receipts/${id}/image`, { method: "POST", body: upload, headers: {} });
      showToast("Изображение загружено.");
    } catch (error) {
      showToast(error.message);
    }
  });
  return form;
}

async function loadReceiptsPanel() {
  try {
    const page = await api(`/api/events/${state.selectedEventId}/receipts?${qs({ limit: 50, offset: 0 })}`);
    const list = el("ul", { class: "list" });
    (page.items || []).forEach((receipt) => {
      list.append(
        el("li", { class: "list-row" }, [
          el("div", {}, [el("strong", { text: receipt.title || "Чек" }), el("p", { class: "muted", text: `${receipt.status} · ${money(receipt.total_amount_kopecks)}` })]),
          el("div", { class: "row-actions" }, [
            el("button", {
              class: "ghost-button",
              text: "Подтвердить",
              onclick: async () => {
                try {
                  await api(`/api/receipts/${receipt.id}/confirm`, { method: "POST" });
                  showToast("Чек подтвержден.");
                  renderReceipts();
                } catch (error) {
                  showToast(error.message);
                }
              }
            })
          ])
        ])
      );
    });
    viewRoot.append(el("section", { class: "panel" }, [el("h2", { text: "Список чеков" }), list]));
  } catch (error) {
    viewRoot.append(el("section", { class: "panel empty", text: error.message }));
  }
}

function renderPayments() {
  viewRoot.append(header("Платежи", "Долги, payment declarations и payment requests."));
  const event = selectedEvent();
  if (!event) {
    viewRoot.append(el("section", { class: "panel empty", text: "Сначала создайте событие." }));
    return;
  }
  const form = el("form", { class: "panel form-grid three" }, [
    el("label", {}, ["Событие", renderEventPicker()]),
    el("label", {}, ["Sender UUID", el("input", { name: "sender_id", required: true })]),
    el("label", {}, ["Receiver UUID", el("input", { name: "receiver_id", required: true })]),
    el("label", {}, ["Сумма, ₽", el("input", { name: "amount", value: "500", inputmode: "decimal" })]),
    el("button", { class: "primary-button", text: "Создать платеж" })
  ]);
  form.addEventListener("submit", async (submit) => {
    submit.preventDefault();
    const data = new FormData(form);
    try {
      await api(`/api/events/${state.selectedEventId}/payments`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey("payment") },
        body: JSON.stringify({
          sender_id: data.get("sender_id"),
          receiver_id: data.get("receiver_id"),
          amount_kopecks: rublesToKopecks(data.get("amount"))
        })
      });
      showToast("Платеж создан. Получатель должен подтвердить.");
      renderPayments();
    } catch (error) {
      showToast(error.message);
    }
  });
  viewRoot.append(form);
  loadBalancesAndPayments();
}

async function loadBalancesAndPayments() {
  try {
    const [balances, payments] = await Promise.all([
      api(`/api/events/${state.selectedEventId}/balances/explain`),
      api(`/api/events/${state.selectedEventId}/payments?${qs({ limit: 50, offset: 0 })}`)
    ]);
    viewRoot.append(
      el("section", { class: "panel" }, [
        el("h2", { text: "Балансы" }),
        renderRows(
          balances,
          (row) => `${row.debitor_id} должен ${row.creditor_id}`,
          (row) => money(row.amount_kopecks),
          "Долгов пока нет."
        )
      ]),
      el("section", { class: "panel" }, [
        el("h2", { text: "Платежи" }),
        renderRows(
          payments.items || [],
          (row) => `${row.sender_id} -> ${row.receiver_id}`,
          (row) => `${money(row.amount_kopecks)} · ${row.status}`,
          "Платежей пока нет."
        )
      ])
    );
  } catch (error) {
    viewRoot.append(el("section", { class: "panel empty", text: error.message }));
  }
}

function renderRows(rows, title, meta, emptyText) {
  const list = el("ul", { class: "list" });
  if (!rows.length) list.append(el("li", { class: "empty", text: emptyText }));
  rows.forEach((row) => list.append(el("li", { class: "list-row" }, [el("strong", { text: title(row) }), el("span", { class: "amount", text: meta(row) })])));
  return list;
}

function renderFriends() {
  viewRoot.append(header("Люди", "Видимые пользователи, друзья, invite preview и nearby accept."));
  const friendForm = el("form", { class: "panel form-grid two" }, [
    el("label", {}, ["User UUID", el("input", { name: "user_id", required: true })]),
    el("button", { class: "primary-button", text: "Отправить friend request" })
  ]);
  friendForm.addEventListener("submit", async (submit) => {
    submit.preventDefault();
    try {
      await api("/api/friends", {
        method: "POST",
        body: JSON.stringify({ user_id: new FormData(friendForm).get("user_id") })
      });
      showToast("Заявка отправлена.");
    } catch (error) {
      showToast(error.message);
    }
  });
  viewRoot.append(friendForm);
  loadFriendsPanel();
}

async function loadFriendsPanel() {
  try {
    const [users, friends] = await Promise.all([
      api(`/api/users?${qs({ limit: 50, offset: 0 })}`),
      api(`/api/friends?${qs({ limit: 50, offset: 0 })}`)
    ]);
    viewRoot.append(
      el("section", { class: "panel" }, [el("h2", { text: "Видимые пользователи" }), renderRows(users.items || [], (u) => u.name, (u) => u.public_handle || u.id, "Пользователей нет.")]),
      el("section", { class: "panel" }, [el("h2", { text: "Друзья" }), renderRows(friends.items || [], (f) => `${f.requester_id} -> ${f.addressee_id}`, (f) => f.status, "Друзей нет.")])
    );
  } catch (error) {
    viewRoot.append(el("section", { class: "panel empty", text: error.message }));
  }
}

function renderProfile() {
  viewRoot.append(header("Профиль", "Локальные токены, discovery и payment phone visibility."));
  const form = el("form", { class: "panel form-grid two" }, [
    el("label", {}, ["Имя", el("input", { name: "name", value: state.user?.name || "" })]),
    el("label", {}, ["Email", el("input", { name: "email", value: state.user?.email || "" })]),
    el("label", {}, ["Public handle", el("input", { name: "public_handle", value: state.user?.public_handle || "" })]),
    el("label", {}, ["Payment phone", el("input", { name: "payment_phone", value: state.user?.payment_phone || "" })]),
    el("label", {}, [
      "Payment phone visibility",
      el("select", { name: "payment_phone_visibility" }, [
        el("option", { value: "nobody", text: "Никому" }),
        el("option", { value: "friends", text: "Друзьям" }),
        el("option", { value: "event_members", text: "Участникам событий" })
      ])
    ]),
    el("button", { class: "primary-button", text: "Сохранить" })
  ]);
  form.addEventListener("submit", async (submit) => {
    submit.preventDefault();
    try {
      const data = Object.fromEntries(new FormData(form).entries());
      state.user = await api("/api/users/me", { method: "PATCH", body: JSON.stringify(data) });
      showToast("Профиль обновлен.");
    } catch (error) {
      showToast(error.message);
    }
  });
  viewRoot.append(form);
}

function renderSplitik() {
  viewRoot.append(header("Сплитик", "Контекстный ассистент с draft/confirm-flow."));
  const panel = el("section", { class: "panel" });
  const log = el("div", { class: "splitik-log" });
  const form = el("form", { class: "form-grid" }, [
    el("label", {}, [
      "Режим",
      el("select", { name: "mode" }, [
        el("option", { value: "general", text: "general" }),
        el("option", { value: "event", text: "event" }),
        el("option", { value: "receipt", text: "receipt" }),
        el("option", { value: "member", text: "member" })
      ])
    ]),
    el("label", {}, ["Сообщение", el("textarea", { name: "message", required: true, placeholder: "Создай событие Завтрак с наставниками" })]),
    el("button", { class: "secondary-button", text: "Отправить Сплитику" })
  ]);
  form.addEventListener("submit", async (submit) => {
    submit.preventDefault();
    const data = new FormData(form);
    const mode = data.get("mode");
    const entry = { type: mode };
    if (state.selectedEventId && mode === "event") entry.event_id = state.selectedEventId;
    const userMessage = data.get("message");
    log.append(el("div", { class: "message user", text: userMessage }));
    try {
      const response = await api("/api/splitik/messages", {
        method: "POST",
        body: JSON.stringify({
          session_id: state.splitikSessionId,
          mode,
          message: userMessage,
          entry_point: entry,
          locale: "ru-RU",
          timezone: "Europe/Moscow"
        })
      });
      state.splitikSessionId = response.session_id;
      log.append(el("div", { class: "message assistant", text: response.assistant_message }));
      if (response.context_chips?.length) {
        log.append(el("div", { class: "chips" }, response.context_chips.map((chip) => el("span", { class: "chip", text: `${chip.label}: ${chip.value}` }))));
      }
      for (const draft of response.drafts || []) log.append(renderDraft(draft));
      form.reset();
    } catch (error) {
      log.append(el("div", { class: "message assistant", text: error.message }));
    }
  });
  panel.append(log, form);
  viewRoot.append(panel);
}

function renderDraft(draft) {
  return el("div", { class: "card" }, [
    el("span", { class: "eyebrow", text: `Draft: ${draft.type}` }),
    el("pre", { text: JSON.stringify(draft.payload, null, 2) }),
    el("button", {
      class: "primary-button",
      text: "Подтвердить draft",
      onclick: async () => {
        try {
          await api(`/api/splitik/drafts/${draft.id}/commit`, { method: "POST" });
          await loadEvents();
          renderSplitik();
          showToast("Draft подтвержден через backend.");
        } catch (error) {
          showToast(error.message);
        }
      }
    })
  ]);
}

bootstrap();
