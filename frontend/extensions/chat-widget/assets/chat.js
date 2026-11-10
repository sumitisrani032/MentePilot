/** Storefront chat widget. All logic lives in the backend; this only renders it. */

const SESSION_KEY = "shopchat-session-id";
const TRANSCRIPT_KEY = "shopchat-transcript";
const OPEN_KEY = "shopchat-open";
const MAX_TRANSCRIPT_ENTRIES = 40;
const STATUS_STEPS = [
  "Thinking about what you need",
  "Searching the store",
  "Comparing products",
  "Picking the best matches",
];
const STATUS_INTERVAL_MS = 1800;

/** Split a server-sent event buffer into complete events and the unfinished rest. */
export function parseSse(buffer) {
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop();
  const events = blocks.map((block) => {
    const lines = block.split("\n");
    const name = lines.find((line) => line.startsWith("event:"));
    const data = lines.find((line) => line.startsWith("data:"));
    return {
      event: name ? name.slice(6).trim() : "message",
      data: data ? JSON.parse(data.slice(5).trim()) : null,
    };
  });
  return { events, rest };
}

/** Customer-facing wording for a failed chat request. */
export function errorText(status) {
  if (status === 413)
    return "That file is too large. Please try a smaller one.";
  if (status === 415) return "Please use a JPEG, PNG or WebP photo.";
  if (status === 403) return "That option isn't available in this store.";
  return "Sorry, I couldn't reach the assistant. Please try again.";
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const ICONS = {
  sparkle:
    '<path fill="currentColor" stroke="none" d="M12 1.5 14.6 9.4 22.5 12l-7.9 2.6L12 22.5l-2.6-7.9L1.5 12l7.9-2.6z"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  restart: '<path d="M4 12a8 8 0 1 0 2.6-5.9L4 8.5M4 4v4.5h4.5"/>',
  send: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  photo:
    '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="1.5"/><path d="m4 18 5.5-5 3.5 3 3-2.5 4 4"/>',
  skin: '<circle cx="12" cy="12" r="9"/><path d="M9 10h.01M15 10h.01M9 15c1.8 1.4 4.2 1.4 6 0"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  sound:
    '<path d="M4 10v4h3l5 4V6L7 10zM16 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11"/>',
  previous: '<path d="m15 5-7 7 7 7"/>',
  next: '<path d="m9 5 7 7-7 7"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
  maximize: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  restore: '<path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/>',
};

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("shopchat-icon");
  svg.innerHTML = ICONS[name];
  return svg;
}

function iconButton(className, iconName, label) {
  const button = element("button", className);
  button.type = "button";
  button.setAttribute("aria-label", label);
  button.append(icon(iconName));
  return button;
}

function isWebUrl(url) {
  try {
    return ["http:", "https:"].includes(new URL(url).protocol);
  } catch {
    return false;
  }
}

function formatPrice(amount, currency) {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
    }).format(Number(amount));
  } catch {
    return `${amount} ${currency}`;
  }
}

function readStored(key, fallback) {
  try {
    const stored = window.sessionStorage.getItem(key);
    return stored === null ? fallback : JSON.parse(stored);
  } catch {
    return fallback;
  }
}

function writeStored(key, value) {
  try {
    window.sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Without storage the chat still works; it just won't survive a page change.
  }
}

function forgetSession() {
  try {
    window.sessionStorage.removeItem(SESSION_KEY);
    window.sessionStorage.removeItem(TRANSCRIPT_KEY);
  } catch {
    // Storage is unavailable, so a new id is already made on every message.
  }
}

function sessionId() {
  try {
    const stored = window.sessionStorage.getItem(SESSION_KEY);
    if (stored) return stored;
    const created = window.crypto.randomUUID();
    window.sessionStorage.setItem(SESSION_KEY, created);
    return created;
  } catch {
    return window.crypto.randomUUID();
  }
}

function sectionAsText(section) {
  const products = section.cards.map(
    (card) => `- ${card.title}: ${formatPrice(card.price, card.currency)}`,
  );
  const extras = [
    ...(section.how_to_use ?? []).map((line) => `How to use: ${line}`),
    ...(section.tips ?? []).map((line) => `Tip: ${line}`),
  ];
  return [section.heading, section.detail, ...products, ...extras]
    .filter(Boolean)
    .join("\n");
}

