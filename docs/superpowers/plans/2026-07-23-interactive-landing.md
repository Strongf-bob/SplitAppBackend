# SplitApp Interactive Landing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current public page with the approved accessible Windows 95-inspired SplitApp product landing and deploy it to `https://split-app.ru`.

**Architecture:** Keep the existing FastAPI static-file delivery model. Build the page from semantic HTML, one token-driven stylesheet, one dependency-free progressive-enhancement script, and local optimized assets derived from the supplied design exports.

**Tech Stack:** HTML5, CSS, vanilla JavaScript, FastAPI `StaticFiles`, pytest, Playwright browser validation.

## Global Constraints

- Pixel typography is limited to the logo, window titles, large display accents, and buttons.
- Montserrat is the primary body, navigation, and caption family.
- The production domain is exactly `https://split-app.ru`.
- Telegram is exactly `https://t.me/nicto999`.
- Email is exactly `mailto:karsakovillya@yandex.ru`.
- GitHub profile is exactly `https://github.com/Strongf-bob`.
- Footer copy is exactly `© 2026 SplitApp`.
- AI copy must describe draft-first behavior with backend validation and explicit user confirmation.
- The page must remain understandable and navigable when JavaScript is unavailable.
- Reduced-motion users receive no reveal or continuous decorative animation.

---

## File Map

- `app/static/landing/index.html`: semantic content, navigation, sections, links, and SEO.
- `app/static/landing/assets/landing.css`: design tokens, window system, responsive layout, focus, and reduced-motion behavior.
- `app/static/landing/assets/landing.js`: mobile navigation, demo tabs, and intersection reveal enhancement.
- `app/static/landing/assets/splitapp-bot.webp`: optimized mascot derived from the supplied design.
- `app/static/landing/assets/app-showcase.webp`: optimized interface composition derived from the presentation.
- `app/static/landing/assets/agent-flow.webp`: optimized agent scheme derived from the presentation.
- `app/static/landing/assets/team.webp`: optimized team artwork derived from the supplied design.
- `app/static/landing/assets/fonts/montserrat-cyrillic.woff2`: local Montserrat subset for body text.
- `app/static/landing/assets/fonts/press-start-2p-cyrillic.woff2`: local pixel display font.
- `app/static/landing/assets/fonts/OFL.txt`: Open Font License for both bundled families.
- `tests/test_app_config.py`: server/static asset and landing-content regression contracts.

### Task 1: Lock the public landing contract

**Files:**
- Modify: `tests/test_app_config.py`

**Interfaces:**
- Consumes: `app.main.configure_landing_site(api: FastAPI) -> None`.
- Produces: regression coverage for the HTML, CSS, JavaScript, assets, contacts, repository links, and truthful product copy.

- [ ] **Step 1: Add failing content and asset tests**

Extend `test_static_landing_is_public_and_retired_routes_are_absent` and add a
content test with these exact assertions:

```python
response = client.get("/")
assert response.status_code == 200
html = response.text
assert 'src="/assets/landing/landing.js"' in html
assert "ABOUT.EXE" in html
assert "SPLITIK.AI" in html
assert "STACK.SYS" in html
assert "DOCS.LNK" in html
assert "TEAM.EXE" in html
assert 'href="https://t.me/nicto999"' in html
assert 'href="mailto:karsakovillya@yandex.ru"' in html
assert 'href="https://github.com/Strongf-bob"' in html
assert "© 2026 SplitApp" in html
assert "hello@split-app.ru" not in html

for asset in (
    "landing.css",
    "landing.js",
    "splitapp-bot.webp",
    "app-showcase.webp",
    "agent-flow.webp",
    "team.webp",
    "fonts/montserrat-cyrillic.woff2",
    "fonts/press-start-2p-cyrillic.woff2",
    "fonts/OFL.txt",
):
    assert client.get(f"/assets/landing/{asset}").status_code == 200
```

- [ ] **Step 2: Run the focused test and confirm red**

Run:

```bash
'/Users/strongf/Developer/SplitApp Yandex/SplitAppBackend/.venv/bin/python' \
  -m pytest tests/test_app_config.py -k static_landing -q
```

Expected: failure because `landing.js`, the new assets, and new content do not exist.

- [ ] **Step 3: Commit the test contract**

