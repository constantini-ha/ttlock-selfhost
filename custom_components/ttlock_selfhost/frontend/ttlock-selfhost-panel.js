// The TTLock Selfhost panel: one screen per lock, laid out like the phone app.

import { t } from "./i18n.js";

const WS = "ttlock_selfhost/";
const DOORS_CARD = "custom:ttlock-selfhost-doors-card";
const HOLD_MS = 700;
const POLL_MS = 15000;
const FLASH_MS = 5000;
const HOUR = 3600000;
const RANDOM_KIND = { permanent: 2, timed: 3, one_time: 1 };
const EKEY_STATUS = { 110401: "ekey_active", 110402: "ekey_pending", 110405: "ekey_frozen" };
const RECORD_ICONS = {
  unlock: "mdi:lock-open-variant-outline",
  lock: "mdi:lock-outline",
  unlock_failed: "mdi:lock-alert-outline",
  lock_failed: "mdi:lock-alert-outline",
  password_change: "mdi:dialpad",
  alarm: "mdi:alarm-light-outline",
  door_open: "mdi:door-open",
  door_closed: "mdi:door-closed",
  other: "mdi:information-outline",
};
const TILES = [
  ["ekeys", "mdi:key-variant"],
  ["passcodes", "mdi:dialpad"],
  ["cards", "mdi:card-account-details-outline"],
  ["fingerprints", "mdi:fingerprint"],
  ["records", "mdi:history"],
  ["gateway", "mdi:router-wireless"],
  ["settings", "mdi:cog-outline"],
];
const LISTS = ["passcodes", "cards", "fingerprints"];

function h(tag, props = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(props)) {
    if (value == null || value === false) continue;
    if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else if (name === "class") node.className = value;
    else if (name in node && name !== "list") node[name] = value;
    else node.setAttribute(name, value === true ? "" : value);
  }
  for (const kid of kids.flat()) {
    if (kid != null && kid !== false) node.append(kid);
  }
  return node;
}

const icon = (name, cls) => h("ha-icon", { icon: name, class: cls });

