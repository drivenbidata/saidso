// Renderer. No Node here — everything goes through window.saidso, which main.js
// exposes. The window holds no state the engine doesn't also hold: it asks on
// start, then reacts to events. That way closing and reopening it can't produce
// a view that disagrees with what is actually recording.

const $ = (id) => document.getElementById(id);

const els = {
  status: $("status"),
  revealNotes: $("reveal-notes"),
  title: $("title"),
  project: $("project"),
  record: $("record"),
  cancel: $("cancel"),
  timer: $("timer"),
  mic: $("dev-mic"),
  sys: $("dev-sys"),
  pick: $("pick"),
  drop: $("drop"),
  bar: $("bar-fill"),
  progressMsg: $("progress-msg"),
  log: $("log"),
  inbox: $("inbox"),
  refresh: $("refresh"),
  sweep: $("sweep"),
  notesDir: $("notes-dir"),
  changeNotes: $("change-notes"),
  speakerName: $("speaker-name"),
  saveName: $("save-name"),
  configPath: $("config-path"),
};

let recording = false;
let busy = false;
let notesDir = "";
let timerHandle = null;
let startedAt = 0;

// ---------------------------------------------------------------- helpers

function log(message, kind) {
  const li = document.createElement("li");
  const time = document.createElement("time");
  time.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const span = document.createElement("span");
  if (kind) span.className = kind;
  span.textContent = message;
  li.append(time, span);
  els.log.prepend(li);
  while (els.log.children.length > 80) els.log.lastElementChild.remove();
}

function setStatus(text, kind) {
  els.status.textContent = text;
  els.status.className = `pill pill-${kind}`;
}

function setProgress(fraction, message) {
  if (message) els.progressMsg.textContent = message;
  if (fraction === null || fraction === undefined) {
    els.bar.classList.add("indeterminate");
    els.bar.style.width = "";
  } else {
    els.bar.classList.remove("indeterminate");
    els.bar.style.width = `${Math.round(fraction * 100)}%`;
  }
}

function clearProgress(message) {
  els.bar.classList.remove("indeterminate");
  els.bar.style.width = "0";
  els.progressMsg.textContent = message || "Idle.";
}

function formatElapsed(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  const mm = String(Math.floor(s / 60) % 60).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  const hh = Math.floor(s / 3600);
  return hh > 0 ? `${String(hh).padStart(2, "0")}:${mm}:${ss}` : `${mm}:${ss}`;
}

function syncControls() {
  els.record.disabled = busy && !recording;
  els.record.textContent = recording ? "Stop & transcribe" : "Record";
  els.record.classList.toggle("recording", recording);
  els.cancel.hidden = !recording;
  els.pick.disabled = busy || recording;
  els.title.disabled = recording;
  els.project.disabled = recording;
  els.timer.classList.toggle("live", recording);
}

function startTimer(offset) {
  startedAt = Date.now() - offset * 1000;
  stopTimer();
  timerHandle = setInterval(() => {
    els.timer.textContent = formatElapsed((Date.now() - startedAt) / 1000);
  }, 250);
}

function stopTimer() {
  if (timerHandle) clearInterval(timerHandle);
  timerHandle = null;
}

// ---------------------------------------------------------------- API

async function api(method, path, body) {
  const result =
    method === "GET" ? await window.saidso.get(path) : await window.saidso.post(path, body);
  if (!result.ok) throw new Error(result.error);
  return result.data;
}

async function loadSettings() {
  const settings = await api("GET", "/settings");
  notesDir = settings.notes_dir;
  els.revealNotes.hidden = false;
  els.notesDir.value = settings.notes_dir;
  els.configPath.textContent = settings.config_path || "config.toml";
  // Only overwrite the field when it isn't being edited, so a refresh mid-type
  // doesn't discard what someone is halfway through writing.
  if (document.activeElement !== els.speakerName) {
    els.speakerName.value = settings.speaker_name || "";
  }
  return settings;
}

async function saveSettings(patch, note) {
  try {
    const settings = await api("POST", "/settings", patch);
    notesDir = settings.notes_dir;
    els.notesDir.value = settings.notes_dir;
    log(note, "good");
    await loadInbox();
  } catch (err) {
    log(err.message, "bad");
  }
}

async function loadProjects() {
  const { projects, default: fallback } = await api("GET", "/projects");
  els.project.replaceChildren();
  for (const project of projects) {
    const option = document.createElement("option");
    option.value = project.key;
    option.textContent = project.label;
    option.selected = project.key === fallback;
    els.project.append(option);
  }
}

async function loadDevices() {
  const devices = await api("GET", "/devices");
  if (!devices.available) {
    els.mic.textContent = els.sys.textContent = "unavailable";
    els.record.disabled = true;
    log(devices.reason.split("\n")[0], "bad");
    return;
  }
  const pick = (list) => list.find((d) => d.is_default) || list[0];
  els.mic.textContent = pick(devices.mics)?.name || "none found";
  els.sys.textContent = pick(devices.system)?.name || "none found";
}

