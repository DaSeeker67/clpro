/**
 * preload.js — IPC bridge between Electron main process and renderer.
 *
 * Exposes a safe API to the renderer via contextBridge.
 * No node integration in the renderer — all communication goes through here.
 */

const { contextBridge, ipcRenderer, clipboard } = require("electron");

contextBridge.exposeInMainWorld("copilot", {
  copyToClipboard: (text) => {
    clipboard.writeText(text);
  },
  onMessage: (callback) => {
    ipcRenderer.on("python-message", (event, msg) => {
      callback(msg);
    });
  },
  sendCommand: (command, data = {}) => {
    ipcRenderer.send("renderer-command", { command, ...data });
  },
  setIgnoreMouse: (ignore) => {
    ipcRenderer.send("set-ignore-mouse", ignore);
  },
  closeWindow: () => {
    ipcRenderer.send("close-window");
  },
  setFocusable: (focusable) => {
    ipcRenderer.send("set-focusable", focusable);
  },
  getApiKey: () => {
    return ipcRenderer.invoke("get-api-key");
  },
  saveApiKey: (key) => {
    return ipcRenderer.invoke("save-api-key", key);
  },
  getUserContext: () => {
    return ipcRenderer.invoke("get-user-context");
  },
  saveUserContext: (text) => {
    return ipcRenderer.invoke("save-user-context", text);
  },
  openExternal: (url) => {
    ipcRenderer.send("open-external", url);
  },
  getLicenseKey: () => {
    return ipcRenderer.invoke("get-license-key");
  },
  saveLicenseKey: (key) => {
    return ipcRenderer.invoke("save-license-key", key);
  },
  getLicenseStatus: () => {
    return ipcRenderer.invoke("get-license-status");
  },
  quitApp: () => {
    ipcRenderer.send("quit-app");
  },
});
