/**
 * main.js -- Electron entry point for Cluely Pro.
 *
 * Creates a stealth BrowserWindow that is:
 * - Transparent and frameless
 * - Always on top (screen-saver level)
 * - Excluded from screen capture (setContentProtection)
 * - Not visible in taskbar
 * - Non-focusable (won't steal focus)
 *
 * Spawns the Python backend as a child process and bridges
 * JSON-line IPC between Python and the renderer.
 */

const {
  app,
  BrowserWindow,
  globalShortcut,
  ipcMain,
  desktopCapturer,
  screen,
} = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const readline = require("readline");
const os = require("os");
const { shell } = require("electron");
const crypto = require("crypto");

// ─── API Key Storage ──────────────────────────────

function getConfigDir() {
  const dir = path.join(app.getPath("userData"), "config");
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  return dir;
}

function getStoredApiKey() {
  try {
    const file = path.join(getConfigDir(), "api-key.json");
    if (fs.existsSync(file)) {
      const data = JSON.parse(fs.readFileSync(file, "utf-8"));
      return data.groq_api_key || "";
    }
  } catch (e) {
    console.error("[electron] Failed to read API key:", e.message);
  }
  // Fallback: check .env
  const envPath = path.join(__dirname, ".env");
  if (fs.existsSync(envPath)) {
    const content = fs.readFileSync(envPath, "utf-8");
    const match = content.match(/GROQ_API_KEY=(.+)/);
    if (match) return match[1].trim();
  }
  return "";
}

function saveApiKey(key) {
  const file = path.join(getConfigDir(), "api-key.json");
  fs.writeFileSync(file, JSON.stringify({ groq_api_key: key }), "utf-8");
  console.log("[electron] API key saved");
}

function getStoredUserContext() {
  try {
    const file = path.join(getConfigDir(), "user-context.txt");
    if (fs.existsSync(file)) {
      return fs.readFileSync(file, "utf-8").substring(0, 1000);
    }
  } catch (e) {
    console.error("[electron] Failed to read user context:", e.message);
  }
  return "";
}

function saveUserContext(text) {
  const file = path.join(getConfigDir(), "user-context.txt");
  fs.writeFileSync(file, text.substring(0, 1000), "utf-8");
  console.log("[electron] User context saved");
}

// ─── License Key Storage ─────────────────────────

const LICENSE_SERVER_URL = "https://cluely-server.vercel.app"; // Change to your deployed URL

function getHWID() {
  const raw = `${os.hostname()}-${os.userInfo().username}-${(os.cpus()[0] || {}).model || "unknown"}-${os.platform()}`;
  return crypto.createHash("sha256").update(raw).digest("hex").substring(0, 32);
}

function getStoredLicenseKey() {
  try {
    const file = path.join(getConfigDir(), "license.json");
    if (fs.existsSync(file)) {
      const data = JSON.parse(fs.readFileSync(file, "utf-8"));
      return data.license_key || "";
    }
  } catch (e) {
    console.error("[electron] Failed to read license key:", e.message);
  }
  return "";
}

function saveLicenseKeyToFile(key) {
  const file = path.join(getConfigDir(), "license.json");
  fs.writeFileSync(file, JSON.stringify({ license_key: key }), "utf-8");
  console.log("[electron] License key saved");
}

let licenseState = {
  valid: false,
  plan: null,
  remainingAnswers: -1,
  remainingScreenshots: -1,
  expiresAt: null,
  token: null,
};