function buildCopyButton(text) {
  const copy = element("button", "shopchat-copy");
  copy.type = "button";
  const label = element("span", "", "Copy");
  copy.append(icon("copy"), label);
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(text);
      label.textContent = "Copied";
    } catch {
      label.textContent = "Select the text to copy";
    }
    setTimeout(() => {
      label.textContent = "Copy";
    }, 1800);
  });
  return copy;
}

function buildCardInfo(card) {
  if (!card.description && !card.reason) return null;
  const info = element("div", "shopchat-card-info");
  info.hidden = true;
  if (card.reason) info.append(element("p", "shopchat-card-why", card.reason));
  if (card.description) info.append(element("p", "", card.description));
  const details = element("a", "shopchat-card-details", "View full details");
  details.href = card.url;
  details.target = "_blank";
  details.rel = "noopener noreferrer";
  info.append(details);
  return info;
}

function buildCard(card) {
  const item = element("article", "shopchat-card");
  const top = element("div", "shopchat-card-top");
  const media = element("a", "shopchat-card-media");
  media.href = card.url;
  media.target = "_blank";
  media.rel = "noopener noreferrer";
  media.setAttribute("aria-label", card.title);
  if (card.image_url && isWebUrl(card.image_url)) {
    const image = element("img", "");
    image.src = card.image_url;
    image.alt = "";
    image.loading = "lazy";
    media.append(image);
  } else {
    media.append(icon("sparkle"));
  }
  top.append(media);

  const info = buildCardInfo(card);
  if (info) {
    const button = iconButton(
      "shopchat-info",
      "info",
      `Details for ${card.title}`,
    );
    button.setAttribute("aria-expanded", "false");
    button.addEventListener("click", () => {
      info.hidden = !info.hidden;
      button.setAttribute("aria-expanded", String(!info.hidden));
      button.replaceChildren(icon(info.hidden ? "info" : "close"));
    });
    top.append(info, button);
  }

  const body = element("div", "shopchat-card-body");
  if (card.vendor)
    body.append(element("p", "shopchat-card-vendor", card.vendor));
  body.append(element("h4", "shopchat-card-title", card.title));
  const price = element(
    "p",
    "shopchat-card-price",
    formatPrice(card.price, card.currency),
  );
  if (card.compare_at_price) {
    price.append(
      " ",
      element("s", "", formatPrice(card.compare_at_price, card.currency)),
    );
  }
  body.append(price);

  const view = element("a", "shopchat-view", "View product");
  view.href = card.url;
  view.target = "_blank";
  view.rel = "noopener noreferrer";
  body.append(view);

  item.append(top, body);
  return item;
}

/** One toggle for the whole reply, with the steps grouped by section. */
function buildHowToUse(sections) {
  const groups = sections.filter((section) => section.how_to_use?.length);
  if (!groups.length) return null;
  const more = element("details", "shopchat-more");
  more.append(element("summary", "", "How to use"));
  for (const section of groups) {
    more.append(element("h5", "shopchat-more-group", section.heading));
    const list = element("ul", "");
    for (const line of section.how_to_use) {
      list.append(element("li", "", line));
    }
    more.append(list);
  }
  return more;
}

function buildMore(label, lines) {
  if (!lines?.length) return null;
  const more = element("details", "shopchat-more");
  more.append(element("summary", "", label));
  const list = element("ul", "");
  for (const line of lines) list.append(element("li", "", line));
  more.append(list);
  return more;
}

