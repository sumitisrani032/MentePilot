import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";
import { JSDOM } from "jsdom";

import {
  createWidget,
  errorText,
  parseSse,
} from "../../extensions/chat-widget/assets/chat.js";

let root;
let widget;

function makeWidget(
  features = { image: true, skin_analysis: false, voice: false },
) {
  widget = createWidget(root, { greeting: "Hello" });
  widget.applyFeatures(features);
  return widget;
}

beforeEach(() => {
  const dom = new JSDOM('<div id="shopchat-root"></div>');
  globalThis.document = dom.window.document;
  globalThis.window = dom.window;
  root = dom.window.document.getElementById("shopchat-root");
});

test("parses complete events and keeps the unfinished remainder", () => {
  const { events, rest } = parseSse(
    'event: token\ndata: {"text":"Hi"}\n\nevent: do',
  );
  assert.deepEqual(events, [{ event: "token", data: { text: "Hi" } }]);
  assert.equal(rest, "event: do");
});

test("renders tokens incrementally", () => {
  makeWidget();
  const bubble = widget.startBotMessage();
  bubble.append("Hello ");
  assert.equal(bubble.element.textContent, "Hello ");
  bubble.append("there");
  assert.equal(bubble.element.textContent, "Hello there");
});

test("escapes HTML in bot text", () => {
  makeWidget();
  const bubble = widget.startBotMessage();
  bubble.append("<img src=x onerror=alert(1)>");
  assert.equal(bubble.element.querySelector("img"), null);
});

function section(overrides = {}) {
  return {
    heading: "Sun protection",
    detail: "Shields your skin all day.",
    how_to_use: ["Apply generously"],
    tips: ["Reapply after swimming"],
    cards: [
      {
        title: "Sea Lotion",
        vendor: "Acme",
        price: "12.50",
        compare_at_price: null,
        currency: "USD",
        image_url: "https://cdn.example.test/a.jpg",
        url: "https://shop.example.test/products/sea-lotion",
        reason: "Great for the beach",
      },
    ],
    ...overrides,
  };
}

test("renders the heading and detail of a section", () => {
  makeWidget();
  widget.renderSections([section()]);
  assert.equal(root.querySelector("h3").textContent, "Sun protection");
  assert.match(root.querySelector(".shopchat-detail").textContent, /all day/);
});

test("renders a card with brand, price, link and reason", () => {
  makeWidget();
  widget.renderSections([section()]);
  const card = root.querySelector(".shopchat-card");
  assert.equal(
    card.querySelector(".shopchat-view").getAttribute("href"),
    "https://shop.example.test/products/sea-lotion",
  );
  assert.match(card.textContent, /Acme/);
  assert.match(card.textContent, /12\.50/);
  assert.match(card.textContent, /Great for the beach/);
});

test("renders each section's cards in its own scrolling row", () => {
  makeWidget();
  widget.renderSections([section(), section({ heading: "After sun" })]);
  assert.equal(root.querySelectorAll(".shopchat-cards").length, 2);
});

test("renders a card without an image", () => {
  makeWidget();
  const cards = [{ ...section().cards[0], image_url: null }];
  widget.renderSections([section({ cards })]);
  assert.equal(root.querySelector(".shopchat-card img"), null);
  assert.match(root.querySelector(".shopchat-card").textContent, /Sea Lotion/);
});

test("how to use and tips are closed toggles", () => {
  makeWidget();
  widget.renderSections([section()]);
  const toggles = [...root.querySelectorAll("details.shopchat-more")];
  assert.deepEqual(
    toggles.map((item) => item.querySelector("summary").textContent),
    ["How to use", "Tips"],
  );
  assert.equal(
    toggles.every((item) => !item.open),
    true,
  );
});

test("a toggle with nothing to show is left out", () => {
  makeWidget();
  widget.renderSections([section({ how_to_use: [], tips: ["Reapply"] })]);
  assert.equal(root.querySelectorAll("details.shopchat-more").length, 1);
});

