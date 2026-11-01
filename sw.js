// Service worker: app shell = cache-first, content JSON = network-first, audio = cache-first.
const VERSION = 'v3';
const SHELL = `shell-${VERSION}`;
const CONTENT = 'content';
const AUDIO = 'audio';
const SHELL_FILES = [
  './', 'index.html', 'styles.css', 'app.js', 'manifest.webmanifest',
  'icons/icon-192.png', 'icons/icon-512.png', 'icons/apple-touch-icon.png',
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(SHELL_FILES)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith('shell-') && key !== SHELL) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

async function networkFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(req, { cache: 'no-cache' });
    if (res.ok) cache.put(req, res.clone());
    return res;
  } catch {
    const hit = await cache.match(req, { ignoreSearch: true });
    if (hit) return hit;
    throw new Error('offline');
  }
}

async function cacheFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req, { ignoreSearch: true });
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) cache.put(req, res.clone());
  return res;
}

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  const path = url.pathname;
  if (path.includes('/content/') && path.endsWith('.json')) {
    e.respondWith(networkFirst(e.request, CONTENT));
  } else if (path.includes('/audio/')) {
    e.respondWith(cacheFirst(e.request, AUDIO));
  } else if (e.request.mode === 'navigate') {
    e.respondWith(networkFirst(e.request, SHELL).catch(() => caches.match('index.html')));
  } else {
    // shell assets: serve cached copy, refresh in background
    e.respondWith((async () => {
      const cache = await caches.open(SHELL);
      const hit = await cache.match(e.request, { ignoreSearch: true });
      const fresh = fetch(e.request).then(res => { if (res.ok) cache.put(e.request, res.clone()); return res; });
      if (hit) { e.waitUntil(fresh.catch(() => {})); return hit; }
      return fresh;
    })());
  }
});
