async function ensureCollector(tab) {
  if (!tab?.id) {
    throw new Error("No active tab id.");
  }

  const url = tab.url || "";
  if (!/^https?:\/\/([^/]+\.)?facebook\.com\//i.test(url)) {
    throw new Error("Open a facebook.com page before running capture.");
  }

  // Always inject to guarantee collector availability on the current document.
  if (chrome.scripting?.executeScript) {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["content.js"]
    });
    return;
  }

  if (chrome.tabs?.executeScript) {
    await chrome.tabs.executeScript(tab.id, { file: "content.js" });
    return;
  }

  throw new Error("Browser does not support script injection APIs required for capture.");
}

async function collectFromPage(tabId) {
  // Primary path: ask injected content script to build the payload.
  try {
    const response = await chrome.tabs.sendMessage(tabId, { type: "CAPTURE_SOCIAL" });
    console.log(response);
    if (response?.ok && response.payload) {
      return response.payload;
    }
    if (response && !response.ok && response.error) {
      throw new Error(String(response.error));
    }
  } catch {
    // Fall through to executeScript fallback.
  }

  // Fallback path for environments where tab messaging is flaky.
  if (chrome.scripting?.executeScript) {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: async () => {
        if (typeof window.__facefieldCollectSocial !== "function") {
          throw new Error("Collector is not initialized in this tab.");
        }
        return window.__facefieldCollectSocial();
      }
    });
    return results?.[0]?.result;
  }

  throw new Error("Browser does not support script execution APIs required for capture.");
}

function loadSettings() {
  return new Promise((resolve) => {
    const syncArea = chrome.storage?.sync;
    const localArea = chrome.storage?.local;
    const area = syncArea || localArea;
    if (!area) {
      resolve({ ...DEFAULT_SETTINGS });
      return;
    }

    area.get(DEFAULT_SETTINGS, (cfg) => {
      if (chrome.runtime?.lastError && localArea && area !== localArea) {
        localArea.get(DEFAULT_SETTINGS, (localCfg) => {
          resolve({ ...DEFAULT_SETTINGS, ...(localCfg || {}) });
        });
        return;
      }
      resolve({ ...DEFAULT_SETTINGS, ...(cfg || {}) });
    });
  });
}

async function submitCapture(payload) {
  const cfg = await loadSettings();
  const response = await fetch(`${String(cfg.apiBaseUrl || "").replace(/\/$/, "")}/api/social/captures`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": cfg.apiKey || ""
    },
    body: JSON.stringify(payload)
  });
  const body = await response.json().catch(() => ({}));
  return { ok: response.ok, status: response.status, body };
}

async function captureCurrentTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) {
    return { ok: false, error: "No active tab found." };
  }

  await ensureCollector(tab);

  const payload = await collectFromPage(tab.id);
  console.log(payload);
  if (!payload || !Array.isArray(payload.interactions)) {
    return { ok: false, error: "Collector returned no usable payload." };
  }

  const submitResult = await submitCapture(payload);

  if (!submitResult?.ok) {
    const details = JSON.stringify(submitResult?.body || {}, null, 2);
    return { ok: false, error: `Backend rejected capture (status ${submitResult?.status}).\n${details}` };
  }

  return {
    ok: true,
    body: submitResult.body,
    interactionCount: payload.interactions.length || 0
  };
}

document.getElementById("capture").addEventListener("click", async () => {
  const statusEl = document.getElementById("status");
  statusEl.textContent = "Capturing...";

  try {
    const result = await captureCurrentTab();
    if (!result.ok) {
      statusEl.textContent = `Error: ${result.error}`;
      return;
    }
    statusEl.textContent = `Captured ${result.interactionCount} interactions.\nInserted: ${result.body.inserted}\nUpdated: ${result.body.updated}`;
  } catch (error) {
    statusEl.textContent = `Error: ${String(error)}`;
  }
});
const DEFAULT_SETTINGS = {
  apiBaseUrl: "http://localhost:8000",
  apiKey: ""
};
