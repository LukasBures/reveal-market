import { mkdirSync, existsSync } from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

const input = process.env.TAILWIND_INPUT ?? "./app/globals.css";
const output = process.env.TAILWIND_OUTPUT ?? "./app/.generated/tailwind.css";

if (!existsSync(input)) {
  console.error(`generate-css: input file not found at ${input}`);
  process.exit(1);
}

mkdirSync(path.dirname(output), { recursive: true });

const result = spawnSync(
  "npx",
  ["tailwindcss", "-c", "tailwind.config.ts", "-i", input, "-o", output, "--minify"],
  {
    stdio: "inherit",
  },
);

if (typeof result.status === "number" && result.status !== 0) {
  process.exit(result.status);
}