function buildSection(section) {
  const cards = section.cards.filter((card) => isWebUrl(card.url));
  if (!cards.length) return null;

  const node = element("section", "shopchat-section");
  node.append(element("h3", "shopchat-heading", section.heading));
  if (section.detail)
    node.append(element("p", "shopchat-detail", section.detail));

  const track = element("div", "shopchat-cards");
  track.tabIndex = 0;
  track.setAttribute("aria-label", `${section.heading} products`);
  track.append(...cards.map(buildCard));
  node.append(track);

  const nav = element("div", "shopchat-nav");
  const previous = iconButton("shopchat-prev", "previous", "Previous products");
  const next = iconButton("shopchat-next", "next", "More products");
  nav.append(previous, next);
  node.append(nav);

  const step = (direction) => {
    const width = track.firstElementChild.getBoundingClientRect().width + 12;
    track.scrollBy({ left: direction * width });
  };
  previous.addEventListener("click", () => step(-1));
  next.addEventListener("click", () => step(1));

  const refresh = () => {
    const overflow = track.scrollWidth - track.clientWidth;
    nav.hidden = overflow <= 1;
    previous.disabled = track.scrollLeft <= 1;
    next.disabled = track.scrollLeft >= overflow - 1;
  };
  track.addEventListener("scroll", refresh, { passive: true });
  track.addEventListener("load", refresh, true);

  return { node, refresh };
}

/** A header button that grows the panel to fill the window, and back. */
function maximizeButton(panel) {
  const button = iconButton("shopchat-maximize", "maximize", "Maximize chat");
  button.setAttribute("aria-pressed", "false");
  button.addEventListener("click", () => {
    const maximized = panel.classList.toggle("shopchat-maximized");
    button.setAttribute("aria-pressed", String(maximized));
    button.setAttribute(
      "aria-label",
      maximized ? "Restore chat size" : "Maximize chat",
    );
    button.replaceChildren(icon(maximized ? "restore" : "maximize"));
  });
  return button;
}

