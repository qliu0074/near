/* Only public, allowlisted assets are persisted. API/HTML/RSC responses stay on the network. */
const CACHE = 'near-public-v2-en';
const OFFLINE = '/offline.html';
const PUBLIC_ASSETS = [OFFLINE, '/manifest.webmanifest', '/icons/icon-192.png', '/icons/icon-512.png',
  '/icons/icon-maskable.png', '/icons/apple-touch-icon.png'];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(PUBLIC_ASSETS)));
  // Let an existing app finish its work. Updates activate after its tabs close.
});
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) {
      if (name.startsWith('near-public-') && name !== CACHE) await caches.delete(name);
    }
    await self.clients.claim();
  })());
});
self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname === '/v1' || url.pathname.startsWith('/v1/')) {
    event.respondWith(fetch(request, {cache: 'no-store'}));
    return;
  }
  if (request.method !== 'GET') return;
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(async () => (await caches.match(OFFLINE)) || Response.error()));
    return;
  }
  const allowed = !url.search && (PUBLIC_ASSETS.includes(url.pathname) || url.pathname.startsWith('/_next/static/'));
  if (!allowed) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const cached = await cache.match(request);
    if (cached) return cached;
    const response = await fetch(request);
    if (response.ok && response.type === 'basic') {
      try {
        await cache.put(request, response.clone());
        const dynamic = (await cache.keys()).filter(key => !PUBLIC_ASSETS.includes(new URL(key.url).pathname));
        for (const key of dynamic.slice(0, Math.max(0, dynamic.length - 60))) await cache.delete(key);
      } catch { /* A full browser cache must not prevent online use. */ }
    }
    return response;
  })());
});
