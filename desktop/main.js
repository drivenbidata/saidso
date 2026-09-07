// SaidSo desktop — the Electron shell.
//
// This process owns the SaidSo engine and nothing else owns anything. It starts
// the engine on an ephemeral port, reads the port and token from the handshake
// line the engine prints on stdout, and proxies every request from the
// renderer. The renderer never sees the token and never gets Node access, so
// the window is a view over the same API the CLI drives.
//
// A packaged build ships a frozen engine and needs no Python at all; running
// from source falls back to an interpreter that can import saidso. Working out
// which is the one genuinely awkward part of shipping this way, so it is done
// explicitly and any failure is explained rather than swallowed.

const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const HANDSHAKE = "saidso-server";
const START_TIMEOUT_MS = 20000;

let win = null;
let engine = null; // { proc, port, token }
let starting = null;
let lastStatus = { state: "starting" };

// ---------------------------------------------------------------- the engine

const ENGINE_NAME = process.platform === "win32" ? "saidso-engine.exe" : "saidso-engine";

// A packaged app ships the frozen engine beside itself; a developer checkout may
// have one built into dist/. Either is preferred over a Python on PATH, because
// it is the one whose dependencies are known to be right.
function bundledEngine() {
  const candidates = [
    process.resourcesPath && path.join(process.resourcesPath, "saidso-engine", ENGINE_NAME),
    path.join(__dirname, "..", "dist", "engine", "saidso-engine", ENGINE_NAME),
  ].filter(Boolean);
  return candidates.find((candidate) => fs.existsSync(candidate)) || null;
}

function pythonCandidates() {
  const explicit = process.env.SAIDSO_PYTHON;
  if (explicit) return [explicit];
  return process.platform === "win32"
    ? ["python", "py", "python3"]
    : ["python3", "python"];
}

// How to start the engine: the frozen binary if there is one, otherwise an
// interpreter that can actually import saidso. Probing with a real import,
// rather than trusting that `python` exists, is what stops a machine with the
// wrong interpreter first on PATH from failing later and far less clearly.
function resolveEngine() {
  const bundled = bundledEngine();
  if (bundled) return { cmd: bundled, args: [], label: "bundled engine" };

  for (const exe of pythonCandidates()) {
    const probe = spawnSync(exe, ["-c", "import saidso, sys; print(saidso.__version__)"], {
      encoding: "utf8",
    });
    if (probe.status === 0) {
      return { cmd: exe, args: ["-m", "saidso.server"], label: `${exe} (${probe.stdout.trim()})` };
    }
  }
  return null;
}

function setStatus(next) {
  lastStatus = next;
  if (win && !win.isDestroyed()) win.webContents.send("engine-status", next);
}

function startEngine() {
  if (starting) return starting;

  starting = new Promise((resolve, reject) => {
    const found = resolveEngine();
    if (!found) {
      reject(
        new Error(
          "No SaidSo engine found.\n\n" +
            "A packaged build ships one. Running from source needs either\n" +
            "  npm run build:engine      (builds a frozen engine into dist/)\n" +
            "or a Python that can import saidso:\n" +
            "  pip install \"saidso[all]\"\n\n" +
            "SAIDSO_PYTHON overrides which interpreter is used."
        )
      );
      return;
    }

    // stdin stays open on purpose: the engine watches it and exits when it
    // closes, so a crashed or force-killed shell can't orphan a process that
    // might be holding the microphone.
    const proc = spawn(found.cmd, [...found.args, "--port", "0", "--exit-with-parent"], {
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });

    let buffered = "";
    let settled = false;

    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      proc.kill();
      reject(new Error("The SaidSo engine didn't start within 20 seconds."));
    }, START_TIMEOUT_MS);

    proc.stdout.on("data", (chunk) => {
      buffered += chunk.toString();
      let index;
      while ((index = buffered.indexOf("\n")) >= 0) {
        const line = buffered.slice(0, index).trim();
        buffered = buffered.slice(index + 1);
        if (!line || settled) continue;
        try {
          const parsed = JSON.parse(line);
          if (parsed[HANDSHAKE]) {
            settled = true;
            clearTimeout(timer);
            engine = { proc, port: parsed.port, token: parsed.token };
            setStatus({ state: "ready", version: parsed[HANDSHAKE], engine: found.label });
            listenForEvents();
            resolve(engine);
          }
        } catch {
          // Not the handshake — engine chatter, ignored.
        }
      }
    });

    proc.stderr.on("data", (chunk) => {
      const text = chunk.toString().trim();
      if (text) console.error("[engine]", text);
    });

    proc.on("exit", (code) => {
      engine = null;
      starting = null;
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(new Error(`The SaidSo engine exited with code ${code} before starting.`));
      } else if (!app.isQuitting) {
        setStatus({ state: "stopped", code });
      }
    });
  }).catch((err) => {
    starting = null;
    setStatus({ state: "error", message: err.message });
    throw err;
  });

  return starting;
}