export function createWidget(root, { greeting, maximizable = false }) {
  root.className = "shopchat";

  const toggle = element("button", "shopchat-toggle");
  toggle.type = "button";
  toggle.setAttribute("aria-label", "Open shopping assistant");
  toggle.append(icon("sparkle"), element("span", "", "Ask"));

  const panel = element("section", "shopchat-panel");
  panel.hidden = true;
  panel.setAttribute("aria-label", "Shopping assistant");

  const header = element("header", "shopchat-header");
  const brand = element("div", "shopchat-brand");
  brand.append(icon("sparkle"), element("span", "", "Shop assistant"));
  const restart = iconButton("shopchat-restart", "restart", "Start a new chat");
  const close = iconButton("shopchat-close", "close", "Close");
  header.append(brand, restart);
  // Only pages that ask for it (the local development page) get this button.
  if (maximizable) header.append(maximizeButton(panel));
  header.append(close);

  const log = element("div", "shopchat-log");
  log.setAttribute("role", "log");
  log.setAttribute("aria-live", "polite");

  const form = element("form", "shopchat-form");
  const input = element("input", "shopchat-input");
  input.type = "text";
  input.maxLength = 1000;
  input.placeholder = "Ask me anything";
  input.setAttribute("aria-label", "Your message");

  const mic = iconButton("shopchat-mic", "mic", "Speak your message");
  mic.hidden = true;

  const send = iconButton("shopchat-send", "send", "Send");
  send.type = "submit";

  const mute = iconButton("shopchat-mute", "sound", "Mute spoken replies");
  mute.hidden = true;
  mute.setAttribute("aria-pressed", "false");

  const fileInput = element("input", "shopchat-file");
  fileInput.type = "file";
  fileInput.accept = "image/jpeg,image/png,image/webp";
  fileInput.hidden = true;
  fileInput.setAttribute("aria-label", "Choose a photo");

  const photo = iconButton("shopchat-photo", "photo", "Upload a photo");

  const skin = iconButton(
    "shopchat-skin",
    "skin",
    "Get skin care suggestions from a photo",
  );
  skin.hidden = true;

  const attachmentNote = element("p", "shopchat-attachment");
  attachmentNote.hidden = true;

  const consent = element("div", "shopchat-consent");
  consent.hidden = true;
  consent.setAttribute("role", "dialog");
  const consentText = element("p", "");
  const agree = element("button", "shopchat-agree", "I agree");
  agree.type = "button";
  const decline = element("button", "shopchat-decline", "No thanks");
  decline.type = "button";
  consent.append(consentText, agree, decline);

  form.append(input, photo, skin, mic, mute, send);
  panel.append(header, log, consent, attachmentNote, fileInput, form);
  root.append(toggle, panel);

  function addMessage(text, who) {
    const bubble = element("p", `shopchat-message shopchat-${who}`, text);
    log.append(bubble);
    log.scrollTop = log.scrollHeight;
    return bubble;
  }

  const suggestionList = element("div", "shopchat-suggestions");
  suggestionList.setAttribute("aria-label", "Suggested questions");

  function showSuggestions() {
    if (suggestionList.childElementCount) log.append(suggestionList);
    suggestionList.hidden = false;
    log.scrollTop = log.scrollHeight;
  }

  function hideSuggestions() {
    suggestionList.hidden = true;
  }

  function greet() {
    addMessage(greeting, "bot");
    showSuggestions();
  }

  greet();

  const transcript = [];

  // What the next send will upload. Consent is only ever set by the agree button.
  let purpose = "product";
  let skinConsent = false;
  let attachment = null;
  let muted = false;
  let voiceEnabled = false;

  mute.addEventListener("click", () => {
    muted = !muted;
    mute.classList.toggle("shopchat-muted", muted);
    mute.setAttribute("aria-pressed", String(muted));
  });

  function clearAttachment() {
    attachment = null;
    purpose = "product";
    skinConsent = false;
    fileInput.value = "";
    attachmentNote.hidden = true;
  }

  photo.addEventListener("click", () => {
    purpose = "product";
    skinConsent = false;
    fileInput.click();
  });
  skin.addEventListener("click", () => {
    consent.hidden = false;
  });
  decline.addEventListener("click", () => {
    consent.hidden = true;
    clearAttachment();
  });
  agree.addEventListener("click", () => {
    consent.hidden = true;
    purpose = "skin";
    skinConsent = true;
    fileInput.click();
  });
  fileInput.addEventListener("change", () => {
    const [file] = fileInput.files;
    if (!file) return;
    attachment = file;
    attachmentNote.textContent = `Attached: ${file.name}`;
    attachmentNote.hidden = false;
  });

  function setOpen(open, { moveFocus = true } = {}) {
    panel.hidden = !open;
    toggle.hidden = open;
    writeStored(OPEN_KEY, open);
    if (!moveFocus) return;
    if (open) input.focus();
    else toggle.focus();
  }

  toggle.addEventListener("click", () => setOpen(true));
  close.addEventListener("click", () => setOpen(false));
  panel.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setOpen(false);
  });

  function buildChips(questions, className) {
    const list = element("div", className);
    for (const question of questions) {
      const chip = element("button", "shopchat-chip", question);
      chip.type = "button";
      chip.addEventListener("click", () => {
        input.value = question;
        form.requestSubmit();
      });
      list.append(chip);
    }
    return list;
  }

  let onRestart = () => {};
  restart.addEventListener("click", () => {
    log.replaceChildren();
    transcript.length = 0;
    greet();
    clearAttachment();
    onRestart();
  });

  return {
    form,
    input,
    send,
    panel,
    log,
    addMessage,

    showSuggestions,
    hideSuggestions,

    setSuggestions(questions) {
      const built = buildChips(questions, "shopchat-suggestions");
      suggestionList.replaceChildren(...built.children);
      if (!suggestionList.isConnected && log.childElementCount <= 1) {
        showSuggestions();
      }
    },

    startBotMessage() {
      hideSuggestions();
      log.querySelectorAll(".shopchat-quick").forEach((old) => old.remove());
      const bubble = addMessage("", "bot");
      bubble.hidden = true;

      const status = element("p", "shopchat-status");
      const statusText = element("span", "", STATUS_STEPS[0]);
      status.append(icon("sparkle"), statusText);
      log.append(status);
      log.scrollTop = log.scrollHeight;

      let step = 0;
      const timer = setInterval(() => {
        step = (step + 1) % STATUS_STEPS.length;
        statusText.textContent = STATUS_STEPS[step];
      }, STATUS_INTERVAL_MS);
      timer.unref?.();

      const stopStatus = () => {
        clearInterval(timer);
        status.remove();
      };
      const copyParts = [];

      return {
        element: bubble,
        status,
        append(text) {
          stopStatus();
          bubble.hidden = false;
          bubble.textContent += text;
          log.scrollTop = log.scrollHeight;
        },
        addCopyText(text) {
          copyParts.push(text);
        },
        finish() {
          stopStatus();
          const text = [bubble.textContent, ...copyParts]
            .filter(Boolean)
            .join("\n\n");
          if (text) log.append(buildCopyButton(text));
        },
      };
    },

    /** Draw the product groups, shared toggles, and what to do next. */
    renderSections(sections, bubble, extras = {}) {
      let first = null;
      const shown = [];
      for (const section of sections) {
        const built = buildSection(section);
        if (!built) continue;
        bubble?.addCopyText(sectionAsText(section));
        log.append(built.node);
        built.refresh();
        first ??= built.node;
        shown.push(section);
      }
      const allTips = shown.flatMap((section) => section.tips ?? []);
      for (const more of [buildHowToUse(shown), buildMore("Tips", allTips)]) {
        if (more) log.append(more);
      }
      if (extras.follow_up_question) {
        log.append(
          element("p", "shopchat-follow-up", extras.follow_up_question),
        );
        bubble?.addCopyText(extras.follow_up_question);
      }
      if (extras.quick_replies?.length) {
        log.append(buildChips(extras.quick_replies, "shopchat-quick"));
      }
      if (first) log.scrollTop = first.offsetTop;
    },

    remember(entry) {
      transcript.push(entry);
      writeStored(TRANSCRIPT_KEY, transcript.slice(-MAX_TRANSCRIPT_ENTRIES));
    },

    /** Redraw the conversation after the customer moves to another page. */
    restore() {
      for (const entry of readStored(TRANSCRIPT_KEY, [])) {
        transcript.push(entry);
        if (entry.who === "customer") {
          hideSuggestions();
          addMessage(entry.text, "customer");
        } else {
          const bubble = this.startBotMessage();
          if (entry.text) bubble.append(entry.text);
          if (entry.reply) {
            this.renderSections(entry.reply.sections, bubble, entry.reply);
          }
          bubble.finish();
        }
      }
      if (readStored(OPEN_KEY, false)) setOpen(true, { moveFocus: false });
    },

    setOnRestart(callback) {
      onRestart = callback;
    },

    applyFeatures(features) {
      mic.hidden = !features.voice;
      mute.hidden = !features.voice;
      voiceEnabled = features.voice;
      photo.hidden = !features.image;
      skin.hidden = !features.skin_analysis;
    },

    setConsentText(text) {
      consentText.textContent = text;
    },

    /** Add the pending photo to a request, then forget it so consent is per photo. */
    consumeAttachment(body) {
      if (!attachment) return false;
      body.append("image", attachment);
      body.append("image_purpose", purpose);
      if (skinConsent) body.append("skin_consent", "true");
      clearAttachment();
      return true;
    },

    mic,
    shouldSpeak: () => voiceEnabled && !muted,
    hasAttachment: () => attachment !== null,
    setAttachment(file) {
      attachment = file;
    },

    handleSessionFailure(status) {
      if (status === 403) root.hidden = true;
    },
  };
}

