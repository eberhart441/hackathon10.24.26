import { defineConfig } from "vite";
import preact from "@preact/preset-vite";
import { VitePWA } from "vite-plugin-pwa";

// Service worker precaches the app shell ONLY; no room/crew data is ever cached (Req 17, 18).
export default defineConfig({
  plugins: [
    preact(),
    VitePWA({
      registerType: "autoUpdate",
      injectRegister: "auto",
      includeAssets: ["icons/apple-touch-icon-180.png"],
      manifest: {
        name: "RoomSense",
        short_name: "RoomSense",
        display: "standalone",
        orientation: "any",
        start_url: "/",
        background_color: "#0E1116",
        theme_color: "#0E1116",
        icons: [
          { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{html,js,css,woff2,svg,png,webmanifest}"],
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//, /^\/ws/],
        runtimeCaching: [],
      },
    }),
  ],
  build: {
    outDir: "../hub/static",
    emptyOutDir: true,
  },
});