test("toggle text cannot inject HTML", () => {
  makeWidget();
  widget.renderSections([section({ tips: ["<img src=x onerror=alert(1)>"] })]);
  assert.equal(root.querySelector(".shopchat-more img"), null);
});

test("refuses a card link that is not http or https", () => {
  makeWidget();
  const cards = [{ ...section().cards[0], url: "javascript:alert(1)" }];
  widget.renderSections([section({ cards })]);
  assert.equal(root.querySelector(".shopchat-card"), null);
  assert.equal(root.querySelector(".shopchat-section"), null);
});

test("the launcher opens the panel and close returns", () => {
  makeWidget();
  root.querySelector(".shopchat-toggle").click();
  assert.equal(root.querySelector(".shopchat-panel").hidden, false);
  assert.equal(root.querySelector(".shopchat-toggle").hidden, true);
  root.querySelector(".shopchat-close").click();
  assert.equal(root.querySelector(".shopchat-panel").hidden, true);
  assert.equal(root.querySelector(".shopchat-toggle").hidden, false);
});

test("starting a new chat clears the conversation", () => {
  makeWidget();
  let restarted = false;
  widget.setOnRestart(() => {
    restarted = true;
  });
  widget.addMessage("hello", "customer");
  root.querySelector(".shopchat-restart").click();
  assert.equal(root.querySelector(".shopchat-customer"), null);
  assert.equal(restarted, true);
});

test("shows what it is doing until the first words arrive", () => {
  makeWidget();
  const bubble = widget.startBotMessage();
  assert.match(root.querySelector(".shopchat-status").textContent, /Thinking/);
  bubble.append("Hello");
  assert.equal(root.querySelector(".shopchat-status"), null);
  bubble.finish();
});

test("the status also clears when a reply never arrives", () => {
  makeWidget();
  widget.startBotMessage().finish();
  assert.equal(root.querySelector(".shopchat-status"), null);
});

test("suggested questions appear and fill the message box", () => {
  makeWidget();
  widget.setSuggestions(["Show me sunscreen", "Help me find a gift"]);
  const chips = root.querySelectorAll(".shopchat-chip");
  assert.equal(chips.length, 2);
  root.querySelector(".shopchat-form").requestSubmit = () => {};
  chips[0].click();
  assert.equal(
    root.querySelector(".shopchat-input").value,
    "Show me sunscreen",
  );
});

test("suggestions hide while a question is answered", () => {
  makeWidget();
  widget.setSuggestions(["Help me find a gift"]);
  const bubble = widget.startBotMessage();
  assert.equal(root.querySelector(".shopchat-suggestions").hidden, true);
  bubble.finish();
});

test("a finished reply can be copied, including products and tips", async () => {
  makeWidget();
  let copied = "";
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {
      clipboard: {
        writeText: async (text) => {
          copied = text;
        },
      },
    },
  });
  const bubble = widget.startBotMessage();
  bubble.append("Here you go.");
  widget.renderSections([section()], bubble);
  bubble.finish();
  root.querySelector(".shopchat-copy").click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.match(copied, /Here you go\./);
  assert.match(copied, /Sea Lotion/);
  assert.match(copied, /Reapply after swimming/);
});

test("how to use is one toggle grouped by section", () => {
  makeWidget();
  widget.renderSections([
    section({ heading: "Step 1: Cleanse", how_to_use: ["Wet face"] }),
    section({ heading: "Step 2: Serum", how_to_use: ["Apply drops"] }),
  ]);
  const howTo = [...root.querySelectorAll("details.shopchat-more")].find(
    (item) => item.querySelector("summary").textContent === "How to use",
  );
  assert.deepEqual(
    [...howTo.querySelectorAll("h5")].map((item) => item.textContent),
    ["Step 1: Cleanse", "Step 2: Serum"],
  );
});

