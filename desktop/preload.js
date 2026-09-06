// The renderer gets a narrow, explicit surface and nothing else: no Node, no
// filesystem, and never the API token — main.js holds that and does the
// talking. Everything below is a message to the main process.
const { contextBridge, ipcRenderer, webUtils } = require("electron");

contextBridge.exposeInMainWorld("saidso", {
  get: (path) => ipcRenderer.invoke("api", { method: "GET", path }),
  post: (path, body) => ipcRenderer.invoke("api", { method: "POST", path, body }),
  pickRecordings: () => ipcRenderer.invoke("pick-recordings"),
  // File.path was removed in Electron 32; this is the supported replacement.
  pathForFile: (file) => webUtils.getPathForFile(file),
  pickFolder: (current) => ipcRenderer.invoke("pick-folder", current),
  reveal: (path) => ipcRenderer.invoke("reveal", path),
  onEvent: (handler) => {
    const listener = (_event, payload) => handler(payload);
    ipcRenderer.on("engine-event", listener);
    return () => ipcRenderer.removeListener("engine-event", listener);
  },
  onStatus: (handler) => {
    const listener = (_event, payload) => handler(payload);
    ipcRenderer.on("engine-status", listener);
    return () => ipcRenderer.removeListener("engine-status", listener);
  },
});