```bash
git add tests/test_app_config.py
git commit -m "test(landing): define interactive page contract"
```

### Task 2: Prepare local design assets and semantic content

**Files:**
- Modify: `app/static/landing/index.html`
- Create: `app/static/landing/assets/splitapp-bot.webp`
- Create: `app/static/landing/assets/app-showcase.webp`
- Create: `app/static/landing/assets/agent-flow.webp`
- Create: `app/static/landing/assets/team.webp`
- Create: `app/static/landing/assets/fonts/montserrat-cyrillic.woff2`
- Create: `app/static/landing/assets/fonts/press-start-2p-cyrillic.woff2`
- Create: `app/static/landing/assets/fonts/OFL.txt`

**Interfaces:**
- Consumes: supplied SVG/PDF exports and the URL/copy constants in Global Constraints.
- Produces: stable local asset paths and semantic section IDs consumed by CSS and JavaScript.

- [ ] **Step 1: Render and optimize the supplied visuals**

Render the relevant source regions at 2x target resolution, crop whitespace,
and encode WebP with alpha where needed. Download the official Google Fonts
WOFF2 files once, store them locally, and include their OFL text. Verify dimensions:

```bash
sips -g pixelWidth -g pixelHeight \
  app/static/landing/assets/splitapp-bot.webp \
  app/static/landing/assets/app-showcase.webp \
  app/static/landing/assets/agent-flow.webp \
  app/static/landing/assets/team.webp
```

Expected: every file reports non-zero dimensions and no source exceeds 2400 px
on its long edge.

- [ ] **Step 2: Replace the page with semantic desktop windows**

The page must expose these stable anchors and window titles:

```html
<main id="main">
  <section id="about" class="desktop-window hero-window" aria-labelledby="about-title">
    <div class="window-titlebar"><span>ABOUT.EXE</span></div>
    <div class="window-body">...</div>
  </section>
  <section id="demo" class="desktop-window demo-window" aria-labelledby="demo-title">
    <div class="window-titlebar"><span>DEMO.MOV</span></div>
    <div class="window-body">...</div>
  </section>
  <section id="how-it-works" class="desktop-window" aria-labelledby="how-title">...</section>
  <section id="splitik" class="desktop-window" aria-labelledby="splitik-title">...</section>
  <section id="stack" class="desktop-window" aria-labelledby="stack-title">...</section>
  <section id="docs" class="desktop-window" aria-labelledby="docs-title">...</section>
  <section id="team" class="desktop-window" aria-labelledby="team-title">...</section>
</main>
```

Use native `<a>`, `<button>`, `<nav>`, `<ol>`, and `<article>` elements.
External links use `target="_blank" rel="noreferrer"`. The Telegram, email,
GitHub, repositories, and both wiki destinations must match Global Constraints.

- [ ] **Step 3: Run the focused content contract**

Run the Task 1 command.

Expected: asset/content assertions pass; CSS/JS behavior work remains.

- [ ] **Step 4: Commit the semantic page and assets**

```bash
git add app/static/landing/index.html app/static/landing/assets
git commit -m "feat(landing): add desktop product story"
```

### Task 3: Implement responsive styling and progressive interaction

**Files:**
- Modify: `app/static/landing/assets/landing.css`
- Create: `app/static/landing/assets/landing.js`

**Interfaces:**
- Consumes: `.desktop-window`, `.window-titlebar`, `[data-menu-toggle]`, `[data-demo-tab]`, and `[data-reveal]` from Task 2.
- Produces: responsive desktop-window layout, accessible navigation state, demo-tab state, and reveal state.

- [ ] **Step 1: Add the tokenized desktop-window system**

Define the shared tokens and component boundaries:

```css
:root {
  --color-desktop: #7bacde;
  --color-ink: #082746;
  --color-surface: #f4f4f4;
  --color-titlebar: #1329db;
  --color-titlebar-text: #ffffff;
  --color-accent: #1329db;
  --font-body: "Montserrat", Arial, sans-serif;
  --font-pixel: "Press Start 2P", "Courier New", monospace;
  --border-pixel: 4px solid var(--color-ink);
  --shadow-pixel: 10px 10px 0 rgba(8, 39, 70, 0.35);
  --content-width: 1180px;
}

.desktop-window {
  border: var(--border-pixel);
  background: var(--color-surface);
  box-shadow: var(--shadow-pixel);
}

.window-titlebar {
  min-height: 48px;
  background: var(--color-titlebar);
  color: var(--color-titlebar-text);
  font-family: var(--font-pixel);
}
```

