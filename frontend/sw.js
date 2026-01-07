/**
 * Service Worker for Bowman Draft Tracker
 * Provides offline support and better caching for static assets
 */

const CACHE_NAME = 'bowman-tracker-v2';
const STATIC_ASSETS = [
    '/',
    '/css/styles.css',
    '/css/components.css',
    '/css/utilities.css',
    '/js/app.js',
    '/js/vendor/lightweight-charts.min.js', // Self-hosted chart library
    '/manifest.json',
    '/icons/icon-192.png',
    '/icons/icon-512.png'
];

// Install event - cache static assets
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                console.log('[SW] Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => self.skipWaiting())
    );
});

// Activate event - clean up old caches
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames
                    .filter(name => name !== CACHE_NAME)
                    .map(name => {
                        console.log('[SW] Removing old cache:', name);
                        return caches.delete(name);
                    })
            );
        }).then(() => self.clients.claim())
    );
});

// Fetch event - serve from cache, fallback to network
self.addEventListener('fetch', event => {
    const { request } = event;
    const url = new URL(request.url);

    // Skip non-GET requests
    if (request.method !== 'GET') return;

    // Skip API requests - always fetch fresh data
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(
            fetch(request)
                .catch(() => {
                    // Return a cached error response for offline API calls
                    return new Response(
                        JSON.stringify({ success: false, error: 'You are offline' }),
                        { headers: { 'Content-Type': 'application/json' } }
                    );
                })
        );
        return;
    }

    // For static assets, use cache-first strategy
    event.respondWith(
        caches.match(request)
            .then(cachedResponse => {
                if (cachedResponse) {
                    // Return cached version, but also update cache in background
                    event.waitUntil(
                        fetch(request)
                            .then(response => {
                                if (response.ok) {
                                    caches.open(CACHE_NAME)
                                        .then(cache => cache.put(request, response));
                                }
                            })
                            .catch(() => { /* Ignore network errors */ })
                    );
                    return cachedResponse;
                }

                // Not in cache - fetch from network
                return fetch(request)
                    .then(response => {
                        // Cache successful responses
                        if (response.ok) {
                            const responseClone = response.clone();
                            caches.open(CACHE_NAME)
                                .then(cache => cache.put(request, responseClone));
                        }
                        return response;
                    });
            })
    );
});

// Handle messages from main thread
self.addEventListener('message', event => {
    if (event.data === 'skipWaiting') {
        self.skipWaiting();
    }
});