async function readStream(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    // The server separates fields with CRLF; a pair can straddle two chunks.
    buffer = (buffer + decoder.decode(value, { stream: true })).replaceAll(
      "\r\n",
      "\n",
    );
    const parsed = parseSse(buffer);
    buffer = parsed.rest;
    parsed.events.forEach(onEvent);
  }
}

function connect(widget, sessionUrl) {
  let session = null;

  async function openSession() {
    const url = `${sessionUrl}?origin=${encodeURIComponent(window.location.origin)}`;
    const response = await fetch(url, { method: "POST" });
    if (!response.ok) {
      widget.handleSessionFailure(response.status);
      throw new Error(`session failed: ${response.status}`);
    }
    session = await response.json();
    widget.applyFeatures(session.features);
    widget.setConsentText(session.skin_consent_text);
    widget.setSuggestions(session.suggestions ?? []);
  }

  async function post(path, body, retry = true) {
    if (!session) await openSession();
    const response = await fetch(`${session.api_base}${path}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${session.token}` },
      body,
    });
    if (response.status === 401 && retry) {
      session = null;
      return post(path, body, false);
    }
    return response;
  }

  async function submit(formData) {
    const bubble = widget.startBotMessage();
    let reply = null;
    widget.send.disabled = true;
    try {
      const response = await post("/v1/chat", formData);
      if (!response.ok) {
        bubble.append(errorText(response.status));
        return;
      }
      await readStream(response, ({ event, data }) => {
        if (event === "token") bubble.append(data.text);
        if (event === "sections") {
          reply = data;
          widget.renderSections(data.sections, bubble, data);
        }
        if (event === "error") bubble.append(data.message);
      });
    } catch {
      bubble.append("Sorry, I couldn't reach the assistant. Please try again.");
    } finally {
      widget.send.disabled = false;
      bubble.finish();
      if (!reply) widget.showSuggestions();
      widget.remember({ who: "bot", text: bubble.element.textContent, reply });
    }
    if (widget.shouldSpeak()) speak(bubble.element.textContent);
  }

  async function speak(text) {
    const body = new FormData();
    body.append("text", text.slice(0, 1000));
    const response = await post("/v1/voice/speak", body).catch(() => null);
    if (!response?.ok) return;
    const url = URL.createObjectURL(await response.blob());
    const audio = new Audio(url);
    audio.addEventListener("ended", () => URL.revokeObjectURL(url));
    audio.play().catch(() => URL.revokeObjectURL(url));
  }

  async function transcribe(blob) {
    const body = new FormData();
    body.append("audio", new File([blob], "speech.webm", { type: blob.type }));
    const response = await post("/v1/voice/transcribe", body);
    if (!response.ok) throw new Error(`transcribe failed: ${response.status}`);
    return (await response.json()).text;
  }

  return { openSession, submit, transcribe };
}

