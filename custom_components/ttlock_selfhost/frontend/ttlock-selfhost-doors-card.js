// Dashboard card: one door per lock. Opening asks first; locking does not.

import { t } from "./i18n.js";

const PLATFORM = "ttlock_selfhost";
const FLASH_MS = 5000;
const SVG = "http://www.w3.org/2000/svg";

function h(tag, props = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(props)) {
    if (value == null || value === false) continue;
    if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else if (name === "class") node.className = value;
    else node.setAttribute(name, value === true ? "" : value);
  }
  for (const kid of kids.flat()) {
    if (kid != null && kid !== false) node.append(kid);
  }
  return node;
}

function s(tag, attrs = {}, ...kids) {
  const node = document.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  node.append(...kids);
  return node;
}

// A doorway with warm light behind a leaf that swings on its left hinge.
function door() {
  return s(
    "svg",
    { viewBox: "0 0 120 132", class: "door", "aria-hidden": "true" },
    s(
      "defs",
      {},
      s(
        "linearGradient",
        { id: "glow", x1: "0", y1: "0", x2: "0", y2: "1" },
        s("stop", { offset: "0", "stop-color": "#FFE2A8" }),
        s("stop", { offset: "1", "stop-color": "#FF9F43" })
      )
    ),
    s("rect", { class: "frame", x: "24", y: "6", width: "72", height: "118", rx: "5" }),
    s("rect", { class: "light", x: "29", y: "11", width: "62", height: "113", rx: "2" }),
    s(
      "g",
      { class: "leaf" },
      s("rect", { class: "wood", x: "29", y: "11", width: "62", height: "113", rx: "2" }),
      s("rect", { class: "inset", x: "37", y: "20", width: "46", height: "40", rx: "2" }),
      s("rect", { class: "inset", x: "37", y: "70", width: "46", height: "44", rx: "2" }),
      s("circle", { class: "knob", cx: "82", cy: "66", r: "3.6" })
    ),
    s("path", { class: "floor", d: "M8 125 H112" })
  );
}

const STYLE = `
  :host { display: block; }
  ha-card { padding: 16px; overflow: hidden; }
  .head { display: flex; align-items: center; gap: 8px; margin: 0 4px 12px; font-size: 20px; }
  .head ha-icon { color: var(--secondary-text-color); }
  .doors { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }
  .tile {
    all: unset; cursor: pointer; box-sizing: border-box; position: relative;
    display: grid; justify-items: center; gap: 4px; padding: 14px 10px 12px;
    border-radius: 18px; text-align: center;
    background: color-mix(in srgb, var(--primary-text-color) 6%, transparent);
    border: 1px solid color-mix(in srgb, var(--primary-text-color) 10%, transparent);
    transition: background 0.2s, border-color 0.2s, transform 0.15s;
    --door: var(--primary-color, #03a9f4);
  }
  .tile:hover { background: color-mix(in srgb, var(--primary-text-color) 10%, transparent); }
  .tile:active { transform: scale(0.98); }
  .tile:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
  .tile.open { --door: var(--warning-color, #ffa600);
    border-color: color-mix(in srgb, var(--warning-color, #ffa600) 55%, transparent); }
  .tile.unknown { --door: var(--disabled-text-color, #8a8a8a); }
  .door { width: 96px; height: 106px; overflow: visible; }
  .frame { fill: none; stroke: color-mix(in srgb, var(--primary-text-color) 45%, transparent); stroke-width: 3; }
  .light { fill: url(#glow); opacity: 0; transition: opacity 0.5s ease; }
  .floor { stroke: color-mix(in srgb, var(--primary-text-color) 30%, transparent); stroke-width: 3; stroke-linecap: round; }
  .leaf { transform-box: view-box; transform-origin: 29px 67px;
    transition: transform 0.8s cubic-bezier(0.3, 0.9, 0.3, 1); }
  .wood { fill: var(--door); transition: fill 0.4s; }
  .inset { fill: none; stroke: rgba(255, 255, 255, 0.35); stroke-width: 2; }
  .knob { fill: #fff; }
  .open .leaf { transform: scaleX(0.34) skewY(9deg); }
  .open .light { opacity: 1; }
  .busy .leaf { animation: nudge 0.9s ease-in-out infinite alternate; }
  .busy.to-open .light { opacity: 0.6; }
  @keyframes nudge {
    from { transform: scaleX(1) skewY(0deg); }
    to { transform: scaleX(0.78) skewY(4deg); }
  }
  .busy.to-close .leaf { animation-name: nudge-close; }
  @keyframes nudge-close {
    from { transform: scaleX(0.34) skewY(9deg); }
    to { transform: scaleX(0.62) skewY(6deg); }
  }
  @media (prefers-reduced-motion: reduce) {
    .leaf, .light { transition: none; }
    .busy .leaf { animation: none; opacity: 0.6; }
  }
  .badge { position: absolute; top: 10px; right: 10px; color: var(--door); --mdc-icon-size: 20px; }
  .name { font-size: 16px; font-weight: 500; margin-top: 4px; overflow-wrap: anywhere; }
  .state { font-size: 13px; color: var(--secondary-text-color); }
  .open .state { color: var(--warning-color, #ffa600); }
  .battery { position: absolute; top: 10px; left: 12px; font-size: 12px; color: var(--secondary-text-color);
    display: inline-flex; align-items: center; gap: 2px; --mdc-icon-size: 16px; }
  .battery.low { color: var(--error-color, #db4437); }
  .flash { margin: 12px 4px 0; font-size: 13px; color: var(--error-color, #db4437); }
  .empty { color: var(--secondary-text-color); padding: 8px 4px; }
`;

