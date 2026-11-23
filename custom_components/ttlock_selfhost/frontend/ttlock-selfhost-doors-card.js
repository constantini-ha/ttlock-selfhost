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

// A doorway with warm light behind a leaf that swings in 3D on its left hinge.
function door() {
  const box = { viewBox: "0 0 120 140", "aria-hidden": "true" };
  return h(
    "div",
    { class: "door" },
    s(
      "svg",
      { ...box, class: "way" },
      s(
        "defs",
        {},
        s(
          "linearGradient",
          { id: "glow", x1: "0", y1: "0", x2: "0", y2: "1" },
          s("stop", { offset: "0", "stop-color": "#FFF1CF" }),
          s("stop", { offset: "1", "stop-color": "#FFB35C" })
        ),
        s(
          "radialGradient",
          { id: "pool", cx: "0.5", cy: "0", r: "1" },
          s("stop", { offset: "0", "stop-color": "#FFC978", "stop-opacity": "0.75" }),
          s("stop", { offset: "1", "stop-color": "#FFC978", "stop-opacity": "0" })
        )
      ),
      s("rect", { class: "dark", x: "29", y: "11", width: "62", height: "113", rx: "2" }),
      s("rect", { class: "light", x: "29", y: "11", width: "62", height: "113", rx: "2" }),
      s("path", { class: "spill", d: "M29 125 H91 L112 139 H16 Z" }),
      s("rect", { class: "frame", x: "24", y: "6", width: "72", height: "118.5", rx: "5" }),
      s("path", { class: "floor", d: "M8 125 H112" })
    ),
    s(
      "svg",
      { ...box, class: "leaf" },
      s("rect", { class: "wood", x: "29", y: "11", width: "62", height: "113", rx: "2" }),
      s("rect", { class: "inset", x: "37", y: "20", width: "46", height: "40", rx: "2" }),
      s("rect", { class: "inset", x: "37", y: "70", width: "46", height: "44", rx: "2" }),
      s(
        "g",
        { class: "handle" },
        s("rect", { x: "69", y: "64.4", width: "13", height: "3.2", rx: "1.6" }),
        s("circle", { cx: "82", cy: "66", r: "3.4" })
      ),
      s("rect", { class: "shade", x: "29", y: "11", width: "62", height: "113", rx: "2" })
    )
  );
}

const DOOR_STYLE = `
  .door { position: relative; width: 96px; height: 112px; }
  .door svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
  .frame { fill: none; stroke: color-mix(in srgb, var(--primary-text-color, #fff) 45%, transparent); stroke-width: 3; }
  .floor { stroke: color-mix(in srgb, var(--primary-text-color, #fff) 30%, transparent); stroke-width: 3; stroke-linecap: round; }
  .dark { fill: color-mix(in srgb, var(--primary-text-color, #fff) 8%, transparent); }
  .light { fill: url(#glow); opacity: 0; transition: opacity 0.6s ease; }
  .spill { fill: url(#pool); opacity: 0; transition: opacity 0.7s ease 0.1s; }
  .leaf { transform-origin: 24.17% 50%; transform: perspective(460px) rotateY(0deg);
    transition: transform 0.5s cubic-bezier(0.55, 0, 0.85, 0.45); will-change: transform; }
  .wood { fill: var(--door); }
  .inset { fill: none; stroke: rgba(255, 255, 255, 0.35); stroke-width: 2; }
  .handle { fill: #fff; transform-box: view-box; transform-origin: 82px 66px;
    transition: transform 0.25s ease; }
  .shade { fill: #000; opacity: 0; transition: opacity 0.6s ease; }
`;

