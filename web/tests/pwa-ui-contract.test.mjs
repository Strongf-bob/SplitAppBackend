import { readFileSync } from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

const page = readFileSync(new URL("../src/app/page.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/lib/splitapp-api.ts", import.meta.url), "utf8");
const sw = readFileSync(new URL("../public/sw.js", import.meta.url), "utf8");

test("PWA implements the SVG screen set as navigable app views", () => {
  for (const view of ["home", "events", "people", "profile", "notifications", "splitik"]) {
    assert.match(page, new RegExp(`["']${view}["']`), `missing view: ${view}`);
  }

  for (const label of ["Главная", "Друзья", "События", "Входящие", "Профиль", "Сплитик"]) {
    assert.match(page, new RegExp(label), `missing navigation label: ${label}`);
  }
});

test("PWA exposes working mobile affordances from the SVG design", () => {
  for (const expected of [
    "event-tab",
    "notification-tab",
    "splitik-message-input",
    "aria-label=\"Назад\"",
    "aria-label=\"На главную\""
  ]) {
    assert.match(page, new RegExp(expected), `missing affordance: ${expected}`);
  }
});

test("service worker cache version is bumped for the redesigned shell", () => {
  assert.match(sw, /splitapp-next-pwa-v12/);
});

test("local preview does not send Yandex OAuth to an unregistered loopback callback", () => {
  assert.match(api, /const productionYandexRedirectUri = "https:\/\/split-app\.ru\/app"/);
  assert.doesNotMatch(api, /\$\{window\.location\.origin\}\/app/);
});

test("auth screen leads with app preview before external OAuth", () => {
  assert.match(page, /Войти через Яндекс/);
  assert.doesNotMatch(page, /Покрутить приложение/);
  assert.doesNotMatch(page, /Яндекс доступен только на зарегистрированном домене/);
});

