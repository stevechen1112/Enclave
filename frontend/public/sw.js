/*
 * Enclave MKA service worker — app shell 快取＋API network-first。
 *
 * 現場網路不穩（廠房金屬屏蔽、地下室），策略：
 * - 導航與靜態資源：cache-first，離線也能開 app shell
 * - /api/ 請求：network-first，失敗回 503 JSON（不 cache 機敏資料）
 * 版本：註冊 URL 帶 ?build=…，每次 production build 自動失效舊 shell。
 */
const BUILD_ID = new URL(self.location.href).searchParams.get('build') || 'dev'
const CACHE_VERSION = `mka-shell-${BUILD_ID}`
const SHELL_ASSETS = ['/', '/job', '/manifest.webmanifest']

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) =>
      // no-store：addAll 預設走 HTTP cache，部署後可能把舊 shell 存進來
      Promise.all(
        SHELL_ASSETS.map((url) =>
          fetch(url, { cache: 'no-store' }).then((r) => cache.put(url, r)),
        ),
      ),
    ),
  )
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))),
      )
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return
  const url = new URL(request.url)

  // API：network-first，絕不快取回應（含租戶機敏資料）
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request).catch(
        () =>
          new Response(
            JSON.stringify({ detail: '目前離線或網路不穩，請到訊號好的地方再試' }),
            { status: 503, headers: { 'Content-Type': 'application/json' } },
          ),
      ),
    )
    return
  }

  // 導航請求：network-first，離線回退 app shell（SPA 路由）
  // 關鍵：fetch 必須 cache:'no-store' — 否則 SW 的 fetch 會被瀏覽器
  // HTTP cache 攔截，拿到部署前的舊 index.html（舊 bundle 缺新路由，
  // 會被 catch-all 彈回首頁），network-first 形同虛設。
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request, { cache: 'no-store' })
        .then((response) => {
          const copy = response.clone()
          caches.open(CACHE_VERSION).then((cache) => cache.put(request, copy))
          return response
        })
        .catch(() => caches.match(request).then((hit) => hit || caches.match('/'))),
    )
    return
  }

  // 靜態資源：cache-first，背景更新
  event.respondWith(
    caches.match(request).then((hit) => {
      const fetching = fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone()
            caches.open(CACHE_VERSION).then((cache) => cache.put(request, copy))
          }
          return response
        })
        .catch(() => hit)
      return hit || fetching
    }),
  )
})
