/* Kill-switch Service Worker
 * 기존 PWA 서비스워커가 /wedding/ 같은 새 정적 경로의 navigation을 가로채는 문제 해결.
 * 새로 페치되는 즉시 자기 자신을 unregister하고 모든 캐시를 비운 뒤 열린 클라이언트를 새로고침한다.
 */
self.addEventListener('install', function () {
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil((async function () {
    try {
      const keys = await caches.keys();
      await Promise.all(keys.map(function (k) { return caches.delete(k); }));
    } catch (e) { /* ignore */ }
    try {
      await self.registration.unregister();
    } catch (e) { /* ignore */ }
    try {
      const clients = await self.clients.matchAll({ type: 'window' });
      clients.forEach(function (c) { c.navigate(c.url); });
    } catch (e) { /* ignore */ }
  })());
});
