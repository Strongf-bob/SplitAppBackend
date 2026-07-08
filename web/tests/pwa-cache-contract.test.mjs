import { readFileSync } from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

const pwaCache = readFileSync(new URL("../src/lib/pwa-cache.ts", import.meta.url), "utf8");
const serviceWorker = readFileSync(new URL("../public/sw.js", import.meta.url), "utf8");

test("PWA app snapshot cache is user scoped and versioned", () => {
  assert.match(pwaCache, /const snapshotPrefix = "splitapp\.pwaSnapshot\.v1"/);
  assert.match(pwaCache, /const snapshotKey = \(userId\?: string \| null\) => `\$\{snapshotPrefix\}:\$\{userId \|\| "anonymous"\}`/);
  assert.match(pwaCache, /version: 1/);
  assert.match(pwaCache, /updatedAt: Date\.now\(\)/);
});

test("PWA app snapshot cache bounds private client data", () => {
  assert.match(pwaCache, /events: snapshot\.events\.slice\(0, 50\)/);
  assert.match(pwaCache, /friendships: snapshot\.friendships\.slice\(0, 100\)/);
  assert.match(pwaCache, /chatMessages: snapshot\.chatMessages\.slice\(-40\)/);
  assert.match(pwaCache, /map\(\(\{ id, from, text \}\) => \(\{ id, from, text \}\)\)/);
});

test("service worker still avoids caching authenticated API responses", () => {
  assert.match(serviceWorker, /if \(url\.pathname\.startsWith\("\/api\/"\)\) \{\n    return;\n  \}/);
  assert.doesNotMatch(serviceWorker, /cache\.put\(event\.request, copy\)[\s\S]*\/api\//);
});
