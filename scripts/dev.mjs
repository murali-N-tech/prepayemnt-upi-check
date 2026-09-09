/**
 * Start both halves of the app with one command.
 *
 * The project needs two processes - FastAPI for scoring, statement parsing and
 * the payee check, Express for the SPA and the API surface. Run in one
 * terminal, the first command occupies it and the second never gets started,
 * which looks exactly like the app being broken: the page loads from a stale
 * tab and every Vite asset fails with ERR_CONNECTION_REFUSED.
 *
 *     npm run dev
 *
 * Ctrl-C stops both. To run them separately (two terminals), use
 * `npm run dev:web` and `npm run dev:api`.
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import process from "node:process";

const isWindows = process.platform === "win32";
const PY = isWindows ? "python" : "python3";

// tsx watch restarts on any change under the project. Vite writes
// vite.config.ts.timestamp-*.mjs into the root on every start, so without
// these the restart writes a new temp file and triggers another restart,
// forever. Uploading a statement or training a model would bounce it too.
const WATCH_IGNORES = [
  "vite.config.ts.timestamp-*",
  "./data/**",
  "./models/**",
  "./dist/**",
  "./archive/**",
  "**/__pycache__/**",
  "*.db",
  "*.db-journal",
].flatMap((glob) => ["--ignore", glob]);

const COLOURS = { api: "[36m", web: "[35m", warn: "[33m", off: "[0m" };

function log(tag, line) {
  if (!line.trim()) return;
  process.stdout.write(`${COLOURS[tag] ?? ""}[${tag}]${COLOURS.off} ${line}\n`);
}

if (!existsSync(".env")) {
  log("warn", "No .env file. Copy .env.example to .env and set JWT_SECRET.");
}

const children = [];
let shuttingDown = false;

function start(tag, command, args) {
  const child = spawn(command, args, {
    stdio: ["ignore", "pipe", "pipe"],
    shell: isWindows, // Windows needs a shell to resolve python/npx
    env: process.env,
  });

  for (const stream of [child.stdout, child.stderr]) {
    let buffer = "";
    stream.setEncoding("utf8");
    stream.on("data", (chunk) => {
      buffer += chunk;
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) log(tag, line);
    });
  }

  child.on("error", (err) => {
    log("warn", `could not start ${command}: ${err.message}`);
    if (tag === "api") {
      log("warn", `Is Python on PATH? Try running "${PY} backend/main.py" yourself.`);
    }
  });

  child.on("exit", (code) => {
    if (shuttingDown) return;
    log("warn", `${tag} exited with code ${code}. Stopping the other process.`);
    shutdown(code ?? 1);
  });

  children.push(child);
  return child;
}

function shutdown(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children) {
    if (!child.killed) child.kill(isWindows ? undefined : "SIGTERM");
  }
  setTimeout(() => process.exit(code), 300);
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

log("api", `starting ${PY} backend/main.py on :8000`);
start("api", PY, ["backend/main.py"]);

// A moment's head start so the web server's readiness probe finds it.
setTimeout(() => {
  log("web", "starting Express + Vite on :3001");
  start("web", isWindows ? "npx.cmd" : "npx", ["tsx", "watch", ...WATCH_IGNORES, "server.ts"]);
}, 1500);
