import { rmSync } from "node:fs";
import { join } from "node:path";
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";

const host = process.env.HOST ?? "127.0.0.1";
const port = process.env.PORT ?? "3000";
const baseUrl = `http://${host}:${port}`;
const nextCommand = process.platform === "win32" ? "next.cmd" : "next";
const nextBuildDir = join(process.cwd(), ".next");

// Next dev can choke on stale production artifacts after switching between build/dev.
rmSync(nextBuildDir, { force: true, recursive: true });

const child = spawn(nextCommand, ["dev", "-H", host, "-p", port], {
  stdio: "inherit",
  env: process.env,
});

let childExited = false;

function forwardSignal(signal) {
  if (!childExited) {
    child.kill(signal);
  }
}

process.on("SIGINT", () => forwardSignal("SIGINT"));
process.on("SIGTERM", () => forwardSignal("SIGTERM"));

child.on("exit", (code, signal) => {
  childExited = true;
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});

void (async () => {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    if (childExited) {
      return;
    }
    try {
      const response = await fetch(baseUrl, { cache: "no-store" });
      if (response.ok) {
        console.log(`[dev] prewarmed ${baseUrl}/`);
        return;
      }
    } catch {
      // Keep polling until Next is ready to serve the app shell.
    }
    await delay(500);
  }

  if (!childExited) {
    console.warn(`[dev] prewarm timed out for ${baseUrl}/`);
  }
})();
