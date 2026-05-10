const CACHE_NAME = 'vui-academia-v1';
const ASSETS_TO_CACHE = [
    '/',
    '/static/css/index.css',
    '/static/js/main.js',
    '/static/img/logo.png'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(ASSETS_TO_CACHE);
        })
    );
});

self.addEventListener('fetch', (event) => {
    event.respondWith(
        caches.match(event.request).then((response) => {
            return response || fetch(event.request);
        })
    );
});
