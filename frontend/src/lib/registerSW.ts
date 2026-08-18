/**
 * Registers the service worker that makes the app installable.
 *
 * Only in a production build: in dev the worker would sit in front of Vite's
 * module graph and serve stale code, which is a miserable way to lose an
 * afternoon. `import.meta.env.DEV` is compile-time, so this whole branch is
 * dropped from the bundle.
 *
 * Service workers require a secure context. Browsers count localhost as
 * secure, but a self-hosted install reached over plain http:// on a LAN
 * address is not — there registration simply does nothing and the app works
 * as it always has, minus the install prompt.
 */
export function registerServiceWorker(): void {
  if (import.meta.env.DEV) return;
  if (!("serviceWorker" in navigator)) return;

  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // Not being installable is not worth an error in anyone's console.
    });
  });
}
