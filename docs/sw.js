// Service worker do app: sempre tenta a rede primeiro (dados do dia) e,
// sem internet, mostra a última versão salva.
const CACHE = 'univap-v1';
const ARQUIVOS = ['./', 'index.html', 'data.json', 'manifest.webmanifest', 'icons/icon-192.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ARQUIVOS)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== location.origin) return;
  const chave = req.url.split('?')[0]; // ignora o ?_=timestamp do data.json
  e.respondWith(
    fetch(req)
      .then(res => {
        if (res.ok) { const copia = res.clone(); caches.open(CACHE).then(c => c.put(chave, copia)); }
        return res;
      })
      .catch(() => caches.match(chave).then(r => r || caches.match('./')))
  );
});
