chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== "SUBMIT_CAPTURE") {
    return false;
  }

  chrome.storage.sync.get(
    {
      apiBaseUrl: "http://localhost:8000",
      apiKey: ""
    },
    async (cfg) => {
      try {
        const response = await fetch(`${cfg.apiBaseUrl.replace(/\/$/, "")}/api/social/captures`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-API-Key": cfg.apiKey || ""
          },
          body: JSON.stringify(message.payload)
        });

        const body = await response.json().catch(() => ({}));
        sendResponse({ ok: response.ok, status: response.status, body });
      } catch (error) {
        sendResponse({ ok: false, status: 0, body: { error: String(error) } });
      }
    }
  );

  return true;
});
