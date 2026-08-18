/*
 * Service worker for the installed app.
 *
 * Chrome will not offer "Install app" without one, which is the only reason
 * this exists. It is deliberately the most conservative worker that satisfies
 * that: it caches the immutable build assets and nothing else.
 *
 * What it must never do, and why:
 *
 *  - Never cache /api/*. Those responses are one family member's private
 *    library, served against a session cookie. A cached copy could be handed
 *    to the next person to sign in on the same device, and stale achievement
 *    data is worse than no data. API requests are not intercepted at all.
 *  - Never cache index.html. Serving a stale shell after a deploy pairs an
 *    old app with new assets whose hashed names it does not know about.
 *
 * That leaves genuine offline support out of scope: open the app with no
 * connection and you get the browser's offline page, same as before. The
 * win here is the install — a home-screen icon, no browser chrome, its own
 * task-switcher entry — not offline reads.
 */

// Bump when the caching rules below change, so old caches are dropped.
const CACHE = "achievist-assets-v1";

self.addEventListener("install", (event) => {
  // Take over promptly rather than waiting for every tab to close.
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n)));
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  // Vite emits content-hashed filenames under /assets, so a hit is always
  // the right bytes for that URL and a new build produces new URLs.
  if (!url.pathname.startsWith("/assets/")) return;

  event.respondWith(
    (async () => {
      const cached = await caches.match(req);
      if (cached) return cached;
      const res = await fetch(req);
      if (res.ok) {
        const cache = await caches.open(CACHE);
        cache.put(req, res.clone());
      }
      return res;
    })(),
  );
});