async function loadInbox() {
  const { items } = await api("GET", "/inbox");
  els.inbox.replaceChildren();
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "Nothing waiting.";
    els.inbox.append(li);
    return;
  }
  for (const item of items) {
    const li = document.createElement("li");

    const name = document.createElement("span");
    name.className = "name";
    name.textContent = item.title || item.name;
    li.append(name);

    if (item.date_inferred) {
      const warn = document.createElement("span");
      warn.className = "warn";
      warn.textContent = "date guessed";
      warn.title = "The date came from the file's modification time — confirm it.";
      li.append(warn);
    }

    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = [item.date, item.project].filter(Boolean).join(" · ");
    li.append(meta);

    const reveal = document.createElement("button");
    reveal.className = "link";
    reveal.type = "button";
    reveal.textContent = "Show";
    reveal.addEventListener("click", () => window.saidso.reveal(item.path));
    li.append(reveal);

    els.inbox.append(li);
  }
}

// The window refreshes on load and again when the engine reports ready, and
// those can overlap. Coalescing them isn't only tidiness: overlapping refreshes
// meant two device queries hitting the engine at once, which used to take the
// whole process down.
let refreshing = null;

async function refreshAll() {
  if (refreshing) return refreshing;
  refreshing = doRefresh().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

async function doRefresh() {
  try {
    await loadSettings();
    await loadProjects();
    await loadDevices();
    await loadInbox();
    const status = await api("GET", "/record/status");
    recording = status.recording;
    busy = status.busy;
    if (recording) startTimer(status.elapsed || 0);
    syncControls();
  } catch (err) {
    log(err.message, "bad");
  }
}

// ---------------------------------------------------------------- actions

els.record.addEventListener("click", async () => {
  try {
    if (recording) {
      await api("POST", "/record/stop");
      recording = false;
      stopTimer();
      busy = true;
      syncControls();
      setProgress(null, "Transcribing…");
      return;
    }
    await api("POST", "/record/start", {
      title: els.title.value.trim(),
      project: els.project.value,
    });
    recording = true;
    startTimer(0);
    syncControls();
  } catch (err) {
    log(err.message, "bad");
  }
});

els.cancel.addEventListener("click", async () => {
  try {
    await api("POST", "/record/cancel");
    recording = false;
    stopTimer();
    els.timer.textContent = "00:00";
    syncControls();
    log("Recording discarded.");
  } catch (err) {
    log(err.message, "bad");
  }
});

async function transcribe(paths) {
  if (!paths.length) return;
  try {
    await api("POST", "/transcribe", { paths, project: els.project.value });
    busy = true;
    syncControls();
    setProgress(null, `Transcribing ${paths.length} file(s)…`);
  } catch (err) {
    log(err.message, "bad");
  }
}

els.pick.addEventListener("click", async () => transcribe(await window.saidso.pickRecordings()));

els.drop.addEventListener("dragover", (event) => {
  event.preventDefault();
  els.drop.classList.add("over");
});
els.drop.addEventListener("dragleave", () => els.drop.classList.remove("over"));
els.drop.addEventListener("drop", (event) => {
  event.preventDefault();
  els.drop.classList.remove("over");
  if (busy || recording) return;
  const paths = [...event.dataTransfer.files]
    .map((file) => window.saidso.pathForFile(file))
    .filter(Boolean);
  transcribe(paths);
});

els.changeNotes.addEventListener("click", async () => {
  const chosen = await window.saidso.pickFolder(notesDir);
  if (!chosen || chosen === notesDir) return;
  await saveSettings({ notes_dir: chosen }, `Notes folder is now ${chosen}`);
});

els.saveName.addEventListener("click", async () => {
  const name = els.speakerName.value.trim();
  await saveSettings({ speaker_name: name }, name ? `Your speaker tag is now “${name}”` : "Speaker tag cleared");
});

els.speakerName.addEventListener("keydown", (event) => {
  if (event.key === "Enter") els.saveName.click();
});

els.refresh.addEventListener("click", refreshAll);
els.revealNotes.addEventListener("click", () => window.saidso.reveal(notesDir));

els.sweep.addEventListener("click", async () => {
  try {
    const result = await api("POST", "/tracker/sweep");
    log(
      result.moved
        ? `Swept ${result.moved} completed item(s).`
        : "Nothing ticked — no items to move.",
      result.moved ? "good" : undefined
    );
    for (const problem of result.problems) log(`Refused: ${problem}`, "bad");
  } catch (err) {
    log(err.message, "bad");
  }
});

// ---------------------------------------------------------------- events

window.saidso.onStatus((status) => {
  if (status.state === "ready") {
    setStatus(`engine ${status.version}`, "ok");
    refreshAll();
  } else if (status.state === "starting") {
    setStatus("starting…", "wait");
  } else if (status.state === "stopped") {
    setStatus("engine stopped", "bad");
    log("The engine stopped unexpectedly.", "bad");
  } else {
    setStatus("engine unavailable", "bad");
    log(status.message || "The engine could not be started.", "bad");
  }
});

window.saidso.onEvent((event) => {
  switch (event.type) {
    case "progress":
      setProgress(event.fraction, event.message);
      break;
    case "done": {
      const results = Array.isArray(event.result) ? event.result : [event.result];
      for (const result of results) {
        if (!result) continue;
        log(`${result.title} → ${result.project} (${result.segments} segments)`, "good");
        for (const note of result.notes || []) log(note);
      }
      loadInbox();
      break;
    }
    case "error":
      log(event.message, "bad");
      break;
    case "idle":
      busy = false;
      syncControls();
      clearProgress("Idle.");
      break;
    case "recording":
      if (event.state === "started") log(`Recording “${event.title}”.`);
      break;
    default:
      break;
  }
});

refreshAll();
