import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

const setupFile = fileURLToPath(new URL("../../tests/client/setup.ts", import.meta.url));

export default defineConfig({
  plugins: [react()],
  server: {
    fs: {
      allow: [fileURLToPath(new URL("../..", import.meta.url))],
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: [setupFile],
    globals: true,
    include: ["../../tests/client/**/*.test.{ts,tsx}"],
    css: false,
  },
});
