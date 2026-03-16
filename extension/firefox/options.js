const DEFAULT_SETTINGS = {
  apiBaseUrl: "http://localhost:8000",
  apiKey: ""
};

function getStorageArea() {
  return chrome.storage?.sync || chrome.storage?.local;
}

function readSettings() {
  return new Promise((resolve) => {
    const area = getStorageArea();
    if (!area) {
      resolve({ ...DEFAULT_SETTINGS });
      return;
    }

    area.get(DEFAULT_SETTINGS, (cfg) => {
      const fallbackCfg = cfg || {};
      if (chrome.runtime?.lastError) {
        const localArea = chrome.storage?.local;
        if (!localArea || localArea === area) {
          resolve({ ...DEFAULT_SETTINGS });
          return;
        }
        localArea.get(DEFAULT_SETTINGS, (localCfg) => {
          resolve({ ...DEFAULT_SETTINGS, ...(localCfg || {}) });
        });
        return;
      }
      resolve({ ...DEFAULT_SETTINGS, ...fallbackCfg });
    });
  });
}

function writeSettings(next) {
  return new Promise((resolve) => {
    const area = getStorageArea();
    if (!area) {
      resolve(false);
      return;
    }

    area.set(next, () => {
      if (chrome.runtime?.lastError) {
        const localArea = chrome.storage?.local;
        if (!localArea || localArea === area) {
          resolve(false);
          return;
        }
        localArea.set(next, () => resolve(!chrome.runtime?.lastError));
        return;
      }
      resolve(true);
    });
  });
}

async function restoreOptions() {
  const cfg = await readSettings();
  document.getElementById("apiBaseUrl").value = cfg.apiBaseUrl || DEFAULT_SETTINGS.apiBaseUrl;
  document.getElementById("apiKey").value = cfg.apiKey || DEFAULT_SETTINGS.apiKey;
}

async function saveOptions() {
  const apiBaseUrl = document.getElementById("apiBaseUrl").value.trim();
  const apiKey = document.getElementById("apiKey").value.trim();
  const status = document.getElementById("status");
  const ok = await writeSettings({ apiBaseUrl, apiKey });

  status.textContent = ok ? "Saved." : "Failed to save settings.";
  setTimeout(() => {
    status.textContent = "";
  }, 1800);
}

document.addEventListener("DOMContentLoaded", restoreOptions);
document.getElementById("save").addEventListener("click", saveOptions);
