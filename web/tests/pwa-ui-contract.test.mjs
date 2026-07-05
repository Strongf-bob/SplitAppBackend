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
  assert.match(sw, /splitapp-next-pwa-v4/);
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