const DIALOG_STYLE = `
  dialog { border: 0; padding: 0; border-radius: 24px; width: min(340px, calc(100vw - 48px));
    background: var(--card-background-color, #1c1c1e); color: var(--primary-text-color, #fff);
    font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif);
    box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45); }
  dialog::backdrop { background: rgba(0, 0, 0, 0.55); backdrop-filter: blur(3px); }
  dialog[open] { animation: rise 0.22s ease-out; }
  @keyframes rise { from { opacity: 0; transform: translateY(12px) scale(0.97); } }
  @media (prefers-reduced-motion: reduce) { dialog[open] { animation: none; } }
  .body { padding: 26px 22px 8px; text-align: center; --door: var(--warning-color, #ffa600); }
  .door { width: 104px; height: 114px; overflow: visible; }
  .frame { fill: none; stroke: color-mix(in srgb, var(--primary-text-color, #fff) 45%, transparent); stroke-width: 3; }
  .light { fill: url(#glow); opacity: 0.85; }
  .floor { stroke: color-mix(in srgb, var(--primary-text-color, #fff) 30%, transparent); stroke-width: 3; stroke-linecap: round; }
  .leaf { transform-box: view-box; transform-origin: 29px 67px; animation: peek 1.6s ease-in-out infinite alternate; }
  @keyframes peek {
    from { transform: scaleX(0.9) skewY(2deg); }
    to { transform: scaleX(0.55) skewY(7deg); }
  }
  @media (prefers-reduced-motion: reduce) { .leaf { animation: none; transform: scaleX(0.6) skewY(6deg); } }
  .wood { fill: var(--door); }
  .inset { fill: none; stroke: rgba(255, 255, 255, 0.35); stroke-width: 2; }
  .knob { fill: #fff; }
  h2 { margin: 14px 0 6px; font-size: 21px; font-weight: 500; }
  p { margin: 0; color: var(--secondary-text-color, #aaa); font-size: 14px; line-height: 1.4; }
  .actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; padding: 20px 18px 18px; }
  button { all: unset; cursor: pointer; text-align: center; padding: 13px 8px; border-radius: 22px;
    font-size: 15px; font-weight: 500; box-sizing: border-box; }
  button:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: 2px; }
  .cancel { background: color-mix(in srgb, var(--primary-text-color, #fff) 10%, transparent); }
  .go { background: var(--warning-color, #ffa600); color: #1b1300; }
`;

// Asks before a door is opened; lives on <body> so no card transform can clip it.
function confirmOpen(hass, name) {
  return new Promise((resolve) => {
    const host = document.createElement("div");
    const root = host.attachShadow({ mode: "open" });
    let answer = false;
    const dialog = h(
      "dialog",
      { "aria-labelledby": "q" },
      h(
        "div",
        { class: "body" },
        door(),
        h("h2", { id: "q" }, t(hass, "door_open_q", { name })),
        h("p", {}, t(hass, "door_open_hint"))
      ),
      h(
        "div",
        { class: "actions" },
        h("button", { class: "cancel", onclick: () => dialog.close() }, t(hass, "no")),
        h(
          "button",
          {
            class: "go",
            onclick: () => {
              answer = true;
              dialog.close();
            },
          },
          t(hass, "door_open")
        )
      )
    );
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    dialog.addEventListener("close", () => {
      host.remove();
      resolve(answer);
    });
    root.append(h("style", {}, DIALOG_STYLE), dialog);
    document.body.append(host);
    dialog.showModal();
    dialog.querySelector(".cancel").focus();
  });
}

class TtlockSelfhostDoorsCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._busy = {};
    this._seen = "";
    this._flash = "";
  }

  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    if (config.entities && !Array.isArray(config.entities)) {
      throw new Error("entities must be a list of lock entities");
    }
    this._config = config;
    this._seen = "";
    this._render();
  }

  getCardSize() {
    return 4;
  }

  getGridOptions() {
    return { columns: "full", min_columns: 6 };
  }

  set hass(hass) {
    this._hass = hass;
    const seen = JSON.stringify([
      hass.language,
      this._locks().map((id) => [id, hass.states[id]?.state, this._battery(id)]),
    ]);
    if (seen === this._seen) return;
    this._seen = seen;
    this._render();
  }

  _locks() {
    if (!this._hass) return [];
    if (this._config.entities) return this._config.entities;
    return Object.values(this._hass.entities || {})
      .filter(
        (entry) =>
          entry.platform === PLATFORM && entry.entity_id.startsWith("lock.") && !entry.hidden
      )
      .map((entry) => entry.entity_id)
      .sort((a, b) => this._name(a).localeCompare(this._name(b)));
  }

  _device(entityId) {
    const entry = (this._hass.entities || {})[entityId];
    return entry && (this._hass.devices || {})[entry.device_id];
  }

  _name(entityId) {
    const device = this._device(entityId);
    if (device) return device.name_by_user || device.name;
    return this._hass.states[entityId]?.attributes.friendly_name || entityId;
  }

  _battery(entityId) {
    const entry = (this._hass.entities || {})[entityId];
    if (!entry) return null;
    const sensor = Object.values(this._hass.entities).find(
      (other) =>
        other.device_id === entry.device_id &&
        other.platform === PLATFORM &&
        other.translation_key === "battery"
    );
    const level = sensor && Number(this._hass.states[sensor.entity_id]?.state);
    return Number.isFinite(level) ? level : null;
  }

  async _press(entityId) {
    if (this._busy[entityId]) return;
    const state = this._hass.states[entityId]?.state;
    const action = state === "unlocked" ? "lock" : "unlock";
    if (action === "unlock" && !(await confirmOpen(this._hass, this._name(entityId)))) return;
    this._busy[entityId] = action;
    this._flash = "";
    this._render();
    try {
      await this._hass.callService("lock", action, { entity_id: entityId });
    } catch (err) {
      this._flash = t(this._hass, "failed", { err: (err && err.message) || String(err) });
      clearTimeout(this._flashTimer);
      this._flashTimer = setTimeout(() => {
        this._flash = "";
        this._render();
      }, FLASH_MS);
    }
    delete this._busy[entityId];
    this._seen = "";
    this._render();
  }

  _tile(entityId) {
    const hass = this._hass;
    const entity = hass.states[entityId];
    const raw = entity ? entity.state : "unavailable";
    const moving = this._busy[entityId]
      ? `${this._busy[entityId]}ing`
      : ["locking", "unlocking"].includes(raw)
        ? raw
        : null;
    const open = raw === "unlocked";
    const known = ["locked", "unlocked", "locking", "unlocking"].includes(raw);
    const label = moving || (known ? raw : "unknown");
    const battery = this._battery(entityId);
    const classes = ["tile"];
    if (open) classes.push("open");
    if (!known) classes.push("unknown");
    if (moving) classes.push("busy", moving === "unlocking" ? "to-open" : "to-close");
    const name = this._name(entityId);
    const badge = h("ha-icon", { class: "badge" });
    badge.icon = open ? "mdi:lock-open-variant" : "mdi:lock";
    const tile = h(
      "button",
      {
        class: classes.join(" "),
        "aria-label": `${name}: ${t(hass, label)}. ${t(hass, open ? "tap_lock" : "tap_open")}`,
        onclick: () => this._press(entityId),
      },
      battery == null
        ? null
        : h("span", { class: `battery${battery <= 20 ? " low" : ""}` }, `${battery}%`),
      badge,
      door(),
      h("span", { class: "name" }, name),
      h("span", { class: "state" }, t(hass, label))
    );
    return tile;
  }

  _render() {
    if (!this._hass) return;
    const locks = this._locks();
    const title = this._config.title;
    const card = h(
      "ha-card",
      {},
      title ? h("div", { class: "head" }, title) : null,
      locks.length
        ? h("div", { class: "doors" }, locks.map((id) => this._tile(id)))
        : h("div", { class: "empty" }, t(this._hass, "no_locks")),
      this._flash ? h("div", { class: "flash", role: "alert" }, this._flash) : null
    );
    this.shadowRoot.replaceChildren(h("style", {}, STYLE), card);
  }
}

customElements.define("ttlock-selfhost-doors-card", TtlockSelfhostDoorsCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "ttlock-selfhost-doors-card",
  name: t({ language: navigator.language }, "card_name"),
  description: t({ language: navigator.language }, "card_desc"),
  preview: true,
});