const pad = (n) => String(n).padStart(2, "0");
const localInput = (ms) => {
  const d = new Date(ms);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
const masked = (code) =>
  code && code.length >= 4 ? `${code[0]}•••${code.slice(-2)}` : "•••";

function* cardsIn(node) {
  if (Array.isArray(node)) for (const item of node) yield* cardsIn(item);
  else if (node && typeof node === "object") {
    if (typeof node.type === "string") yield node;
    for (const value of Object.values(node)) yield* cardsIn(value);
  }
}

const STYLE = `
  :host {
    --tt-blue: #1a9bfc;
    --tt-blue-soft: rgba(26, 155, 252, 0.14);
    --tt-line: var(--divider-color, rgba(127, 127, 127, 0.25));
    display: block;
    min-height: 100vh;
    background: var(--primary-background-color);
    color: var(--primary-text-color);
    font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif);
  }
  * { box-sizing: border-box; }
  .bar {
    position: sticky; top: 0; z-index: 2;
    display: grid; grid-template-columns: 56px 1fr 56px; align-items: center;
    height: 56px; padding: 0 4px;
    background: var(--app-header-background-color, var(--tt-blue));
    color: var(--app-header-text-color, #fff);
  }
  .bar h1 { margin: 0; font-size: 18px; font-weight: 500; text-align: center;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bar button { all: unset; cursor: pointer; width: 48px; height: 48px; display: grid;
    place-items: center; border-radius: 50%; }
  .bar button:focus-visible { outline: 2px solid currentColor; }
  .page { max-width: 480px; margin: 0 auto; padding: 16px 16px 96px; }
  .status { display: flex; justify-content: center; gap: 18px; align-items: center;
    color: var(--secondary-text-color); font-size: 14px; min-height: 28px; }
  .status span { display: inline-flex; align-items: center; gap: 4px; }
  .status ha-icon { --mdc-icon-size: 20px; }
  .status .on { color: var(--tt-blue); }
  .status .off { opacity: 0.45; }
  .ring-wrap { display: grid; place-items: center; padding: 28px 0 12px; }
  .ring {
    all: unset; cursor: pointer; position: relative;
    width: 196px; height: 196px; border-radius: 50%;
    display: grid; place-items: center;
    border: 6px solid var(--tt-blue);
    box-shadow: 0 0 0 12px var(--tt-blue-soft);
    color: var(--tt-blue);
    background: var(--card-background-color, #fff);
    touch-action: none; user-select: none; -webkit-user-select: none;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }
  .ring ha-icon { --mdc-icon-size: 84px; }
  .ring:active, .ring.held { transform: scale(0.97); box-shadow: 0 0 0 6px var(--tt-blue-soft); }
  .ring:focus-visible { outline: 3px solid var(--tt-blue); outline-offset: 16px; }
  .ring.unknown { border-color: var(--tt-line); color: var(--secondary-text-color);
    box-shadow: 0 0 0 12px rgba(127, 127, 127, 0.1); }
  .ring.busy::after {
    content: ""; position: absolute; inset: -6px; border-radius: 50%;
    border: 6px solid transparent; border-top-color: var(--card-background-color, #fff);
    animation: spin 0.9s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) {
    .ring.busy::after { animation: none; opacity: 0.6; }
    .ring { transition: none; }
  }
  .state { text-align: center; font-size: 20px; font-weight: 500; margin: 14px 0 4px; }
  .hint { text-align: center; color: var(--secondary-text-color); font-size: 14px; margin: 0 0 24px; }
  .tiles { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px;
    background: var(--card-background-color, #fff); border-radius: 12px; padding: 12px 4px; }
  @media (max-width: 340px) { .tiles { grid-template-columns: repeat(3, 1fr); } }
  .tile { all: unset; cursor: pointer; display: grid; justify-items: center; gap: 6px;
    padding: 12px 2px; border-radius: 10px; font-size: 13px; text-align: center; }
  .tile ha-icon { --mdc-icon-size: 30px; color: var(--tt-blue); }
  .tile:hover, .tile:focus-visible { background: var(--tt-blue-soft); }
  .tile.dim ha-icon { color: var(--secondary-text-color); opacity: 0.6; }
  .card { background: var(--card-background-color, #fff); border-radius: 12px; overflow: hidden;
    margin-bottom: 16px; }
  .row { display: flex; align-items: center; gap: 12px; min-height: 56px; padding: 10px 16px;
    border-bottom: 1px solid var(--tt-line); }
  .row:last-child { border-bottom: 0; }
  .row > ha-icon { color: var(--tt-blue); flex: none; }
  .row .main { flex: 1; min-width: 0; }
  .row .main b { display: block; font-weight: 500; overflow: hidden; text-overflow: ellipsis; }
  .row .main small, .row .side { color: var(--secondary-text-color); font-size: 13px; }
  .row .main small { display: block; overflow-wrap: anywhere; }
  .row .side { text-align: right; flex: none; }
  button.row { all: unset; cursor: pointer; display: flex; align-items: center; gap: 12px;
    min-height: 56px; padding: 10px 16px; border-bottom: 1px solid var(--tt-line);
    width: 100%; box-sizing: border-box; }
  button.row:hover, button.row:focus-visible { background: var(--tt-blue-soft); }
  .mono { font-family: ui-monospace, "Roboto Mono", monospace; letter-spacing: 1px; }
  .ghost { all: unset; cursor: pointer; color: var(--tt-blue); padding: 8px; border-radius: 8px;
    display: inline-grid; place-items: center; font-size: 14px; }
  .ghost:hover, .ghost:focus-visible { background: var(--tt-blue-soft); }
  .ghost.danger { color: var(--error-color, #d93025); }
  .note { color: var(--secondary-text-color); font-size: 13px; line-height: 1.45; margin: 0 4px 14px; }
  .day { color: var(--secondary-text-color); font-size: 13px; margin: 14px 4px 6px; }
  .tabs { display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; gap: 4px;
    background: var(--card-background-color, #fff); padding: 4px; border-radius: 10px; margin-bottom: 16px; }
  .tabs button { all: unset; cursor: pointer; text-align: center; padding: 9px 2px; border-radius: 8px;
    font-size: 13px; }
  .tabs button[aria-selected="true"] { background: var(--tt-blue); color: #fff; }
  .tabs button:disabled { opacity: 0.4; cursor: default; }
  label.field { display: block; padding: 10px 16px; border-bottom: 1px solid var(--tt-line); }
  label.field span { display: block; font-size: 12px; color: var(--secondary-text-color); margin-bottom: 4px; }
  label.field input, label.field select { width: 100%; border: 0; outline: 0; background: transparent;
    color: inherit; font: inherit; font-size: 16px; padding: 4px 0; color-scheme: light dark; }
  label.check { display: flex; align-items: center; gap: 10px; padding: 14px 16px; }
  .primary { all: unset; cursor: pointer; display: block; width: 100%; box-sizing: border-box;
    text-align: center; background: var(--tt-blue); color: #fff; border-radius: 26px;
    padding: 14px; font-size: 16px; font-weight: 500; }
  .primary:disabled { opacity: 0.5; cursor: default; }
  .primary:focus-visible { outline: 3px solid var(--tt-blue); outline-offset: 3px; }
  .secondary { all: unset; cursor: pointer; display: block; width: 100%; box-sizing: border-box;
    text-align: center; color: var(--error-color, #d93025); padding: 14px; font-size: 15px; }
  .url { padding: 12px 16px; font-size: 12px; letter-spacing: 0; overflow-wrap: anywhere;
    color: var(--secondary-text-color); user-select: all; }
  .big-code { text-align: center; font-size: 34px; padding: 22px 8px 6px; }
  .center { text-align: center; }
  .toast { position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%);
    background: var(--primary-text-color, #222); color: var(--primary-background-color, #fff);
    padding: 10px 18px; border-radius: 22px; font-size: 14px; max-width: calc(100vw - 32px);
    z-index: 5; }
  .empty { text-align: center; color: var(--secondary-text-color); padding: 36px 16px; }
  .empty ha-icon { --mdc-icon-size: 48px; opacity: 0.5; display: block; margin: 0 auto 10px; }
  .radio { width: 20px; height: 20px; border-radius: 50%; border: 2px solid var(--tt-line); flex: none; }
  .radio.on { border: 6px solid var(--tt-blue); }
  .switch { width: 44px; height: 26px; border-radius: 13px; background: var(--tt-line);
    position: relative; flex: none; transition: background 0.15s; }
  .switch::after { content: ""; position: absolute; top: 3px; left: 3px; width: 20px; height: 20px;
    border-radius: 50%; background: #fff; transition: transform 0.15s; }
  .switch.on { background: var(--tt-blue); }
  .switch.on::after { transform: translateX(18px); }
`;

class TtlockSelfhostPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._locks = null;
    this._view = "home";
    this._mac = null;
    this._data = {};
    this._form = {};
    this._busy = null;
    this._flash = "";
    this._shown = {};
  }

  _t(key, vars) {
    return t(this._hass, key, vars);
  }

  set narrow(value) {
    this._narrow = value;
    this._render();
  }

  set hass(hass) {
    const before = this._hass;
    this._hass = hass;
    if (!before) {
      this._load();
      return;
    }
    if (!["home", "list"].includes(this._view)) return;
    const changed = (this._locks || []).some((lock) => {
      const id = lock.entities.lock;
      return id && before.states[id] !== hass.states[id];
    });
    if (changed || before.language !== hass.language) this._render();
  }

  connectedCallback() {
    this._poll = setInterval(() => this._load(), POLL_MS);
    if (this._hass) this._load();
  }

  disconnectedCallback() {
    clearInterval(this._poll);
    clearTimeout(this._hold);
  }

  _ws(command, fields = {}) {
    return this._hass.callWS({ type: WS + command, ...fields });
  }

  async _load() {
    if (!this._hass) return;
    try {
      this._locks = await this._ws("locks");
    } catch (err) {
      this._locks = this._locks || [];
    }
    if (!this._mac && this._locks.length === 1) this._mac = this._locks[0].mac;
    if (["home", "list", "gateway", "settings", "callback"].includes(this._view) && !this._editing()) {
      this._render();
    }
  }

  _editing() {
    const active = this.shadowRoot.activeElement;
    return active && ["INPUT", "SELECT"].includes(active.tagName);
  }

  _lock() {
    return (this._locks || []).find((lock) => lock.mac === this._mac) || null;
  }

  _say(text) {
    this._flash = text;
    clearTimeout(this._flashTimer);
    this._flashTimer = setTimeout(() => {
      this._flash = "";
      this._render();
    }, FLASH_MS);
    this._render();
  }

  _error(err) {
    const code = err && err.code;
    const known = { need_account: "err_need_account", unreachable: "err_unreachable", no_gateway: "err_no_gateway" };
    if (known[code]) return this._t(known[code]);
    const message = (err && err.message) || String(err);
    return message === "no_gateway" ? this._t("err_no_gateway") : this._t("failed", { err: message });
  }

  // Adds one lock to the dashboard, once: a card that already shows it is left alone.
  async _toDashboard(lock) {
    let config;
    try {
      config = await this._hass.callWS({ type: "lovelace/config", url_path: null });
    } catch (err) {
      config = null;
    }
    if (!config || !Array.isArray(config.views) || !config.views.length) {
      this._say(this._t("dashboard_auto"));
      return;
    }
    const entity = lock.entities.lock;
    const cards = [...cardsIn(config.views)].filter((card) => card.type === DOORS_CARD);
    if (cards.some((card) => !Array.isArray(card.entities) || card.entities.includes(entity))) {
      this._say(this._t("already_on_dashboard", { name: lock.name }));
      return;
    }
    // Doors stay side by side: a card with a fixed list takes the new lock.
    if (cards.length) cards[0].entities.push(entity);
    else {
      const card = { type: DOORS_CARD, entities: [entity] };
      const view = config.views[0];
      if (view.sections) view.sections.push({ type: "grid", cards: [card] });
      else (view.cards ||= []).push(card);
    }
    try {
      await this._hass.callWS({ type: "lovelace/config/save", url_path: null, config });
      this._say(this._t("sent_to_dashboard", { name: lock.name }));
    } catch (err) {
      this._say(this._error(err));
    }
  }

  _go(view, mac) {
    if (mac) this._mac = mac;
    this._view = view;
    this._form = {};
    this._shown = {};
    this._confirm = null;
    if (LISTS.includes(view)) this._fetch("credentials");
    if (view === "records") this._fetch("records");
    if (view === "ekeys" && this._lock().gateway.configured) this._fetch("ekeys");
    this._render();
  }

  async _fetch(what) {
    this._data[what] = null;
    this._render();
    try {
      this._data[what] = await this._ws(what, { mac: this._mac });
    } catch (err) {
      this._data[what] = { failed: this._error(err) };
    }
    this._render();
  }

  // ---- the bolt -------------------------------------------------------

  _stateOf(lock) {
    const entity = this._hass.states[lock.entities.lock];
    const state = entity ? entity.state : null;
    if (["locked", "unlocked", "locking", "unlocking"].includes(state)) return state;
    if (lock.locked === true) return "locked";
    return lock.locked === false ? "unlocked" : "unknown";
  }

  async _command(action) {
    const lock = this._lock();
    if (!lock || this._busy || !lock.entities.lock) return;
    this._busy = action;
    this._render();
    try {
      await this._hass.callService("lock", action, { entity_id: lock.entities.lock });
      const entity = this._hass.states[lock.entities.lock];
      const route = entity && entity.attributes.last_route;
      const via = route ? this._t(`via_${route}`) : "";
      this._busy = null;
      this._say(this._t(`done_${action}`, { via }).replace(" .", "."));
    } catch (err) {
      this._busy = null;
      this._say(this._error(err));
    }
    this._load();
  }

  _pressStart(event) {
    if (this._busy) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    this._held = false;
    clearTimeout(this._hold);
    this._hold = setTimeout(() => {
      this._held = true;
      this._hold = null;
      navigator.vibrate?.(40);
      this._command("lock");
    }, HOLD_MS);
  }

  _pressEnd() {
    if (!this._hold) return;
    clearTimeout(this._hold);
    this._hold = null;
    if (!this._held) this._command("unlock");
  }

  _pressCancel() {
    clearTimeout(this._hold);
    this._hold = null;
  }

  // ---- screens --------------------------------------------------------

  _render() {
    if (!this._hass) return;
    const root = this.shadowRoot;
    const lock = this._lock();
    let view = this._view;
    if (view !== "list" && !lock) view = "list";
    if (view === "home" && !lock) view = "list";
    const body = {
      list: () => this._list(),
      home: () => this._home(lock),
      passcodes: () => this._credentials(lock, "passcodes"),
      cards: () => this._credentials(lock, "cards"),
      fingerprints: () => this._credentials(lock, "fingerprints"),
      new_passcode: () => this._newPasscode(lock),
      ekeys: () => this._ekeys(lock),
      records: () => this._records(),
      gateway: () => this._gateway(lock),
      callback: () => this._callback(lock.gateway.callback),
      settings: () => this._settings(lock),
    }[view]();
    const single = (this._locks || []).length <= 1;
    const top = view === "list" || (view === "home" && single);
    const title =
      view === "list"
        ? this._t("locks")
        : view === "home"
          ? lock.name
          : this._t(view === "callback" ? "callback_title" : view);
    const back = () =>
      this._go(
        view === "home"
          ? "list"
          : view === "new_passcode"
            ? "passcodes"
            : view === "callback"
              ? this._callbackFrom || "list"
              : "home"
      );
    const menu = h("ha-menu-button");
    menu.hass = this._hass;
    menu.narrow = this._narrow;
    const left = top
      ? menu
      : h("button", { "aria-label": this._t("back"), onclick: back }, icon("mdi:chevron-left"));
    const right =
      view === "passcodes"
        ? h(
            "button",
            { "aria-label": this._t("new_passcode"), onclick: () => this._go("new_passcode") },
            icon("mdi:plus")
          )
        : view === "home"
          ? h(
              "button",
              {
                "aria-label": this._t("to_dashboard"),
                title: this._t("to_dashboard"),
                onclick: () => this._toDashboard(lock),
              },
              icon("mdi:view-dashboard-outline")
            )
          : h("span");
    const parts = [
      h("style", {}, STYLE),
      h("div", { class: "bar" }, left, h("h1", {}, title), right),
      h("div", { class: "page" }, body),
    ];
    if (this._flash) parts.push(h("div", { class: "toast", role: "status" }, this._flash));
    root.replaceChildren(...parts);
  }

  _list() {
    if (this._locks === null) return h("div", { class: "empty" }, this._t("loading"));
    if (!this._locks.length) {
      return h(
        "div",
        { class: "empty" },
        icon("mdi:lock-plus-outline"),
        h("p", {}, this._t("no_locks")),
        h(
          "a",
          { class: "primary", href: "/config/integrations/dashboard/add?domain=ttlock_selfhost" },
          this._t("add_lock")
        )
      );
    }
    return [
      h(
      "div",
      { class: "card" },
      this._locks.map((lock) =>
        h(
          "button",
          { class: "row", onclick: () => this._go("home", lock.mac) },
          icon(this._stateOf(lock) === "unlocked" ? "mdi:lock-open-variant" : "mdi:lock"),
          h("span", { class: "main" }, h("b", {}, lock.name), h("small", {}, this._t(this._stateOf(lock)))),
          h("span", { class: "side" }, lock.battery == null ? "" : `${lock.battery}%`),
          icon("mdi:chevron-right")
        )
      )
      ),
      // The callback belongs to the account, so it is offered once per entry.
      ...this._locks
        .filter(
          (lock, at, all) =>
            lock.gateway.callback && all.findIndex((other) => other.entry_id === lock.entry_id) === at
        )
        .map((lock) => this._callbackRow(lock, "list")),
    ];
  }

  _callbackRow(lock, from) {
    const cb = lock.gateway.callback;
    return h(
      "div",
      { class: "card" },
      h(
        "button",
        {
          class: "row",
          onclick: () => {
            this._callbackFrom = from;
            this._go("callback", lock.mac);
          },
        },
        icon(cb.received_at ? "mdi:bell-check-outline" : "mdi:bell-sleep-outline"),
        h(
          "span",
          { class: "main" },
          h("b", {}, this._t("callback_title")),
          h(
            "small",
            {},
            cb.received_at
              ? this._t("callback_last", { when: this._when(cb.received_at) })
              : this._t("callback_off")
          )
        ),
        icon("mdi:chevron-right")
      )
    );
  }

  _status(lock) {
    const near = lock.bluetooth.rssi != null;
    const gw = lock.gateway;
    const gwKey = !gw.configured ? "gw_off" : gw.has_gateway === false ? "gw_none" : "gw_on";
    const battery = lock.battery;
    const level = battery == null ? "unknown" : Math.max(10, Math.round(battery / 10) * 10);
    return h(
      "div",
      { class: "status" },
      h(
        "span",
        { title: this._t("battery") },
        icon(level === 100 ? "mdi:battery" : `mdi:battery-${level}`),
        battery == null ? "–" : `${battery}%`
      ),
      h(
        "span",
        {
          class: near ? "on" : "off",
          title: near ? this._t("bt_near", { rssi: lock.bluetooth.rssi }) : this._t("bt_far"),
        },
        icon(near ? "mdi:bluetooth" : "mdi:bluetooth-off")
      ),
      h(
        "span",
        { class: gwKey === "gw_on" ? "on" : "off", title: this._t(gwKey) },
        icon(gwKey === "gw_on" ? "mdi:router-wireless" : "mdi:router-wireless-off")
      )
    );
  }

  _home(lock) {
    const state = this._busy ? `${this._busy}ing` : this._stateOf(lock);
    const open = state === "unlocked" || state === "unlocking";
    const busy = state === "locking" || state === "unlocking";
    const ring = h(
      "button",
      {
        class: `ring${busy ? " busy" : ""}${state === "unknown" ? " unknown" : ""}`,
        "aria-label": `${this._t(state)}. ${this._t("hint_press")}`,
        onpointerdown: (event) => this._pressStart(event),
        onpointerup: () => this._pressEnd(),
        onpointercancel: () => this._pressCancel(),
        oncontextmenu: (event) => event.preventDefault(),
        onkeydown: (event) => {
          if (event.repeat) return;
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            this._command(event.shiftKey ? "lock" : "unlock");
          }
        },
      },
      icon(open ? "mdi:lock-open-variant" : "mdi:lock")
    );
    return [
      this._status(lock),
      h("div", { class: "ring-wrap" }, ring),
      h("p", { class: "state", "aria-live": "polite" }, this._t(state)),
      h("p", { class: "hint" }, this._t("hint_press")),
      h(
        "div",
        { class: "tiles" },
        TILES.map(([view, glyph]) =>
          h(
            "button",
            {
              class: `tile${view === "ekeys" && !lock.gateway.configured ? " dim" : ""}`,
              onclick: () => this._go(view),
            },
            icon(glyph),
            this._t(view)
          )
        )
      ),
    ];
  }

  _when(ms) {
    return new Date(ms).toLocaleString(this._hass.language, {
      dateStyle: "short",
      timeStyle: "short",
    });
  }

  _validity(item) {
    if (item.kind === 1) return this._t("one_time");
    if (!item.end || item.kind === 2) return this._t("permanent");
    return this._t("until", { start: this._when(item.start), end: this._when(item.end) });
  }

  _needsCloud() {
    return h(
      "div",
      { class: "empty" },
      icon("mdi:router-wireless-off"),
      h("p", {}, this._t("needs_cloud")),
      h("button", { class: "primary", onclick: () => this._go("gateway") }, this._t("connect_gateway"))
    );
  }

  _credentials(lock, kind) {
    const data = this._data.credentials;
    if (!data) return h("div", { class: "empty" }, this._t("loading"));
    if (data.failed) return h("div", { class: "empty" }, data.failed);
    const cloud = data.cloud && data.cloud[kind];
    const glyph = { passcodes: "mdi:dialpad", cards: "mdi:card-account-details-outline", fingerprints: "mdi:fingerprint" }[kind];
    const note =
      kind === "passcodes"
        ? cloud
          ? null
          : this._t("names_hint")
        : this._t(cloud ? "enroll_hint" : "names_hint");
    const rows = cloud
      ? cloud.map((item) => this._cloudRow(item, kind, glyph))
      : data.lock[kind].map((item) =>
          h(
            "div",
            { class: "row" },
            icon(glyph),
            h(
              "span",
              { class: "main" },
              h("b", {}, item.name || this._t(kind)),
              h("small", { class: "mono" }, item.label)
            )
          )
        );
    return [
      h("p", { class: "note" }, this._t(cloud ? "from_cloud" : "from_lock")),
      rows.length
        ? h("div", { class: "card" }, rows)
        : h("div", { class: "empty" }, icon(glyph), this._t("empty")),
      note ? h("p", { class: "note" }, note) : null,
      data.cloud && data.cloud.error
        ? h("p", { class: "note" }, this._t("cloud_error", { err: data.cloud.error }))
        : null,
    ];
  }

  _cloudRow(item, kind, glyph) {
    const name = item.name || this._t(kind);
    if (kind !== "passcodes") {
      return h(
        "div",
        { class: "row" },
        icon(glyph),
        h("span", { class: "main" }, h("b", {}, name), h("small", {}, this._validity(item))),
        h("span", { class: "side mono" }, item.label || "")
      );
    }
    if (this._confirm === item.id) {
      return h(
        "div",
        { class: "row" },
        h("span", { class: "main" }, this._t("confirm_delete", { name })),
        h("button", { class: "ghost danger", onclick: () => this._deletePasscode(item) }, this._t("yes")),
        h(
          "button",
          {
            class: "ghost",
            onclick: () => {
              this._confirm = null;
              this._render();
            },
          },
          this._t("no")
        )
      );
    }
    const shown = this._shown[item.id];
    return h(
      "div",
      { class: "row" },
      icon(glyph),
      h(
        "span",
        { class: "main" },
        h("b", {}, name),
        h("small", {}, this._validity(item)),
        h("small", { class: "mono" }, shown ? item.code : masked(item.code))
      ),
      h(
        "button",
        {
          class: "ghost",
          "aria-label": this._t(shown ? "hide" : "show"),
          onclick: () => {
            this._shown[item.id] = !shown;
            this._render();
          },
        },
        icon(shown ? "mdi:eye-off-outline" : "mdi:eye-outline")
      ),
      h(
        "button",
        {
          class: "ghost danger",
          "aria-label": this._t("delete"),
          onclick: () => {
            this._confirm = item.id;
            this._render();
          },
        },
        icon("mdi:trash-can-outline")
      )
    );
  }

  async _deletePasscode(item) {
    this._confirm = null;
    try {
      await this._ws("passcode/delete", { mac: this._mac, passcode_id: item.id });
      this._say(this._t("deleted"));
      this._fetch("credentials");
    } catch (err) {
      this._say(this._error(err));
    }
  }

  _field(label, name, props = {}) {
    const input = h("input", {
      value: this._form[name] ?? "",
      oninput: (event) => {
        this._form[name] = event.target.value;
      },
      ...props,
    });
    return h("label", { class: "field" }, h("span", {}, label), input);
  }

  _newPasscode(lock) {
    const form = this._form;
    const cloud = lock.gateway.configured;
    if (form.done) {
      return [
        h(
          "div",
          { class: "card" },
          h("p", { class: "center note", style: "margin-top:18px" }, this._t("passcode_ready")),
          h("div", { class: "big-code mono" }, form.done.code),
          h("p", { class: "center note" }, this._t(`via_${form.done.via}`))
        ),
        h(
          "button",
          {
            class: "primary",
            onclick: async () => {
              await navigator.clipboard?.writeText(form.done.code);
              this._say(this._t("copied"));
            },
          },
          this._t("copy")
        ),
      ];
    }
    form.tab = form.tab || (cloud ? "permanent" : "custom");
    const now = Math.floor(Date.now() / HOUR) * HOUR;
    form.start = form.start || localInput(now);
    form.end = form.end || localInput(now + 24 * HOUR);
    const tab = form.tab;
    const tabs = h(
      "div",
      { class: "tabs", role: "tablist" },
      ["permanent", "timed", "one_time", "custom"].map((name) =>
        h(
          "button",
          {
            role: "tab",
            "aria-selected": String(tab === name),
            disabled: name !== "custom" && !cloud,
            onclick: () => {
              form.tab = name;
              this._render();
            },
          },
          this._t(name)
        )
      )
    );
    const timed = tab === "timed" || (tab === "custom" && !form.forever);
    const fields = [
      tab === "custom"
        ? this._field(this._t("code"), "code", {
            inputMode: "numeric",
            maxLength: 9,
            autocomplete: "off",
            pattern: "[0-9]*",
          })
        : null,
      this._field(this._t("name"), "name", { placeholder: this._t("name_hint"), maxLength: 40 }),
      tab === "custom"
        ? h(
            "label",
            { class: "check" },
            h("input", {
              type: "checkbox",
              checked: !!form.forever,
              onchange: (event) => {
                form.forever = event.target.checked;
                this._render();
              },
            }),
            this._t("no_end")
          )
        : null,
      timed ? this._field(this._t("starts"), "start", { type: "datetime-local" }) : null,
      timed ? this._field(this._t("ends"), "end", { type: "datetime-local" }) : null,
    ];
    const hint =
      tab === "custom"
        ? this._t(lock.admin || cloud ? "hint_custom" : "hint_custom_admin")
        : this._t(tab === "one_time" ? "hint_one_time" : "hint_random");
    return [
      tabs,
      h("div", { class: "card" }, fields),
      h("p", { class: "note" }, hint),
      !cloud && tab !== "custom" ? h("p", { class: "note" }, this._t("needs_cloud")) : null,
      h(
        "button",
        { class: "primary", disabled: !!form.sending, onclick: () => this._createPasscode() },
        this._t(tab === "custom" ? "set_code" : "generate")
      ),
    ];
  }

  async _createPasscode() {
    const form = this._form;
    const fields = { mac: this._mac, name: (form.name || "").trim() };
    const timed = form.tab === "timed" || (form.tab === "custom" && !form.forever);
    if (timed) {
      fields.start = new Date(form.start).getTime();
      fields.end = new Date(form.end).getTime();
      if (!(fields.end > fields.start)) return this._say(this._t("failed", { err: this._t("ends") }));
    }
    if (form.tab === "custom") {
      if (!/^\d{4,9}$/.test(form.code || "")) return this._say(this._t("code"));
      fields.code = form.code;
    } else {
      fields.random = RANDOM_KIND[form.tab];
      if (!timed) fields.start = Math.floor(Date.now() / HOUR) * HOUR;
    }
    form.sending = true;
    this._render();
    try {
      form.done = await this._ws("passcode/add", fields);
    } catch (err) {
      this._say(this._error(err));
    }
    form.sending = false;
    this._render();
    return null;
  }

  _ekeys(lock) {
    if (!lock.gateway.configured) return this._needsCloud();
    const data = this._data.ekeys;
    if (!data) return h("div", { class: "empty" }, this._t("loading"));
    if (data.failed) return h("div", { class: "empty" }, data.failed);
    if (!data.length) return h("div", { class: "empty" }, icon("mdi:key-variant"), this._t("empty"));
    return h(
      "div",
      { class: "card" },
      data.map((key) =>
        h(
          "div",
          { class: "row" },
          icon("mdi:key-variant"),
          h(
            "span",
            { class: "main" },
            h("b", {}, key.name || key.user || ""),
            h("small", {}, key.user || ""),
            h("small", {}, key.admin ? this._t("ekey_admin") : this._validity(key))
          ),
          h("span", { class: "side" }, this._t(EKEY_STATUS[key.status] || "ekey_other"))
        )
      )
    );
  }

  _recordText(record) {
    const type = record.type in RECORD_ICONS ? record.type : "other";
    const what = this._t(`rec_${type}`, { code: record.code ?? "" });
    const how = record.how ? this._t(`how_${record.how}`) : "";
    return how && !how.startsWith("how_") ? this._t("with_how", { what, how }) : what;
  }

  _dayOf(ms) {
    const day = new Date(ms);
    const today = new Date();
    const gap = Math.round(
      (new Date(today.getFullYear(), today.getMonth(), today.getDate()) -
        new Date(day.getFullYear(), day.getMonth(), day.getDate())) /
        86400000
    );
    if (gap === 0) return this._t("today");
    if (gap === 1) return this._t("yesterday");
    return day.toLocaleDateString(this._hass.language, { dateStyle: "medium" });
  }

  _records() {
    const data = this._data.records;
    if (!data) return h("div", { class: "empty" }, this._t("loading"));
    if (data.failed) return h("div", { class: "empty" }, data.failed);
    const out = [h("p", { class: "note" }, this._t(data.source === "cloud" ? "from_cloud" : "from_lock"))];
    if (!data.records.length) {
      out.push(h("div", { class: "empty" }, icon("mdi:history"), this._t("empty")));
      return out;
    }
    let day = null;
    let card = null;
    for (const record of data.records) {
      const label = record.at ? this._dayOf(record.at) : "";
      if (label !== day || !card) {
        day = label;
        card = h("div", { class: "card" });
        out.push(h("div", { class: "day" }, label), card);
      }
      const type = record.type in RECORD_ICONS ? record.type : "other";
      card.append(
        h(
          "div",
          { class: "row" },
          icon(RECORD_ICONS[type]),
          h(
            "span",
            { class: "main" },
            h("b", {}, this._recordText(record)),
            record.who ? h("small", {}, record.who) : null
          ),
          h(
            "span",
            { class: "side" },
            record.at
              ? new Date(record.at).toLocaleTimeString(this._hass.language, { timeStyle: "short" })
              : ""
          )
        )
      );
    }
    return out;
  }

  _callback(cb) {
    if (!cb) return [];
    const url = cb.url || location.origin + cb.path;
    return [
      h(
        "div",
        { class: "card" },
        h(
          "div",
          { class: "row" },
          icon(cb.received_at ? "mdi:bell-check-outline" : "mdi:bell-sleep-outline"),
          h(
            "span",
            { class: "main" },
            h("b", {}, this._t(cb.received_at ? "callback_on" : "callback_off")),
            h(
              "small",
              {},
              cb.received_at
                ? this._t("callback_last", { when: this._when(cb.received_at) })
                : this._t("callback_never")
            )
          )
        ),
        h("div", { class: "url mono" }, url)
      ),
      h("p", { class: "note" }, this._t(cb.url ? "callback_steps" : "callback_steps_local")),
      h(
        "button",
        {
          class: "primary",
          onclick: async () => {
            await navigator.clipboard?.writeText(url);
            this._say(this._t("callback_copied"));
          },
        },
        this._t("callback_copy")
      ),
    ];
  }

  _gateway(lock) {
    const gw = lock.gateway;
    const form = this._form;
    if (gw.configured) {
      return [
        h(
          "div",
          { class: "card" },
          h(
            "div",
            { class: "row" },
            icon("mdi:cloud-check-outline"),
            h(
              "span",
              { class: "main" },
              h("b", {}, this._t("connected_as", { account: lock.account || "TTLock" })),
              h("small", {}, this._t(gw.has_gateway === false ? "gw_none" : "gw_on"))
            )
          )
        ),
        gw.gateways.length ? h("div", { class: "day" }, this._t("gateways_near")) : null,
        gw.gateways.length
          ? h(
              "div",
              { class: "card" },
              gw.gateways.map((row) =>
                h(
                  "div",
                  { class: "row" },
                  icon("mdi:router-wireless"),
                  h("span", { class: "main" }, h("b", {}, row.name || "Gateway")),
                  h("span", { class: "side" }, row.rssi == null ? "" : this._t("signal", { rssi: row.rssi }))
                )
              )
            )
          : null,
        gw.error ? h("p", { class: "note" }, this._t("cloud_error", { err: gw.error })) : null,
        gw.callback ? this._callbackRow(lock, "gateway") : null,
        h("p", { class: "note" }, this._t("gw_intro")),
        h("button", { class: "secondary", onclick: () => this._disconnect(lock) }, this._t("disconnect")),
      ];
    }
    return [
      h("p", { class: "note" }, this._t("gw_intro")),
      h("p", { class: "note" }, this._t("gw_steps")),
      h(
        "div",
        { class: "card" },
        this._field(this._t("client_id"), "client_id", { autocomplete: "off", spellcheck: false }),
        this._field(this._t("client_secret"), "client_secret", {
          type: "password",
          autocomplete: "new-password",
        }),
        lock.account
          ? null
          : [
              this._field(this._t("username"), "username", { autocomplete: "off" }),
              this._field(this._t("password"), "password", {
                type: "password",
                autocomplete: "new-password",
              }),
            ],
        h(
          "label",
          { class: "field" },
          h("span", {}, this._t("region")),
          h(
            "select",
            {
              onchange: (event) => {
                form.region = event.target.value;
              },
            },
            ["eu", "cn"].map((region) =>
              h(
                "option",
                { value: region, selected: (form.region || "eu") === region },
                this._t(`region_${region}`)
              )
            )
          )
        )
      ),
      h(
        "button",
        { class: "primary", disabled: !!form.sending, onclick: () => this._connect(lock) },
        this._t("connect")
      ),
    ];
  }

  async _connect(lock) {
    const form = this._form;
    const fields = {
      entry_id: lock.entry_id,
      client_id: (form.client_id || "").trim(),
      client_secret: (form.client_secret || "").trim(),
      region: form.region || "eu",
    };
    if (!fields.client_id || !fields.client_secret) return;
    if (form.username) fields.username = form.username.trim();
    if (form.password) fields.password = form.password;
    form.sending = true;
    this._render();
    try {
      const result = await this._ws("gateway/connect", fields);
      this._form = {};
      this._say(this._t("connected_ok", { n: result.locks }));
      setTimeout(() => this._load(), 2500);
    } catch (err) {
      form.sending = false;
      this._say(this._error(err));
    }
  }

  async _disconnect(lock) {
    try {
      await this._ws("gateway/disconnect", { entry_id: lock.entry_id });
      this._say(this._t("disconnected"));
      setTimeout(() => this._load(), 2500);
    } catch (err) {
      this._say(this._error(err));
    }
  }

  async _option(lock, fields) {
    Object.assign(lock, fields);
    this._render();
    try {
      await this._ws("options", { entry_id: lock.entry_id, ...fields });
      this._say(this._t("saved"));
      setTimeout(() => this._load(), 2500);
    } catch (err) {
      this._say(this._error(err));
    }
  }

  _settings(lock) {
    const sound = lock.entities.sound && this._hass.states[lock.entities.sound];
    const toggle = (label, hint, on, change) =>
      h(
        "button",
        { class: "row", role: "switch", "aria-checked": String(on), onclick: change },
        h("span", { class: "main" }, h("b", {}, label), hint ? h("small", {}, hint) : null),
        h("span", { class: `switch${on ? " on" : ""}` })
      );
    const info = (label, value) =>
      h("div", { class: "row" }, h("span", { class: "main" }, label), h("span", { class: "side" }, value ?? "–"));
    return [
      h("div", { class: "day" }, this._t("route")),
      h(
        "div",
        { class: "card" },
        ["auto", "bluetooth", "gateway"].map((route) =>
          h(
            "button",
            {
              class: "row",
              role: "radio",
              "aria-checked": String(lock.route === route),
              onclick: () => lock.route !== route && this._option(lock, { route }),
            },
            h("span", { class: `radio${lock.route === route ? " on" : ""}` }),
            h(
              "span",
              { class: "main" },
              h("b", {}, this._t(`route_${route}`)),
              h("small", {}, this._t(`route_${route}_hint`))
            )
          )
        )
      ),
      h(
        "div",
        { class: "card" },
        sound && sound.state !== "unavailable"
          ? toggle(this._t("sound"), null, sound.state === "on", async () => {
              try {
                await this._hass.callService("switch", sound.state === "on" ? "turn_off" : "turn_on", {
                  entity_id: lock.entities.sound,
                });
              } catch (err) {
                this._say(this._error(err));
              }
              this._render();
            })
          : null,
        toggle(
          this._t("permanent_connection"),
          this._t("permanent_connection_hint"),
          lock.permanent_connection,
          () => this._option(lock, { permanent_connection: !lock.permanent_connection })
        )
      ),
      h("div", { class: "day" }, this._t("about")),
      h(
        "div",
        { class: "card" },
        info(this._t("model"), lock.model),
        info(this._t("battery"), lock.battery == null ? null : `${lock.battery}%`),
        info(this._t("mac"), lock.mac),
        info(this._t("lock_id"), lock.lock_id),
        info(this._t("account"), lock.account),
        info(this._t("admin_key"), this._t(lock.admin ? "yes_word" : "no_word"))
      ),
      h(
        "button",
        {
          class: "primary",
          disabled: !!this._form.sending,
          onclick: async () => {
            this._form.sending = true;
            this._render();
            try {
              const result = await this._ws("refresh", { mac: lock.mac });
              this._say(this._t(`read_${result.via}`));
            } catch (err) {
              this._say(this._error(err));
            }
            this._form.sending = false;
            this._load();
          },
        },
        this._t("read_now")
      ),
    ];
  }
}

customElements.define("ttlock-selfhost-panel", TtlockSelfhostPanel);
