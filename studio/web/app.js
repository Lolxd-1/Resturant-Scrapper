// Menu Studio single-page UI. No frameworks, no build step, no external requests.
// Every server-provided string is inserted as text (textContent), never as HTML.

"use strict";

const THUMB_SUFFIX = "?fit=around%7C300%3A300&crop=300%3A300%3B%2A%2C%2A";
const IMGBB_URL = "https://api.imgbb.com/";

const STAGES = [
  ["read", "Read menu", "Reading the menu"],
  ["source", "Restaurant", "Looking for the restaurant on Zomato"],
  ["match", "Match", "Matching dishes"],
  ["search", "Search", "Searching Zomato"],
  ["verify", "Check", "Checking photos"],
  ["photos", "Photos", "Downloading photos"],
  ["upload", "Upload", "Uploading photos"],
  ["build", "Sheets", "Building sheets"],
];

const STATUS_PILL = {
  queued: ["Queued", "blue", "clock"],
  running: ["Running", "blue", "spin"],
  done: ["Done", "green", "check"],
  cancelled: ["Cancelled", "", "x"],
  failed: ["Failed", "red", "alert"],
  interrupted: ["Interrupted", "orange", "pause"],
};

const DISH_STATUS = {
  ready: ["Ready", "green", "check"],
  needs_photo: ["Needs photo", "orange", "photo"],
  needs_price: ["Needs price", "orange", "tag"],
  error: ["Error", "red", "alert"],
};

const FILTERS = [
  ["all", "All"],
  ["ready", "Ready"],
  ["needs_photo", "Needs photo"],
  ["needs_price", "Needs price"],
  ["error", "Errors"],
];

const DEPTHS = [[80, "Quick (80 menus)"], [250, "Standard (250 menus)"], [600, "Deep (600 menus)"]];
const MENU_EXTS = [".xlsx", ".xlsm", ".csv"];

// Static SVG path data only (never data from the server).
const ICONS = {
  new: '<rect x="4" y="4" width="16" height="16" rx="4"/><path d="M12 8.5v7M8.5 12h7"/>',
  history: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  settings: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  x: '<path d="M7 7l10 10M17 7L7 17"/>',
  alert: '<path d="M12 3.5l9 16H3z"/><path d="M12 10v4.5M12 17.3v.2"/>',
  pause: '<path d="M9.5 7v10M14.5 7v10"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  chevron: '<path d="M9.5 6l6 6-6 6"/>',
  upload: '<path d="M12 15.5V4.5M7.5 9l4.5-4.5L16.5 9"/><path d="M4.5 15v3.5a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5V15"/>',
  download: '<path d="M12 4.5v11M7.5 11l4.5 4.5 4.5-4.5"/><path d="M4.5 19.5h15"/>',
  photo: '<rect x="3.5" y="5" width="17" height="14" rx="3"/><circle cx="9" cy="10" r="1.6"/><path d="M4 17l5-4.5 3.5 3 3-2.5 4.5 4"/>',
  tag: '<path d="M4 4h7.5l8.5 8.5-7.5 7.5L4 11.5z"/><circle cx="8.3" cy="8.3" r="1.3"/>',
  key: '<circle cx="8" cy="15" r="3.5"/><path d="M10.5 12.5L19 4M16 7l2.5 2.5M14 9l1.5 1.5"/>',
  trash: '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 12.5h9l1-12.5"/>',
  paste: '<rect x="6" y="5" width="12" height="15.5" rx="2"/><path d="M9.5 3.5h5v3h-5z"/>',
  link: '<path d="M14 4.5h5.5V10M19.5 4.5L11 13"/><path d="M17 14v4a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 5 18V8.5A1.5 1.5 0 0 1 6.5 7h4"/>',
  tray: '<path d="M3.5 13.5l2.5-8h12l2.5 8v5a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5z"/><path d="M3.5 13.5h5l1 2h5l1-2h5"/>',
  fork: '<path d="M7 3.5v6a2.5 2.5 0 0 0 5 0v-6M9.5 3.5v17"/><path d="M17 20.5v-17c-2 1-3 3.5-3 6.5v3h3"/>',
};

// ---------- DOM helpers ----------

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "value" || k === "checked") el[k] = v;
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  append(el, kids);
  return el;
}

function append(el, kids) {
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function fromStatic(markup) {
  const t = document.createElement("template");
  t.innerHTML = markup;
  return t.content.firstElementChild;
}

function icon(name) {
  if (name === "spin") return h("span", { class: "spinner", "aria-hidden": "true" });
  return fromStatic(`<svg class="svg-ic" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${ICONS[name]}</svg>`);
}

function pill(label, colour, iconName) {
  return h("span", { class: `pill ${colour || ""}` }, iconName ? icon(iconName) : null, label);
}

function statusPill(status) {
  const [label, colour, ic] = STATUS_PILL[status] || [status || "Unknown", "", null];
  return pill(label, colour, ic);
}

function clear(el) {
  el.replaceChildren();
  return el;
}

// ---------- API ----------

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch {
    throw new Error("Menu Studio is not responding. Is the app still running?");
  }
  const text = await res.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = null; }
  }
  if (!res.ok) {
    const detail = data && data.detail;
    const message = typeof detail === "string" ? detail
      : res.status === 404 ? "Not found" : `Request failed (${res.status})`;
    throw new Error(message);
  }
  return data;
}