Add 375/768/1024/1440-responsive behavior, 44 px controls, visible
`:focus-visible`, no horizontal overflow, and stable image aspect ratios.

- [ ] **Step 2: Add dependency-free progressive enhancement**

Implement the stable state contract:

```javascript
const menuToggle = document.querySelector("[data-menu-toggle]");
const menu = document.querySelector("[data-menu]");

menuToggle?.addEventListener("click", () => {
  const expanded = menuToggle.getAttribute("aria-expanded") === "true";
  menuToggle.setAttribute("aria-expanded", String(!expanded));
  menu?.toggleAttribute("data-open", !expanded);
});

document.querySelectorAll("[data-demo-tab]").forEach((tab) => {
  tab.addEventListener("click", () => {
    const target = tab.getAttribute("aria-controls");
    document.querySelectorAll("[data-demo-tab]").forEach((item) => {
      item.setAttribute("aria-selected", String(item === tab));
    });
    document.querySelectorAll("[data-demo-panel]").forEach((panel) => {
      panel.hidden = panel.id !== target;
    });
  });
});
```

Add an `IntersectionObserver` only when reduced motion is not requested.
The observer toggles `data-visible` and does not hide readable content when
JavaScript fails.

- [ ] **Step 3: Run focused and full automated tests**

Run:

```bash
'/Users/strongf/Developer/SplitApp Yandex/SplitAppBackend/.venv/bin/python' \
  -m pytest tests/test_app_config.py -k static_landing -q
'/Users/strongf/Developer/SplitApp Yandex/SplitAppBackend/.venv/bin/python' \
  -m pytest
```

Expected: focused tests pass; full suite reports 295 passed and 2 skipped or
more passing tests if the new assertions increase the count.

- [ ] **Step 4: Commit the responsive interaction layer**

```bash
git add app/static/landing/assets/landing.css app/static/landing/assets/landing.js
git commit -m "feat(landing): add responsive desktop interactions"
```

### Task 4: Browser QA, release, and production verification

**Files:**
- Modify only if QA uncovers a concrete landing defect.

**Interfaces:**
- Consumes: the complete static landing and FastAPI app.
- Produces: verified `main` and a confirmed production page at `https://split-app.ru`.

- [ ] **Step 1: Run repository gates**

```bash
'/Users/strongf/Developer/SplitApp Yandex/SplitAppBackend/.venv/bin/python' -m ruff check .
'/Users/strongf/Developer/SplitApp Yandex/SplitAppBackend/.venv/bin/python' -m ruff format --check .
'/Users/strongf/Developer/SplitApp Yandex/SplitAppBackend/.venv/bin/python' -m pytest
git diff --check origin/main...HEAD
```

Expected: all commands exit 0.

- [ ] **Step 2: Validate in a real browser**

Start Uvicorn on a dedicated local port and inspect 375, 768, 1024, and
1440 px widths. Verify:

```text
no horizontal overflow
all title bars and body text are legible
keyboard focus follows document order
mobile navigation updates aria-expanded
demo tabs update aria-selected and hidden
reduced motion removes reveal movement
all local assets return HTTP 200
Telegram/email/GitHub/Wiki href values are exact
```

- [ ] **Step 3: Push the verified branch to main**

```bash
git push origin HEAD:main
```

Expected: GitHub accepts the update or identifies the required protected-branch
PR path. If protected, push the feature branch, open a ready PR, wait for CI,
and merge it without bypassing checks.

- [ ] **Step 4: Verify deployment**

Poll the repository deployment workflow and then verify:

```bash
curl -fsS https://split-app.ru/ | grep -F "ABOUT.EXE"
curl -fsSI https://split-app.ru/assets/landing/landing.css
curl -fsSI https://split-app.ru/assets/landing/landing.js
curl -fsSI https://split-app.ru/assets/landing/app-showcase.webp
```

Expected: HTML contains `ABOUT.EXE`; every asset returns HTTP 200. Open the
production page at desktop and mobile widths and repeat the critical contact,
navigation, and interaction checks.
