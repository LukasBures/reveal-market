import fs from "node:fs";
import path from "node:path";

const BYTES_IN_MB = 1024 * 1024;
const budgets = [
  { name: "total js", path: ".next/static/chunks", maxBytes: 2.5 * BYTES_IN_MB },
  { name: "root route", path: ".next/server/app/(public)/page.js", maxBytes: 450 * 1024 },
  { name: "search route", path: ".next/server/app/(public)/search/page.js", maxBytes: 350 * 1024 },
  { name: "event route", path: ".next/server/app/(app)/events/[eventId]/page.js", maxBytes: 450 * 1024 },
];

const projectRoot = path.resolve(process.cwd());

function statSafe(targetPath) {
  try {
    return fs.statSync(targetPath);
  } catch {
    return null;
  }
}

function collectJsSize(dirPath) {
  let total = 0;
  const entries = fs.readdirSync(dirPath, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dirPath, entry.name);
    if (entry.isDirectory()) {
      total += collectJsSize(fullPath);
    } else if (entry.isFile() && entry.name.endsWith(".js")) {
      total += fs.statSync(fullPath).size;
    }
  }
  return total;
}

const failures = [];
const report = [];

for (const budget of budgets) {
  const target = path.join(projectRoot, budget.path);
  const stats = statSafe(target);
  if (!stats) {
    failures.push(`${budget.name}: missing ${budget.path}`);
    continue;
  }
  let size = stats.size;
  if (stats.isDirectory()) {
    size = collectJsSize(target);
  }
  report.push({ name: budget.name, size, maxBytes: budget.maxBytes });
  if (size > budget.maxBytes) {
    failures.push(
      `${budget.name}: ${(size / BYTES_IN_MB).toFixed(2)}MB > ${(budget.maxBytes / BYTES_IN_MB).toFixed(2)}MB`,
    );
  }
}

const lines = report.map((entry) => {
  const sizeMb = (entry.size / BYTES_IN_MB).toFixed(2);
  const maxMb = (entry.maxBytes / BYTES_IN_MB).toFixed(2);
  return `${entry.name.padEnd(14)} ${sizeMb}MB / ${maxMb}MB`;
});

console.log("Bundle budget report:");
console.log(lines.join("\n"));

if (failures.length > 0) {
  console.error("\nBundle budget failures:");
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}
