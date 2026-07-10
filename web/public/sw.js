const CACHE_NAME = "splitapp-next-pwa-v38";
const APP_SHELL = [
  "/",
  "/app",
  "/manifest.webmanifest",
  "/assets/icon.svg",
  "/assets/icon-192.png",
  "/assets/icon-512.png",
  "/assets/apple-touch-icon.png",
  "/assets/app-preview.svg",
  "/assets/figma-home/down.png",
  "/assets/figma-home/nav-add.png",
  "/assets/figma-home/nav-events.png",
  "/assets/figma-home/nav-friends.png",
  "/assets/figma-home/nav-home.png",
  "/assets/figma-home/nav-profile.png",
  "/assets/figma-home/quick-add.png",
  "/assets/figma-home/quick-inbox.png",
  "/assets/figma-home/quick-scan.svg",
  "/assets/figma-home/up.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/api/")) {
    return;
  }

  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put("/app", copy));
          return response;
        })
        .catch(() => caches.match("/app").then((response) => response || caches.match("/")))
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        if (event.request.method === "GET" && response.ok) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        }
        return response;
      });
    })
  );
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = { body: event.data?.text() };
  }

  const title = payload.title || "SplitApp";
  const options = {
    body: payload.body || "Есть новое действие в SplitApp.",
    icon: "/assets/icon-192.png",
    badge: "/assets/apple-touch-icon.png",
    data: {
      url: payload.url || "/app"
    }
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = event.notification.data?.url || "/app";

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ("focus" in client) {
          client.navigate?.(targetUrl);
          return client.focus();
        }
      }
      return self.clients.openWindow(targetUrl);
    })
  );
});