test("real mobile app shell does not draw a fake phone around the app", () => {
  for (const fakeDeviceMarker of ["9:41", "Wi-Fi", "rounded-[38px]", "max-w-[430px]", "iPhone: Share"]) {
    assert.doesNotMatch(page, new RegExp(fakeDeviceMarker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
});

test("Yandex callback posts the backend login schema", () => {
  assert.match(api, /body: JSON\.stringify\(\{ yandex_token: accessToken \}\)/);
  assert.doesNotMatch(api, /provider: "yandex"/);
  assert.doesNotMatch(api, /\{\s*token: accessToken\s*\}/);
});

test("authenticated app uses real backend actions instead of static cards", () => {
  for (const endpoint of [
    "/api/events",
    "/api/events/${event.id}/receipts",
    "/api/splitik/messages"
  ]) {
    assert.match(page, new RegExp(endpoint.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `missing endpoint: ${endpoint}`);
  }

  assert.match(page, /createEvent/);
  assert.match(page, /selectedEventId/);
  assert.match(page, /friendSearch/);
  assert.doesNotMatch(page, /const answer = splitikAnswer/);
});

test("mobile shell keeps the real app surface full-height and gallery input mounted", () => {
  assert.match(page, /bg-\[#f5f5f7\]/);
  assert.match(page, /pb-\[calc\(120px\+env\(safe-area-inset-bottom\)\)\]/);
  assert.match(page, /galleryInputRef/);
  assert.doesNotMatch(page, /bg-\[#1e1e1e\]/);
});

test("toast messages are transient and not shown on initial load", () => {
  assert.match(page, /const \[message, setMessage\] = useState\(""\)/);
  assert.match(page, /setTimeout\(\(\) => setMessage\(""\), 3200\)/);
  assert.doesNotMatch(page, /useState\("Готов к работе"\)/);
});

test("profile screen shows the authenticated Yandex user instead of a hardcoded profile", () => {
  assert.match(page, /\/api\/users\/me/);
  assert.match(page, /currentUser/);
  assert.doesNotMatch(page, /ContentPanel title="Анна"/);
  assert.doesNotMatch(page, />A<\/div>/);
});

test("bottom navigation active tab stays readable with a liquid glass state", () => {
  assert.match(page, /backdrop-blur-\[22px\]/);
  assert.match(page, /bg-white\/72 text-\[#1f3d8f\]/);
  assert.doesNotMatch(page, /active && "bg-white\/22 text-white"/);
});

test("Splitik chat keeps backend error detail visible to diagnose LLM failures", () => {
  assert.match(api, /class ApiError extends Error/);
  assert.match(page, /splitikErrorMessage/);
  assert.doesNotMatch(page, /catch \{\n      setChatMessages/);
});

test("authenticated startup refreshes expired access tokens instead of showing a fake offline slice", () => {
  assert.match(api, /\/api\/refresh/);
  assert.match(api, /const nextTokens = \{ \.\.\.tokens, \.\.\.refreshedTokens \}/);
  assert.match(api, /saveTokens\(nextTokens\)/);
  assert.match(page, /handleInitialDataError/);
  assert.match(page, /Сессия истекла\. Войдите через Яндекс еще раз\./);
  assert.doesNotMatch(page, /Backend недоступен, показан локальный срез PWA\./);
});

test("Splitik assistant replies render safe Markdown instead of a flattened text blob", () => {
  assert.match(page, /function MarkdownMessage/);
  assert.match(page, /parseMarkdownMessage/);
  assert.match(page, /<MarkdownMessage text=\{item\.text\} \/>/);
  assert.doesNotMatch(page, /\{item\.text\}\s*<\/div>/);
});

test("Splitik requests do not send demo event ids as UUID event context", () => {
  assert.match(page, /const splitikEventId = isUuid\(selectedEventId\) \? selectedEventId : null/);
  assert.match(page, /mode: splitikEventId \? "event" : "general"/);
  assert.match(page, /entry_point: splitikEventId \? \{ type: "event", event_id: splitikEventId \} : undefined/);
});

test("API errors show FastAPI validation details instead of a bare HTTP 422", () => {
  assert.match(api, /formatValidationDetail/);
  assert.match(api, /Array\.isArray\(body\.detail\)/);
  assert.match(api, /detail\.loc/);
});

test("event creation surfaces backend errors instead of hiding the cause", () => {
  assert.match(page, /catch \(error\)/);
  assert.match(page, /error instanceof ApiError/);
  assert.match(page, /setMessage\(`Не удалось создать событие: \$\{error\.message\}`\)/);
});

test("event creation clears expired auth sessions when refresh fails", () => {
  assert.match(page, /if \(error instanceof ApiError && error\.status === 401\)/);
  assert.match(page, /clearTokens\(\)/);
  assert.match(page, /navigate\("home"\)/);
});

test("refreshed tokens update React state, not only localStorage", () => {
  assert.match(api, /onTokensRefreshed\?: \(tokens: SplitAppTokens\) => void/);
  assert.match(api, /onTokensRefreshed\?\.\(nextTokens\)/);
  assert.match(page, /const authedApi = useCallback/);
  assert.match(page, /setTokens\(nextTokens\)/);
  assert.match(page, /api<T>\(path, tokens, init, \(nextTokens\) =>/);
});

test("Splitik composer is fixed above the bottom nav and keyboard viewport", () => {
  assert.match(page, /data-testid="splitik-composer"/);
  assert.match(page, /fixed inset-x-4 bottom-\[calc\(86px\+env\(safe-area-inset-bottom\)\)\]/);
  assert.match(page, /pb-\[112px\]/);
  assert.match(page, /max-w-\[calc\(100vw-2rem\)\]/);
});

test("event cards navigate into a detail screen instead of expanding with plus icons", () => {
  assert.match(page, /function EventDetailScreen/);
  assert.match(page, /data-testid="event-detail-screen"/);
  assert.match(page, /selectedEvent \? \(/);
  assert.doesNotMatch(page, /selectedEventId === event\.id \? "−" : "\+"/);
});

test("event detail exposes invite code, participants, receipts and add actions", () => {
  for (const expected of ["Код события", "Добавить друзей", "Добавить чек", "Участники", "Чеки"]) {
    assert.match(page, new RegExp(expected), `missing event detail copy: ${expected}`);
  }
  assert.match(page, /createEventInvite/);
  assert.match(page, /startReceiptFromEvent/);
  assert.match(page, /setChatDraft\(`Добавь чек в событие/);
  assert.match(page, /navigate\("splitik"\)/);
  assert.match(page, /\/api\/events\/\$\{event\.id\}\/invites/);
  assert.match(page, /Чеков пока нет/);
  assert.doesNotMatch(page, /Загружаем чеки\.\.\.<\/p>/);
});

test("event invite codes are displayed as compact six-character codes", () => {
  assert.match(page, /function eventInviteDisplayCode/);
  assert.match(page, /\.slice\(0, 6\)\.padEnd\(6, "0"\)/);
  assert.match(page, /const inviteCode = eventInviteDisplayCode\(/);
  assert.doesNotMatch(page, /inviteCode = invite\?\.token \?\? event\.token \?\? demoInviteCode/);
});

test("event creation adds every selected friend as a participant", () => {
  assert.match(api, /export type Friendship/);
  assert.match(page, /const \[friendships, setFriendships\] = useState<Friendship\[\]>/);
  assert.match(page, /const \[selectedEventFriendIds, setSelectedEventFriendIds\] = useState<string\[\]>/);
  assert.match(page, /authedApi<FriendshipPage>\("\/api\/friends\?status=accepted&limit=50"\)/);
  assert.match(page, /const selectedUserIds = selectedEventFriendIds;/);
  assert.match(page, /`\/api\/events\/\$\{created\.id\}\/participants`/);
  assert.match(page, /body: JSON\.stringify\(\{ user_ids: selectedUserIds \}\)/);
  assert.match(page, /eventParticipants\(event, friendOptions\)\.map/);
  assert.doesNotMatch(page, /friends\.slice\(0, Math\.max\(1, Math\.min\(participantCount, friends\.length\)\)\)\.map/);
});

test("home add action opens a dedicated event creation screen", () => {
  assert.match(page, /function EventCreateScreen/);
  assert.match(page, /data-testid="event-create-screen"/);
  assert.match(page, /Создание события/);
  assert.match(page, /Добавить участников/);
  assert.match(page, /onCreateEventOpen/);
});

test("friends screen exposes add-by-code affordance", () => {
  assert.match(page, /Добавить друга по коду/);
  assert.match(page, /friend-code-input/);
  assert.match(page, /Мой код/);
});
