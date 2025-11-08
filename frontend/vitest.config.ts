import { defineConfig } from "vitest/config";
import path from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  test: {
    globals: true,
    environment: "happy-dom",
    setupFiles: "./vitest.setup.tsx",
    include: ["tests/**/*.test.ts?(x)"],
    coverage: {
      reporter: ["text", "lcov"],
    },
  },
  resolve: {
    alias: [
      { find: /^@\//, replacement: `${path.resolve(projectRoot, ".")}/` },
      { find: "@", replacement: path.resolve(projectRoot, ".") },
    ],
  },
  esbuild: {
    jsx: "automatic",
    jsxImportSource: "react",
  },
});