async function validateLicense() {
  const key = getStoredLicenseKey();
  if (!key) {
    licenseState.valid = false;
    return false;
  }
  try {
    const res = await fetch(`${LICENSE_SERVER_URL}/api/license/validate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ license_key: key, hwid: getHWID() }),
    });
    const data = await res.json();
    if (data.valid) {
      licenseState = {
        valid: true,
        plan: data.plan,
        remainingAnswers: data.remaining_answers,
        remainingScreenshots: data.remaining_screenshots,
        expiresAt: data.expires_at,
        token: data.token,
      };
      console.log(`[electron] License valid — Plan: ${data.plan}`);
      return true;
    } else {
      licenseState.valid = false;
      console.log(`[electron] License invalid: ${data.error}`);
      return false;
    }
  } catch (e) {
    console.error("[electron] License validation failed:", e.message);
    if (licenseState.valid) return true; // keep valid if server unreachable
    return false;
  }
}

async function trackUsage(type) {
  const key = getStoredLicenseKey();
  if (!key) return { error: "No license key" };
  try {
    const res = await fetch(`${LICENSE_SERVER_URL}/api/license/usage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ license_key: key, type }),
    });
    const data = await res.json();
    if (data.remaining !== undefined) {
      if (type === "answer") licenseState.remainingAnswers = data.remaining;
      if (type === "screenshot") licenseState.remainingScreenshots = data.remaining;
    }
    return data;
  } catch (e) {
    console.error("[electron] Usage tracking failed:", e.message);
    return { error: "Network error" };
  }
}

async function checkAndTrackUsage(type) {
  const remaining = type === "answer" ? licenseState.remainingAnswers : licenseState.remainingScreenshots;
  if (remaining === -1) return true; // unlimited
  if (remaining === 0) return false; // at limit
  const result = await trackUsage(type);
  if (result.limit_reached) return false;
  return true; // allow on network error
}

let mainWindow = null;
let pythonProcess = null;
let isVisible = true;

// ─── Window Setup ────────────────────────────────

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 420,
    height: 340,
    x: 20,
    y: 80,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    focusable: false,
    resizable: true,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Forward renderer console logs to our terminal
  mainWindow.webContents.on("console-message", (event, level, message, line, sourceId) => {
    console.log(`[renderer] ${message}`);
  });

  // Stealth: exclude from screen capture
  mainWindow.setContentProtection(true);

  // Highest z-order -- above everything
  mainWindow.setAlwaysOnTop(true, "screen-saver");

  // Make click-through when holding Ctrl (so you can interact with apps behind)
  mainWindow.setIgnoreMouseEvents(false);

  // Load the overlay UI
  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));

  // Don't show in alt-tab on Windows
  mainWindow.setSkipTaskbar(true);

  console.log("[electron] Stealth window created");
}

// ─── Python Backend ──────────────────────────────

function startPythonBackend() {
  let cmd, args, cwd;

  // In packaged mode, use the bundled PyInstaller exe
  const isPacked = app.isPackaged;
  if (isPacked) {
    const exeName = process.platform === "win32" ? "cluely-backend.exe" : "cluely-backend";
    cmd = path.join(process.resourcesPath, "backend", exeName);
    args = ["--ipc"];
    cwd = path.dirname(cmd);
  } else {
    cmd = process.platform === "win32" ? "python" : "python3";
    args = [path.join(__dirname, "backend", "main.py"), "--ipc"];
    cwd = __dirname;
  }

  // Pass API key and user context as env vars so Python can use them
  const apiKey = getStoredApiKey();
  const userContext = getStoredUserContext();
  const env = { ...process.env, PYTHONIOENCODING: "utf-8" };
  if (apiKey) env.GROQ_API_KEY = apiKey;
  if (userContext) env.CLUELY_USER_CONTEXT = userContext;

  pythonProcess = spawn(cmd, args, {
    stdio: ["pipe", "pipe", "pipe"],
    cwd: cwd,
    env: env,
  });

  console.log(`[electron] Python backend started (PID: ${pythonProcess.pid})`);

  // Read JSON lines from Python's stdout
  const rl = readline.createInterface({
    input: pythonProcess.stdout,
    crlfDelay: Infinity,
  });

  rl.on("line", (line) => {
    try {
      const msg = JSON.parse(line);
      handlePythonMessage(msg);
    } catch (e) {
      console.error("[electron] Failed to parse Python message:", line);
    }
  });

  // Log stderr
  pythonProcess.stderr.on("data", (data) => {
    const text = data.toString().trim();
    if (text) {
      console.log(`[python] ${text}`);
    }
  });

  pythonProcess.on("close", (code) => {
    console.log(`[electron] Python process exited with code ${code}`);
    pythonProcess = null;
  });

  pythonProcess.on("error", (err) => {
    console.error("[electron] Failed to start Python:", err.message);
  });
}

