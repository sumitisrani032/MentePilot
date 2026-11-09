/** Merchant page: shows sync status and usage, and saves feature switches. */

/* global shopify */

const FEATURES = ["image", "skin_analysis", "voice"];
const byId = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const token = await shopify.idToken();
  const response = await fetch(path, {
    ...options,
    headers: {
      ...options.headers,
      Authorization: `Bearer ${token}`,
    },
  });
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response.json();
}

function say(text) {
  byId("message").textContent = text;
}

function render(status) {
  byId("products").textContent = status.products;
  byId("indexed").textContent = status.indexed;
  byId("sync").textContent = status.sync ? status.sync.status : "not started";
  const failure = status.sync?.error;
  byId("sync-error").hidden = !failure;
  byId("sync-error").textContent = failure ?? "";
  byId("chats").textContent = status.usage.chat ?? 0;
  byId("images").textContent = status.usage.image ?? 0;
  for (const name of FEATURES) byId(name).checked = status.features[name];
  byId("voice").disabled = !status.voice_available;
  byId("voice-note").hidden = status.voice_available;
}

async function refresh() {
  render(await api("/admin/api/status"));
}

for (const name of FEATURES) {
  byId(name).addEventListener("change", async (event) => {
    try {
      await api("/admin/api/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [name]: event.target.checked }),
      });
      say("Saved.");
    } catch {
      event.target.checked = !event.target.checked;
      say("Could not save. Please try again.");
    }
  });
}

byId("resync").addEventListener("click", async () => {
  try {
    await api("/admin/api/resync", { method: "POST" });
    say("Sync started.");
  } catch {
    say("Could not start a sync. Please try again.");
  }
});

refresh().catch(() => say("Could not load the page. Please reload."));
