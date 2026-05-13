import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { spawn } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const appRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const appTypesDir = join(appRoot, ".next", "types", "app");
const requiredFiles = ["layout.ts", "page.ts"];

mkdirSync(appTypesDir, { recursive: true });

for (const fileName of requiredFiles) {
  const filePath = join(appTypesDir, fileName);
  if (!existsSync(filePath)) {
    writeFileSync(filePath, "export {};\n", "utf8");
  }
}

const packageManagerCommand = process.platform === "win32" ? "pnpm.cmd" : "pnpm";
const child = spawn(packageManagerCommand, ["exec", "tsc", "--noEmit"], {
  stdio: "inherit",
  env: process.env,
  cwd: appRoot,
});

child.on("error", (error) => {
  console.error(error);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