test("shows the follow-up question and quick replies", () => {
  makeWidget();
  widget.renderSections([section()], null, {
    follow_up_question: "Want a sleeping mask?",
    quick_replies: ["Show more options"],
  });
  assert.match(
    root.querySelector(".shopchat-follow-up").textContent,
    /sleeping/,
  );
  assert.equal(
    root.querySelector(".shopchat-quick .shopchat-chip").textContent,
    "Show more options",
  );
});

test("old quick replies go away when a new question starts", () => {
  makeWidget();
  widget.renderSections([section()], null, { quick_replies: ["More"] });
  widget.startBotMessage().finish();
  assert.equal(root.querySelector(".shopchat-quick"), null);
});

test("the info button reveals product details", () => {
  makeWidget();
  const cards = [{ ...section().cards[0], description: "Light daily cream" }];
  widget.renderSections([section({ cards })]);
  const panel = root.querySelector(".shopchat-card-info");
  assert.equal(panel.hidden, true);
  root.querySelector(".shopchat-info").click();
  assert.equal(panel.hidden, false);
  assert.match(panel.textContent, /Light daily cream/);
  assert.match(panel.textContent, /Great for the beach/);
});

test("a card with no details has no info button", () => {
  makeWidget();
  const cards = [{ ...section().cards[0], reason: "", description: "" }];
  widget.renderSections([section({ cards })]);
  assert.equal(root.querySelector(".shopchat-info"), null);
});

test("the chat still works where page storage is blocked", () => {
  makeWidget();
  widget.remember({ who: "customer", text: "hi" });
  widget.restore();
  assert.equal(root.querySelector(".shopchat-customer"), null);
});

test("hides the mic button unless features.voice", () => {
  makeWidget({ image: true, skin_analysis: false, voice: false });
  assert.equal(root.querySelector(".shopchat-mic").hidden, true);
  widget.applyFeatures({ image: true, skin_analysis: false, voice: true });
  assert.equal(root.querySelector(".shopchat-mic").hidden, false);
});

test("spoken replies are off when voice is off", () => {
  makeWidget({ image: true, skin_analysis: false, voice: false });
  assert.equal(widget.shouldSpeak(), false);
});

test("mute stops spoken replies", () => {
  makeWidget({ image: true, skin_analysis: false, voice: true });
  assert.equal(widget.shouldSpeak(), true);
  root.querySelector(".shopchat-mute").click();
  assert.equal(widget.shouldSpeak(), false);
});

test("hides the photo button when images are off", () => {
  makeWidget({ image: false, skin_analysis: false, voice: false });
  assert.equal(root.querySelector(".shopchat-photo").hidden, true);
});

test("hides the skin button unless the store enabled it", () => {
  makeWidget({ image: true, skin_analysis: false, voice: false });
  assert.equal(root.querySelector(".shopchat-skin").hidden, true);
});

test("skin consent is never sent without pressing agree", () => {
  makeWidget({ image: true, skin_analysis: true, voice: false });
  root.querySelector(".shopchat-skin").click();
  root.querySelector(".shopchat-decline").click();
  widget.setAttachment("file");
  const sent = [];
  widget.consumeAttachment({ append: (key) => sent.push(key) });
  assert.equal(sent.includes("skin_consent"), false);
});

test("skin consent is sent once and forgotten", () => {
  makeWidget({ image: true, skin_analysis: true, voice: false });
  root.querySelector(".shopchat-file").click = () => {};
  root.querySelector(".shopchat-skin").click();
  root.querySelector(".shopchat-agree").click();
  widget.setAttachment("file");
  const first = [];
  widget.consumeAttachment({ append: (key) => first.push(key) });
  assert.equal(first.includes("skin_consent"), true);
  assert.equal(widget.hasAttachment(), false);
});

test("hides the widget on 403", () => {
  makeWidget();
  widget.handleSessionFailure(403);
  assert.equal(root.hidden, true);
});

test("explains an oversized upload", () => {
  assert.match(errorText(413), /too large/);
});