// Downloads go through fetch so a refused download (e.g. the sheet is open in Excel) shows its reason
// as a toast instead of saving an error page as the file.
async function download(e) {
  e.preventDefault();
  const link = e.currentTarget;
  let res;
  try {
    res = await fetch(link.href);
  } catch {
    toastError(new Error("Menu Studio is not responding. Is the app still running?"));
    return;
  }
  if (!res.ok) {
    let detail = null;
    try { detail = (await res.json()).detail; } catch { detail = null; }
    toastError(new Error(typeof detail === "string" ? detail : `Download failed (${res.status})`));
    return;
  }
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = /filename\*=utf-8''([^;]+)/i.exec(disposition) || /filename="([^"]+)"/i.exec(disposition);
  const url = URL.createObjectURL(await res.blob());
  const a = h("a", { href: url, download: match ? decodeURIComponent(match[1]) : "" });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------- toasts ----------

function toast(message, kind = "ok") {
  const el = h("div", { class: `toast ${kind}` }, icon(kind === "error" ? "alert" : "check"), message);
  document.getElementById("toasts").append(el);
  setTimeout(() => {
    el.classList.add("out");
    setTimeout(() => el.remove(), 250);
  }, 2500);
}

function toastError(err) {
  toast(err && err.message ? err.message : String(err), "error");
}

// ---------- formatting ----------

function formatPrice(p) {
  if (p == null) return "—";
  return "₹" + Number(p).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function formatCount(n) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (n >= 1000) return `${Math.round(n / 1000)}k`;
  return String(n);
}

function formatDate(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso || "";
  return d.toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
}

