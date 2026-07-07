import { readFileSync } from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

const page = readFileSync(new URL("../src/app/page.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/lib/splitapp-api.ts", import.meta.url), "utf8");
const sw = readFileSync(new URL("../public/sw.js", import.meta.url), "utf8");
const globals = readFileSync(new URL("../src/app/globals.css", import.meta.url), "utf8");

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
  assert.match(sw, /splitapp-next-pwa-v15/);
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

test("auth screen does not draw a fake iPhone notch or Dynamic Island", () => {
  for (const fakeNotchMarker of ["Dynamic Island", "device-notch", "fake-notch", "notch", "aria-label=\"Dynamic Island\""]) {
    assert.doesNotMatch(page, new RegExp(fakeNotchMarker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"));
  }

  assert.doesNotMatch(page, /fixed\s+top-\d+\s+left-1\/2[^"]*rounded-full[^"]*(?:bg-black|bg-\[#000)/);
  assert.doesNotMatch(page, /absolute\s+top-\d+\s+left-1\/2[^"]*rounded-full[^"]*(?:bg-black|bg-\[#000)/);
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
  assert.match(page, /pb-\[var\(--bottom-nav-reserve\)\]/);
  assert.match(globals, /--bottom-nav-reserve:\s*calc\(104px \+ env\(safe-area-inset-bottom\)\)/);
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

test("PWA surfaces are built on shadcn primitives instead of one-off controls", () => {
  for (const primitive of [
    /import \{ Button \} from "@\/components\/ui\/button"/,
    /import \{ Card,\s*CardContent,\s*CardHeader,\s*CardTitle \} from "@\/components\/ui\/card"/,
    /import \{ Input \} from "@\/components\/ui\/input"/
  ]) {
    assert.match(page, primitive);
  }

  assert.match(page, /<Button[^>]+onClick=\{onLogin\}/);
  assert.match(page, /<Card[^>]+data-slot="content-panel"/);
  assert.match(page, /<Input[^>]+data-testid="friend-code-input"/);
});

test("iOS mobile shell uses a safe-area glass tab bar instead of a generic nav slab", () => {
  assert.match(page, /data-platform-nav="ios-tab-bar"/);
  assert.match(page, /supports-\[backdrop-filter\]:bg-white\/62/);
  assert.match(page, /pb-\[max\(env\(safe-area-inset-bottom\),12px\)\]/);
  assert.doesNotMatch(page, /rounded-t-\[26px\]/);
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

test("authenticated startup tolerates malformed page payloads without crashing the route", () => {
  assert.match(page, /function pageItems<T>\(page: \{ items\?: T\[\] \} \| null \| undefined\)/);
  assert.match(page, /const nextEvents = pageItems\(eventPage\)\.map\(normalizeEvent\)/);
  assert.match(page, /setEvents\(nextEvents\.length \? nextEvents : fallbackEvents\)/);
  assert.match(page, /setFriendships\(pageItems\(friendshipPage\)\)/);
  assert.doesNotMatch(page, /eventPage\.items\.length/);
  assert.doesNotMatch(page, /friendshipPage\.items \?\? \[\]/);
});

test("client error reports include a sanitized error message for production diagnosis", () => {
  assert.match(page, /error_message: error instanceof Error \? error\.message : String\(error \?\? "unknown"\)/);
  assert.match(api, /"error_message"/);
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
  assert.match(page, /notifyProblem\(error, "events", "Не удалось создать событие\.", \{ action: "create_event", component: "EventCreateScreen" \}\)/);
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

test("mobile layout scales from compact phones with adaptive tokens instead of fixed SVG dimensions", () => {
  for (const token of [
    "--page-x: clamp(",
    "--balance-font: clamp(",
    "--action-icon-size: clamp(",
    "--activity-avatar-size: clamp(",
    "--bottom-nav-reserve:"
  ]) {
    assert.match(globals, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `missing adaptive token: ${token}`);
  }

  assert.match(globals, /-webkit-text-size-adjust:\s*100%/);
  assert.match(globals, /overflow-x:\s*hidden/);
  assert.match(page, /style=\{\{ fontSize: "var\(--balance-font\)" \}\}/);
  assert.match(page, /grid-cols-\[repeat\(3,minmax\(0,1fr\)\)\]/);
  assert.match(page, /style=\{\{ width: "var\(--action-icon-size\)", height: "var\(--action-icon-size\)" \}\}/);
  assert.doesNotMatch(page, /text-\[72px\]/);
  assert.doesNotMatch(page, /h-28 w-28/);
  assert.doesNotMatch(page, /grid-cols-\[92px_1fr_auto\]/);
});

test("Splitik chat uses a messenger-style bottom anchored message list", () => {
  assert.match(page, /data-testid="splitik-chat-shell"/);
  assert.match(page, /data-testid="splitik-message-list"/);
  assert.match(page, /flex min-h-0 flex-1 flex-col justify-end gap-3 overflow-y-auto/);
  assert.doesNotMatch(page, /grid min-h-\[690px\] gap-3 pb-\[112px\]/);
  assert.doesNotMatch(page, /grid content-end gap-3 overflow-hidden rounded-2xl bg-white p-3/);
});

test("event cards navigate into a detail screen instead of expanding with plus icons", () => {
  assert.match(page, /function EventDetailScreen/);
  assert.match(page, /testId="event-detail-screen"/);
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

test("event invite codes are stable six-digit event codes", () => {
  assert.match(page, /function eventInviteDisplayCode/);
  assert.match(page, /return String\(numericCode\)\.padStart\(6, "0"\)/);
  assert.match(page, /const inviteCode = eventInviteDisplayCode\(event\.id\)/);
  assert.doesNotMatch(page, /inviteCode = invite\?\.token \?\? event\.token \?\? demoInviteCode/);
  assert.doesNotMatch(page, /Создать \/ обновить код/);
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
  assert.match(page, /testId="event-create-screen"/);
  assert.match(page, /Создание события/);
  assert.match(page, /Добавить участников/);
  assert.match(page, /onCreateEventOpen/);
});

test("home screen follows the Figma balance card and activity sheet composition", () => {
  assert.match(page, /data-testid="home-balance-screen"/);
  assert.match(page, /w-full overflow-hidden/);
  assert.match(page, /fontSize: "var\(--balance-font\)"/);
  assert.match(page, /ArrowUp/);
  assert.match(page, /ArrowDown/);
  assert.match(page, /data-testid="home-event-card"/);
  assert.match(page, /function AvatarStack/);
  assert.match(page, /Сканировать чек/);
  assert.match(page, /Добавить платеж/);
  assert.match(page, /rounded-t-\[28px\]/);
  assert.doesNotMatch(page, /Синхрониз\./);
});

test("home shell covers the viewport instead of exposing the dark page background", () => {
  assert.match(globals, /--background:\s*240 11% 96%/);
  assert.match(page, /<main className="min-h-dvh w-full overflow-x-hidden bg-\[#f5f5f7\]/);
  assert.match(page, /<div className="min-h-dvh w-full overflow-x-hidden bg-\[#f5f5f7\]">/);
  assert.match(page, /className="min-h-\[calc\(100dvh-74px\)\] w-full overflow-hidden/);
});

test("home inbox action badge is conditional on unread incoming items", () => {
  assert.match(page, /function QuickAction\(\{\s*icon: Icon,\s*label,\s*onClick,\s*showBadge = false\s*\}/);
  assert.match(page, /showBadge \? <span className="absolute right-5 top-5 h-4 w-4 rounded-full bg-red-500" \/> : null/);
  assert.doesNotMatch(page, /label === "Входящие" \?/);
});

test("friends screen exposes add-by-code affordance", () => {
  assert.match(page, /Добавить друга по коду/);
  assert.match(page, /friend-code-input/);
  assert.match(page, /Мой код/);
  assert.match(page, /onShowFriendCode/);
  assert.match(page, /onAddFriendByCode/);
  assert.match(page, /\/api\/users\/search\?q=/);
  assert.match(page, /\/api\/friends/);
  assert.match(page, /\/api\/users\/me/);
});

test("friends screen owns its title without duplicating the global app header", () => {
  assert.match(page, /showHeader=\{view === "home"\}/);
  assert.match(page, /showHeader: boolean/);
  assert.match(page, /showHeader && loggedIn \? \(/);
  assert.match(page, /testId="friends-screen"[\s\S]*title="Друзья"/);
});

test("SVG auth screen is a clean first screen before Yandex OAuth", () => {
  assert.match(page, /data-testid="svg-auth-screen"/);
  assert.match(page, /grid min-h-dvh bg-\[#1f3d8f\]/);
  assert.match(page, /text-\[clamp\(4rem,20vw,5\.5rem\)\]/);
  assert.match(page, /Делите счета поровну/);
  assert.match(page, /Войти через Яндекс/);
  assert.doesNotMatch(page, /Войдите, чтобы открыть события/);
});

test("shared SVG app screens use a blue header with a white bottom sheet", () => {
  assert.match(page, /function SvgScreenFrame/);
  for (const testId of [
    "friends-screen",
    "events-screen",
    "notifications-screen",
    "profile-screen",
    "splitik-screen"
  ]) {
    assert.match(page, new RegExp(`testId="${testId}"`), `missing ${testId}`);
  }
  assert.match(page, /data-testid="svg-screen-sheet"/);
  assert.match(page, /rounded-t-\[28px\]/);
});

test("friends add-by-code is a compact expandable control, not an always-open form", () => {
  assert.match(page, /const \[isFriendCodeOpen, setIsFriendCodeOpen\] = useState\(false\)/);
  assert.match(page, /data-testid="friend-code-toggle"/);
  assert.match(page, /data-testid="friend-code-panel"/);
  assert.match(page, /isFriendCodeOpen \? \(/);
});

test("Splitik keeps the SVG intro card while anchoring conversation to the composer", () => {
  assert.match(page, /data-testid="splitik-intro-card"/);
  assert.match(page, /flex min-h-0 flex-1 flex-col justify-end/);
  assert.match(page, /fixed inset-x-4 bottom-\[calc\(86px\+env\(safe-area-inset-bottom\)\)\]/);
});

test("Splitik failures are reported silently and shown inline instead of blocking the chat", () => {
  assert.match(page, /void reportProblem\(\{\s*screen: "splitik"/);
  assert.match(page, /setMessage\("Сплитик сейчас не смог ответить\. Попробуйте еще раз чуть позже\."\)/);
  assert.doesNotMatch(page, /notifyProblem\(error, "splitik"/);
});