const STYLE = `
  :host { display: block; }
  ha-card { padding: 16px; overflow: hidden; }
  .head { display: flex; align-items: center; gap: 8px; margin: 0 4px 12px; font-size: 20px; }
  .doors { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }
  .tile {
    all: unset; cursor: pointer; box-sizing: border-box; position: relative;
    display: grid; justify-items: center; gap: 4px; padding: 14px 10px 12px;
    border-radius: 18px; text-align: center;
    background: color-mix(in srgb, var(--primary-text-color) 6%, transparent);
    border: 1px solid color-mix(in srgb, var(--primary-text-color) 10%, transparent);
    transition: background 0.3s, border-color 0.3s, transform 0.15s;
    --door: var(--primary-color, #03a9f4);
    --mark: var(--primary-color, #03a9f4);
  }
  .tile:hover { background: color-mix(in srgb, var(--primary-text-color) 10%, transparent); }
  .tile:active { transform: scale(0.98); }
  .tile:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
  .tile.open { --mark: var(--warning-color, #ffa600);
    border-color: color-mix(in srgb, var(--warning-color, #ffa600) 45%, transparent); }
  .tile.unknown { --door: var(--disabled-text-color, #8a8a8a); --mark: var(--disabled-text-color, #8a8a8a); }
  ${DOOR_STYLE}
  .open .leaf { transform: perspective(460px) rotateY(72deg);
    transition: transform 1s cubic-bezier(0.3, 1.45, 0.45, 1); }
  .open .light, .open .spill { opacity: 1; }
  .open .shade { opacity: 0.28; }
  .to-open .leaf { transform: perspective(460px) rotateY(16deg);
    transition: transform 0.45s cubic-bezier(0.3, 0.8, 0.4, 1) 0.15s; }
  .to-open .handle { transform: rotate(-28deg); }
  .to-open .light { opacity: 0.75; animation: breathe 1.1s ease-in-out infinite alternate; }
  .to-open .shade { opacity: 0.08; }
  .to-close .leaf { transform: perspective(460px) rotateY(34deg);
    transition: transform 0.6s cubic-bezier(0.4, 0, 0.3, 1); }
  .to-close .light { opacity: 0.8; animation: breathe 1.1s ease-in-out infinite alternate; }
  .to-close .spill { opacity: 0.5; }
  .to-close .shade { opacity: 0.14; }
  @keyframes breathe { to { opacity: 0.45; } }
  @media (prefers-reduced-motion: reduce) {
    .leaf, .light, .spill, .shade, .handle { transition: none !important; animation: none !important; }
  }
  .badge { position: absolute; top: 10px; right: 10px; color: var(--mark); --mdc-icon-size: 20px;
    transition: color 0.3s; }
  .name { font-size: 16px; font-weight: 500; margin-top: 4px; overflow-wrap: anywhere; }
  .state { font-size: 13px; color: var(--secondary-text-color); transition: color 0.3s; }
  .open .state { color: var(--warning-color, #ffa600); }
  .battery { position: absolute; top: 10px; left: 12px; font-size: 12px; color: var(--secondary-text-color); }
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
  .body { padding: 26px 22px 8px; display: grid; justify-items: center; text-align: center;
    --door: var(--primary-color, #03a9f4); }
  ${DOOR_STYLE}
  .door { width: 108px; height: 126px; }
  .light { opacity: 0.9; }
  .spill { opacity: 0.6; }
  .shade { opacity: 0.1; }
  .handle { transform: rotate(-28deg); }
  .leaf { animation: peek 1.8s cubic-bezier(0.45, 0, 0.55, 1) infinite alternate; }
  @keyframes peek {
    from { transform: perspective(460px) rotateY(8deg); }
    to { transform: perspective(460px) rotateY(40deg); }
  }
  @media (prefers-reduced-motion: reduce) {
    dialog[open] { animation: none; }
    .leaf { animation: none; transform: perspective(460px) rotateY(30deg); }
  }
  h2 { margin: 14px 0 6px; font-size: 21px; font-weight: 500; }
  p { margin: 0; color: var(--secondary-text-color, #aaa); font-size: 14px; line-height: 1.4; }
  .actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; padding: 20px 18px 18px; }
  button { all: unset; cursor: pointer; text-align: center; padding: 13px 8px; border-radius: 22px;
    font-size: 15px; font-weight: 500; box-sizing: border-box; transition: filter 0.15s; }
  button:hover { filter: brightness(1.08); }
  button:focus-visible { outline: 2px solid var(--primary-text-color, #fff); outline-offset: 2px; }
  .cancel { background: color-mix(in srgb, var(--primary-text-color, #fff) 10%, transparent); }
  .go { background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); }
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
    const badge = h("ha-icon", { class: "badge" });
    const battery = h("span", { class: "battery" });
    const name = h("span", { class: "name" });
    const state = h("span", { class: "state" });
    const node = h(
      "button",
      { class: "tile", onclick: () => this._press(entityId) },
      battery,
      badge,
      door(),
      name,
      state
    );
    return { node, badge, battery, name, state };
  }

  // Tiles are updated in place: a rebuilt door would jump instead of swinging.
  _paint(tile, entityId) {
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
    const classes = ["tile"];
    if (moving) classes.push(moving === "unlocking" ? "to-open" : "to-close");
    else if (open) classes.push("open");
    if (!known) classes.push("unknown");
    const name = this._name(entityId);
    tile.node.className = classes.join(" ");
    tile.node.setAttribute(
      "aria-label",
      `${name}: ${t(hass, label)}. ${t(hass, open ? "tap_lock" : "tap_open")}`
    );
    tile.name.textContent = name;
    tile.state.textContent = t(hass, label);
    const battery = this._battery(entityId);
    tile.battery.hidden = battery == null;
    tile.battery.textContent = battery == null ? "" : `${battery}%`;
    tile.battery.className = `battery${battery != null && battery <= 20 ? " low" : ""}`;
    const icon = open ? "mdi:lock-open-variant" : "mdi:lock";
    if (tile.badge.icon !== icon) {
      const first = !tile.badge.icon;
      tile.badge.icon = icon;
      if (!first && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
        tile.badge.animate(
          [{ transform: "scale(0.5)" }, { transform: "scale(1.25)" }, { transform: "scale(1)" }],
          { duration: 360, easing: "ease-out" }
        );
      }
    }
  }

  _render() {
    if (!this._hass) return;
    const locks = this._locks();
    const layout = JSON.stringify([locks, this._config.title]);
    if (layout !== this._layout) {
      this._layout = layout;
      this._tiles = new Map(locks.map((id) => [id, this._tile(id)]));
      this._flashNode = h("div", { class: "flash", role: "alert", hidden: true });
      this._emptyNode = h("div", { class: "empty" });
      const title = this._config.title;
      this.shadowRoot.replaceChildren(
        h("style", {}, STYLE),
        h(
          "ha-card",
          {},
          title ? h("div", { class: "head" }, title) : null,
          locks.length
            ? h("div", { class: "doors" }, [...this._tiles.values()].map((tile) => tile.node))
            : this._emptyNode,
          this._flashNode
        )
      );
    }
    for (const [id, tile] of this._tiles) this._paint(tile, id);
    this._emptyNode.textContent = t(this._hass, "no_locks");
    this._flashNode.textContent = this._flash;
    this._flashNode.hidden = !this._flash;
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
