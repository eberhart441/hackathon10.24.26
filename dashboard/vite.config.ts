/// <reference types="vitest" />
import { defineConfig } from 'vite';
import preact from '@preact/preset-vite';
import { VitePWA } from 'vite-plugin-pwa';

const HUB = process.env.HUB_URL ?? 'http://127.0.0.1:8443';

// Exported separately so the privacy test can assert there is no runtime caching (Kiro R17.1).
export const workbox = {
  globPatterns: ['**/*.{js,css,html,woff2,png,svg,webmanifest}'],
  navigateFallback: '/index.html',
  navigateFallbackDenylist: [/^\/api\//, /^\/ws/],
  runtimeCaching: [],
  cleanupOutdatedCaches: true,
};

export default defineConfig({
  plugins: [
    preact(),
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: 'auto',
      includeAssets: ['icons/apple-touch-icon.png', 'icons/favicon.svg'],
      manifest: {
        name: 'Beacon',
        short_name: 'Beacon',
        description: 'Search priority for responders. Decision support only; does not replace a full search.',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        orientation: 'any',
        background_color: '#0B0F14',
        theme_color: '#0B0F14',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox,
    }),
  ],
  build: {
    outDir: '../hub/static',
    emptyOutDir: true,
    chunkSizeWarningLimit: 900,
  },
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': HUB,
      '/ws': { target: HUB.replace(/^http/, 'ws'), ws: true },
    },
  },
  test: {
    environment: 'node',
    include: ['tests/**/*.test.ts'],
  },
});
