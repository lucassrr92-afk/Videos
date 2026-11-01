// Service worker mínimo: permite instalar o app. Não faz cache (o app depende do servidor).
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});
