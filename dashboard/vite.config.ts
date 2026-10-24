import { defineConfig } from "vite";
import preact from "@preact/preset-vite";

// PWA plugin (vite-plugin-pwa) is wired in a later task (Req 17, 18).
export default defineConfig({
  plugins: [preact()],
  build: {
    outDir: "../hub/static",
    emptyOutDir: true,
  },
});
