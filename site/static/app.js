// The changes between two versions of the Bluetooth Core Specification: a ranked list, a
// map of every section across every version, the sweeping edits, and a panel with the diff
// and the blame of one section. The data is in data/, written by `specdiff diff`: index.json
// at once, a step's changes when a range needs it, a Part's text when a section is opened.
"use strict";

(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en")} ${n === 1 ? one : many}`;
  // Words as the search splits them: letters and digits. Must match search_words in history.py.
  const words = (text) => text.toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  const smooth = () => (matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth");
  const SVG = "http://www.w3.org/2000/svg";

  // Build elements without innerHTML: all text from the spec goes in as text.
  function el(tag, attrs = {}, ...children) {
    const node = tag.startsWith("svg:") ? document.createElementNS(SVG, tag.slice(4)) : document.createElement(tag);
    for (const [name, value] of Object.entries(attrs)) {
      if (value === false || value === null || value === undefined) continue;
      if (name === "class") node.setAttribute("class", value);
      else if (name === "text") node.textContent = value;
      else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
      else node.setAttribute(name, value === true ? "" : value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  // Must match specdiff/history.py
  const STATUS = { ABSENT: 0, SAME: 1, EDITORIAL: 2, CHANGED: 3, ADDED: 4, REMOVED: 5 };
  const ENTRY = { EQUAL: 0, DELETE: 1, INSERT: 2, CHANGE: 3 };
  const SEG = { KEEP: 0, OUT: 1, IN: 2, OUT_EDITORIAL: 3, IN_EDITORIAL: 4 };
  const REWORDED = 3;
  const QUIET = { 1: "moved", 2: "extraction", 3: "reworded" };
  const SIGNAL_BITS = { n: 1, x: 2, v: 4 };
  const SMALL = 3; // a small edit changes at most this many sentences
  const LIMIT = 150;
  const NAME = "<name>"; // a sweeping pattern's identifier

  const root = document.documentElement;
  root.classList.add("js");
  const dataVersion = document.currentScript?.dataset.version ?? "";
  const page = $(".page");
  const main = $("main");
  const form = $("[data-controls]");
  const input = $("#q");
  const fromSelect = $('select[name="from"]');
  const toSelect = $('select[name="to"]');
  const partSelect = $('select[name="part"]');
  const editorialBox = $('input[name="editorial"]');
  const onlyBox = $('input[name="only"]');
  const rail = $("[data-rail]");
  const filters = $("[data-filters]");
  const filtersToggle = $("[data-filters-toggle]");
  const kindsBox = $("[data-kinds]");
  const count = $("[data-count]");
  const changesTable = $(".listing.changes");
  const rowsBody = $("[data-rows]");
  const more = $("[data-more]");
  const mapBox = $("[data-map]");
  const rulesBody = $("[data-rules]");
  const empty = $("[data-empty]");
  const panel = $("[data-panel]");
  const panelBody = $("[data-panel-body]");
  const tooltip = $("[data-tooltip]");
  const status = $("[data-status]");
  const wide = matchMedia("(min-width: 80rem)");
  const tableLayout = matchMedia("(min-width: 48rem)");

  let index;
  let versions;
  let sections;
  const byId = new Map();
  const partsByKey = new Map();
  const stepCache = new Map();
  const partCache = new Map();
  let rangeCache = { key: "", items: null };

  const state = {
    view: "changes",
    from: 0,
    to: 1,
    kind: "all",
    signals: new Set(),
    part: "",
    q: "",
    sort: "score",
    reverse: false,
    editorial: false,
    selected: null,
    mode: "diff",
    step: null, // a single step chosen in the panel, or null for the whole range
    bySteps: false, // the panel shows a range step by step rather than all at once
    only: false, // the map shows only the sections changed in the range
    off: new Set(), // sweeping rules counted as changes: "step:rule"
    limit: LIMIT,
    open: new Set(), // Parts opened on the map
    expanded: new Set(), // sweeping rules whose sections are listed
  };

  const fetchJson = (path) =>
    fetch(`data/${path}?v=${dataVersion}`).then((response) => {
      if (!response.ok) throw new Error(`${path}: ${response.status}`);
      return response.json();
    });
  // A failed load is forgotten, so the next try loads again
  const cached = (cache, key, load) => {
    if (!cache.has(key)) cache.set(key, load().catch((error) => (cache.delete(key), Promise.reject(error))));
    return cache.get(key);
  };
  const loadStep = (n) => cached(stepCache, n, () => fetchJson(`steps/${n}.json`));
  // A big Part is split into files; the index says which one holds a section
  const fileOf = (section) => (section.f === undefined ? section.p : `${section.p}-${section.f}`);
  const loadPart = (section) => cached(partCache, fileOf(section), () => fetchJson(`parts/${fileOf(section)}.json`));

  // Names

  const label = (n) => versions[n].label;
  const originLabel = (n) => (n === 0 ? `${label(0)} or earlier` : label(n));
  const stepLabel = (n) => `${label(n)} → ${label(n + 1)}`;
  const rangeLabel = () => (state.to - state.from === 1 ? `in ${label(state.to)}` : `from ${label(state.from)} to ${label(state.to)}`);
  const formatChange = (n) => versions[n].format !== versions[n + 1].format;
  const partOf = (section) => partsByKey.get(section.p);
  const partAt = (section, n) => section.pp?.[n] ?? section.p; // the Part it was in, in version n
  const partName = (part) => `Vol ${part.vol}, Part ${part.letter}`;
  const partTitle = (part, n = versions.length - 1) => {
    for (let k = n; k >= 0; k--) if (part.titles[k]) return part.titles[k];
    return part.titles.find(Boolean) ?? "";
  };
  const present = (section, n) => n >= section.v[0] && n <= section.v[1];
  const numberAt = (section, n) => section.no?.[n] ?? section.n;
  const titleAt = (section, n) => section.to?.[n] ?? section.t;
  // the version a section is shown as: the range's end, or its last version before that
  const shownVersion = (section) => Math.max(section.v[0], Math.min(state.to, section.v[1]));
  const heading = (section, n = shownVersion(section)) => {
    const number = numberAt(section, n);
    const title = titleAt(section, n);
    return number ? `${number} ${title}` : title;
  };
  // a heading with its Part, where that isn't the Part it is in now
  const placedHeading = (section, n) => {
    const key = partAt(section, n);
    return key === section.p ? heading(section, n) : `${partName(partsByKey.get(key))} · ${heading(section, n)}`;
  };

  function specLink(section, n) {
    const part = partsByKey.get(partAt(section, n));
    const url = part?.urls[n];
    if (!url) return null;
    if (versions[n].format === "pdf") {
      const pageNumber = section.pg?.[n];
      return { href: pageNumber ? `${url}#page=${pageNumber}` : url, text: `Core ${label(n)} PDF${pageNumber ? `, page ${pageNumber}` : ""}` };
    }
    const anchor = section.ao?.[n] ?? section.a;
    return { href: anchor ? `${url}#${anchor}` : url, text: `Core ${label(n)}` };
  }

  // Sweeping rules switched off: their edits count as changes
  const ruleKey = (n, k) => `${n}:${k}`;
  const isOff = (n, k) => n !== null && k !== undefined && k !== null && state.off.has(ruleKey(n, k));
  const ruleName = (n, k) => {
    const rule = index.steps[n]?.rules[k];
    return rule ? `${rule[0] || "(nothing)"} → ${rule[1] || "(nothing)"}`.replaceAll(NAME, "‹name›") : "";
  };
  const hasOff = (segments, n) => n !== null && segments.some((segment) => isOff(n, segment[2]));
  // A changed sentence is editorial if all its edits are and none follows a rule switched off
  const isEditorialEntry = (entry, n) => {
    if (entry[0] === ENTRY.CHANGE) return Boolean(entry[1]) && !hasOff(entry[3], n);
    if (entry[0] === ENTRY.INSERT && entry[1] === REWORDED) return Boolean(entry[4]) && !hasOff(entry[3], n);
    return false;
  };

  // URL: #from=5.2&to=5.3&view=map&kind=small&sig=n,x&part=3H&q=passkey&s=3H.27&mode=blame&ed=1
  //      &sort=order&rev=1&only=1&off=5.3-0,6.1-2&steps=1

  // Everything the URL doesn't name goes back to its default: the latest step, all changes
  function readUrl() {
    const params = new URLSearchParams(location.hash.slice(1));
    const at = (name) => versions.findIndex((v) => v.label === params.get(name));
    const from = at("from");
    const to = at("to");
    const valid = from >= 0 && to > from;
    state.from = valid ? from : versions.length - 2;
    state.to = valid ? to : versions.length - 1;
    state.view = ["changes", "map", "sweeping"].includes(params.get("view")) ? params.get("view") : "changes";
    state.kind = KINDS.some((kind) => kind.key === params.get("kind")) ? params.get("kind") : "all";
    state.signals = new Set((params.get("sig") ?? "").split(",").filter((s) => Object.hasOwn(SIGNAL_BITS, s)));
    state.part = partsByKey.has(params.get("part")) ? params.get("part") : "";
    state.q = params.get("q") ?? "";
    state.editorial = params.get("ed") === "1";
    state.mode = params.get("mode") === "blame" ? "blame" : "diff";
    state.sort = Object.hasOwn(NATURAL, params.get("sort") ?? "") ? params.get("sort") : "score";
    state.reverse = params.get("rev") === "1";
    state.only = params.get("only") === "1";
    state.bySteps = params.get("steps") === "1";
    state.off = new Set();
    for (const code of (params.get("off") ?? "").split(",").filter(Boolean)) {
      const dash = code.lastIndexOf("-");
      const n = versions.findIndex((v) => v.label === code.slice(0, dash)) - 1;
      const k = Number(code.slice(dash + 1));
      if (n >= 0 && index.steps[n]?.rules[k]) state.off.add(ruleKey(n, k));
    }
    const selected = params.get("s");
    state.selected = byId.has(selected) ? selected : null;
    const step = Number(params.get("step"));
    state.step = params.has("step") && step >= 0 && step < index.steps.length ? step : null;
  }

  function params() {
    const found = new URLSearchParams();
    found.set("from", label(state.from));
    found.set("to", label(state.to));
    if (state.view !== "changes") found.set("view", state.view);
    if (state.kind !== "all") found.set("kind", state.kind);
    if (state.signals.size) found.set("sig", [...state.signals].join(","));
    if (state.part) found.set("part", state.part);
    if (state.q) found.set("q", state.q);
    if (state.editorial) found.set("ed", "1");
    if (state.sort !== "score") found.set("sort", state.sort);
    if (state.reverse) found.set("rev", "1");
    if (state.only) found.set("only", "1");
    if (state.off.size) {
      const codes = [...state.off].map((key) => {
        const [n, k] = key.split(":").map(Number);
        return `${label(n + 1)}-${k}`;
      });
      found.set("off", codes.join(","));
    }
    if (state.selected) found.set("s", state.selected);
    if (state.selected && state.mode === "blame") found.set("mode", "blame");
    if (state.selected && state.step !== null) found.set("step", String(state.step));
    if (state.selected && state.bySteps) found.set("steps", "1");
    return found;
  }

  const toHash = (found) => `#${found.toString().replaceAll("%2C", ",")}`;

  function hrefFor(id, step = null) {
    const found = params();
    found.set("s", id);
    found.delete("step");
    if (step !== null) found.set("step", String(step));
    return toHash(found);
  }

  // A choice adds to the browser's history (Back undoes it); typing replaces the entry
  let lastHash = "";
  function writeUrl({ push = false } = {}) {
    const hash = toHash(params());
    if (hash === location.hash) return;
    if (push) history.pushState(null, "", hash);
    else history.replaceState(null, "", hash);
    lastHash = hash;
  }

  // Controls

  const PLACEHOLDERS = {
    changes: "Search sections, changed text, numbers",
    map: "Search sections, changed text, numbers",
    sweeping: "Search the sweeping edits",
  };

  function syncControls() {
    fromSelect.value = String(state.from);
    toSelect.value = String(state.to);
    for (const option of fromSelect.options) option.disabled = Number(option.value) >= state.to;
    for (const option of toSelect.options) option.disabled = Number(option.value) <= state.from;
    $$("[data-shift]").forEach((button) => {
      const shift = Number(button.dataset.shift);
      button.disabled = state.from + shift < 0 || state.to + shift >= versions.length;
    });
    for (const radio of $$('input[name="view"]', form)) radio.checked = radio.value === state.view;
    for (const box of $$('input[name="signal"]')) box.checked = state.signals.has(box.value);
    partSelect.value = state.part;
    editorialBox.checked = state.editorial;
    onlyBox.checked = state.only;
    if (input.value !== state.q) input.value = state.q;
    input.placeholder = PLACEHOLDERS[state.view];
    for (const view of $$("[data-view]", main)) view.hidden = view.dataset.view !== state.view;
    for (const filter of $$("[data-only]")) filter.hidden = !filter.dataset.only.split(" ").includes(state.view);
    root.classList.toggle("show-editorial", state.editorial);
    changesTable.classList.toggle("single-step", state.to - state.from === 1);
    const active = (state.kind !== "all") + state.signals.size + Boolean(state.part) + state.editorial + state.only;
    $("[data-filters-active]").textContent = active ? String(active) : "";
    syncSort();
    renderRail();
  }

  function syncSort() {
    for (const th of $$("th[data-sort]")) {
      if (th.dataset.sort !== state.sort) {
        th.removeAttribute("aria-sort");
        continue;
      }
      const natural = NATURAL[state.sort];
      th.setAttribute("aria-sort", state.reverse ? (natural === "ascending" ? "descending" : "ascending") : natural);
    }
  }

  // The rail: a step is a button that chooses it alone; shift-click extends the range
  function renderRail() {
    const max = Math.max(...index.steps.map((s) => s.sections.changed + s.sections.added));
    rail.style.setProperty("--steps", String(index.steps.length));
    const boundary = index.steps.findIndex((_, n) => formatChange(n));
    rail.replaceChildren(
      ...index.steps.map((step, n) => {
        const height = (value) => `${Math.max(value ? 3 : 0, Math.sqrt(value / max) * 100)}%`;
        const note = formatChange(n) ? ` (${versions[n].format.toUpperCase()} to ${versions[n + 1].format.toUpperCase()}: expect more noise)` : "";
        return el(
          "button",
          {
            type: "button",
            class: `rail-step${n >= state.from && n < state.to ? " in-range" : ""}${formatChange(n) ? " format-change" : ""}`,
            title: `${stepLabel(n)}: ${plural(step.sections.changed, "section")} changed, ${step.sections.added} added, ${step.sections.removed} removed${note}. Shift-click to extend the range.`,
            tabindex: "-1",
            onclick: (event) => {
              if (event.shiftKey) setRange(Math.min(state.from, n), Math.max(state.to, n + 1));
              else setRange(n, n + 1);
            },
          },
          el(
            "span",
            { class: "rail-bars" },
            el("span", { class: "b-changed", style: `height:${height(step.sections.changed)}` }),
            el("span", { class: "b-new", style: `height:${height(step.sections.added)}` }),
          ),
          // narrow screens show only the version a step leads to
          el("span", { class: "rail-label" }, el("span", { class: "rail-from", text: `${label(n)} → ` }), label(n + 1)),
        );
      }),
      el(
        "p",
        { class: "rail-note" },
        boundary >= 0 ? `* ${label(boundary)} and earlier are read from the PDF, ${label(boundary + 1)} and later from the HTML: expect more noise in ${stepLabel(boundary)}. ` : "",
        "Click a step to see it alone, ",
        el("kbd", { text: "Shift" }),
        "-click to extend the range.",
      ),
    );
  }

  function setRange(from, to) {
    state.from = Math.max(0, Math.min(from, versions.length - 2));
    state.to = Math.max(state.from + 1, Math.min(to, versions.length - 1));
    state.step = null;
    state.limit = LIMIT;
    update({ push: true });
  }

  // Search: words of the headings and the changed text, and section numbers by prefix
  // ("7.8.13" finds 7.8.13 and 7.8.13.1, not 7.8.130)

  const NUMBER = /^(?:[A-Z]|\d+)(?:\.\d+)+\.?$/i;
  let parsedQuery = { q: null };
  function query() {
    if (parsedQuery.q === state.q) return parsedQuery;
    const numbers = [];
    const terms = [];
    for (const raw of state.q.split(/\s+/).filter(Boolean)) {
      if (NUMBER.test(raw)) numbers.push(raw.replace(/\.$/, "").toUpperCase());
      else terms.push(...words(raw));
    }
    parsedQuery = { q: state.q, numbers, terms };
    return parsedQuery;
  }

  function matchesQuery(target) {
    const { numbers, terms } = query();
    return (
      numbers.every((n) => target.numbers.some((number) => number === n || number.startsWith(`${n}.`))) &&
      terms.every((term) => target.haystack.includes(` ${term}`))
    );
  }

  const numbersOf = (section) => [...new Set([section.n, ...Object.values(section.no ?? {})])].map((n) => n.toUpperCase());
  const haystackOf = (section, extra = "") => {
    const part = partOf(section);
    return ` ${words(`${heading(section)} ${partName(part)} ${partTitle(part)} ${extra}`).join(" ")}`;
  };

  // Changes: the steps of the range, merged per section

  const KINDS = [
    { key: "all", label: "All changes", test: (entry) => entry.kind !== "edit" },
    { key: "small", label: "Small edits", test: (entry) => entry.kind === "mod" && entry.size <= SMALL },
    { key: "large", label: "Larger edits", test: (entry) => entry.kind === "mod" && entry.size > SMALL },
    { key: "new", label: "New sections", test: (entry) => entry.kind === "add" },
    { key: "removed", label: "Removed", test: (entry) => entry.kind === "del" || entry.kind === "temp" },
    { key: "edit", label: "Editorial only", test: (entry) => entry.kind === "edit" },
  ];
  const KIND_NAMES = { add: "New section", del: "Removed", edit: "Editorial", temp: "Added and removed" };
  const kindName = (entry) => (entry.kind === "mod" ? (entry.size <= SMALL ? "Small edit" : "Larger edit") : KIND_NAMES[entry.kind]);

  // Each step's change of a section, with the sweeping rules switched off applied: an
  // editorial sentence that follows one becomes a changed sentence
  function stepChange(n, item) {
    const flipped = (item.rs ?? []).filter(([, rules]) => rules.some((k) => isOff(n, k))).map(([sid]) => sid);
    if (!flipped.length) return { n, item, k: item.k, sc: item.sc, flipped };
    return { n, item, k: item.k === "edit" ? "mod" : item.k, sc: Math.max(item.sc, 2), flipped };
  }

  async function rangeItems() {
    const key = `${state.from}-${state.to}-${[...state.off].sort().join(",")}`;
    if (rangeCache.key === key) return rangeCache.items;
    const steps = [];
    for (let n = state.from; n < state.to; n++) steps.push(n);
    const docs = await Promise.all(steps.map(loadStep));
    const merged = new Map();
    docs.forEach((doc, k) => {
      const n = steps[k];
      for (const item of doc.items) {
        let entry = merged.get(item.id);
        if (!entry) {
          entry = { id: item.id, section: byId.get(item.id), steps: [], ops: new Map(), noise: 0, net: new Map(), signals: new Set(), score: 0, best: null, extra: [] };
          merged.set(item.id, entry);
        }
        const change = stepChange(n, item);
        entry.steps.push(change);
        const op = (sid, what) => {
          if (!entry.ops.has(sid)) entry.ops.set(sid, []);
          entry.ops.get(sid).push(what);
        };
        for (const sid of item.na ?? []) op(sid, "a");
        for (const sid of item.nd ?? []) op(sid, "d");
        for (const sid of [...(item.nm ?? []), ...change.flipped]) op(sid, "m");
        for (const sid of item.ne ?? []) if (!change.flipped.includes(sid)) op(sid, "e");
        for (const sid of item.nv ?? []) op(sid, "v");
        entry.noise += item.c[5];
        for (const signed of item.w ?? []) {
          const word = signed.slice(1);
          entry.net.set(word, (entry.net.get(word) ?? 0) + (signed[0] === "+" ? 1 : -1));
        }
        for (const code of item.x ?? "") entry.signals.add(code);
        if (!entry.best || change.sc > entry.best.sc || (change.sc === entry.best.sc && change.k === "mod" && entry.best.k !== "mod")) entry.best = change;
        entry.score = Math.max(entry.score, change.sc);
        if (item.q) entry.extra.push(item.q);
        if (item.tt) entry.extra.push(item.tt[0], item.tt[1]);
      }
    });
    for (const entry of merged.values()) {
      const section = entry.section;
      const before = present(section, state.from);
      const after = present(section, state.to);
      const substantive = entry.steps.some((change) => change.k !== "edit");
      entry.kind = before && after ? (substantive ? "mod" : "edit") : after ? "add" : before ? "del" : "temp";
      // each sentence once, as it differs between the two ends of the range: added (and not
      // removed again), removed, changed, else only edited editorially, else only moved
      let added = 0;
      let removed = 0;
      let changed = 0;
      let editorial = 0;
      let moved = 0;
      for (const ops of entry.ops.values()) {
        const real = ops.filter((o) => o === "a" || o === "d" || o === "m");
        if (real[0] === "a") added += real.at(-1) !== "d";
        else if (real.at(-1) === "d") removed++;
        else if (real.length) changed++;
        else if (ops.includes("e")) editorial++;
        else moved++;
      }
      entry.counts = [added, removed, changed, editorial, moved, entry.noise];
      entry.size = added + removed + changed;
      // "+should" in 5.3 and "-should" in 6.2 cancel out; what is left is the net change
      entry.words = [...entry.net].filter(([, sum]) => sum).map(([word, sum]) => `${sum > 0 ? "+" : "-"}${word}`);
      entry.order = entry.steps[0].item.o;
      entry.changedIn = entry.steps.filter((change) => change.k !== "edit" || entry.kind === "edit").map((change) => change.n + 1);
      entry.haystack = haystackOf(section, entry.extra.join(" "));
      entry.numbers = numbersOf(section);
    }
    rangeCache = { key, items: [...merged.values()] };
    return rangeCache.items;
  }

  function filterCommon(entry) {
    if (state.part && entry.section.p !== state.part) return false;
    if (state.signals.size && ![...state.signals].some((s) => entry.signals.has(s))) return false;
    return !state.q || matchesQuery(entry);
  }

  // Each sorts in its natural direction: the strongest, the first, the biggest, the earliest.
  // Of changes as strong, the smaller first: one changed sentence says more than forty.
  const NATURAL = { score: "descending", order: "ascending", size: "descending", in: "ascending" };
  const sorters = {
    score: (a, b) => b.score - a.score || b.signals.size - a.signals.size || a.size - b.size || a.order - b.order,
    order: (a, b) => a.order - b.order,
    size: (a, b) => b.size - a.size || a.order - b.order,
    in: (a, b) => (a.changedIn[0] ?? 0) - (b.changedIn[0] ?? 0) || a.order - b.order,
  };
  const SORT_NAMES = { score: "the strongest changes first", order: "in the order of the specification", size: "the most sentences first", in: "by version" };

  let renderToken = 0;

  async function renderChanges() {
    const token = ++renderToken;
    const items = await rangeItems();
    if (token !== renderToken) return;
    const common = items.filter(filterCommon);
    const kindCounts = Object.fromEntries(KINDS.map((kind) => [kind.key, common.filter(kind.test).length]));
    renderKinds(kindCounts);
    const test = KINDS.find((kind) => kind.key === state.kind).test;
    const shown = common.filter(test);
    const sorter = sorters[state.sort];
    shown.sort((a, b) => (state.reverse ? -sorter(a, b) : sorter(a, b)));
    $('[data-count-view="changes"]').textContent = kindCounts.all.toLocaleString("en");

    const fragment = document.createDocumentFragment();
    for (const entry of shown.slice(0, state.limit)) fragment.append(changeRow(entry));
    rowsBody.replaceChildren(fragment);
    more.hidden = shown.length <= state.limit;
    $("[data-more-button]").textContent = `Show ${Math.min(LIMIT, shown.length - state.limit)} more of ${shown.length - state.limit}`;
    const kindLabel = KINDS.find((kind) => kind.key === state.kind).label.toLowerCase();
    const where = state.part ? ` in ${partName(partsByKey.get(state.part))}` : "";
    const off = state.off.size ? `; ${plural(state.off.size, "sweeping edit")} counted as changes` : "";
    count.textContent = `${plural(shown.length, "section")}, ${kindLabel}, ${rangeLabel()}${where}; ${SORT_NAMES[state.sort]}${off}`;
    showEmpty(shown.length === 0, "No changes match.");
    markSelectedRow();
    highlightMatches();
  }

  function renderKinds(counts) {
    if (!kindsBox.childElementCount) {
      kindsBox.append(
        ...KINDS.map((kind) =>
          el(
            "label",
            {},
            el("input", { type: "radio", name: "kind", value: kind.key }),
            el("span", {}, kind.label, " ", el("span", { class: "n", "data-kind-count": kind.key })),
          ),
        ),
      );
    }
    for (const radio of $$("input", kindsBox)) {
      radio.checked = radio.value === state.kind;
      const n = counts[radio.value];
      $(`[data-kind-count="${radio.value}"]`, kindsBox).textContent = n.toLocaleString("en");
      radio.closest("label").classList.toggle("is-zero", n === 0);
    }
  }

  function changeRow(entry) {
    const section = entry.section;
    const n = shownVersion(section);
    const part = partOf(section);
    const number = numberAt(section, n);
    const was = state.from >= section.v[0] ? placedHeading(section, state.from) : null;
    const change = el("td", { class: "c-change" }, el("span", { class: `kind k-${entry.kind}`, text: kindName(entry) }));
    // the excerpt: the section's first sentence when it is new or gone, else its strongest change
    const whole = { add: "add", temp: "add", del: "del" }[entry.kind];
    const shown = whole ? (entry.steps.find((s) => s.item.k === whole) ?? entry.best) : entry.best;
    if (whole === "add") {
      const moved = shown.item.c[4];
      change.append(` ${plural(shown.item.u, "sentence")}${moved ? `, ${moved.toLocaleString("en")} of them moved from elsewhere` : ""}`);
    }
    if (entry.kind === "temp") change.append(`, removed again in ${label(section.v[1] + 1)}`);
    if (shown.item.ex?.length) change.append(el("span", { class: "excerpt" }, segments(shown.item.ex, { n: shown.n, inline: true })));
    else {
      const retitled = entry.steps.find((s) => s.item.tt);
      if (retitled) change.append(titleChange(retitled.item.tt, section, retitled.n));
    }
    if (entry.words.length) change.append(el("span", { class: "signals" }, signalTags(entry.words)));
    const others = entry.changedIn.filter((v) => v !== entry.best.n + 1);
    if (others.length && entry.changedIn.length > 1) change.append(el("span", { class: "also", text: `Also changed in ${others.map(label).join(", ")}` }));
    return el(
      "tr",
      { "data-id": entry.id },
      el(
        "th",
        { scope: "row", class: "c-sec" },
        el("span", { class: "where-line", text: `${partName(part)}${number ? ` · ${number}` : ""}` }),
        el("a", { class: "sec-name", href: hrefFor(entry.id), text: titleAt(section, n) }),
        was && was !== heading(section, n) ? el("span", { class: "formerly", text: `was ${was}` }) : null,
      ),
      change,
      el("td", { class: "c-size" }, sizes(entry.counts)),
      el("td", { class: "c-in" }, entry.changedIn.map((v) => el("span", { class: "tag", text: label(v) }))),
    );
  }

  // "Retitled: 4.5 ~~ServiceSearch~~ Service Search transaction", "Moved from Vol 2, Part F"
  function titleChange([before, after, oldPart], section, n) {
    const moved = oldPart !== partAt(section, n + 1);
    const box = el("span", { class: "tt" });
    if (moved) box.append(`Moved from ${partName(partsByKey.get(oldPart))}${before !== after ? "; " : ""}`);
    if (before !== after) box.append(`${moved ? "r" : "R"}etitled: `, ...segments(wordDiff(before, after).segments, { inline: true }));
    return box;
  }

  // Sentences added, removed, changed; editorial, moved and extraction apart
  function sizes([added, removed, changed, editorial = 0, moved = 0, noise = 0]) {
    const item = (cls, n, text, title) => (n ? el("span", { class: cls, title }, el("b", { text: n.toLocaleString("en") }), ` ${text}`) : null);
    return el(
      "span",
      { class: "sizes" },
      item("s-add", added, "added", `${plural(added, "sentence")} added`),
      item("s-del", removed, "removed", `${plural(removed, "sentence")} removed`),
      item("s-mod", changed, "changed", `${plural(changed, "sentence")} changed`),
      item("s-ed", editorial, "editorial", `${plural(editorial, "sentence")} with editorial edits only`),
      item("s-moved", moved, "moved", `${plural(moved, "sentence")} moved, unchanged`),
      item("s-noise", noise, "extraction", `${plural(noise, "scrap")} the PDF and the HTML extract differently`),
    );
  }

  // "+shall" "-should" "+not"
  function signalTags(list) {
    const order = (w) => (w.slice(1) === "not" ? 1 : 0);
    const sorted = list.sort((a, b) => order(a) - order(b) || a.slice(1).localeCompare(b.slice(1)) || a.localeCompare(b));
    const shown = sorted.slice(0, 5);
    return [
      ...shown.map((w) => el("span", { class: "tag sig", title: `${w[0] === "+" ? "adds" : "removes"} “${w.slice(1)}”` }, el("b", { text: w[0] === "+" ? "+" : "−" }), ` ${w.slice(1)}`)),
      sorted.length > shown.length ? el("span", { class: "tag", text: `+${sorted.length - shown.length}` }) : null,
    ];
  }

  // Segments of a changed sentence: kept, removed, added; editorial ones apart, unless the
  // sweeping rule they follow is switched off (`n` is the step they belong to)
  function segments(list, { n = null, inline = false } = {}) {
    return list.map(([kind, text, rule]) => {
      const content = cells(text, inline);
      const off = isOff(n, rule);
      if (kind === SEG.KEEP) return el("span", {}, content);
      if (kind === SEG.OUT || (kind === SEG.OUT_EDITORIAL && off)) return el("del", {}, content);
      if (kind === SEG.IN || (kind === SEG.IN_EDITORIAL && off)) return el("ins", {}, content);
      const title = rule !== undefined && n !== null ? `editorial: the sweeping edit ${ruleName(n, rule)}` : "editorial";
      return el("span", { class: kind === SEG.OUT_EDITORIAL ? "ed-out" : "ed-in", title }, content);
    });
  }

  // " | " between table cells, drawn as a rule; " ¶ " between the lines of a cell
  function cells(text, inline = false) {
    return text.split(" | ").flatMap((cell, i) => {
      const lines = cell.split(/ ?¶ ?/).flatMap((line, k) => (k ? [inline ? el("span", { class: "line-sep", text: "/" }) : el("br"), line] : [line]));
      return i ? [el("span", { class: "cell-sep", text: "|" }), ...lines] : lines;
    });
  }

  function showEmpty(isEmpty, text) {
    empty.hidden = !isEmpty;
    $("[data-empty-text]", empty).textContent = text;
  }

  // Search matches marked with the CSS Custom Highlight API, where there is one
  function highlightMatches() {
    if (!("highlights" in CSS)) return;
    CSS.highlights.delete("match");
    const { terms, numbers } = query();
    const marks = [...terms.filter((term) => term.length > 1), ...numbers.map((n) => n.toLowerCase())];
    if (!marks.length) return;
    const ranges = [];
    const scope = state.view === "changes" ? rowsBody : state.view === "map" ? mapBox : rulesBody;
    const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const text = node.textContent.toLowerCase();
      for (const term of marks) {
        let at = text.indexOf(term);
        while (at >= 0) {
          const range = new Range();
          range.setStart(node, at);
          range.setEnd(node, at + term.length);
          ranges.push(range);
          at = text.indexOf(term, at + term.length);
        }
      }
    }
    CSS.highlights.set("match", new Highlight(...ranges));
  }

  // Map

  const MAP = { row: 28, partRow: 36, r: [0, 3.5, 4.5, 6] };

  // A step's status, with sweeping rules switched off: editorial only becomes changed
  const statusAt = (section, n) => {
    const found = section.s[n];
    if (found === STATUS.EDITORIAL && section.er?.[n]?.some((k) => isOff(n, k))) return STATUS.CHANGED;
    return found;
  };
  const changedIn = (section, n) => ![STATUS.SAME, STATUS.ABSENT].includes(statusAt(section, n));

  // Part bars on one scale for the whole specification (square root: small Parts stay visible)
  let partMax = 0;
  function tally(list, n) {
    const found = { changed: 0, added: 0, removed: 0 };
    for (const s of list) {
      const st = statusAt(s, n);
      if (st === STATUS.CHANGED) found.changed++;
      else if (st === STATUS.ADDED) found.added++;
      else if (st === STATUS.REMOVED) found.removed++;
    }
    return found;
  }

  async function renderMap() {
    const token = ++renderToken;
    const items = await rangeItems();
    if (token !== renderToken) return;
    const entries = new Map(items.map((entry) => [entry.id, entry]));
    const cols = versions.length;
    mapBox.style.setProperty("--cols", String(cols));
    const head = el(
      "div",
      { class: "map-head", role: "row" },
      el("div", { class: "map-label", role: "columnheader", text: "Section" }),
      el(
        "div",
        { class: "map-cols", role: "columnheader" },
        versions.map((v, n) =>
          el("span", {
            class: `${v.format === "pdf" ? "is-pdf" : ""}${n > state.from && n <= state.to ? " in-range" : ""}${n === state.from ? " is-base" : ""}`,
            title: `Core ${v.label} (${v.format.toUpperCase()}, ${v.date})${n === state.from ? ": the range's start, compared against" : ""}`,
            text: v.label,
          }),
        ),
      ),
    );
    const rows = [head];
    const searching = Boolean(state.q.trim());
    const byPart = new Map();
    for (const section of sections) {
      if (!byPart.has(section.p)) byPart.set(section.p, []);
      byPart.get(section.p).push(section);
    }
    if (!partMax) {
      // the scale, from the statuses as computed: switching a rule off doesn't rescale
      for (const list of byPart.values()) {
        for (let n = 0; n < index.steps.length; n++) {
          partMax = Math.max(partMax, list.filter((s) => s.s[n] === STATUS.CHANGED).length, list.filter((s) => s.s[n] === STATUS.ADDED).length);
        }
      }
    }
    const inRange = (section) => {
      for (let n = state.from; n < state.to; n++) if (changedIn(section, n) && marked(section, n)) return true;
      return false;
    };
    const target = (section) => entries.get(section.id) ?? { haystack: haystackOf(section), numbers: numbersOf(section) };
    let lastVol = null;
    let shownSections = 0;
    for (const part of index.parts) {
      const list = byPart.get(part.key);
      if (!list) continue;
      if (state.part && part.key !== state.part) continue;
      let matching = searching ? list.filter((s) => matchesQuery(target(s))) : list;
      if (state.only) matching = matching.filter(inRange);
      if ((searching || state.only) && !matching.length) continue;
      if (part.vol !== lastVol) {
        rows.push(el("div", { class: "map-vol", role: "row", text: `Vol ${part.vol}` }));
        lastVol = part.vol;
      }
      const open = state.open.has(part.key) || Boolean(state.part) || searching;
      rows.push(partRow(part, list, open));
      if (open) {
        for (const section of matching) {
          rows.push(sectionRow(section));
          shownSections++;
        }
      }
    }
    mapBox.replaceChildren(...rows);
    const legend = mapLegend();
    mapBox.before(legend);
    $$(".map-legend").slice(0, -1).forEach((old) => old.remove());
    const only = state.only ? `the sections changed ${rangeLabel()}` : "every section of every version";
    count.textContent = `The map: ${only}. Open a Part to see its sections${shownSections ? ` (${plural(shownSections, "section")} shown)` : ""}; click a mark to read that change, or move between marks with the arrow keys.`;
    showEmpty(rows.length === 1, "No sections match.");
    highlightMatches();
  }

  function mapLegend() {
    const lastPdf = versions.filter((v) => v.format === "pdf").at(-1)?.label;
    const key = (shape, text) => el("span", {}, shape, text);
    const svg = (...children) => el("svg:svg", { viewBox: "-7 -7 14 14", "aria-hidden": "true" }, ...children);
    return el(
      "p",
      { class: "map-legend" },
      key(svg(el("svg:rect", { x: -4.5, y: -4.5, width: 9, height: 9, rx: 1, class: "m-new", style: "fill:var(--new-mark)" })), "section added"),
      key(svg(el("svg:circle", { r: 4.5, style: "fill:var(--changed-mark)" })), "text changed (bigger: more sentences)"),
      key(svg(el("svg:circle", { r: 4.5, style: "fill:var(--changed-mark);stroke:var(--ink);stroke-width:1.5" })), "a shall, negation or value changed"),
      key(svg(el("svg:line", { x1: 0, x2: 0, y1: -5, y2: 5, style: "stroke:var(--edge);stroke-width:2" })), "editorial only"),
      key(svg(el("svg:path", { d: "M-4 -4L4 4M4 -4L-4 4", style: "stroke:var(--ink);stroke-width:1.75;stroke-linecap:round" })), "removed"),
      lastPdf ? el("span", {}, el("span", { class: "pdf-key", text: lastPdf }), "grey: read from the PDF") : null,
      el("span", {}, el("span", { class: "base-key", text: label(state.from) }), "underlined: the range's start; shaded: the versions whose changes are in the range"),
    );
  }

  const colX = (n) => `${((n + 0.5) / versions.length) * 100}%`;

  // The versions whose changes are in the range: those after its start, up to its end
  function rangeBand(height) {
    return el("svg:rect", { class: "band", x: `${((state.from + 1) / versions.length) * 100}%`, y: 0, width: `${((state.to - state.from) / versions.length) * 100}%`, height });
  }

  function partRow(part, list, open) {
    const cells = [];
    const h = MAP.partRow;
    cells.push(rangeBand(h));
    index.steps.forEach((_, n) => {
      const { changed, added, removed } = tally(list, n);
      if (!changed && !added && !removed) return;
      const scale = (value) => (value ? Math.max(2, Math.sqrt(value / Math.max(1, partMax)) * (h - 8)) : 0);
      const group = el("svg:svg", { x: colX(n + 1), y: 0, width: 1, height: h, overflow: "visible" });
      const ch = scale(changed);
      const ad = scale(added);
      if (ch) group.append(el("svg:rect", { class: "bar-changed", x: -7, y: h - 2 - ch, width: 6, height: ch, rx: 2 }));
      if (ad) group.append(el("svg:rect", { class: "bar-new", x: 1, y: h - 2 - ad, width: 6, height: ad, rx: 2 }));
      cells.push(
        hitArea(
          n + 1,
          h,
          () => [`${partName(part)} in ${label(n + 1)}`, `${plural(changed, "section")} changed, ${added} added, ${removed} removed. Click to see this step alone`],
          () => {
            state.open.add(part.key);
            setRange(n, n + 1);
            toast(`Showing ${stepLabel(n)}`);
          },
        ),
      );
      cells.push(group);
    });
    const toggle = el(
      "button",
      {
        type: "button",
        "aria-expanded": String(open),
        "data-nav": "",
        onclick: () => {
          if (state.open.has(part.key)) state.open.delete(part.key);
          else state.open.add(part.key);
          renderMap();
        },
      },
      el("span", { class: "num", text: `Part ${part.letter}` }),
      el("span", { class: "title", text: partTitle(part) }),
    );
    const moved = part.from ? Object.entries(part.from).map(([n, key]) => `was Vol ${key[0]}, Part ${key.slice(1)} until ${label(Number(n) - 1)}`) : [];
    return el(
      "div",
      { class: "map-row map-part", role: "row" },
      el("div", { class: "map-label", role: "rowheader" }, toggle, moved.length ? el("span", { class: "muted", text: moved.join("; ") }) : null),
      el("div", { role: "gridcell" }, el("svg:svg", { class: "marks", height: h }, cells)),
    );
  }

  // Marked: any of the signals chosen
  function marked(section, n) {
    if (!state.signals.size) return true;
    const bits = section.x?.[n] ?? 0;
    return [...state.signals].some((s) => bits & SIGNAL_BITS[s]);
  }

  function lifeMarks(section, h, { onPick, labels = false } = {}) {
    const items = [];
    const y = labels ? h - 22 : h / 2;
    const [first, last] = section.v;
    items.push(el("svg:line", { class: "life", x1: colX(first), x2: colX(last), y1: y, y2: y }));
    section.s.forEach((_, n) => {
      const status = statusAt(section, n);
      const v = n + 1;
      const x = colX(v);
      const dim = !marked(section, n) && status !== STATUS.SAME ? { opacity: 0.25 } : {};
      let mark = null;
      if (status === STATUS.ADDED) {
        mark = el("svg:rect", { class: "m-new", x, y: y - 4.5, width: 9, height: 9, rx: 1, transform: "translate(-4.5 0)", ...dim });
      } else if (status === STATUS.CHANGED) {
        const size = Math.max(1, section.m[n]);
        const r = size >= 6 ? MAP.r[3] : size >= 2 ? MAP.r[2] : MAP.r[1];
        mark = el("svg:circle", { class: `m-changed${section.x?.[n] ? " is-marked" : ""}`, cx: x, cy: y, r, ...dim });
      } else if (status === STATUS.EDITORIAL) {
        mark = el("svg:line", { class: "m-edit", x1: x, x2: x, y1: y - 5, y2: y + 5, ...dim });
      } else if (status === STATUS.REMOVED) {
        // a nested <svg> at the column, so the cross can be drawn in pixels around it
        mark = el("svg:svg", { x, y: 0, width: 1, height: h, overflow: "visible", ...dim }, el("svg:path", { class: "m-gone", d: `M-4 ${y - 4}L4 ${y + 4}M4 ${y - 4}L-4 ${y + 4}` }));
      }
      if (!mark) return;
      items.push(hitArea(v, h, () => markTip(section, n), () => onPick?.(n), labels));
      items.push(mark);
    });
    if (labels) {
      versions.forEach((version, n) => {
        const cls = n === state.from ? "is-base" : n > state.from && n <= state.to ? "in-range" : "";
        items.push(el("svg:text", { x: colX(n), y: h - 2, class: cls, text: version.label }));
      });
    }
    return items;
  }

  function markTip(section, n) {
    const status = statusAt(section, n);
    const what = {
      [STATUS.ADDED]: "added",
      [STATUS.REMOVED]: "removed",
      [STATUS.EDITORIAL]: "editorial edits only",
      [STATUS.CHANGED]: `${plural(Math.max(1, section.m[n]), "sentence")} changed`,
    }[status];
    const bits = section.x?.[n] ?? 0;
    const signals = [bits & 1 && "shall/should/may", bits & 2 && "negation", bits & 4 && "values"].filter(Boolean);
    return [`${placedHeading(section, Math.min(n + 1, section.v[1]))}`, `${label(n + 1)}: ${what}${signals.length ? `; ${signals.join(", ")}` : ""}`];
  }

  // A transparent column over a mark: hover and focus show the tooltip, a click picks it.
  // On the map the arrow keys move between them (one tab stop per row); in the panel's life
  // strip each is a tab stop of its own.
  function hitArea(column, h, tip, pick, tabbable = false) {
    const rect = el("svg:rect", {
      class: "hit",
      x: `${(column / versions.length) * 100}%`,
      y: 0,
      width: `${(1 / versions.length) * 100}%`,
      height: h,
      tabindex: tabbable ? "0" : "-1",
      role: "button",
      "data-col": String(column),
      "aria-label": tip().join(": "),
    });
    const show = (event) => showTip(tip(), event);
    rect.addEventListener("pointerenter", show);
    rect.addEventListener("pointermove", show);
    rect.addEventListener("pointerleave", hideTip);
    rect.addEventListener("focus", show);
    rect.addEventListener("blur", hideTip);
    rect.addEventListener("click", (event) => {
      event.stopPropagation();
      hideTip();
      pick?.();
    });
    rect.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        hideTip();
        pick?.();
      }
    });
    return rect;
  }

  function showTip([title, detail], event) {
    tooltip.replaceChildren(el("strong", { text: detail }), el("span", { text: title }));
    tooltip.hidden = false;
    const box = event.target.getBoundingClientRect();
    const x = event.clientX ?? box.left + box.width / 2;
    const y = event.clientY ?? box.top;
    const width = tooltip.offsetWidth;
    tooltip.style.left = `${Math.min(window.innerWidth - width - 8, Math.max(8, x - width / 2))}px`;
    tooltip.style.top = `${Math.max(8, y - tooltip.offsetHeight - 14)}px`;
  }
  function hideTip() {
    tooltip.hidden = true;
  }

  function sectionRow(section) {
    const h = MAP.row;
    const n = shownVersion(section);
    const number = numberAt(section, n);
    return el(
      "div",
      { class: `map-row map-section${state.selected === section.id ? " is-selected" : ""}`, role: "row", "data-section": section.id },
      el(
        "div",
        {
          class: "map-label",
          role: "rowheader",
          style: `--depth:${Math.max(0, section.d - 1)}`,
          tabindex: "0",
          "data-nav": "",
          onclick: () => openSection(section.id),
          onkeydown: (event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              openSection(section.id);
            }
          },
        },
        number ? el("span", { class: "num", text: number }) : null,
        el("span", { class: "title", title: titleAt(section, n), text: titleAt(section, n) }),
      ),
      el(
        "div",
        { role: "gridcell" },
        el("svg:svg", { class: "marks", height: h }, rangeBand(h), lifeMarks(section, h, { onPick: (step) => openSection(section.id, { step }) })),
      ),
    );
  }

  // The arrow keys on the map: up and down between rows, left and right between a row's marks
  function mapKeys(event) {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
    const target = event.target;
    const row = target.closest(".map-row");
    if (!row) return;
    const rowNav = $("[data-nav]", row);
    const hits = $$(".hit", row);
    const onMark = target.classList.contains("hit");
    let next = null;
    if (event.key === "ArrowRight") next = onMark ? hits[hits.indexOf(target) + 1] : hits[0];
    else if (event.key === "ArrowLeft") next = onMark ? (hits[hits.indexOf(target) - 1] ?? rowNav) : null;
    else if (event.key === "Home") next = rowNav;
    else if (event.key === "End") next = hits.at(-1);
    else {
      const navs = $$("[data-nav]", mapBox);
      const other = navs[navs.indexOf(rowNav) + (event.key === "ArrowDown" ? 1 : -1)];
      if (other) next = (onMark && $(`.hit[data-col="${target.dataset.col}"]`, other.closest(".map-row"))) || other;
    }
    if (next) {
      event.preventDefault();
      next.focus();
    }
  }

  // Sweeping edits: where each applied, and whether it counts as editorial

  async function renderSweeping() {
    const token = ++renderToken;
    const steps = [];
    for (let n = state.from; n < state.to; n++) steps.push(n);
    const docs = await Promise.all(steps.map(loadStep));
    if (token !== renderToken) return;
    const rows = [];
    let total = 0;
    let shown = 0;
    const code = (text) => (text ? el("code", { text: text.replaceAll(NAME, "‹name›") }) : el("span", { class: "muted", text: "(nothing)" }));
    steps.forEach((n, s) => {
      index.steps[n].rules.forEach(([was, is, times, inSections, exampleWas, exampleIs], k) => {
        total++;
        let ids = docs[s].rules?.[k] ?? [];
        if (state.part) ids = ids.filter((id) => byId.get(id)?.p === state.part);
        if (state.part && !ids.length) return;
        if (state.q && !matchesQuery({ haystack: ` ${words(`${was} ${is} ${exampleWas ?? ""} ${exampleIs ?? ""}`).join(" ")}`, numbers: [] })) return;
        shown++;
        const key = ruleKey(n, k);
        const off = state.off.has(key);
        const open = state.expanded.has(key);
        const pattern = `${was} ${is}`.includes(NAME);
        const example = pattern && exampleWas !== undefined ? el("span", { class: "example", text: `e.g. “${exampleWas || "(nothing)"}” → “${exampleIs || "(nothing)"}”` }) : null;
        const toggle = () => {
          if (state.expanded.has(key)) state.expanded.delete(key);
          else state.expanded.add(key);
          renderSweeping();
        };
        rows.push(
          el(
            "tr",
            { class: off ? "is-off" : null },
            el("td", { class: "c-in" }, el("span", { class: "tag", text: label(n + 1) })),
            // as written once, where the rule is a plain rewrite; the pattern, where it names something
            el("td", { title: was }, code(pattern ? was : (exampleWas ?? was)), example),
            el("td", { title: is }, code(pattern ? is : (exampleIs ?? is))),
            el("td", { class: "c-num", text: times.toLocaleString("en") }),
            el("td", { class: "c-num" }, el("button", { type: "button", "aria-expanded": String(open), title: "List the sections", onclick: toggle, text: (ids.length || inSections).toLocaleString("en") })),
            el(
              "td",
              { class: "c-ed" },
              el(
                "label",
                { class: "check", title: off ? "Counted as a change: tick to count it as editorial again" : "Untick to count it as a change" },
                el("input", {
                  type: "checkbox",
                  checked: !off,
                  "aria-label": `Count ${ruleName(n, k)} in ${label(n + 1)} as editorial`,
                  onchange: (event) => {
                    if (event.target.checked) state.off.delete(key);
                    else state.off.add(key);
                    update({ push: true });
                  },
                }),
                el("span", { text: off ? "no" : "yes" }),
              ),
            ),
          ),
        );
        if (open) {
          const list = ids.length
            ? el(
                "ul",
                {},
                ids.map((id) => {
                  const section = byId.get(id);
                  return el("li", {}, el("a", { href: hrefFor(id, n), onclick: (event) => { if (event.metaKey || event.ctrlKey || event.shiftKey) return; event.preventDefault(); openSection(id, { step: n }); }, text: placedHeading(section, Math.min(n + 1, section.v[1])) }), " ", el("span", { class: "muted", text: partName(partOf(section)) }));
                }),
              )
            : el("p", { class: "muted", text: "Where it applied isn't recorded in this build: run specdiff diff again." });
          rows.push(el("tr", { class: "rule-sections" }, el("td", {}), el("td", { colspan: "5" }, list)));
        }
      });
    });
    rulesBody.replaceChildren(...rows);
    $('[data-count-view="sweeping"]').textContent = total.toLocaleString("en");
    const off = state.off.size ? `; ${state.off.size.toLocaleString("en")} counted as changes` : "";
    count.textContent = `${plural(shown, "sweeping edit")} ${rangeLabel()}${state.part ? ` in ${partName(partsByKey.get(state.part))}` : ""}, the most frequent first${off}`;
    showEmpty(shown === 0, "No sweeping edits match.");
    highlightMatches();
  }

  // The panel: one section, its life, its diff or its blame

  async function openSection(id, { step = null, scroll = true } = {}) {
    state.selected = id;
    state.step = step;
    writeUrl({ push: true });
    await renderPanel({ scroll });
  }

  function closePanel() {
    state.selected = null;
    state.step = null;
    panel.hidden = true;
    page.append(panel);
    $$(".detail-row").forEach((row) => row.remove());
    markSelectedRow();
    $$(".map-section.is-selected").forEach((row) => row.classList.remove("is-selected"));
    writeUrl({ push: true });
  }

  function markSelectedRow() {
    for (const row of $$("tr[data-id]", rowsBody)) row.classList.toggle("is-selected", row.dataset.id === state.selected);
    for (const row of $$(".map-section", mapBox)) row.classList.toggle("is-selected", row.dataset.section === state.selected);
  }

  function placePanel() {
    $$(".detail-row").forEach((row) => row.remove());
    if (wide.matches || !state.selected) {
      page.append(panel);
      return;
    }
    const row = state.view === "changes" ? $(`tr[data-id="${CSS.escape(state.selected)}"]`, rowsBody) : null;
    if (row) {
      const cell = el("td", { colspan: state.to - state.from === 1 ? "3" : "4" });
      row.after(el("tr", { class: "detail-row" }, cell));
      cell.append(panel);
    } else {
      main.prepend(panel);
    }
  }

  let panelToken = 0;

  async function renderPanel({ scroll = false } = {}) {
    const section = byId.get(state.selected);
    if (!section) {
      closePanel();
      return;
    }
    const token = ++panelToken;
    panel.hidden = false;
    placePanel();
    markSelectedRow();
    const part = partOf(section);
    const n = shownVersion(section);
    const number = numberAt(section, n);
    const head = [
      el("p", { class: "sec-part", text: `${partName(part)} · ${partTitle(part, n)}` }),
      el("h3", { class: "sec-title" }, number ? el("span", { class: "num", text: number }) : null, titleAt(section, n)),
    ];
    const former = formerHeadings(section);
    if (former.length) head.push(el("p", { class: "sec-former", text: `Was ${former.join("; ")}` }));
    const links = [];
    for (const v of new Set([Math.max(section.v[0], state.from), n])) {
      const link = specLink(section, v);
      if (link) links.push(el("a", { href: link.href, class: "external", target: "_blank", rel: "noopener", text: link.text }));
    }
    links.push(el("a", { href: location.href, onclick: copyLink, text: "Copy link" }));
    head.push(el("p", { class: "sec-links" }, links));
    head.push(lifeStrip(section));
    head.push(modeSwitch(section));
    panelBody.replaceChildren(...head, el("p", { class: "panel-empty", text: "Loading the text…" }));
    if (scroll && !wide.matches) panel.scrollIntoView({ behavior: smooth(), block: "start" });
    if (wide.matches) panel.scrollTop = 0;

    let data;
    try {
      data = await loadPart(section);
    } catch (error) {
      panelBody.lastChild.textContent = `Could not load the text: ${error.message}`;
      return;
    }
    if (token !== panelToken) return;
    const body = state.mode === "blame" ? blameView(section, data) : diffView(section, data);
    panelBody.lastChild.replaceWith(body);
  }

  function formerHeadings(section) {
    const seen = new Map();
    for (let n = section.v[0]; n <= section.v[1]; n++) {
      const text = placedHeading(section, n);
      if (!seen.has(text)) seen.set(text, [n, n]);
      else seen.get(text)[1] = n;
    }
    const plain = (text) => words(text).join(" ");
    const current = plain(heading(section));
    return [...seen.entries()].filter(([text]) => plain(text) !== current).map(([text, [a, b]]) => `${text} (${a === b ? label(a) : `${label(a)}–${label(b)}`})`);
  }

  function lifeStrip(section) {
    const h = 44;
    return el(
      "div",
      { class: "life-strip" },
      el(
        "svg:svg",
        { class: "marks", height: h, role: "group", "aria-label": `The life of this section: added in ${originLabel(section.v[0])}${section.v[1] < versions.length - 1 ? `, removed in ${label(section.v[1] + 1)}` : ""}` },
        el("svg:rect", { class: "band", x: `${((state.from + 1) / versions.length) * 100}%`, y: 0, width: `${((state.to - state.from) / versions.length) * 100}%`, height: h - 18 }),
        lifeMarks(section, h, { labels: true, onPick: (step) => openSection(section.id, { step, scroll: false }) }),
      ),
    );
  }

  const changedSteps = (section) => {
    const found = [];
    for (let n = state.from; n < state.to; n++) if (changedIn(section, n)) found.push(n);
    return found;
  };
  // A range of several steps in which the section changed more than once: all at once, or by
  // version. A section added and removed within the range has no two ends to compare.
  const netPossible = (section) => state.step === null && changedSteps(section).length > 1 && (present(section, state.from) || present(section, state.to));
  const netShown = (section) => netPossible(section) && !state.bySteps;

  function modeSwitch(section) {
    const radio = (name, value, text, checked, onchange) => el("label", {}, el("input", { type: "radio", name, value, checked, onchange }), el("span", { text }));
    const rerender = () => {
      writeUrl({ push: true });
      renderPanel();
    };
    const modes = el(
      "fieldset",
      { class: "switch" },
      el("legend", { class: "visually-hidden", text: "Show" }),
      radio("mode", "diff", "Diff", state.mode === "diff", () => ((state.mode = "diff"), rerender())),
      radio("mode", "blame", "Blame", state.mode === "blame", () => ((state.mode = "blame"), rerender())),
    );
    const several = netPossible(section) && state.mode === "diff";
    const net = several
      ? el(
          "fieldset",
          { class: "switch small" },
          el("legend", { class: "visually-hidden", text: "Show the range" }),
          radio("net", "all", `${label(state.from)} → ${label(state.to)} at once`, !state.bySteps, () => ((state.bySteps = false), rerender())),
          radio("net", "steps", "By version", state.bySteps, () => ((state.bySteps = true), rerender())),
        )
      : null;
    const editorial = el(
      "label",
      { class: "check" },
      el("input", {
        type: "checkbox",
        checked: state.editorial,
        onchange: (event) => {
          state.editorial = event.target.checked;
          update({ push: true });
        },
      }),
      el("span", { text: "Show editorial edits" }),
    );
    const pinned = state.step !== null ? el("button", { type: "button", class: "fold", onclick: () => openSection(state.selected, { scroll: false }), text: `Showing ${stepLabel(state.step)} only. Show ${label(state.from)} → ${label(state.to)}` }) : null;
    return el("div", { class: "panel-modes" }, modes, net, editorial, pinned);
  }

  // The text of a section in version n: blocks [kind, sentences] and sentences [text, blame]
  function contentAt(data, section, n) {
    if (!present(section, n)) return null;
    const versionsStored = data.sections[section.id].v;
    let found = null;
    for (const key of Object.keys(versionsStored).map(Number).sort((a, b) => a - b)) {
      if (key <= n) found = versionsStored[key];
    }
    return found;
  }

  // What a list of diff entries adds up to: [added, removed, changed, editorial, moved, extraction]
  function entryCounts(entries, n) {
    const counts = [0, 0, 0, 0, 0, 0];
    const quiet = { 1: 4, 2: 5 };
    // a sentence moved within the section is one sentence moved: count its arrival only
    const arrived = new Set(entries.filter((e) => e[0] === ENTRY.INSERT && e[1] === 1 && e[5] !== undefined && e[5] !== null).map((e) => e[5]));
    let i = 0;
    for (const entry of entries) {
      if (entry[0] === ENTRY.EQUAL) i += entry[1];
      else if (entry[0] === ENTRY.CHANGE) {
        counts[isEditorialEntry(entry, n) ? 3 : 2]++;
        i++;
      } else if (entry[0] === ENTRY.INSERT && entry[1] === REWORDED) counts[isEditorialEntry(entry, n) ? 3 : 2]++;
      else if (entry[0] === ENTRY.INSERT) counts[quiet[entry[1]] ?? 0]++;
      else {
        if (entry[1] !== REWORDED && !(entry[1] === 1 && arrived.has(i))) counts[quiet[entry[1]] ?? 1]++;
        i++;
      }
    }
    return counts;
  }

  // What happened to the section's heading between versions a and b
  function headingNote(section, a, b) {
    if (!present(section, a) || !present(section, b)) return null;
    const before = heading(section, a);
    const after = heading(section, b);
    const moved = partAt(section, a) !== partAt(section, b);
    if (before === after && !moved) return null;
    return el("p", { class: "step-note title-change" }, titleChange([before, after, partAt(section, a)], section, b - 1));
  }

  function diffView(section, data) {
    if (netShown(section)) return netView(section, data);
    const box = el("div", { class: "doc" });
    const steps = state.step !== null ? [state.step] : changedSteps(section);
    if (!steps.length) {
      const changes = section.s.map((_, n) => n).filter((n) => statusAt(section, n) >= STATUS.EDITORIAL);
      const before = changes.filter((n) => n < state.from).at(-1);
      const after = changes.find((n) => n >= state.to);
      box.append(el("p", { class: "panel-empty", text: `No changes from ${label(state.from)} to ${label(state.to)}.` }));
      const offer = [before, after].filter((n) => n !== undefined);
      if (offer.length) {
        box.append(
          el("p", { class: "panel-empty" }, "Changed in ", ...offer.flatMap((n, i) => [i ? " and " : "", el("a", { href: hrefFor(section.id, n), onclick: (event) => { event.preventDefault(); openSection(section.id, { step: n, scroll: false }); }, text: label(n + 1) })]), "."),
        );
      }
      return box;
    }
    for (const n of steps) {
      const entries = data.sections[section.id].d[n] ?? [];
      const before = contentAt(data, section, n);
      const after = contentAt(data, section, n + 1);
      box.append(el("div", { class: "step-head" }, el("h3", { text: stepLabel(n) }), sizes(entryCounts(entries, n))));
      if (formatChange(n)) box.append(el("p", { class: "step-note", text: `${label(n)} is read from the PDF, ${label(n + 1)} from the HTML: tables and equations come out differently, so some of these changes are the extraction's.` }));
      const note = headingNote(section, n, n + 1);
      if (note) box.append(note);
      if (section.s[n] === STATUS.ADDED) box.append(el("p", { class: "step-note", text: "A new section." }));
      if (section.s[n] === STATUS.REMOVED) box.append(el("p", { class: "step-note", text: `Removed in ${label(n + 1)}.` }));
      box.append(...diffBlocks(data.texts, before, after, entries, n));
    }
    return box;
  }

  // The whole range at once: the text of `from` against the text of `to`
  function netView(section, data) {
    const a = state.from;
    const b = state.to;
    const box = el("div", { class: "doc" });
    const { entries, counts } = netEntries(section, data, a, b);
    const steps = changedSteps(section);
    box.append(el("div", { class: "step-head" }, el("h3", { text: `${label(a)} → ${label(b)}` }), sizes(counts)));
    box.append(el("p", { class: "step-note", text: `The changes of ${steps.map((n) => label(n + 1)).join(", ")} at once: the text of ${present(section, a) ? label(a) : "nothing"} against the text of ${present(section, b) ? label(b) : "nothing"}. Words written in the range are marked as changes; see them version by version for what each one did.` }));
    if (steps.some(formatChange)) box.append(el("p", { class: "step-note", text: "The range crosses from the PDF to the HTML: tables and equations come out differently, so some of these changes are the extraction's." }));
    const note = headingNote(section, a, b);
    if (note) box.append(note);
    if (!present(section, a)) box.append(el("p", { class: "step-note", text: `A new section in ${label(section.v[0])}.` }));
    if (!present(section, b)) box.append(el("p", { class: "step-note", text: `Removed in ${label(section.v[1] + 1)}.` }));
    const none = { b: [], u: [] };
    box.append(...diffBlocks(data.texts, contentAt(data, section, a) ?? none, contentAt(data, section, b) ?? none, entries, null));
    return box;
  }

  // Follow the sentences of version a through each step to version b, from the steps' own
  // alignments: which pairs stayed (and whether they changed), which went, which came
  function composeRange(section, data, a, b) {
    const stored = data.sections[section.id];
    const start = contentAt(data, section, a);
    const live = (start?.u ?? []).map((_, i) => ({ i, at: i, gone: null, substantive: false, off: false }));
    let born = new Map(); // index in the current version -> how it came (0 added, 1 moved, 2 extraction)
    for (let n = a; n < b; n++) {
      const status = section.s[n];
      if (status === STATUS.ABSENT || status === STATUS.SAME) continue;
      const entries = stored.d[n] ?? [];
      if (status === STATUS.ADDED) {
        born = new Map(entries.map((entry, j) => [j, entry[1]]));
        continue;
      }
      if (status === STATUS.REMOVED) {
        for (const s of live) if (s.at !== null) [s.gone, s.at] = [entries[s.at]?.[1] ?? 0, null];
        born = new Map();
        continue;
      }
      const map = new Map();
      const touched = new Map();
      const gone = new Map();
      const fresh = new Map();
      let i = 0;
      let j = 0;
      for (const entry of entries) {
        if (entry[0] === ENTRY.EQUAL) {
          for (let k = 0; k < entry[1]; k++) map.set(i + k, j + k);
          i += entry[1];
          j += entry[1];
        } else if (entry[0] === ENTRY.CHANGE) {
          map.set(i, j);
          touched.set(i, { editorial: isEditorialEntry(entry, n), off: hasOff(entry[3], n) });
          i++;
          j++;
        } else if (entry[0] === ENTRY.DELETE) {
          if (entry[1] !== REWORDED) gone.set(i, entry[1]);
          i++;
        } else {
          if (entry[1] === REWORDED && entry[5] !== undefined) {
            map.set(entry[5], j);
            touched.set(entry[5], { editorial: isEditorialEntry(entry, n), off: hasOff(entry[3], n) });
          } else if (entry[1] === 1 && entry[5] !== undefined && entry[5] !== null) {
            map.set(entry[5], j); // moved within the section, unchanged
          } else fresh.set(j, entry[1] === REWORDED ? 0 : entry[1]);
          j++;
        }
      }
      for (const s of live) {
        if (s.at === null) continue;
        if (!map.has(s.at)) {
          [s.gone, s.at] = [gone.get(s.at) ?? 0, null];
          continue;
        }
        const t = touched.get(s.at);
        if (t && !t.editorial) s.substantive = true;
        if (t?.off) s.off = true;
        s.at = map.get(s.at);
      }
      const next = new Map();
      for (const [at, how] of born) if (map.has(at)) next.set(map.get(at), how);
      for (const [at, how] of fresh) next.set(at, how);
      born = next;
    }
    return { live, born };
  }

  function netEntries(section, data, a, b) {
    const { live, born } = composeRange(section, data, a, b);
    const before = contentAt(data, section, a) ?? { u: [] };
    const after = contentAt(data, section, b) ?? { u: [] };
    const textOf = (content, k) => data.texts[content.u[k][0]];
    const pairs = live.filter((s) => s.at !== null);
    // the pairs in reading order on both sides; the others moved within the section
    const ordered = longestIncreasing(pairs.map((s) => s.at));
    const movedTo = new Map(pairs.filter((_, k) => !ordered.has(k)).map((s) => [s.at, s]));
    const movedFrom = new Set([...movedTo.values()].map((s) => s.i));
    const goneHow = new Map(live.filter((s) => s.gone !== null).map((s) => [s.i, s.gone]));
    const entries = [];
    const quiet = { 1: 4, 2: 5 };
    const counts = [0, 0, 0, 0, 0, 0];
    const diff = (s) => {
      const found = wordDiff(textOf(before, s.i), textOf(after, s.at), { blame: after.u[s.at][1], since: a, substantive: s.substantive, off: s.off });
      counts[found.editorial ? 3 : 2]++;
      return found;
    };
    const same = (s) => textOf(before, s.i) === textOf(after, s.at);
    const pairOf = new Map(pairs.map((s) => [s.i, s]));
    const old = (i) => {
      const moved = movedFrom.has(i) ? pairOf.get(i) : null;
      if (moved && same(moved)) entries.push([ENTRY.DELETE, 1, ""]); // counted where it arrives
      else if (movedFrom.has(i)) entries.push([ENTRY.DELETE, REWORDED, ""]);
      else {
        const how = goneHow.get(i) ?? 0;
        entries.push([ENTRY.DELETE, how, ""]);
        counts[quiet[how] ?? 1]++;
      }
    };
    const fresh = (j) => {
      const s = movedTo.get(j);
      if (s && same(s)) {
        entries.push([ENTRY.INSERT, 1, ""]);
        counts[4]++;
      } else if (s) {
        const found = diff(s);
        entries.push([ENTRY.INSERT, REWORDED, "", found.segments, found.editorial, s.i]);
      } else {
        const how = born.get(j) ?? 0;
        entries.push([ENTRY.INSERT, how, ""]);
        counts[quiet[how] ?? 0]++;
      }
    };
    let i = 0;
    let j = 0;
    pairs.forEach((s, k) => {
      if (!ordered.has(k)) return;
      for (; i < s.i; i++) old(i);
      for (; j < s.at; j++) fresh(j);
      if (textOf(before, s.i) === textOf(after, s.at)) {
        const last = entries.at(-1);
        if (last?.[0] === ENTRY.EQUAL) last[1]++;
        else entries.push([ENTRY.EQUAL, 1]);
      } else {
        const found = diff(s);
        entries.push([ENTRY.CHANGE, found.editorial, "", found.segments]);
      }
      i = s.i + 1;
      j = s.at + 1;
    });
    for (; i < before.u.length; i++) old(i);
    for (; j < after.u.length; j++) fresh(j);
    return { entries, counts };
  }

  // The indices of a longest strictly increasing run of `values`
  function longestIncreasing(values) {
    const tails = [];
    const previous = new Array(values.length).fill(-1);
    values.forEach((value, k) => {
      let lo = 0;
      let hi = tails.length;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (values[tails[mid]] < value) lo = mid + 1;
        else hi = mid;
      }
      if (lo) previous[k] = tails[lo - 1];
      tails[lo] = k;
    });
    const found = new Set();
    for (let k = tails.at(-1) ?? -1; k >= 0; k = previous[k]) found.add(k);
    return found;
  }

  // Word-level diff of two sentences, for the net view and retitled headings. With a blame,
  // a word inserted that was written before `since` came from an editorial edit.
  const TOKEN = /[\p{L}\p{N}_]+(?:[-_.'’][\p{L}\p{N}_]+)*|[^\p{L}\p{N}_\s]/gu;
  const WORDY = /[\p{L}\p{N}]/u;
  const foldToken = (token) =>
    token
      .normalize("NFKC")
      .replace(/[‘’‚‛′]/g, "'")
      .replace(/[“”„″]/g, '"')
      .replace(/[‐-—−]/g, "-");
  const tokenize = (text) => [...text.matchAll(TOKEN)].map((m) => ({ text: m[0], start: m.index, key: foldToken(m[0]) }));

  function diffTokens(a, b) {
    const ops = [];
    const push = (tag, i1, i2, j1, j2) => {
      if (i1 === i2 && j1 === j2) return;
      const last = ops.at(-1);
      if (last && (last[0] === "equal") === (tag === "equal")) [last[2], last[4]] = [i2, j2];
      else ops.push([tag === "equal" ? "equal" : "replace", i1, i2, j1, j2]);
    };
    let start = 0;
    while (start < a.length && start < b.length && a[start] === b[start]) start++;
    let endA = a.length;
    let endB = b.length;
    while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) [endA, endB] = [endA - 1, endB - 1];
    push("equal", 0, start, 0, start);
    const n = endA - start;
    const m = endB - start;
    if (!n || !m || n * m > 1_000_000) push("replace", start, endA, start, endB);
    else {
      const w = m + 1;
      const table = new Uint16Array((n + 1) * w);
      for (let i = n - 1; i >= 0; i--) {
        for (let j = m - 1; j >= 0; j--) {
          table[i * w + j] = a[start + i] === b[start + j] ? table[(i + 1) * w + j + 1] + 1 : Math.max(table[(i + 1) * w + j], table[i * w + j + 1]);
        }
      }
      let i = 0;
      let j = 0;
      while (i < n || j < m) {
        if (i < n && j < m && a[start + i] === b[start + j]) {
          push("equal", start + i, start + i + 1, start + j, start + j + 1);
          i++;
          j++;
        } else if (j < m && (i === n || table[i * w + j + 1] >= table[(i + 1) * w + j])) {
          push("insert", start + i, start + i, start + j, start + j + 1);
          j++;
        } else {
          push("delete", start + i, start + i + 1, start + j, start + j);
          i++;
        }
      }
    }
    push("equal", endA, a.length, endB, b.length);
    // a lone punctuation mark kept between two edits is part of one edit
    const merged = [];
    for (const op of ops) {
      const last = merged.at(-1);
      const lone = last?.[0] === "equal" && last[2] - last[1] === 1 && !WORDY.test(a[last[1]]) && merged.length > 1;
      if (op[0] !== "equal" && lone) {
        merged.pop();
        const before = merged.at(-1);
        [before[2], before[4]] = [op[2], op[4]];
      } else merged.push(op);
    }
    return merged;
  }

  function wordDiff(oldText, newText, { blame = null, since = -1, substantive = true, off = false } = {}) {
    const A = tokenize(oldText);
    const B = tokenize(newText);
    const originAt = blame === null ? () => Infinity : typeof blame === "number" ? () => blame : (position) => (blame.find(([, end]) => position < end) ?? blame.at(-1))[0];
    const pieceOf = (text, tokens, from, to) => (from >= to ? "" : text.slice(tokens[from].start, to < tokens.length ? tokens[to].start : text.length));
    const found = [];
    const add = (kind, text) => {
      if (!text) return;
      const last = found.at(-1);
      if (last?.[0] === kind) last[1] += text;
      else found.push([kind, text]);
    };
    let editorialOnly = true;
    for (const [tag, i1, i2, j1, j2] of diffTokens(
      A.map((t) => t.key),
      B.map((t) => t.key),
    )) {
      if (tag === "equal") {
        add(SEG.KEEP, pieceOf(newText, B, j1, j2));
        continue;
      }
      let editorial;
      if (off) editorial = false;
      else if (!substantive) editorial = blame !== null;
      else if (j2 > j1) editorial = B.slice(j1, j2).every((t) => originAt(t.start) <= since);
      else editorial = A.slice(i1, i2).every((t) => !WORDY.test(t.text));
      if (!editorial) editorialOnly = false;
      let removed = pieceOf(oldText, A, i1, i2);
      const spaced = removed && i1 > 0 && /\s/.test(oldText[A[i1].start - 1] ?? "");
      if (spaced && found.length && !/\s$/.test(found.at(-1)[1])) removed = ` ${removed}`;
      add(editorial ? SEG.OUT_EDITORIAL : SEG.OUT, removed);
      add(editorial ? SEG.IN_EDITORIAL : SEG.IN, pieceOf(newText, B, j1, j2));
    }
    // removed text doesn't end in a space where what follows starts with one or with punctuation
    found.forEach((segment, k) => {
      if (segment[0] !== SEG.OUT && segment[0] !== SEG.OUT_EDITORIAL) return;
      const following = found[k + 1]?.[1] ?? "";
      if (!following || /^[\s.,;:)\]]/.test(following)) segment[1] = segment[1].trimEnd();
    });
    return { segments: found.filter((segment) => segment[1]), editorial: editorialOnly };
  }

  // Lay the diff out in the blocks of the newer version; sentences removed join the block
  // their neighbours went to, or stand as a block of their own.
  function diffBlocks(texts, before, after, entries, n) {
    const blockOf = (content) => {
      const result = [];
      content?.b.forEach(([, count], block) => {
        for (let i = 0; i < count; i++) result.push(block);
      });
      return result;
    };
    const aBlock = blockOf(before);
    const bBlock = blockOf(after);
    // first pass: which new block each old block continues in
    const continues = new Map();
    let ai = 0;
    let bi = 0;
    for (const entry of entries) {
      if (entry[0] === ENTRY.EQUAL) {
        for (let k = 0; k < entry[1]; k++) if (!continues.has(aBlock[ai + k])) continues.set(aBlock[ai + k], bBlock[bi + k]);
        ai += entry[1];
        bi += entry[1];
      } else if (entry[0] === ENTRY.CHANGE) {
        if (!continues.has(aBlock[ai])) continues.set(aBlock[ai], bBlock[bi]);
        ai++;
        bi++;
      } else if (entry[0] === ENTRY.DELETE) ai++;
      else bi++;
    }
    const out = [];
    const newBlocks = new Map();
    const oldBlocks = new Map();
    const newBlock = (b) => {
      if (!newBlocks.has(b)) {
        const block = { kind: after.b[b][0], parts: [], changed: false };
        newBlocks.set(b, block);
        out.push(block);
      }
      return newBlocks.get(b);
    };
    const oldBlock = (a) => {
      if (continues.has(a)) return newBlock(continues.get(a));
      if (!oldBlocks.has(a)) {
        const block = { kind: before.b[a][0], parts: [], changed: true, removed: true };
        oldBlocks.set(a, block);
        out.push(block);
      }
      return oldBlocks.get(a);
    };
    ai = 0;
    bi = 0;
    for (const entry of entries) {
      const [type] = entry;
      if (type === ENTRY.EQUAL) {
        for (let k = 0; k < entry[1]; k++) newBlock(bBlock[bi + k]).parts.push({ type: "same", text: texts[after.u[bi + k][0]] });
        ai += entry[1];
        bi += entry[1];
      } else if (type === ENTRY.CHANGE) {
        const block = newBlock(bBlock[bi]);
        const editorial = isEditorialEntry(entry, n);
        block.parts.push({ type: "change", segments: entry[3] });
        if (editorial) block.edited = true;
        else block.changed = true;
        ai++;
        bi++;
      } else if (type === ENTRY.INSERT) {
        const block = newBlock(bBlock[bi]);
        if (entry[1] === REWORDED) {
          const editorial = isEditorialEntry(entry, n);
          block.parts.push({ type: "change", segments: entry[3], reworded: true });
          if (editorial) block.edited = true;
          else block.changed = true;
        } else {
          block.parts.push({ type: "add", text: texts[after.u[bi][0]], quiet: entry[1] });
          if (entry[1] === 0) block.changed = true;
          else block.edited = true;
        }
        bi++;
      } else {
        const block = oldBlock(aBlock[ai]);
        block.parts.push({ type: "del", text: texts[before.u[ai][0]], quiet: entry[1] });
        if (entry[1] === 0) block.changed = true;
        else block.edited = true;
        ai++;
      }
    }
    return foldUnchanged(out.map((block) => ({ block, node: renderBlock(block, n) })));
  }

  function renderBlock(block, n) {
    const joiner = block.kind === "pre" ? "\n" : " ";
    const children = [];
    block.parts.forEach((part, i) => {
      if (i) children.push(joiner);
      if (part.type === "same") children.push(...cells(part.text));
      else if (part.type === "change") {
        children.push(...segments(part.segments, { n }));
        if (part.reworded) children.push(" ", el("span", { class: "tag", title: "this sentence moved within the section and was reworded; the diff is against where it was", text: "moved here" }));
      } else if (part.type === "add") {
        const node = el("ins", {}, cells(part.text));
        children.push(part.quiet ? el("span", { class: "s-quiet" }, node, el("span", { class: "tag", text: QUIET[part.quiet] })) : node);
      } else {
        const node = el("del", {}, cells(part.text));
        children.push(part.quiet ? el("span", { class: `s-quiet${part.quiet === REWORDED ? " ed-out" : ""}` }, node, el("span", { class: "tag", text: part.quiet === REWORDED ? "moved, reworded" : QUIET[part.quiet] })) : node);
      }
    });
    const tag = { pre: "pre", li: "div", row: "div", caption: "p", figure: "p", note: "p", eq: "p" }[block.kind] ?? "p";
    return el(tag, { class: `block ${block.kind}${block.removed ? " removed" : ""}` }, children);
  }

  // Unchanged blocks fold away, but for one on either side of a change
  function foldUnchanged(blocks) {
    const keep = blocks.map(({ block }) => block.changed || (state.editorial && block.edited));
    const near = keep.map((_, i) => keep[i] || keep[i - 1] || keep[i + 1]);
    const out = [];
    let run = [];
    const flush = () => {
      if (!run.length) return;
      if (run.length === 1) out.push(run[0]);
      else {
        const hidden = run;
        const edited = hidden.filter((node) => node.dataset.edited).length;
        const button = el("button", {
          type: "button",
          class: "fold",
          text: `${plural(hidden.length, "block")} without changes${edited ? ` (${edited} with editorial edits)` : ""}`,
          onclick: () => button.replaceWith(...hidden),
        });
        out.push(button);
      }
      run = [];
    };
    blocks.forEach(({ block, node }, i) => {
      if (block.edited) node.dataset.edited = "1";
      if (near[i]) {
        flush();
        out.push(node);
      } else run.push(node);
    });
    flush();
    return out;
  }

  // Blame: the text of the shown version, the words written after the range's start marked
  function blameView(section, data) {
    const n = state.step !== null ? state.step + 1 : shownVersion(section);
    const content = contentAt(data, section, n);
    const since = state.step !== null ? state.step : state.from;
    const box = el("div", { class: "doc blame" });
    box.append(
      el(
        "p",
        { class: "blame-legend" },
        `The text of ${label(n)}. `,
        el("span", { class: "since", text: `Written after ${label(since)}` }),
        " is marked; each block names the newest version that wrote in it. Text removed doesn't show here: see Diff.",
      ),
    );
    if (!content) {
      box.append(el("p", { class: "panel-empty", text: `Not in ${label(n)}.` }));
      return box;
    }
    let u = 0;
    for (const [kind, count] of content.b) {
      const children = [];
      let newest = 0;
      for (let k = 0; k < count; k++, u++) {
        const [t, blame] = content.u[u];
        const text = data.texts[t];
        if (k) children.push(kind === "pre" ? "\n" : " ");
        const runs = typeof blame === "number" ? [[blame, text.length]] : blame;
        let start = 0;
        for (const [origin, end] of runs) {
          newest = Math.max(newest, origin);
          const piece = text.slice(start, end);
          children.push(el("span", { class: origin > since ? "since" : null, title: `since ${originLabel(origin)}` }, cells(piece)));
          start = end;
        }
      }
      const tag = { pre: "pre", li: "div", row: "div" }[kind] ?? "p";
      box.append(
        el(
          tag,
          { class: `block ${kind}` },
          el("span", { class: "gutter" }, el("span", { class: `tag${newest > since ? " v-new" : ""}`, text: newest === 0 ? `≤${label(0)}` : label(newest) })),
          children,
        ),
      );
    }
    return box;
  }

  async function copyLink(event) {
    event.preventDefault();
    try {
      await navigator.clipboard.writeText(location.href);
      toast("Link copied");
    } catch {
      toast("Copying is blocked here. Copy the address from the address bar.");
    }
  }

  let toastTimer = 0;
  function toast(text) {
    status.textContent = text;
    status.classList.add("is-shown");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => status.classList.remove("is-shown"), 1800);
  }

  // Updating everything

  async function update({ url = true, push = false } = {}) {
    syncControls();
    if (url) writeUrl({ push });
    try {
      if (state.view === "changes") await renderChanges();
      else if (state.view === "map") await renderMap();
      else await renderSweeping();
    } catch (error) {
      count.textContent = `Could not load the changes (${error.message}). Reload to try again.`;
      return;
    }
    if (state.view !== "map") $$(".map-legend").forEach((legend) => legend.remove());
    if (state.selected) await renderPanel();
    else panel.hidden = true;
  }

  // Wiring

  function wire() {
    const themePicker = $("[data-theme-picker]");
    for (const radio of $$("input", themePicker)) radio.checked = radio.value === (root.dataset.theme ?? "auto");
    themePicker.addEventListener("change", (event) => {
      const chosen = event.target.value;
      if (chosen === "auto") delete root.dataset.theme;
      else root.dataset.theme = chosen;
      try {
        if (chosen === "auto") localStorage.removeItem("theme");
        else localStorage.setItem("theme", chosen);
      } catch {
        // Storage blocked: the choice lasts until the page is reloaded.
      }
    });
    themePicker.hidden = false;

    form.addEventListener("submit", (event) => event.preventDefault());
    form.addEventListener("change", (event) => {
      const target = event.target;
      if (target.name === "view") {
        state.view = target.value;
        update({ push: true });
      } else if (target === fromSelect || target === toSelect) {
        setRange(Number(fromSelect.value), Number(toSelect.value));
      }
    });
    $$("[data-shift]").forEach((button) =>
      button.addEventListener("click", () => setRange(state.from + Number(button.dataset.shift), state.to + Number(button.dataset.shift))),
    );
    let typing = 0;
    input.addEventListener("input", () => {
      clearTimeout(typing);
      typing = setTimeout(() => {
        state.q = input.value.trim();
        state.limit = LIMIT;
        update();
      }, 120);
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && input.value) {
        input.value = "";
        state.q = "";
        update();
      }
    });
    filtersToggle.addEventListener("click", () => {
      const open = !filters.classList.contains("is-open");
      filters.classList.toggle("is-open", open);
      filtersToggle.setAttribute("aria-expanded", String(open));
    });
    kindsBox.addEventListener("change", (event) => {
      state.kind = event.target.value;
      state.limit = LIMIT;
      update({ push: true });
    });
    $("fieldset.signals").addEventListener("change", () => {
      state.signals = new Set($$('input[name="signal"]:checked').map((box) => box.value));
      update({ push: true });
    });
    partSelect.addEventListener("change", () => {
      state.part = partSelect.value;
      update({ push: true });
    });
    editorialBox.addEventListener("change", () => {
      state.editorial = editorialBox.checked;
      update({ push: true });
    });
    onlyBox.addEventListener("change", () => {
      state.only = onlyBox.checked;
      update({ push: true });
    });
    $("[data-more-button]").addEventListener("click", () => {
      state.limit += LIMIT;
      renderChanges();
    });
    $("[data-clear]").addEventListener("click", () => {
      state.q = "";
      state.kind = "all";
      state.signals.clear();
      state.part = "";
      state.only = false;
      update({ push: true });
    });
    rowsBody.addEventListener("click", (event) => {
      const row = event.target.closest("tr[data-id]");
      if (!row || event.target.closest("a.external")) return;
      // a new tab or window for the section, as for any link
      if (event.target.closest("a") && (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)) return;
      event.preventDefault();
      if (state.selected === row.dataset.id && !wide.matches) closePanel();
      else openSection(row.dataset.id);
    });
    for (const th of $$("th[data-sort]")) {
      const button = el("button", { type: "button" }, ...th.childNodes);
      th.replaceChildren(button);
      button.addEventListener("click", () => {
        const key = th.dataset.sort;
        state.reverse = state.sort === key ? !state.reverse : false;
        state.sort = key;
        writeUrl({ push: true });
        syncSort();
        renderChanges();
      });
    }
    mapBox.addEventListener("keydown", mapKeys);
    $("[data-close]").addEventListener("click", closePanel);
    document.addEventListener("keydown", (event) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.target.closest("input, textarea, select, [contenteditable]")) return;
      if (event.key === "/") {
        event.preventDefault();
        input.focus();
        input.select();
      } else if (event.key === "Escape" && state.selected) {
        closePanel();
      } else if ((event.key === "j" || event.key === "k") && state.view === "changes") {
        const rows = $$("tr[data-id]", rowsBody);
        if (!rows.length) return;
        const at = rows.findIndex((row) => row.dataset.id === state.selected);
        const next = rows[Math.max(0, Math.min(rows.length - 1, at < 0 ? 0 : at + (event.key === "j" ? 1 : -1)))];
        event.preventDefault();
        openSection(next.dataset.id, { scroll: false });
        next.scrollIntoView({ block: "nearest" });
      }
    });
    // Back and Forward, and a hash typed or pasted
    const navigated = () => {
      if (location.hash === lastHash) return;
      lastHash = location.hash;
      readUrl();
      update({ url: false });
    };
    window.addEventListener("popstate", navigated);
    window.addEventListener("hashchange", navigated);
    wide.addEventListener("change", () => state.selected && placePanel());
    const measureFinder = () => root.style.setProperty("--finder-h", tableLayout.matches ? `${form.offsetHeight}px` : "0px");
    new ResizeObserver(measureFinder).observe(form);
    tableLayout.addEventListener("change", measureFinder);
  }

  async function start() {
    try {
      index = await fetchJson("index.json");
    } catch (error) {
      count.textContent = `Could not load data/index.json (${error.message}). Serve the folder over HTTP: python3 -m http.server -d dist`;
      return;
    }
    versions = index.versions;
    sections = index.sections;
    for (const section of sections) byId.set(section.id, section);
    for (const part of index.parts) partsByKey.set(part.key, part);
    state.from = versions.length - 2;
    state.to = versions.length - 1;
    readUrl();
    lastHash = location.hash;
    wire();
    await update({ url: false });
    if (state.selected && !wide.matches) panel.scrollIntoView({ block: "start" });
  }

  start();
})();