// ---------------------------------------------------------------- API proxy

async function callEngine(method, endpoint, body) {
  const target = engine || (await startEngine());
  const response = await fetch(`http://127.0.0.1:${target.port}${endpoint}`, {
    method,
    headers: {
      Authorization: `Bearer ${target.token}`,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

// Server-Sent Events, read as a stream and forwarded to the window. Reconnects
// on drop, because a long transcription outliving a hiccup matters more than
// the events lost during it.
async function listenForEvents() {
  if (!engine) return;
  const { port, token } = engine;
  try {
    const response = await fetch(`http://127.0.0.1:${port}/events`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let split;
      while ((split = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, split);
        buffer = buffer.slice(split + 2);
        for (const line of frame.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));
            if (win && !win.isDestroyed()) win.webContents.send("engine-event", event);
          } catch {
            // A malformed frame is not worth tearing the stream down for.
          }
        }
      }
    }
  } catch {
    // fall through to the retry below
  }
  if (engine && !app.isQuitting) setTimeout(listenForEvents, 1000);
}

// ---------------------------------------------------------------- window

function createWindow() {
  win = new BrowserWindow({
    width: 940,
    height: 760,
    minWidth: 720,
    minHeight: 560,
    title: "SaidSo",
    backgroundColor: "#14161a",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  win.removeMenu();
  win.loadFile(path.join(__dirname, "renderer", "index.html"));
  win.once("ready-to-show", () => {
    win.show();
    win.webContents.send("engine-status", lastStatus);
  });
}

ipcMain.handle("api", async (_event, { method, path: endpoint, body }) => {
  try {
    return { ok: true, data: await callEngine(method, endpoint, body) };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle("pick-recordings", async () => {
  const result = await dialog.showOpenDialog(win, {
    title: "Choose recordings",
    properties: ["openFile", "multiSelections"],
    filters: [
      {
        name: "Recordings",
        extensions: ["mp3", "mp4", "m4a", "wav", "webm", "ogg", "flac", "mkv", "mov", "aac", "opus"],
      },
      { name: "All files", extensions: ["*"] },
    ],
  });
  return result.canceled ? [] : result.filePaths;
});

ipcMain.handle("pick-folder", async (_event, current) => {
  const result = await dialog.showOpenDialog(win, {
    title: "Choose a notes folder",
    defaultPath: current || undefined,
    properties: ["openDirectory", "createDirectory"],
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle("reveal", (_event, target) => {
  if (typeof target === "string" && target) shell.showItemInFolder(target);
});

app.whenReady().then(() => {
  createWindow();
  startEngine().catch(() => {
    // The status message is already in the window; nothing to add here.
  });

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

// Ask the engine to stop cleanly, so a recording in progress isn't orphaned.
app.on("before-quit", async (event) => {
  if (app.isQuitting || !engine) return;
  event.preventDefault();
  app.isQuitting = true;
  try {
    await callEngine("POST", "/shutdown");
  } catch {
    engine.proc.kill();
  }
  setTimeout(() => app.quit(), 300);
});
