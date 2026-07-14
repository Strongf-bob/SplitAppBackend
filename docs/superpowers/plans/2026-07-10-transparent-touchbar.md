# Transparent Touchbar Implementation Plan

> Historical plan. The PWA surface was retired on 2026-07-14; do not implement this plan.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the PWA's Liquid Glass bottom navigation with the approved lightweight transparent rail while preserving navigation behavior and the Splitik artwork.

**Architecture:** The existing `PhoneShell` and `BottomNavButton` remain the navigation boundary. `navItems` becomes a discriminated presentation model: four regular tabs render an OS emoji and the Splitik tab continues to render its PNG. CSS owns a single blurred rail and a non-blurred active state; no API or view-state logic changes.

**Tech Stack:** Next.js, React, TypeScript, Tailwind utility classes, global CSS, Node built-in test runner.

## Global Constraints

- Keep the five existing views and their order: home, people, splitik, events, profile.
- Keep `nav-add.png` as the central Splitik icon; use system Unicode emoji for all other tabs.
- Keep iOS safe-area placement and 44 px-or-larger touch targets.
- Use a maximum of one `backdrop-filter` layer in the navigation component.
- Do not introduce new packages, API changes, or animation that causes layout work.
- Bump the service-worker cache version when the installed shell changes.

---

### Task 1: Specify the new PWA navigation contract

**Files:**
- Modify: `web/tests/pwa-ui-contract.test.mjs:127-139,208-219`

**Interfaces:**
- Consumes: `PhoneShell`, `BottomNavButton`, `navItems`, `web/src/app/globals.css`.
- Produces: assertions that define the transparent rail, emoji tabs, retained Splitik artwork, safe-area fallback, and removal of Liquid Glass layers.

- [ ] **Step 1: Write the failing test**

Replace the Liquid Glass expectations with a test named `bottom navigation uses a lightweight transparent rail with system emoji`, asserting:

```js
assert.match(page, /data-platform-nav="transparent-tab-bar"/);
assert.match(globals, /\.transparent-tabbar \{/);
assert.match(globals, /backdrop-filter: blur\(16px\)/);
assert.doesNotMatch(globals, /mix-blend-mode: screen/);
assert.doesNotMatch(globals, /\.transparent-tabbar::after/);
assert.match(page, /emoji: "🏠"/);
assert.match(page, /emoji: "👥"/);
assert.match(page, /emoji: "🗓️"/);
assert.match(page, /emoji: "👤"/);
assert.match(page, /figmaHomeAsset\("nav-add\.png"\)/);
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `node --test tests/pwa-ui-contract.test.mjs --test-name-pattern='bottom navigation uses a lightweight transparent rail with system emoji'`

Expected: FAIL because current page and CSS still use `liquid-tabbar` and PNG items.

- [ ] **Step 3: Add the safe fallback assertion**

In the iOS tab bar test, require `data-platform-nav="transparent-tab-bar"`, retain the existing safe-area placement assertion, and assert the fallback selector `.transparent-tabbar` has a background declaration under `@supports not`.

- [ ] **Step 4: Run the focused test again**

Run: `node --test tests/pwa-ui-contract.test.mjs --test-name-pattern='bottom navigation uses a lightweight transparent rail with system emoji|iOS mobile shell uses a safe-area transparent tab bar'`

Expected: FAIL only because the production implementation is not changed yet.

### Task 2: Implement the transparent rail and semantic emoji model

**Files:**
- Modify: `web/src/app/page.tsx:118-124,1327-1378`
- Modify: `web/src/app/globals.css:85-193`

**Interfaces:**
- Consumes: test assertions from Task 1 and existing `onNavigate(item.id)` behavior.
- Produces: `navItems` with `emoji` for standard tabs and `image` only for Splitik; `transparent-tabbar` CSS classes.

- [ ] **Step 1: Replace the nav item presentation model**

Use the exact model shape below and preserve the existing five ids and labels:

```ts
type BottomNavItem =
  | { id: Exclude<View, "splitik">; label: string; emoji: string }
  | { id: "splitik"; label: string; image: string; width: number; height: number; center: true };
```

Use `🏠`, `👥`, `🗓️`, and `👤` for home, people, events, and profile respectively. Keep the existing `figmaHomeAsset("nav-add.png")` record for Splitik.

- [ ] **Step 2: Render presentation type accessibly**

Render a span with `aria-hidden="true"` and an `emoji-tabbar__symbol` class for emoji items. Render `<Image>` only when `"image" in item`. Keep a visible label for regular tabs; keep the existing screen-reader-only Splitik label.

- [ ] **Step 3: Replace visual CSS with the single-filter rail**

Replace all `.liquid-tabbar*` rules with `.transparent-tabbar*` rules that have one `backdrop-filter: blur(16px)`, a translucent white background, one border and one exterior shadow. The active item may have a translucent background and border, but must not define `backdrop-filter`, pseudo-element highlights, `mix-blend-mode`, grain, or radial gradients.

- [ ] **Step 4: Preserve responsive interaction behavior**

Keep the existing `h-[58px]`, `active:scale-[0.97]`, safe-area placement and `prefers-reduced-motion` behavior. Do not alter the click handler, `href`, `aria-current`, `view`, or `onNavigate` code.

- [ ] **Step 5: Run contract tests to verify green**

Run: `node --test tests/*.test.mjs`

Expected: all PWA contract tests pass.

### Task 3: Refresh the installed PWA shell and validate quality gates

**Files:**
- Modify: `web/public/sw.js:1-20`

**Interfaces:**
- Consumes: changed PWA shell assets.
- Produces: a new cache identifier so installed clients receive the new navigation assets and styles.

- [ ] **Step 1: Bump the service-worker cache version once**

Increment only the `splitapp-next-pwa-vNN` cache identifier; retain the asset list and authenticated-response exclusions.

- [ ] **Step 2: Run type and production build checks**

Run: `npm run typecheck && npm run build`

Expected: both commands exit 0.

- [ ] **Step 3: Run repository quality gates**

Run: `make test && make lint && make format-check`

Expected: tests, lint, and formatting exit 0.

- [ ] **Step 4: Manually inspect the built UI locally**

Run: `npm run dev` and open the local app. Confirm the rail is readable over blue and white screens; activate each of five tabs; confirm no horizontal overflow or movement delay.

- [ ] **Step 5: Commit the implementation**

```bash
git add web/src/app/page.tsx web/src/app/globals.css web/tests/pwa-ui-contract.test.mjs web/public/sw.js docs/superpowers/plans/2026-07-10-transparent-touchbar.md
git commit -m "feat(pwa): simplify transparent touchbar"
```
