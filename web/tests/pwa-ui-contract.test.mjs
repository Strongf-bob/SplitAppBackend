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
  assert.match(sw, /splitapp-next-pwa-v2/);
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
