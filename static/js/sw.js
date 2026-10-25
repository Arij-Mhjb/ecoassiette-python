/* Service worker EcoAssiette (application installable).
   - Fichiers statiques (CSS, JS, police, icônes) : servis depuis le cache, mis à jour en arrière-plan.
   - Pages : toujours le réseau (données personnelles jamais mises en cache) ; hors ligne -> page « hors ligne ».
   - Requêtes POST / API / admin : jamais interceptées. */
const VERSION = "ecoassiette-v1";
const PRECACHE = ["/hors-ligne/", "/static/css/style.css", "/static/js/app.js", "/static/img/logo.svg",
  "/static/fonts/plus-jakarta-sans-latin-wght-normal.woff2", "/static/img/pwa/icone-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((cles) => Promise.all(cles.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/static/")) {                 // stale-while-revalidate
    e.respondWith(caches.open(VERSION).then(async (c) => {
      const enCache = await c.match(req);
      const reseau = fetch(req).then((r) => { if (r.ok) c.put(req, r.clone()); return r; }).catch(() => enCache);
      return enCache || reseau;
    }));
    return;
  }
  if (req.mode === "navigate") {                            // pages : réseau d'abord, page hors ligne sinon
    e.respondWith(fetch(req).catch(() => caches.match("/hors-ligne/")));
  }
});