function handlePythonMessage(msg) {
  // Forward all messages to the renderer
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("python-message", msg);
  }
}

function sendToPython(command, data = {}) {
  if (pythonProcess && pythonProcess.stdin.writable) {
    const msg = JSON.stringify({ command, ...data });
    pythonProcess.stdin.write(msg + "\n");
  }
}

// ─── Screenshot Capture ─────────────────────────

async function captureScreenshot() {
  console.log("[electron] Capturing screenshot...");

  // Check screenshot usage limit
  if (licenseState.valid) {
    const allowed = await checkAndTrackUsage("screenshot");
    if (!allowed) {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send("python-message", {
          type: "answer_error",
          text: "Screenshot limit reached. Upgrade your plan at cluelypro.com",
        });
      }
      return;
    }
  }

  // Show the overlay is processing
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("python-message", {
      type: "screenshot_start",
    });
  }

  try {
    // Temporarily disable content protection so we can capture
    // (the overlay itself won't appear since it's content-protected)
    const sources = await desktopCapturer.getSources({
      types: ["screen"],
      thumbnailSize: {
        width: screen.getPrimaryDisplay().workAreaSize.width,
        height: screen.getPrimaryDisplay().workAreaSize.height,
      },
    });

    if (sources.length === 0) {
      console.error("[electron] No screen sources found");
      return;
    }

    // Get the primary screen
    const primarySource = sources[0];
    const image = primarySource.thumbnail;

    // Save to temp file
    const tmpPath = path.join(os.tmpdir(), `cluely_screenshot_${Date.now()}.png`);
    fs.writeFileSync(tmpPath, image.toPNG());

    console.log(`[electron] Screenshot saved: ${tmpPath}`);

    // Send to Python for vision analysis
    sendToPython("screenshot", { image_path: tmpPath });
  } catch (err) {
    console.error("[electron] Screenshot failed:", err.message);
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("python-message", {
        type: "answer_error",
        text: `Screenshot failed: ${err.message}`,
      });
    }
  }
}

// ─── Hotkeys ─────────────────────────────────────

function registerHotkeys() {
  // Toggle visibility — Ctrl+Shift+Z
  globalShortcut.register("CommandOrControl+Shift+Z", () => {
    if (mainWindow) {
      isVisible = !isVisible;
      if (isVisible) {
        mainWindow.show();
      } else {
        mainWindow.hide();
      }
      console.log(`[electron] Overlay ${isVisible ? "shown" : "hidden"}`);
    }
  });

  // Spawn/reopen window — Ctrl+Shift+P
  globalShortcut.register("CommandOrControl+Shift+P", () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.show();
      isVisible = true;
      console.log("[electron] Overlay re-opened");
    } else {
      createWindow();
      isVisible = true;
      console.log("[electron] Overlay spawned");
    }
  });

  // Screenshot + Answer — Ctrl+G
  globalShortcut.register("CommandOrControl+G", () => {
    captureScreenshot();
    console.log("[electron] Screenshot capture triggered");
  });

  // Force answer on last 10 seconds of audio
  globalShortcut.register("CommandOrControl+Shift+A", async () => {
    if (licenseState.valid) {
      const allowed = await checkAndTrackUsage("answer");
      if (!allowed) {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send("python-message", {
            type: "answer_error",
            text: "Answer limit reached. Upgrade your plan at cluelypro.com",
          });
        }
        return;
      }
    }
    sendToPython("force_answer");
    console.log("[electron] Force answer triggered");
  });

  // Toggle listening
  globalShortcut.register("CommandOrControl+Shift+L", () => {
    sendToPython("toggle");
    console.log("[electron] Toggle listening");
  });

  console.log("[electron] Hotkeys registered:");
  console.log("  Ctrl+Shift+Z -> Toggle overlay visibility");
  console.log("  Ctrl+Shift+P -> Reopen/spawn overlay");
  console.log("  Ctrl+G       -> Screenshot + AI answer");
  console.log("  Ctrl+Shift+A -> Force answer on last 10s audio");
  console.log("  Ctrl+Shift+L -> Toggle listening on/off");
}