function attachMicrophone(widget, client) {
  let recorder = null;

  widget.mic.addEventListener("click", async () => {
    if (recorder) {
      recorder.stop();
      return;
    }
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      widget.addMessage("I couldn't access your microphone.", "bot");
      return;
    }
    const chunks = [];
    recorder = new MediaRecorder(stream);
    recorder.addEventListener("dataavailable", (event) =>
      chunks.push(event.data),
    );
    recorder.addEventListener("stop", async () => {
      const type = recorder.mimeType.split(";")[0];
      recorder = null;
      widget.mic.classList.remove("shopchat-recording");
      stream.getTracks().forEach((track) => track.stop());
      try {
        widget.input.value = await client.transcribe(
          new Blob(chunks, { type }),
        );
        widget.form.requestSubmit();
      } catch {
        widget.addMessage(
          "Sorry, I couldn't hear that. Please try again.",
          "bot",
        );
      }
    });
    recorder.start();
    widget.mic.classList.add("shopchat-recording");
  });
}

function boot() {
  const root = document.getElementById("shopchat-root");
  if (!root) return;
  const widget = createWidget(root, {
    greeting: root.dataset.greeting,
    maximizable: "maximizable" in root.dataset,
  });
  const client = connect(widget, root.dataset.sessionUrl);
  widget.restore();
  client.openSession().catch(() => {});
  attachMicrophone(widget, client);
  widget.setOnRestart(forgetSession);

  widget.form.addEventListener("submit", (event) => {
    event.preventDefault();
    const message = widget.input.value.trim();
    if (!message && !widget.hasAttachment()) return;
    const shownMessage = message || "Sent a photo";
    widget.addMessage(shownMessage, "customer");
    widget.remember({ who: "customer", text: shownMessage });
    widget.input.value = "";
    const body = new FormData();
    body.append("session_id", sessionId());
    body.append("message", message);
    widget.consumeAttachment(body);
    client.submit(body);
  });
}

if (
  typeof document !== "undefined" &&
  document.getElementById("shopchat-root")
) {
  boot();
}
