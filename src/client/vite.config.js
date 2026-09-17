import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
// GitHub Pages serves a repo (not a <user>.github.io repo) under
// /<repo-name>/, not /. GITHUB_PAGES is set only by
// .github/workflows/deploy-pages.yml's build step -- every other build
// (local dev, the Docker/nginx deployment) keeps the normal root base.
var BASE_PATH = process.env.GITHUB_PAGES ? "/CogniLec/" : "/";
export default defineConfig({
    base: BASE_PATH,
    plugins: [
        react(),
        VitePWA({
            registerType: "autoUpdate",
            workbox: {
                // Without these, a new service worker only takes control after
                // every open tab is closed and reopened -- confirmed live: the
                // entire compiled JS bundle (including config.ts's build-time-baked
                // apiBaseUrl) is precached below, so a tab left open across a
                // backend URL change kept running the OLD bundle indefinitely and
                // every fetch (login included) failed. Reported by users as "have
                // to clear cookies to log in" -- clearing cookies incidentally also
                // wipes Cache Storage/SW state, which is what actually fixed it;
                // cookies themselves are unused (auth is Bearer-token-in-
                // localStorage, see services/auth.ts). skipWaiting+clientsClaim
                // make a new SW activate immediately; main.tsx's controllerchange
                // listener then reloads the (now out-of-date) open tab once that
                // happens, so this fixes itself instead of needing manual cache
                // clearing.
                skipWaiting: true,
                clientsClaim: true,
                globPatterns: ["**/*.{js,css,html,svg,png,ico}"],
                // Chunk buffering itself is handled by the app's own IndexedDB
                // ring buffer (see src/services/db.ts), not by Workbox caching —
                // Workbox here only makes the app shell installable/offline.
                runtimeCaching: [
                    {
                        urlPattern: function (_a) {
                            var url = _a.url;
                            return url.pathname.startsWith("/api/");
                        },
                        handler: "NetworkOnly",
                    },
                ],
            },
            manifest: {
                name: "Notely",
                short_name: "Notely",
                start_url: BASE_PATH,
                display: "standalone",
                background_color: "#0f172a",
                theme_color: "#0f172a",
                icons: [],
            },
            devOptions: {
                enabled: false,
            },
        }),
    ],
    server: {
        port: 5173,
    },
    build: {
        sourcemap: true,
    },
});