// ─── IPC from Renderer ──────────────────────────

ipcMain.on("renderer-command", async (event, data) => {
  if (data.command === "screenshot") {
    captureScreenshot();
  } else if (data.command === "chat" || data.command === "force_answer") {
    // Check answer usage limit
    if (licenseState.valid) {
      const allowed = await checkAndTrackUsage("answer");
      if (!allowed) {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send("python-message", {
            type: "answer_error",
            text: "Answer limit reached. Upgrade your plan at cluelypro.com",
          });
        }
        return;
      }
    }
    sendToPython(data.command, data);
  } else {
    sendToPython(data.command, data);
  }
});

ipcMain.on("set-ignore-mouse", (event, ignore) => {
  if (mainWindow) {
    mainWindow.setIgnoreMouseEvents(ignore, { forward: true });
  }
});

ipcMain.on("close-window", () => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.hide();
    isVisible = false;
    console.log("[electron] Overlay closed (Ctrl+Shift+P to reopen)");
  }
});

ipcMain.on("set-focusable", (event, focusable) => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.setFocusable(focusable);
    if (focusable) {
      mainWindow.focus();
    }
  }
});

ipcMain.handle("get-api-key", () => {
  return getStoredApiKey();
});

ipcMain.handle("get-user-context", () => {
  return getStoredUserContext();
});

ipcMain.handle("save-user-context", (event, text) => {
  saveUserContext(text);
  // Tell Python backend about the new context
  sendToPython("set_user_context", { user_context: text.substring(0, 1000) });
  return true;
});

ipcMain.handle("save-api-key", (event, key) => {
  saveApiKey(key);
  // Restart python backend with new key
  if (pythonProcess) {
    sendToPython("quit");
    setTimeout(() => {
      if (pythonProcess) pythonProcess.kill();
      pythonProcess = null;
      startPythonBackend();
    }, 1000);
  } else {
    startPythonBackend();
  }
  return true;
});

ipcMain.on("open-external", (event, url) => {
  shell.openExternal(url);
});

ipcMain.handle("get-license-key", () => {
  return getStoredLicenseKey();
});

ipcMain.handle("save-license-key", async (event, key) => {
  saveLicenseKeyToFile(key);
  const valid = await validateLicense();
  if (valid && !pythonProcess && getStoredApiKey()) {
    startPythonBackend();
  }
  return { valid, ...licenseState };
});

ipcMain.handle("get-license-status", () => {
  return { ...licenseState };
});

// ─── App Lifecycle ───────────────────────────────

app.whenReady().then(async () => {
  createWindow();

  const licenseValid = await validateLicense();
  const hasApiKey = !!getStoredApiKey();

  if (licenseValid && hasApiKey) {
    startPythonBackend();
  } else {
    console.log("[electron] Waiting for license key and/or API key...");
  }

  registerHotkeys();

  // Hourly license heartbeat
  setInterval(async () => {
    const valid = await validateLicense();
    if (!valid && pythonProcess) {
      console.log("[electron] License expired, stopping backend");
      sendToPython("quit");
      setTimeout(() => {
        if (pythonProcess) pythonProcess.kill();
        pythonProcess = null;
      }, 1000);
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send("python-message", {
          type: "answer_error",
          text: "License expired. Please renew at cluelypro.com",
        });
      }
    }
  }, 60 * 60 * 1000);
});

app.on("will-quit", () => {
  globalShortcut.unregisterAll();
  if (pythonProcess) {
    sendToPython("quit");
    setTimeout(() => {
      if (pythonProcess) {
        pythonProcess.kill();
      }
    }, 2000);
  }
});

app.on("window-all-closed", () => {
  app.quit();
});