function derivePrefix(vendor) {
  const words = (vendor || "").match(/[A-Za-z0-9]+(?:'[A-Za-z]+)?/g) || [];
  let prefix;
  if (!words.length) prefix = "SKU";
  else if (words.length === 1) prefix = words[0].toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 3);
  else prefix = words.slice(0, 3).map((w) => w[0]).join("").toUpperCase();
  prefix = prefix.replace(/[^A-Z0-9]/g, "").slice(0, 6);
  return prefix || "SKU";
}

function sourceCaption(r) {
  if (!r.source) return "";
  if (r.source === "own") return "Own menu";
  if (r.source === "chain") return "Chain photo";
  return r.restaurant ? `From ${r.restaurant}` : "From Zomato";
}

function confidenceDot(r) {
  const has = Boolean(r.zomato_img);
  const cls = !has ? "" : r.confidence >= 0.85 ? "green" : "orange";
  const label = has ? `Confidence ${Math.round(r.confidence * 100)}%` : "No match";
  return h("span", { class: `conf ${cls}`, role: "img", "aria-label": label, title: label });
}

// ---------- system status ----------

let system = null;
let systemTimer = null;

async function refreshSystem() {
  clearTimeout(systemTimer);
  try {
    system = await api("GET", "/api/system");
  } catch {
    system = null;
  }
  renderSystem();
  systemTimer = setTimeout(refreshSystem, system && system.ready ? 30000 : 3000);
}

function renderSystem() {
  const box = clear(document.getElementById("sys"));
  if (!system) {
    box.append(pill("Not connected", "red", "alert"));
  } else if (typeof system.free_gb === "number" && system.free_gb < 1.5) {
    box.append(pill(`Low disk space · ${system.free_gb} GB free`, "orange", "alert"));
  } else if (!system.ready) {
    const failed = system.status.startsWith("Engine failed");
    box.append(failed ? pill(system.status, "red", "alert") : pill(system.status, "blue", "spin"));
  } else if (!system.vision) {
    const msg = system.status && system.status !== "Ready" ? system.status : "Visual check unavailable";
    box.append(pill(msg, "orange", "alert"));
  } else if (!system.keys) {
    box.append(h("a", { class: "pill orange", href: "#/settings" }, icon("key"), "No ImgBB key — add one"));
  } else {
    box.append(pill(`Ready · ${formatCount(system.pool_items)} photos`, "green", "check"));
  }
}

// ---------- router ----------

const NAV = [
  ["#/new", "New Job", "new"],
  ["#/history", "History", "history"],
  ["#/settings", "Settings", "settings"],
];

let cleanup = null;

function renderNav(active) {
  const nav = clear(document.getElementById("nav"));
  for (const [href, label, ic] of NAV) {
    nav.append(h("li", null, h("a", { href, "aria-current": href === active ? "page" : null }, icon(ic), h("span", null, label))));
  }
}

function route() {
  if (cleanup) cleanup();
  cleanup = null;
  closeSheet();
  const hash = location.hash || "#/new";
  const view = clear(document.getElementById("view"));
  const job = hash.match(/^#\/job\/([^/?#]+)$/);
  if (job) {
    renderNav("#/history");
    cleanup = jobView(view, decodeURIComponent(job[1]));
  } else if (hash === "#/history") {
    renderNav(hash);
    historyView(view);
  } else if (hash === "#/settings") {
    renderNav(hash);
    settingsView(view);
  } else {
    renderNav("#/new");
    cleanup = newJobView(view);
  }
  view.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

// ---------- New Job ----------

function newJobView(view) {
  let preview = null;
  let prefixEdited = false;
  let busy = false;
  let alive = true;

  const fileInput = h("input", { type: "file", accept: MENU_EXTS.join(","), hidden: true, onchange: () => fileInput.files[0] && upload(fileInput.files[0]) });
  const dropText = h("strong", null, "Drop your menu here");
  const dropSub = h("span", null, "Excel (.xlsx, .xlsm) or CSV · or click to browse");
  const drop = h("div", {
    class: "drop", role: "button", tabindex: "0", "aria-label": "Choose a menu file",
    onclick: () => fileInput.click(),
    onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } },
    ondragover: (e) => { e.preventDefault(); drop.classList.add("over"); },
    ondragleave: () => drop.classList.remove("over"),
    ondrop: (e) => {
      e.preventDefault();
      drop.classList.remove("over");
      const f = e.dataTransfer.files[0];
      if (f) upload(f);
    },
  }, icon("upload"), dropText, dropSub);

  const nameInput = h("input", { class: "input", id: "f-name", required: true, autocomplete: "off", placeholder: "e.g. Hungry Fox Cafe", oninput: () => {
    if (!prefixEdited) prefixInput.value = nameInput.value.trim() ? derivePrefix(nameInput.value) : "";
    updateStart();
  } });
  const citySelect = h("select", { class: "input", id: "f-city" }, h("option", { value: "" }, "Any city"));
  const prefixInput = h("input", { class: "input", id: "f-prefix", maxlength: "6", autocomplete: "off", placeholder: "HFC", oninput: () => {
    prefixEdited = prefixInput.value.trim() !== "";
    prefixInput.value = prefixInput.value.toUpperCase().replace(/[^A-Z0-9]/g, "");
  } });
  const urlInput = h("input", { class: "input", id: "f-url", type: "url", autocomplete: "off", placeholder: "zomato.com/pune/…", "aria-describedby": "f-url-help" });

  const banner = h("div", { hidden: true });
  const summary = h("div");
  const startBtn = h("button", { class: "btn primary big", disabled: true, onclick: start }, "Find photos");

  view.append(
    h("h1", { class: "large-title" }, "New job"),
    banner,
    h("section", { class: "card", "aria-label": "Menu and restaurant" },
      drop, fileInput,
      h("div", { class: "fields" },
        h("div", { class: "field" }, h("label", { for: "f-name" }, "Restaurant name"), nameInput),
        h("div", { class: "field" }, h("label", { for: "f-city" }, "City"), citySelect),
        h("div", { class: "field" }, h("label", { for: "f-prefix" }, "SKU prefix"), prefixInput),
        h("div", { class: "field" }, h("label", { for: "f-url" }, "Zomato link (optional)"), urlInput,
          h("span", { class: "caption", id: "f-url-help" }, "Paste the restaurant's own Zomato page for exact photos")),
      ),
    ),
    summary,
    h("div", { class: "actions" }, startBtn),
  );

  api("GET", "/api/settings").then((s) => {
    if (!alive) return;
    for (const c of s.cities) citySelect.append(h("option", { value: c }, cityLabel(c)));
    citySelect.value = s.default_city || "";
    const keys = s.imgbb_keys.filter((k) => k.tail).length;
    if (!keys) {
      banner.className = "banner";
      banner.hidden = false;
      append(clear(banner), [icon("key"),
        h("span", null, "No ImgBB key yet. Photos will be found, but the sheet can't link them until you add a key."),
        h("a", { class: "btn", href: "#/settings" }, "Add key")]);
    }
  }).catch(toastError);

  function updateStart() {
    startBtn.disabled = busy || !preview || preview.errors.length > 0 || !nameInput.value.trim();
  }

  async function upload(file) {
    const ext = (file.name.match(/\.[^.]+$/) || [""])[0].toLowerCase();
    if (!MENU_EXTS.includes(ext)) {
      toast("Choose an .xlsx, .xlsm or .csv file", "error");
      return;
    }
    const form = new FormData();
    form.append("file", file);
    drop.classList.add("busy");
    dropText.textContent = `Reading ${file.name}…`;
    try {
      const p = await api("POST", "/api/menu/preview", form);
      if (!alive) return;
      preview = p;
      dropText.textContent = p.file_name || file.name;
      dropSub.textContent = "Drop another file or click to replace";
      renderSummary();
    } catch (err) {
      dropText.textContent = "Drop your menu here";
      toastError(err);
    } finally {
      drop.classList.remove("busy");
      fileInput.value = "";
      updateStart();
    }
  }

  function renderSummary() {
    const p = preview;
    clear(summary);
    const card = h("section", { class: "card", "aria-label": "Menu summary" },
      h("div", { class: "card-head" },
        h("h2", { class: "title2 num" }, `${p.rows.length} dishes · ${p.categories.length} categories`),
        h("span", { class: "caption" }, p.sheet ? `Sheet: ${p.sheet}` : "")),
      h("div", { class: "chips" }, p.categories.map((c) => h("span", { class: "chip" }, c.name || "Uncategorised", h("b", { class: "num" }, c.count)))),
    );
    if (p.errors.length) {
      card.append(h("div", { class: "banner red", role: "alert" }, icon("alert"),
        h("span", null, h("strong", null, "This file can't be used yet. Fix it and upload again."),
          h("ul", { class: "errors" }, p.errors.map((e) => h("li", null, e))))));
    }
    if (p.warnings.length) {
      card.append(h("details", { class: "warn" },
        h("summary", null, `${p.warnings.length} warning${p.warnings.length === 1 ? "" : "s"}`),
        h("ul", null, p.warnings.map((w) => h("li", null, w)))));
    }
    if (p.rows.length) {
      card.append(h("div", { class: "table-wrap" }, h("table", null,
        h("thead", null, h("tr", null, h("th", { scope: "col" }, "Dish"), h("th", { scope: "col" }, "Category"), h("th", { scope: "col", class: "num" }, "Price"))),
        h("tbody", null, p.rows.map((r) => h("tr", null,
          h("td", null, r.name), h("td", null, r.category), h("td", { class: "num" }, formatPrice(r.price))))))));
    }
    summary.append(card);
  }

  async function start() {
    busy = true;
    updateStart();
    try {
      const res = await api("POST", "/api/jobs", {
        vendor: nameInput.value.trim(),
        upload_id: preview.upload_id,
        city: citySelect.value,
        sku_prefix: prefixInput.value.trim(),
        zomato_url: urlInput.value.trim(),
      });
      location.hash = `#/job/${encodeURIComponent(res.id)}`;
    } catch (err) {
      toastError(err);
      busy = false;
      updateStart();
    }
  }

  return () => { alive = false; };
}

function cityLabel(slug) {
  if (slug === "ncr") return "Delhi NCR";
  return slug.split(/[-_]/).map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

// ---------- Job view ----------

function jobView(view, id) {
  const base = `/api/jobs/${encodeURIComponent(id)}`;
  let job = null;
  let active = false;
  const results = new Map(); // sku -> DishResult
  const tiles = new Map(); // sku -> { r, el }
  const imgVersion = new Map();
  let stage = "";
  let stageProgress = 0;
  let stageLabel = "";
  let lastLog = "";
  let lastId = -1;
  let es = null;
  let retry = 0;
  let retryTimer = null;
  let alive = true;
  let filter = "all";
  let query = "";
  let frame = 0;

  const head = h("div", { class: "job-head" });
  const tracker = h("div");
  const hero = h("div");
  const toolbar = h("div", { class: "toolbar", hidden: true });
  const list = h("div");
  view.append(head, tracker, hero, toolbar, list);

  const seg = h("div", { class: "seg", role: "group", "aria-label": "Filter dishes" });
  const search = h("input", { class: "input search", type: "search", placeholder: "Search dishes", "aria-label": "Search dishes", oninput: () => { query = search.value.trim().toLowerCase(); renderList(); } });
  toolbar.append(seg, search);

  load();

  async function load() {
    try {
      const data = await api("GET", base);
      if (!alive) return;
      applyJob(data);
      if (active) connect();
    } catch (err) {
      if (!alive) return;
      clear(view).append(h("div", { class: "empty" }, icon("alert"), h("h2", { class: "title2" }, "Couldn't open this job"), h("p", null, err.message),
        h("a", { class: "btn", href: "#/history" }, "Back to history")));
    }
  }

  function applyJob(data) {
    job = data.job;
    active = data.active;
    if (!active || results.size === 0) {
      results.clear();
      for (const r of data.results) results.set(r.sku, r);
    }
    if (job.stage && !stage) stage = job.stage;
    renderAll();
  }

  function status() {
    if (!job) return "";
    if (active && job.status !== "running") return job.status === "queued" ? "queued" : "running";
    return job.status;
  }

  function isRunning() {
    const s = status();
    return s === "running" || s === "queued";
  }

  function connect() {
    if (!alive) return;
    es = new EventSource(`${base}/events?after=${lastId}`);
    es.onmessage = (e) => {
      retry = 0;
      if (e.lastEventId !== "") lastId = Number(e.lastEventId);
      let ev;
      try { ev = JSON.parse(e.data); } catch { return; }
      handleEvent(ev);
    };
    // The server ends the stream after done/error or when the job stops; EventSource would then
    // reconnect with a stale ?after=, so reconnect manually after checking the job state.
    es.onerror = () => {
      es.close();
      es = null;
      if (!alive) return;
      const wait = Math.min(10000, 500 * 2 ** retry);
      retry = Math.min(retry + 1, 5);
      retryTimer = setTimeout(() => recheck(false, false), wait);
    };
  }

  // terminal: a done/error event was just received; the worker may still list the job as active
  // for a moment while it cleans up, so trust the finished job.json status instead.
  async function recheck(showError, terminal) {
    if (!alive) return;
    try {
      const data = await api("GET", base);
      if (!alive) return;
      if (terminal && ["done", "failed", "cancelled"].includes(data.job.status)) data.active = false;
      applyJob(data);
      if (active) {
        if (!es) connect();
      } else if (showError && job.status === "failed" && job.error) {
        toast(job.error, "error");
      }
    } catch {
      if (alive) retryTimer = setTimeout(() => recheck(showError, terminal), 5000);
    }
  }

  function handleEvent(ev) {
    if (ev.type === "stage") {
      stage = ev.stage;
      stageProgress = ev.progress || 0;
      stageLabel = ev.label || "";
      if (job.status !== "running") {
        job.status = "running";
        renderHead();
      }
      renderTracker();
    } else if (ev.type === "log") {
      lastLog = ev.message || "";
      renderTracker();
    } else if (ev.type === "dish") {
      results.set(ev.result.sku, ev.result);
      scheduleList();
      renderTracker();
    } else if (ev.type === "done" || ev.type === "error") {
      if (es) { es.close(); es = null; }
      clearTimeout(retryTimer);
      recheck(ev.type === "error", true);
    }
  }

  function renderAll() {
    renderHead();
    renderTracker();
    renderHero();
    renderList();
  }

  function renderHead() {
    const s = status();
    const actions = [];
    if (isRunning()) {
      actions.push(h("button", { class: "btn danger", onclick: cancel }, icon("x"), "Cancel"));
    } else if (["interrupted", "failed", "cancelled"].includes(s)) {
      actions.push(h("button", { class: "btn primary", onclick: resume }, "Resume"));
    }
    append(clear(head), [h("h1", { class: "large-title" }, job.vendor || id), statusPill(s), actions]);
  }

  function counts() {
    const c = { total: results.size, photos: 0, ready: 0, needs_photo: 0, needs_price: 0, error: 0 };
    for (const r of results.values()) {
      if (r.local_image) c.photos += 1;
      if (r.status in c) c[r.status] += 1;
    }
    return c;
  }

  // Built once per run and then updated in place, so the pulse animation isn't restarted on every event.
  let tr = null;

  function buildTracker() {
    const items = STAGES.map(([, short]) => {
      const dot = h("span", { class: "dot" });
      return { li: h("li", { class: "stage" }, dot, h("span", null, short)), dot, short, state: "" };
    });
    tr = {
      items,
      label: h("span", { class: "headline" }),
      pct: h("span", { class: "caption num" }),
      bar: h("div", { class: "bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-label": "Overall progress" }),
      fill: h("i"),
      log: h("p", { class: "caption", style: "margin:8px 0 0" }),
      photos: h("b"), needPhoto: h("b"), needPrice: h("b"),
    };
    tr.bar.append(tr.fill);
    append(clear(tracker), [h("section", { class: "card", "aria-label": "Progress" },
      h("ol", { class: "stages" }, items.map((it) => it.li)),
      h("div", { class: "stage-label" }, tr.label, tr.pct),
      tr.bar, tr.log,
      h("div", { class: "counters" },
        h("div", { class: "counter" }, tr.photos, h("span", { class: "caption" }, "Photos found")),
        h("div", { class: "counter" }, tr.needPhoto, h("span", { class: "caption" }, "Need owner photo")),
        h("div", { class: "counter" }, tr.needPrice, h("span", { class: "caption" }, "Need price"))))]);
  }

  function renderTracker() {
    if (!isRunning()) {
      clear(tracker);
      tr = null;
      return;
    }
    if (!tr) buildTracker();
    const idx = STAGES.findIndex(([sid]) => sid === stage);
    const overall = idx < 0 ? 0 : (idx + Math.min(1, stageProgress)) / STAGES.length;
    tr.items.forEach((it, i) => {
      const state = i < idx ? "done" : i === idx ? "current" : "pending";
      if (state === it.state) return;
      it.state = state;
      it.li.className = `stage ${state}`;
      it.li.setAttribute("aria-label", `${it.short}: ${state === "current" ? "in progress" : state}`);
      clear(it.dot).append(state === "done" ? icon("check") : h("b", { class: "num" }, i + 1));
    });
    const current = idx < 0 ? null : STAGES[idx];
    tr.label.textContent = status() === "queued" && idx < 0 ? "Waiting to start…" : stageLabel || (current ? current[2] : "Starting…");
    const pct = Math.round(overall * 100);
    tr.pct.textContent = `${pct}%`;
    tr.bar.setAttribute("aria-valuenow", String(pct));
    tr.fill.style.width = `${(overall * 100).toFixed(1)}%`;
    tr.log.textContent = lastLog;
    tr.log.hidden = !lastLog;
    const c = counts();
    tr.photos.textContent = c.photos;
    tr.needPhoto.textContent = c.needs_photo;
    tr.needPrice.textContent = c.needs_price;
  }

  function renderHero() {
    clear(hero);
    if (isRunning() || !job || !job.summary) return;
    const c = counts();
    const pct = c.total ? Math.round((c.photos / c.total) * 100) : 0;
    const ring = fromStatic('<svg viewBox="0 0 120 120" aria-hidden="true"><circle class="track" cx="60" cy="60" r="52"/><circle class="val" cx="60" cy="60" r="52"/></svg>');
    const circ = 2 * Math.PI * 52;
    const val = ring.querySelector(".val");
    val.style.strokeDasharray = String(circ);
    val.style.strokeDashoffset = String(circ * (1 - pct / 100));
    const files = job.summary.files || {};
    const dl = [];
    if (files.ready) dl.push(h("a", { class: "btn primary", href: `${base}/files/ready`, download: "", onclick: download }, icon("download"), "Upload-ready sheet"));
    if (files.pending) dl.push(h("a", { class: "btn", href: `${base}/files/pending`, download: "", onclick: download }, "Pending sheet"));
    if (files.report) dl.push(h("a", { class: "btn", href: `${base}/files/report`, download: "", onclick: download }, "Report"));
    if (dl.length) dl.push(h("a", { class: "btn", href: `${base}/zip`, download: "", onclick: download }, "Everything (.zip)"));
    hero.append(h("section", { class: "card", "aria-label": "Summary" },
      h("div", { class: "hero" },
        h("div", { class: "ring", role: "img", "aria-label": `${pct}% of dishes have a photo` }, ring, h("span", null, `${pct}%`)),
        h("div", { style: "flex:1;min-width:240px" },
          h("h2", { class: "title2 num", style: "margin-bottom:16px" }, `${c.ready} of ${c.total} ready`),
          h("div", { class: "stats" },
            stat(c.photos, "Photos found"), stat(c.needs_photo, "Need owner photo"),
            stat(c.needs_price, "Need price"), stat(c.error, "Errors")))),
      dl.length ? h("div", { class: "downloads" }, dl) : null,
      job.error ? h("p", { class: "caption", style: "margin:16px 0 0" }, job.error) : null,
    ));
  }

  function stat(n, label) {
    return h("div", null, h("b", null, n), h("span", { class: "caption" }, label));
  }

  function scheduleList() {
    if (frame) return;
    frame = requestAnimationFrame(() => { frame = 0; if (alive) renderList(); });
  }

  function renderList() {
    clear(list);
    const all = [...results.values()].sort((a, b) => a.row - b.row);
    toolbar.hidden = all.length === 0;
    const counts = { all: all.length };
    for (const r of all) counts[r.status] = (counts[r.status] || 0) + 1;
    clear(seg).append(...FILTERS.map(([key, label]) => h("button", {
      type: "button", "aria-pressed": filter === key ? "true" : "false",
      onclick: () => { filter = key; renderList(); },
    }, label, h("span", { class: "num" }, counts[key] || 0))));

    if (!all.length) {
      if (!isRunning()) list.append(h("div", { class: "empty" }, icon("tray"), h("p", null, "No dishes yet.")));
      else list.append(h("div", { class: "empty" }, h("p", null, "Dishes appear here as photos are found.")));
      return;
    }
    const shown = all.filter((r) => (filter === "all" || r.status === filter)
      && (!query || r.name.toLowerCase().includes(query) || r.sku.toLowerCase().includes(query)));
    if (!shown.length) {
      list.append(h("div", { class: "empty" }, h("p", null, "No dishes match.")));
      return;
    }
    const byCat = new Map();
    for (const r of shown) {
      const cat = r.category || "Menu";
      if (!byCat.has(cat)) byCat.set(cat, []);
      byCat.get(cat).push(r);
    }
    for (const [cat, rows] of byCat) {
      list.append(
        h("h2", { class: "cat-head" }, h("span", { class: "headline" }, cat), h("span", { class: "caption num" }, rows.length)),
        h("div", { class: "grid" }, rows.map(tileFor)));
    }
  }

  function imageUrl(r) {
    const v = imgVersion.get(r.sku);
    return `${base}/images/${encodeURIComponent(r.sku)}.jpg${v ? `?v=${v}` : ""}`;
  }

  function tileFor(r) {
    const cached = tiles.get(r.sku);
    if (cached && cached.r === r) return cached.el;
    const [statusText, , statusIcon] = DISH_STATUS[r.status] || [r.status, "", "alert"];
    const photo = r.local_image
      ? h("span", { class: "ph" }, h("img", { src: imageUrl(r), alt: r.name, loading: "lazy", decoding: "async" }))
      : h("span", { class: "ph ph-empty" }, icon(statusIcon), h("span", null, r.reason || statusText));
    const el = h("button", { type: "button", class: "tile", "aria-label": `${r.name}, ${statusText}`, onclick: () => openDetail(r.sku) },
      photo,
      h("span", { class: "tile-body" },
        h("span", { class: "tile-name" }, r.name),
        h("span", { class: "tile-meta num" }, formatPrice(r.price), " · ", statusText),
        h("span", { class: "tile-meta" }, confidenceDot(r), h("span", { class: "src" }, sourceCaption(r) || "No photo"))));
    tiles.set(r.sku, { r, el });
    return el;
  }

  function openDetail(sku) {
    const r = results.get(sku);
    if (!r) return;
    const [statusText, colour, statusIcon] = DISH_STATUS[r.status] || [r.status, "", "alert"];
    const canEdit = !isRunning();
    const matched = r.item_name
      ? [r.item_name, r.restaurant ? " @ " : "",
        r.restaurant_url ? h("a", { href: r.restaurant_url, target: "_blank", rel: "noopener noreferrer" }, r.restaurant || "Zomato") : r.restaurant]
      : "—";
    const body = h("div", { class: "sheet-body" },
      h("h2", { class: "title2", id: "sheet-title" }, r.name),
      h("div", { class: "caption" }, `${r.category || "Menu"} · ${r.sku}`),
      h("div", null, pill(statusText, colour, statusIcon)),
      r.reason ? h("p", { style: "margin:0" }, r.reason) : null,
      h("dl", { class: "kv" },
        h("dt", null, "Price"), h("dd", { class: "num" }, formatPrice(r.price)),
        h("dt", null, "Matched"), h("dd", null, matched),
        h("dt", null, "Confidence"), h("dd", { class: "num" }, r.zomato_img ? [confidenceDot(r), " ", `${Math.round(r.confidence * 100)}%`] : "—"),
        h("dt", null, "Tier"), h("dd", null, r.tier || "—"),
        h("dt", null, "Source"), h("dd", null, sourceCaption(r) || "—")),
    );
    if (r.alternates && r.alternates.length) {
      body.append(h("h3", { class: "headline", style: "margin:8px 0 0" }, "Other photos"),
        h("div", { class: "alts" }, r.alternates.map((alt, i) => h("div", { class: "alt" },
          alt.zomato_img ? h("img", { src: alt.zomato_img + THUMB_SUFFIX, alt: alt.item_name || r.name, loading: "lazy" }) : null,
          h("span", null, alt.item_name || "", alt.restaurant ? h("span", { class: "muted" }, ` @ ${alt.restaurant}`) : null),
          h("button", { class: "btn", type: "button", disabled: !canEdit || !alt.zomato_img, onclick: (e) => choose(sku, i, e.currentTarget) }, "Use this photo")))));
    }
    if (r.local_image) {
      body.append(h("div", { class: "actions", style: "justify-content:flex-start" },
        h("button", { class: "btn danger", type: "button", disabled: !canEdit, onclick: (e) => choose(sku, null, e.currentTarget) }, icon("photo"), "Needs owner photo")));
    }
    if (!canEdit) body.append(h("p", { class: "caption", style: "margin:0" }, "You can swap photos when the job finishes."));
    const photo = r.local_image
      ? h("div", { class: "sheet-photo" }, h("img", { src: imageUrl(r), alt: r.name }))
      : h("div", { class: "sheet-photo ph-empty" }, icon("photo"), h("span", null, r.reason || "No photo yet"));
    openSheet(h("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "sheet-title" },
      h("button", { class: "icon-btn close", type: "button", "aria-label": "Close", onclick: closeSheet }, icon("x")),
      photo, body));
  }

  async function choose(sku, altIndex, button) {
    button.disabled = true;
    button.prepend(icon("spin"));
    try {
      const updated = await api("POST", `${base}/dishes/${encodeURIComponent(sku)}/choose`, { alt_index: altIndex });
      if (!alive) return;
      results.set(sku, updated);
      imgVersion.set(sku, Date.now());
      closeSheet();
      renderList();
      renderHero();
      toast(altIndex == null ? "Marked as needing an owner photo" : "Photo updated");
    } catch (err) {
      toastError(err);
      button.disabled = false;
      button.querySelector(".spinner")?.remove();
    }
  }

  async function cancel() {
    try {
      await api("POST", `${base}/cancel`);
      toast("Cancelling…");
    } catch (err) {
      toastError(err);
    }
  }

  async function resume() {
    try {
      await api("POST", `${base}/resume`);
      if (!alive) return;
      job.status = "queued";
      job.error = null;
      active = true;
      stage = "";
      stageProgress = 0;
      stageLabel = "";
      lastLog = "";
      renderAll();
      if (!es) connect();
      refreshSystem();
    } catch (err) {
      toastError(err);
    }
  }

  return () => {
    alive = false;
    if (es) es.close();
    clearTimeout(retryTimer);
    if (frame) cancelAnimationFrame(frame);
  };
}

// ---------- sheet (modal) ----------

let sheetState = null;

function openSheet(sheet) {
  closeSheet();
  const overlay = h("div", { class: "overlay", onclick: (e) => { if (e.target === overlay) closeSheet(); } }, sheet);
  const onKey = (e) => {
    if (e.key === "Escape") closeSheet();
    else if (e.key === "Tab") trapFocus(e, sheet);
  };
  sheetState = { overlay, onKey, returnTo: document.activeElement };
  document.addEventListener("keydown", onKey);
  document.getElementById("sheet-root").append(overlay);
  sheet.querySelector(".close").focus();
}

function trapFocus(e, root) {
  const items = [...root.querySelectorAll("a[href], button:not([disabled]), input, select")];
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

function closeSheet() {
  if (!sheetState) return;
  const { overlay, onKey, returnTo } = sheetState;
  sheetState = null;
  document.removeEventListener("keydown", onKey);
  overlay.remove();
  if (returnTo && returnTo.isConnected) returnTo.focus();
}

// ---------- History ----------

async function historyView(view) {
  view.append(h("h1", { class: "large-title" }, "History"));
  const box = h("div", { class: "rows" }, h("p", { class: "muted" }, "Loading…"));
  view.append(box);
  let jobs;
  try {
    jobs = await api("GET", "/api/jobs");
  } catch (err) {
    clear(box);
    toastError(err);
    return;
  }
  clear(box);
  if (!jobs.length) {
    box.append(h("div", { class: "empty card" }, icon("fork"),
      h("h2", { class: "title2" }, "No jobs yet"),
      h("p", null, "Drop in a menu and Menu Studio finds a photo for every dish."),
      h("a", { class: "btn primary", href: "#/new" }, "Start your first job")));
    return;
  }
  for (const j of jobs) {
    const s = j.summary;
    box.append(h("a", { class: "row-card", href: `#/job/${encodeURIComponent(j.id)}` },
      h("div", { class: "main" },
        h("div", { class: "headline" }, j.vendor || j.id),
        h("div", { class: "caption num" }, formatDate(j.created), s ? ` · ${s.ready} of ${s.total} ready` : "")),
      statusPill(j.status),
      h("span", { class: "chev" }, icon("chevron"))));
  }
}

// ---------- Settings ----------

function settingsView(view) {
  let s = null;
  let saving = Promise.resolve();
  const testMsgs = new Map(); // key id -> { ok, message } | "busy"
  let adding = false;

  view.append(h("h1", { class: "large-title" }, "Settings"));
  const body = h("div", null, h("p", { class: "muted" }, "Loading…"));
  view.append(body);

  api("GET", "/api/settings").then((data) => { s = data; render(); }).catch(toastError);

  function payload(keys) {
    return {
      imgbb_keys: keys,
      strictness: s.strictness,
      live_search: s.live_search,
      live_budget_menus: s.live_budget_menus,
      default_city: s.default_city,
    };
  }

  function existingKeys() {
    return s.imgbb_keys.map((k) => ({ id: k.id, label: k.label, enabled: k.enabled }));
  }

  function save(keys, message = "Saved") {
    const run = () => api("PUT", "/api/settings", payload(keys || existingKeys())).then((data) => {
      s = data;
      testMsgs.clear();
      render();
      toast(message);
      refreshSystem();
      return true;
    }).catch((err) => { toastError(err); return false; });
    saving = saving.then(run);
    return saving;
  }

  // Re-rendering replaces every control; keep keyboard focus on the control the user was using.
  function render() {
    const focused = body.contains(document.activeElement) ? document.activeElement.getAttribute("aria-label") : null;
    clear(body);
    body.append(keysGroup(), matchingGroup());
    if (focused) {
      const again = [...body.querySelectorAll("[aria-label]")].find((el) => el.getAttribute("aria-label") === focused);
      if (again) again.focus();
    }
  }

  function keysGroup() {
    const rows = s.imgbb_keys.map((k) => {
      const msg = testMsgs.get(k.id);
      const toggle = h("label", { class: "switch" },
        h("input", { type: "checkbox", role: "switch", checked: k.enabled, "aria-label": `Use ${k.label}`, onchange: (e) => {
          k.enabled = e.target.checked;
          save();
        } }), h("i"));
      return h("div", { class: "li" },
        icon("key"),
        h("div", { class: "grow" }, h("div", { class: "headline" }, k.label), h("div", { class: "caption num" }, `•••• ${k.tail}`)),
        msg === "busy" ? h("span", { class: "msg" }, icon("spin"), "Testing…")
          : msg ? h("span", { class: `msg ${msg.ok ? "ok" : "bad"}` }, msg.ok ? "✓ " : "✕ ", msg.message) : null,
        h("button", { class: "btn", type: "button", "aria-label": `Test ${k.label}`, disabled: msg === "busy", onclick: () => testKey(k.id) }, "Test"),
        toggle,
        h("button", { class: "icon-btn", type: "button", "aria-label": `Delete ${k.label}`, onclick: () => {
          if (!confirm(`Delete the key "${k.label}"?`)) return;
          save(existingKeys().filter((e) => e.id !== k.id), "Key deleted");
        } }, icon("trash")));
    });

    let addRow;
    if (adding) {
      const label = h("input", { class: "input", placeholder: "Label", "aria-label": "Key label", value: `Key ${s.imgbb_keys.length + 1}` });
      const key = h("input", { class: "input", placeholder: "Paste your ImgBB API key", "aria-label": "ImgBB API key", autocomplete: "off", spellcheck: "false" });
      const paste = h("button", { class: "btn", type: "button", onclick: async () => {
        try { key.value = (await navigator.clipboard.readText()).trim(); key.focus(); }
        catch { toast("Paste with Ctrl+V instead", "error"); }
      } }, icon("paste"), "Paste");
      const submit = async (e) => {
        e.preventDefault();
        const value = key.value.trim();
        if (!value) { key.focus(); return; }
        const ok = await save([...existingKeys(), { label: label.value.trim(), key: value, enabled: true }], "Key added");
        if (ok) { adding = false; render(); }
      };
      addRow = h("form", { class: "li", onsubmit: submit },
        h("div", { class: "add-form" }, label, h("div", { style: "display:flex;gap:8px" }, key, paste),
          h("div", { style: "display:flex;gap:8px" },
            h("button", { class: "btn primary", type: "submit" }, "Add"),
            h("button", { class: "btn plain", type: "button", onclick: () => { adding = false; render(); } }, "Cancel"))));
      setTimeout(() => key.focus(), 0);
    } else {
      addRow = h("div", { class: "li" }, h("button", { class: "btn add-row", type: "button", onclick: () => { adding = true; render(); } }, icon("new"), "Add key"));
    }

    return h("section", { class: "group", "aria-labelledby": "g-keys" },
      h("h2", { class: "group-title", id: "g-keys" }, "ImgBB keys"),
      h("div", { class: "list" }, rows, addRow),
      h("p", { class: "caption group-foot" }, "Add 2–4 free keys from ",
        h("a", { href: IMGBB_URL, target: "_blank", rel: "noopener noreferrer" }, "api.imgbb.com"),
        ". Menu Studio rotates between them and skips a key that hits its limit."));
  }

  async function testKey(keyId) {
    testMsgs.set(keyId, "busy");
    render();
    try {
      const res = await api("POST", "/api/settings/test-key", { id: keyId });
      testMsgs.set(keyId, res);
    } catch (err) {
      testMsgs.set(keyId, { ok: false, message: err.message });
    }
    render();
  }

  function matchingGroup() {
    const strict = h("div", { class: "seg", role: "group", "aria-label": "Strictness" },
      [["balanced", "Balanced (recommended)"], ["strict", "Strict"]].map(([val, label]) =>
        h("button", { type: "button", "aria-label": label, "aria-pressed": s.strictness === val ? "true" : "false", onclick: () => {
          if (s.strictness === val) return;
          s.strictness = val;
          save();
        } }, label)));
    const live = h("label", { class: "switch" },
      h("input", { type: "checkbox", role: "switch", checked: s.live_search, "aria-label": "Search all of Zomato live", onchange: (e) => {
        s.live_search = e.target.checked;
        save();
      } }), h("i"));
    const depthOpts = DEPTHS.some(([n]) => n === s.live_budget_menus) ? DEPTHS : [...DEPTHS, [s.live_budget_menus, `Custom (${s.live_budget_menus} menus)`]];
    const depth = h("select", { class: "input", style: "width:auto", "aria-label": "Search depth", onchange: (e) => {
      s.live_budget_menus = Number(e.target.value);
      save();
    } }, depthOpts.map(([n, label]) => h("option", { value: n }, label)));
    depth.value = String(s.live_budget_menus);
    const city = h("select", { class: "input", style: "width:auto", "aria-label": "Home city", onchange: (e) => {
      s.default_city = e.target.value;
      save();
    } }, h("option", { value: "" }, "Any city"), s.cities.map((c) => h("option", { value: c }, cityLabel(c))));
    city.value = s.default_city || "";

    return h("section", { class: "group", "aria-labelledby": "g-match" },
      h("h2", { class: "group-title", id: "g-match" }, "Matching"),
      h("div", { class: "list" },
        h("div", { class: "li" }, h("div", { class: "grow" }, h("div", null, "Strictness"),
          h("div", { class: "caption" }, "Strict only accepts near-certain matches.")), strict),
        h("div", { class: "li" }, h("div", { class: "grow" }, h("div", null, "Search all of Zomato live"),
          h("div", { class: "caption" }, "Looks beyond the built-in photo library.")), live),
        h("div", { class: "li" }, h("div", { class: "grow" }, "Search depth"), depth),
        h("div", { class: "li" }, h("div", { class: "grow" }, "Home city"), city)));
  }
}

// ---------- boot ----------

window.addEventListener("hashchange", route);
if (!location.hash) history.replaceState(null, "", "#/new");
route();
refreshSystem();
