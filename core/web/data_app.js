"use strict";
// Explorateur de données Æther : tableur (formules calculées par le module data_lab), graphiques, ajustements,
// balayages, Monte-Carlo, valeur cible, statistiques, tri et filtre. La page garde le contenu brut des cellules ;
// le Hub renvoie les valeurs. Collage depuis Excel ou un CSV (Ctrl+V), recopie avec références relatives (Ctrl+D).
(function () {
  const $ = (id) => document.getElementById(id);
  const COLS = 26, MAX_ROWS = 2000;
  const local = {
    get(key, fallback) { try { const v = localStorage.getItem(`data.${key}`); return v === null ? fallback : JSON.parse(v); } catch (e) { return fallback; } },
    set(key, value) { try { localStorage.setItem(`data.${key}`, JSON.stringify(value)); } catch (e) { /* stockage plein ou indisponible */ } },
  };
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const fmt = (x, d = 6) => (x === null || x === undefined || Number.isNaN(x) ? "—"
    : Math.abs(x) >= 1e6 || (Math.abs(x) < 1e-3 && x !== 0) ? x.toExponential(3).replace(".", ",") : (+x.toPrecision(d)).toString().replace(".", ","));

  // ---------- références ----------
  const colName = (c) => { let s = ""; c += 1; while (c) { const r = (c - 1) % 26; s = String.fromCharCode(65 + r) + s; c = Math.floor((c - 1) / 26); } return s; };
  const colIndex = (s) => [...s.toUpperCase()].reduce((n, ch) => n * 26 + ch.charCodeAt(0) - 64, 0) - 1;
  const refName = (c, r) => `${colName(c)}${r + 1}`;
  function parseRef(text) {
    const m = /^\$?([A-Za-z]{1,2})\$?(\d{1,4})$/.exec(String(text).trim());
    if (!m) return null;
    return { c: colIndex(m[1]), r: Number(m[2]) - 1 };
  }
  function rangeRefs(text) {
    const t = String(text).trim().replace(/\$/g, "");
    if (!t) return [];
    const [a, b] = t.split(":");
    const p = parseRef(a), q = parseRef(b || a);
    if (!p || !q) throw new Error(`plage invalide : ${text}`);
    const out = [];
    for (let r = Math.min(p.r, q.r); r <= Math.max(p.r, q.r); r += 1) for (let c = Math.min(p.c, q.c); c <= Math.max(p.c, q.c); c += 1) out.push(refName(c, r));
    return out;
  }
  // décale les références relatives d'une formule (recopie, collage) ; les $ restent fixes
  const REF_RE = /(?<![A-Za-z0-9_.$])(\$?)([A-Za-z]{1,2})(\$?)(\d{1,4})(?![A-Za-z0-9_(])/g;
  function shiftFormula(text, dc, dr) {
    if (typeof text !== "string" || !text.startsWith("=")) return text;
    return text.split('"').map((part, i) => (i % 2 ? part : part.replace(REF_RE, (all, d1, col, d2, row) => {
      const c = d1 ? colIndex(col) : colIndex(col) + dc, r = d2 ? Number(row) - 1 : Number(row) - 1 + dr;
      if (c < 0 || r < 0) return "#REF!";
      return `${d1}${colName(c)}${d2}${r + 1}`;
    }))).join('"');
  }

  // ---------- état ----------
  const S = {
    cells: {}, values: {}, rows: 200, tds: [], heads: [], rowHeads: [],
    cur: { c: 0, r: 0 }, anchor: { c: 0, r: 0 }, editing: null, undo: [], dirty: false,
    clip: null, gs: null, sweep: null, drag: false,
  };

  // ---------- Hub ----------
  let activated = false, queue = Promise.resolve();
  async function post(path, body) {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(data.detail || `erreur ${r.status}`); e.status = r.status; throw e; }
    return data;
  }
  async function send(command, payload) {
    if (!activated) { await post("/modules/data_lab/activate"); activated = true; }
    let reply;
    try { reply = await post(`/modules/data_lab/command/${command}`, payload); }
    catch (e) {
      if (e instanceof TypeError) throw new Error("Hub injoignable : lance AetherTwin, puis rouvre l'explorateur");
      if (e.status !== 409) throw e;
      await post("/modules/data_lab/activate");
      reply = await post(`/modules/data_lab/command/${command}`, payload);
    }
    if (!reply.ok) throw new Error((reply.error || "erreur du module").replace(/^\w+Error: /, ""));
    return reply.result;
  }
  function call(command, payload = {}) {
    const run = queue.then(() => send(command, payload));
    queue = run.catch(() => {});
    return run;
  }
  function status(text, bad = false) { $("status").textContent = text; $("status").classList.toggle("err", bad); }
  const fail = (box, e) => box.replaceChildren(el("div", "err-box", e.message));

  // ---------- grille ----------
  function buildGrid() {
    const grid = $("grid");
    grid.replaceChildren();
    const head = el("tr");
    head.append(el("th", "rh corner", ""));
    S.heads = [];
    for (let c = 0; c < COLS; c += 1) { const th = el("th", "", colName(c)); S.heads.push(th); head.append(th); }
    const thead = el("thead"); thead.append(head); grid.append(thead);
    const body = el("tbody"); body.id = "grid-body"; grid.append(body);
    S.tds = []; S.rowHeads = [];
    addRows(S.rows);
  }
  function addRows(count) {
    const body = $("grid-body");
    const start = S.tds.length;
    const frag = document.createDocumentFragment();
    for (let r = start; r < Math.min(start + count, MAX_ROWS); r += 1) {
      const tr = el("tr");
      const th = el("th", "rh", r + 1);
      tr.append(th); S.rowHeads.push(th);
      const row = [];
      for (let c = 0; c < COLS; c += 1) { const td = el("td"); td.dataset.c = c; td.dataset.r = r; tr.append(td); row.push(td); }
      S.tds.push(row);
      frag.append(tr);
    }
    body.append(frag);
    S.rows = S.tds.length;
    $("btn-more").hidden = S.rows >= MAX_ROWS;
    paintValues();
  }
  function ensureRows(r) { if (r >= S.rows && r < MAX_ROWS) addRows(Math.min(MAX_ROWS, Math.ceil((r + 1) / 200) * 200) - S.rows); }
  function paintValues() {
    for (let r = 0; r < S.tds.length; r += 1) for (let c = 0; c < COLS; c += 1) {
      const td = S.tds[r][c], ref = refName(c, r), v = S.values[ref];
      const text = v ? v[0] : "";
      if (td.textContent !== text) td.textContent = text;
      const raw = S.cells[ref];
      const cls = (v ? v[1] : "") + (typeof raw === "string" && raw.startsWith("=") ? " f" : "");
      td.className = cls.trim();
      if (v && v[1] === "e") td.title = errorHelp(v[0]); else if (td.title) td.title = "";
    }
    paintSelection();
  }
  function errorHelp(code) {
    return { "#DIV/0!": "division par zéro", "#VALEUR!": "type de valeur incorrect (texte au lieu d'un nombre ?)",
      "#REF!": "référence hors de la feuille", "#NOM?": "fonction inconnue (voir l'onglet Formules)", "#CYCLE!": "référence circulaire",
      "#NUM!": "résultat non numérique ou pas de solution", "#FORMULE!": "formule mal écrite", "#N/A": "plages de tailles différentes" }[code] || "";
  }
  function selRect() {
    return { c1: Math.min(S.anchor.c, S.cur.c), c2: Math.max(S.anchor.c, S.cur.c), r1: Math.min(S.anchor.r, S.cur.r), r2: Math.max(S.anchor.r, S.cur.r) };
  }
  const selText = () => { const s = selRect(); return s.c1 === s.c2 && s.r1 === s.r2 ? refName(s.c1, s.r1) : `${refName(s.c1, s.r1)}:${refName(s.c2, s.r2)}`; };
  let lastSel = [];
  function paintSelection() {
    for (const td of lastSel) td.classList.remove("sel", "cur");
    for (const th of S.heads.concat(S.rowHeads)) th.classList.remove("on");
    lastSel = [];
    const s = selRect();
    for (let r = s.r1; r <= Math.min(s.r2, S.rows - 1); r += 1) {
      S.rowHeads[r].classList.add("on");
      for (let c = s.c1; c <= s.c2; c += 1) { const td = S.tds[r][c]; td.classList.add("sel"); lastSel.push(td); }
    }
    for (let c = s.c1; c <= s.c2; c += 1) S.heads[c].classList.add("on");
    const cur = S.tds[S.cur.r] && S.tds[S.cur.r][S.cur.c];
    if (cur) { cur.classList.add("cur"); lastSel.push(cur); }
    $("cell-name").value = selText();
    if (S.editing !== "fx") $("fx").value = S.cells[refName(S.cur.c, S.cur.r)] ?? "";
  }
  function select(c, r, extend = false) {
    c = Math.max(0, Math.min(COLS - 1, c)); r = Math.max(0, Math.min(MAX_ROWS - 1, r));
    ensureRows(r);
    S.cur = { c, r };
    if (!extend) S.anchor = { c, r };
    paintSelection();
    S.tds[r][c].scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  // ---------- modifications ----------
  function setCells(changes, label = "") {
    const before = {};
    for (const [ref, raw] of Object.entries(changes)) {
      before[ref] = S.cells[ref] ?? "";
      const text = raw === null || raw === undefined ? "" : String(raw);
      if (text === "") delete S.cells[ref]; else S.cells[ref] = text;
      const p = parseRef(ref); if (p) ensureRows(p.r);
    }
    S.undo.push(before);
    if (S.undo.length > 200) S.undo.shift();
    S.dirty = true;
    saveDraft();
    recalc();
    if (label) status(label);
  }
  function undo() {
    const last = S.undo.pop();
    if (!last) return;
    for (const [ref, raw] of Object.entries(last)) { if (raw === "") delete S.cells[ref]; else S.cells[ref] = raw; }
    saveDraft(); recalc(); status("Annulé.");
  }
  let recalcTimer = 0, recalcSeq = 0;
  function recalc() {
    clearTimeout(recalcTimer);
    recalcTimer = setTimeout(async () => {
      const seq = ++recalcSeq;
      try {
        const r = await call("recalc", { cells: S.cells });
        if (seq !== recalcSeq) return;
        S.values = r.values;
        paintValues();
        const errs = Object.values(S.values).filter((v) => v[1] === "e").length;
        if (errs) status(`${errs} cellule(s) en erreur — survole-les pour l'explication.`, false);
      } catch (e) { status(e.message, true); }
    }, 60);
  }
  let draftTimer = 0;
  function saveDraft() {
    clearTimeout(draftTimer);
    draftTimer = setTimeout(() => local.set("draft", { name: $("book-name").value, cells: S.cells }), 400);
  }
  function numAt(ref) { const v = S.values[ref]; return v && v[1] === "n" ? Number(v[0]) : null; }

  // ---------- édition ----------
  function startEdit(text, mode = "cell") {
    const td = S.tds[S.cur.r][S.cur.c];
    const ed = $("editor");
    S.editing = mode;
    if (mode === "cell") {
      ed.hidden = false;
      ed.style.left = `${td.offsetLeft}px`; ed.style.top = `${td.offsetTop}px`;
      ed.style.minWidth = `${td.offsetWidth}px`; ed.style.height = `${td.offsetHeight}px`;
      ed.value = text;
      ed.focus();
      ed.setSelectionRange(ed.value.length, ed.value.length);
    }
  }
  function commitEdit(move) {
    const ref = refName(S.cur.c, S.cur.r);
    const text = S.editing === "fx" ? $("fx").value : $("editor").value;
    const mode = S.editing;
    S.editing = null;
    $("editor").hidden = true;
    if ((S.cells[ref] ?? "") !== text) setCells({ [ref]: text });
    if (move === "down") select(S.cur.c, S.cur.r + 1);
    else if (move === "right") select(S.cur.c + 1, S.cur.r);
    else paintSelection();
    if (mode) $("grid-wrap").focus();
  }
  function cancelEdit() { S.editing = null; $("editor").hidden = true; paintSelection(); $("grid-wrap").focus(); }
  const formulaInProgress = () => {
    const box = S.editing === "fx" ? $("fx") : S.editing === "cell" ? $("editor") : null;
    return box && box.value.startsWith("=") && /[=(;,:+\-*/^&<>]$/.test(box.value.slice(0, box.selectionStart).trimEnd()) ? box : null;
  };
  $("editor").addEventListener("keydown", (e) => {
    e.stopPropagation();   // l'éditeur est dans la grille : sans ça, Entrée rouvrirait aussitôt la cellule suivante
    if (e.key === "Enter") { e.preventDefault(); commitEdit("down"); }
    else if (e.key === "Tab") { e.preventDefault(); commitEdit("right"); }
    else if (e.key === "Escape") { e.preventDefault(); cancelEdit(); }
  });
  $("editor").addEventListener("blur", () => { if (S.editing === "cell" && !S.pickingRef) commitEdit(); });
  $("fx").addEventListener("focus", () => { S.editing = "fx"; });
  $("fx").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); commitEdit("down"); }
    else if (e.key === "Escape") { e.preventDefault(); cancelEdit(); }
  });
  $("fx").addEventListener("blur", () => { if (S.editing === "fx" && !S.pickingRef) commitEdit(); });
  $("cell-name").addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const [a, b] = $("cell-name").value.split(":");
    const p = parseRef(a), q = parseRef(b || a);
    if (!p || !q) { status("Référence invalide.", true); return; }
    select(q.c, q.r); S.anchor = p; paintSelection(); $("grid-wrap").focus();
  });

  // souris : sélection, glisser, clic sur une cellule pendant une formule = insérer sa référence
  $("grid").addEventListener("mousedown", (e) => {
    const td = e.target.closest("td");
    if (!td) return;
    const c = Number(td.dataset.c), r = Number(td.dataset.r);
    const box = formulaInProgress();
    if (box) {
      e.preventDefault();
      S.pickingRef = true;
      const pos = box.selectionStart;
      box.value = box.value.slice(0, pos) + refName(c, r) + box.value.slice(box.selectionEnd);
      box.focus(); box.setSelectionRange(pos + refName(c, r).length, pos + refName(c, r).length);
      S.pickingRef = false;
      return;
    }
    if (S.editing) commitEdit();
    select(c, r, e.shiftKey);
    S.drag = true;
    $("grid-wrap").focus();
    e.preventDefault();
  });
  $("grid").addEventListener("mouseover", (e) => {
    if (!S.drag) return;
    const td = e.target.closest("td");
    if (td) { S.cur = { c: Number(td.dataset.c), r: Number(td.dataset.r) }; paintSelection(); }
  });
  window.addEventListener("mouseup", () => { S.drag = false; });
  $("grid").addEventListener("dblclick", (e) => { if (e.target.closest("td")) startEdit(S.cells[refName(S.cur.c, S.cur.r)] ?? ""); });
  $("grid").addEventListener("click", (e) => {
    const th = e.target.closest("th");
    if (!th || th.classList.contains("corner")) return;
    if (th.classList.contains("rh")) { const r = Number(th.textContent) - 1; S.anchor = { c: 0, r }; S.cur = { c: COLS - 1, r }; }
    else { const c = colIndex(th.textContent); S.anchor = { c, r: 0 }; S.cur = { c, r: S.rows - 1 }; }
    paintSelection();
  });

  $("grid-wrap").addEventListener("keydown", (e) => {
    if (S.editing) return;
    const k = e.key, ctrl = e.ctrlKey || e.metaKey;
    const moves = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0] };
    if (moves[k]) { e.preventDefault(); select(S.cur.c + moves[k][0], S.cur.r + moves[k][1], e.shiftKey); return; }
    if (k === "Enter" || k === "F2") { e.preventDefault(); startEdit(S.cells[refName(S.cur.c, S.cur.r)] ?? ""); return; }
    if (k === "Tab") { e.preventDefault(); select(S.cur.c + (e.shiftKey ? -1 : 1), S.cur.r); return; }
    if (k === "Delete" || k === "Backspace") { e.preventDefault(); clearSelection(); return; }
    if (ctrl && k.toLowerCase() === "z") { e.preventDefault(); undo(); return; }
    if (ctrl && k.toLowerCase() === "d") { e.preventDefault(); fill("down"); return; }
    if (ctrl && k.toLowerCase() === "r") { e.preventDefault(); fill("right"); return; }
    if (ctrl && k.toLowerCase() === "s") { e.preventDefault(); save(); return; }
    if (ctrl && k.toLowerCase() === "a") { e.preventDefault(); S.anchor = { c: 0, r: 0 }; S.cur = { c: COLS - 1, r: S.rows - 1 }; paintSelection(); return; }
    if (!ctrl && !e.altKey && k.length === 1) { e.preventDefault(); startEdit(k); }
  });
  document.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(); } });

  function clearSelection() {
    const s = selRect(), ch = {};
    for (let r = s.r1; r <= s.r2; r += 1) for (let c = s.c1; c <= s.c2; c += 1) if (S.cells[refName(c, r)] !== undefined) ch[refName(c, r)] = "";
    if (Object.keys(ch).length) setCells(ch, `${Object.keys(ch).length} cellule(s) effacée(s).`);
  }
  function fill(dir) {
    const s = selRect(), ch = {};
    if (dir === "down") {
      if (s.r2 === s.r1) { status("Sélectionne la cellule modèle et les cellules en dessous, puis Ctrl+D."); return; }
      for (let c = s.c1; c <= s.c2; c += 1) { const src = S.cells[refName(c, s.r1)] ?? ""; for (let r = s.r1 + 1; r <= s.r2; r += 1) ch[refName(c, r)] = shiftFormula(src, 0, r - s.r1); }
    } else {
      if (s.c2 === s.c1) { status("Sélectionne la cellule modèle et les cellules à droite, puis Ctrl+R."); return; }
      for (let r = s.r1; r <= s.r2; r += 1) { const src = S.cells[refName(s.c1, r)] ?? ""; for (let c = s.c1 + 1; c <= s.c2; c += 1) ch[refName(c, r)] = shiftFormula(src, c - s.c1, 0); }
    }
    setCells(ch, `Recopie : ${Object.keys(ch).length} cellule(s).`);
  }
  $("btn-fill-down").addEventListener("click", () => fill("down"));
  $("btn-fill-right").addEventListener("click", () => fill("right"));
  $("btn-values").addEventListener("click", () => {
    const s = selRect(), ch = {};
    for (let r = s.r1; r <= s.r2; r += 1) for (let c = s.c1; c <= s.c2; c += 1) {
      const ref = refName(c, r), raw = S.cells[ref];
      if (typeof raw === "string" && raw.startsWith("=") && S.values[ref]) ch[ref] = S.values[ref][0];
    }
    if (Object.keys(ch).length) setCells(ch, `${Object.keys(ch).length} formule(s) remplacée(s) par leur valeur.`);
  });

  // presse-papiers : TSV (Excel, LibreOffice, un CSV ouvert…) ; entre deux cellules d'ici, les formules suivent
  document.addEventListener("copy", (e) => {
    if (S.editing || document.activeElement !== $("grid-wrap")) return;
    const s = selRect(), lines = [];
    for (let r = s.r1; r <= s.r2; r += 1) {
      const row = [];
      for (let c = s.c1; c <= s.c2; c += 1) row.push(S.values[refName(c, r)] ? S.values[refName(c, r)][0] : "");
      lines.push(row.join("\t"));
    }
    const text = lines.join("\r\n");
    S.clip = { text, origin: { c: s.c1, r: s.r1 }, raw: [] };
    for (let r = s.r1; r <= s.r2; r += 1) { const row = []; for (let c = s.c1; c <= s.c2; c += 1) row.push(S.cells[refName(c, r)] ?? ""); S.clip.raw.push(row); }
    e.clipboardData.setData("text/plain", text);
    e.preventDefault();
    status(`${(s.r2 - s.r1 + 1) * (s.c2 - s.c1 + 1)} cellule(s) copiée(s).`);
  });
  document.addEventListener("cut", (e) => {
    if (S.editing || document.activeElement !== $("grid-wrap")) return;
    document.dispatchEvent(new ClipboardEvent("copy", { clipboardData: e.clipboardData }));
    e.preventDefault();
    clearSelection();
  });
  document.addEventListener("paste", (e) => {
    if (S.editing || document.activeElement !== $("grid-wrap")) return;
    const text = e.clipboardData.getData("text/plain");
    if (!text) return;
    e.preventDefault();
    const ch = {};
    if (S.clip && S.clip.text === text) {
      const dc = S.cur.c - S.clip.origin.c, dr = S.cur.r - S.clip.origin.r;
      S.clip.raw.forEach((row, i) => row.forEach((raw, j) => { if (S.cur.c + j < COLS) ch[refName(S.cur.c + j, S.cur.r + i)] = shiftFormula(raw, dc, dr); }));
    } else {
      const rows = text.replace(/\r\n?/g, "\n").replace(/\n$/, "").split("\n").map((l) => l.split("\t"));
      rows.forEach((row, i) => row.forEach((v, j) => { if (S.cur.c + j < COLS && S.cur.r + i < MAX_ROWS) ch[refName(S.cur.c + j, S.cur.r + i)] = v; }));
    }
    setCells(ch, `${Object.keys(ch).length} cellule(s) collée(s).`);
  });
  $("btn-more").addEventListener("click", () => addRows(200));

  // ---------- fichiers ----------
  async function refreshList() {
    try {
      const books = await call("list");
      const sel = $("book-list");
      sel.replaceChildren(el("option", "", "Ouvrir…")); sel.firstChild.value = "";
      for (const b of books) { const o = el("option", "", `${b.name} (${b.cells} cellules, ${b.modified})`); o.value = b.name; sel.append(o); }
    } catch (e) { status(e.message, true); }
  }
  async function save() {
    try {
      const r = await call("save", { name: $("book-name").value.trim(), cells: S.cells });
      S.dirty = false;
      status(`Enregistré : ${r.name} (${r.cells} cellules).`);
      refreshList();
    } catch (e) { status(e.message, true); }
  }
  function loadCells(cells, name) {
    S.cells = { ...cells }; S.undo = []; S.values = {};
    if (name) $("book-name").value = name;
    let maxR = 0;
    for (const ref of Object.keys(S.cells)) { const p = parseRef(ref); if (p) maxR = Math.max(maxR, p.r); }
    ensureRows(maxR + 20);
    clearFilter();
    saveDraft(); recalc(); select(0, 0);
  }
  $("btn-save").addEventListener("click", save);
  $("book-list").addEventListener("change", async () => {
    const name = $("book-list").value;
    if (!name) return;
    if (S.dirty && !confirm("Des modifications ne sont pas enregistrées. Ouvrir quand même ?")) { $("book-list").value = ""; return; }
    try { const b = await call("load", { name }); loadCells(b.cells, b.name); S.dirty = false; status(`Ouvert : ${b.name}.`); }
    catch (e) { status(e.message, true); }
    $("book-list").value = "";
  });
  $("btn-new").addEventListener("click", () => {
    if (S.dirty && !confirm("Des modifications ne sont pas enregistrées. Nouveau classeur quand même ?")) return;
    loadCells({}, "classeur"); S.dirty = false; status("Nouveau classeur.");
  });
  $("file-in").addEventListener("change", async () => {
    const file = $("file-in").files[0];
    $("file-in").value = "";
    if (!file) return;
    try {
      const buf = new Uint8Array(await file.arrayBuffer());
      let bin = "";
      for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
      const r = await call("import", { filename: file.name, data: btoa(bin) });
      loadCells(r.cells, file.name.replace(/\.[^.]+$/, "").replace(/[^\w .-]/g, "_").slice(0, 60));
      S.dirty = true;
      status(`Importé : ${file.name} (${Object.keys(r.cells).length} cellules). Pense à enregistrer.`);
    } catch (e) { status(e.message, true); }
  });
  $("btn-export").addEventListener("click", async () => {
    try {
      const r = await call("export_csv", { cells: S.cells });
      const a = el("a");
      a.href = URL.createObjectURL(new Blob(["﻿" + r.csv], { type: "text/csv" }));
      a.download = `${$("book-name").value || "classeur"}.csv`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    } catch (e) { status(e.message, true); }
  });

  // ---------- graphiques ----------
  const PALETTE = ["#2ec4d6", "#f2a541", "#b07cff", "#5ad17a", "#ff6b8b", "#8fb4ff"];
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  function ticks(lo, hi, n = 6) {
    if (lo === hi) { lo -= 1; hi += 1; }
    const step0 = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(step0));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0) || 10 * mag;
    const out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toPrecision(12));
    return out;
  }
  function plot(spec) {
    const cv = $("plot"), w = cv.clientWidth, h = cv.clientHeight, dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    const g = cv.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const all = [...(spec.series || []).flatMap((s) => s.pts), ...(spec.curves || []).flatMap((s) => s.pts),
      ...(spec.bars || []).flatMap((b) => [[b.x0, 0], [b.x1, b.y]])].filter((p) => p[1] !== null && Number.isFinite(p[1]));
    if (!all.length) { g.fillStyle = css("--muted"); g.font = "12px Segoe UI"; g.fillText(spec.empty || "Rien à tracer.", 14, 24); return; }
    let [x0, x1] = [Math.min(...all.map((p) => p[0])), Math.max(...all.map((p) => p[0]))];
    let [y0, y1] = [Math.min(...all.map((p) => p[1])), Math.max(...all.map((p) => p[1]))];
    if (spec.bars || (spec.series || []).some((s) => s.type === "bar")) y0 = Math.min(0, y0);
    const padY = (y1 - y0) * 0.06 || 1; y0 -= padY; y1 += padY;
    if (x0 === x1) { x0 -= 1; x1 += 1; }
    const L = 52, R = 10, T = 14, B = 28;
    const X = (v) => L + (v - x0) / (x1 - x0) * (w - L - R), Y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (h - T - B);
    g.font = "10.5px Segoe UI, sans-serif"; g.lineWidth = 1;
    for (const t of ticks(y0, y1)) { g.strokeStyle = css("--line"); g.beginPath(); g.moveTo(L, Y(t)); g.lineTo(w - R, Y(t)); g.stroke(); g.fillStyle = css("--muted"); g.fillText(fmt(t, 4), 4, Y(t) + 3); }
    for (const t of ticks(x0, x1, 7)) { g.strokeStyle = css("--line"); g.beginPath(); g.moveTo(X(t), T); g.lineTo(X(t), h - B); g.stroke(); g.fillStyle = css("--muted"); g.fillText(fmt(t, 4), X(t) - 8, h - B + 14); }
    if (spec.bars) {   // histogramme : [{x0, x1, y}]
      g.fillStyle = PALETTE[0] + "cc";
      for (const b of spec.bars) g.fillRect(X(b.x0) + 1, Y(b.y), Math.max(1, X(b.x1) - X(b.x0) - 2), Y(y0 < 0 ? 0 : y0) - Y(b.y));
    }
    (spec.series || []).forEach((s, i) => {
      const color = s.color || PALETTE[i % PALETTE.length];
      g.strokeStyle = color; g.fillStyle = color; g.lineWidth = 2;
      const pts = s.pts.filter((p) => p[1] !== null && Number.isFinite(p[1]));
      if (s.type === "line") { g.beginPath(); pts.forEach(([x, y], k) => (k ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y)))); g.stroke(); }
      else if (s.type === "bar") {
        const n = spec.series.length, bw = Math.max(2, (w - L - R) / Math.max(1, pts.length) / (n + 0.6));
        pts.forEach(([x, y]) => g.fillRect(X(x) - (n * bw) / 2 + i * bw, Math.min(Y(y), Y(0)), bw - 1, Math.abs(Y(y) - Y(0))));
      } else pts.forEach(([x, y]) => { g.beginPath(); g.arc(X(x), Y(y), 3, 0, Math.PI * 2); g.fill(); });
    });
    (spec.curves || []).forEach((s) => {
      g.strokeStyle = s.color || css("--second"); g.lineWidth = 2; g.setLineDash(s.dash || []);
      g.beginPath(); s.pts.filter((p) => p[1] !== null).forEach(([x, y], k) => (k ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y)))); g.stroke(); g.setLineDash([]);
    });
    (spec.vlines || []).forEach((v) => { g.strokeStyle = v.color || css("--second"); g.setLineDash([4, 4]); g.beginPath(); g.moveTo(X(v.x), T); g.lineTo(X(v.x), h - B); g.stroke(); g.setLineDash([]); });
    const names = (spec.series || []).map((s, i) => [s.name, s.color || PALETTE[i % PALETTE.length]]).concat((spec.curves || []).filter((c) => c.name).map((c) => [c.name, c.color || css("--second")]));
    let lx = L + 8;
    for (const [name, color] of names) { if (!name) continue; g.fillStyle = color; g.fillRect(lx, T + 2, 10, 3); g.fillStyle = css("--ink"); g.fillText(name, lx + 14, T + 7); lx += g.measureText(name).width + 30; }
  }
  let lastPlot = { empty: "Choisis des données à tracer (onglet Graphique)." };
  function show(spec) { lastPlot = spec; plot(spec); }
  window.addEventListener("resize", () => plot(lastPlot));

  function fromSelection() {   // première colonne = X, autres = Y ; titres reconnus
    const s = selRect();
    if (s.c2 === s.c1) return { x: "", y: [selText()], names: [] };
    let r1 = s.r1;
    const names = [];
    const headerRow = [];
    for (let c = s.c1; c <= s.c2; c += 1) headerRow.push(S.values[refName(c, s.r1)]);
    if (headerRow.some((v) => v && v[1] === "t")) { r1 += 1; for (let c = s.c1 + 1; c <= s.c2; c += 1) names.push(S.values[refName(c, s.r1)]?.[0] || colName(c)); }
    const range = (c) => `${refName(c, r1)}:${refName(c, s.r2)}`;
    const y = [];
    for (let c = s.c1 + 1; c <= s.c2; c += 1) y.push(range(c));
    return { x: range(s.c1), y, names };
  }
  let chartNames = [];
  $("ch-from-sel").addEventListener("click", () => { const f = fromSelection(); $("ch-x").value = f.x; $("ch-y").value = f.y.join(" ; "); chartNames = f.names; drawChart(); });
  $("ch-draw").addEventListener("click", () => { chartNames = []; drawChart(); });
  $("ch-type").addEventListener("change", drawChart);
  function drawChart() {
    try {
      const ys = $("ch-y").value.split(/[;,]/).map((t) => t.trim()).filter(Boolean);
      if (!ys.length) { show({ empty: "Indique au moins une plage Y." }); return; }
      const xr = $("ch-x").value.trim() ? rangeRefs($("ch-x").value) : null;
      const type = $("ch-type").value;
      show({ series: ys.map((yr, i) => {
        const refs = rangeRefs(yr);
        return { name: chartNames[i] || yr, type, pts: refs.map((ref, k) => [xr ? numAt(xr[k]) : k + 1, numAt(ref)]).filter((p) => p[0] !== null) };
      }) });
      local.set("chart", { x: $("ch-x").value, y: $("ch-y").value, type });
    } catch (e) { status(e.message, true); }
  }

  // ---------- ajustement ----------
  let lastFit = null;
  $("fit-from-sel").addEventListener("click", () => { const f = fromSelection(); $("fit-x").value = f.x; $("fit-y").value = f.y[0] || ""; });
  $("fit-model").addEventListener("change", () => { $("fit-deg").disabled = $("fit-model").value !== "polynome"; });
  $("fit-go").addEventListener("click", async () => {
    try {
      lastFit = await call("fit", { cells: S.cells, x_range: $("fit-x").value, y_range: $("fit-y").value, model: $("fit-model").value, degree: Number($("fit-deg").value) });
      show({ series: [{ name: "mesures", pts: lastFit.points }], curves: [{ name: "modèle", pts: lastFit.curve }] });
      const t = el("table", "t");
      for (const [k, v] of Object.entries(lastFit.coefficients)) { const tr = el("tr"); tr.append(el("td", "", k), el("td", "", fmt(v, 8))); t.append(tr); }
      $("fit-out").replaceChildren(el("div", "result", lastFit.equation), el("div", "", `R² = ${fmt(lastFit.r2, 6)} · écart quadratique moyen ${fmt(lastFit.rmse, 4)}`), t);
      $("fit-insert").hidden = false;
      const x = rangeRefs($("fit-x").value)[0];
      if (x) { $("fit-xcell").value = x; const p = parseRef(x); $("fit-cell").value = refName(Math.min(COLS - 1, selRect().c2 + 1), p.r); }
    } catch (e) { fail($("fit-out"), e); $("fit-insert").hidden = true; }
  });
  $("fit-put").addEventListener("click", () => {
    if (!lastFit) return;
    const xref = $("fit-xcell").value.trim().toUpperCase(), cell = $("fit-cell").value.trim().toUpperCase();
    if (!parseRef(xref) || !parseRef(cell)) { status("Références invalides.", true); return; }
    setCells({ [cell]: lastFit.formula.replaceAll("{x}", xref) }, `Modèle écrit en ${cell} — recopie-le vers le bas (Ctrl+D).`);
  });

  // ---------- simulations ----------
  const outList = (text) => text.split(/[;,\s]+/).map((t) => t.trim().toUpperCase()).filter(Boolean);
  $("sw-go").addEventListener("click", async () => {
    try {
      const r = await call("sweep", { cells: S.cells, input: $("sw-in").value, start: Number($("sw-a").value), stop: Number($("sw-b").value), steps: Number($("sw-n").value), outputs: outList($("sw-out").value) });
      S.sweep = r;
      show({ series: Object.entries(r.series).map(([name, ys]) => ({ name, type: "line", pts: r.x.map((x, i) => [x, ys[i]]) })) });
      const t = el("table", "t"), head = el("tr");
      head.append(el("th", "", r.input), ...Object.keys(r.series).map((k) => el("th", "", k)));
      t.append(head);
      const step = Math.max(1, Math.floor(r.x.length / 12));
      for (let i = 0; i < r.x.length; i += step) { const tr = el("tr"); tr.append(el("td", "", fmt(r.x[i])), ...Object.values(r.series).map((ys) => el("td", "", fmt(ys[i])))); t.append(tr); }
      $("sim-out").replaceChildren(el("div", "result", `Balayage de ${r.input} : ${r.x.length} valeurs`), t);
      $("sw-copy").disabled = false;
    } catch (e) { fail($("sim-out"), e); }
  });
  $("sw-copy").addEventListener("click", () => {
    const p = parseRef($("sw-dest").value || "");
    if (!S.sweep || !p) { status("Indique la cellule de départ (ex. E1).", true); return; }
    const cols = [[S.sweep.input, S.sweep.x], ...Object.entries(S.sweep.series)];
    const ch = {};
    cols.forEach(([name, vals], j) => { ch[refName(p.c + j, p.r)] = name; vals.forEach((v, i) => { ch[refName(p.c + j, p.r + 1 + i)] = v === null ? "" : String(v); }); });
    setCells(ch, "Tableau du balayage copié.");
  });
  const LAWS = [["normale", "normale (moyenne a, écart type b)"], ["uniforme", "uniforme (entre a et b)"], ["triangulaire", "triangulaire (a, b, mode c)"], ["lognormale", "lognormale (μ a, σ b du log)"], ["exponentielle", "exponentielle (moyenne a)"]];
  function addMcRow(spec = {}) {
    const row = el("div", "mc-row");
    const cell = el("input", "field"); cell.placeholder = "B2"; cell.value = spec.cell || "";
    const law = el("select");
    for (const [v, t] of LAWS) { const o = el("option", "", t); o.value = v; law.append(o); }
    law.value = spec.law || "normale";
    const [a, b, c] = ["a", "b", "c"].map((k) => { const i = el("input", "field"); i.type = "number"; i.step = "any"; i.placeholder = k; i.value = spec[k] ?? ""; return i; });
    const del = el("button", "", "×"); del.type = "button"; del.title = "Retirer"; del.addEventListener("click", () => row.remove());
    row.append(cell, law, a, b, c, del);
    $("mc-inputs").append(row);
  }
  $("mc-add").addEventListener("click", () => addMcRow());
  $("mc-go").addEventListener("click", async () => {
    const inputs = {};
    for (const row of $("mc-inputs").querySelectorAll(".mc-row")) {
      const [cell, law, a, b, c] = row.querySelectorAll("input, select");
      if (cell.value.trim()) inputs[cell.value.trim().toUpperCase()] = { law: law.value, a: Number(a.value), b: Number(b.value), c: Number(c.value) };
    }
    const out = outList($("mc-out").value);
    $("sim-out").replaceChildren(el("div", "muted", "Simulation en cours…"));
    try {
      const r = await call("montecarlo", { cells: S.cells, inputs, outputs: out, runs: Number($("mc-n").value), threshold: $("mc-t").value === "" ? null : Number($("mc-t").value) });
      const o = r.outputs[out[0]];
      if (!o || !o.n) throw new Error("aucun résultat numérique : vérifie la cellule de sortie");
      const hst = o.histogram;
      show({ bars: hst.counts.map((y, i) => ({ x0: hst.edges[i], x1: hst.edges[i + 1], y })), series: [],
        vlines: [{ x: o.p5 }, { x: o.p95 }, { x: o.mean, color: css("--accent") }] });
      const t = el("table", "t");
      for (const [k, v] of [["moyenne", o.mean], ["écart type", o.std], ["minimum", o.min], ["5e centile", o.p5], ["médiane", o.median], ["95e centile", o.p95], ["maximum", o.max]]) {
        const tr = el("tr"); tr.append(el("td", "", k), el("td", "", fmt(v, 7))); t.append(tr);
      }
      const lines = [el("div", "result", `${out[0]} : ${fmt(o.mean, 6)} ± ${fmt(o.std, 4)} (${r.runs} tirages)`), t,
        el("div", "muted small", `Intervalle à 90 % : ${fmt(o.p5, 5)} → ${fmt(o.p95, 5)} (pointillés).${r.errors ? ` ${r.errors} tirage(s) en erreur ignoré(s).` : ""}`)];
      if (r.above) lines.splice(1, 0, el("div", "", `P(${out[0]} > ${$("mc-t").value}) ≈ ${fmt(100 * r.above[out[0]], 4)} %`));
      $("sim-out").replaceChildren(...lines);
    } catch (e) { fail($("sim-out"), e); }
  });

  // ---------- valeur cible ----------
  $("gs-go").addEventListener("click", async () => {
    try {
      S.gs = await call("goal_seek", { cells: S.cells, target: $("gs-target").value, value: Number($("gs-value").value), input: $("gs-input").value });
      $("gs-out").replaceChildren(el("div", "result", `${S.gs.input} = ${S.gs.display}`), el("div", "muted", `${S.gs.target} vaut alors ${fmt(S.gs.reached, 10)}`));
      $("gs-apply").disabled = false;
    } catch (e) { fail($("gs-out"), e); $("gs-apply").disabled = true; }
  });
  $("gs-apply").addEventListener("click", () => { if (S.gs) setCells({ [S.gs.input]: String(S.gs.value) }, `${S.gs.input} mis à ${S.gs.display}.`); });

  // ---------- statistiques ----------
  $("st-from-sel").addEventListener("click", () => { $("st-range").value = selText(); });
  $("st-go").addEventListener("click", async () => {
    try {
      const o = await call("describe", { cells: S.cells, range: $("st-range").value });
      if (!o.n) throw new Error("aucun nombre dans cette plage");
      const hst = o.histogram;
      show({ bars: hst.counts.map((y, i) => ({ x0: hst.edges[i], x1: hst.edges[i + 1], y })), series: [], vlines: [{ x: o.mean, color: css("--accent") }] });
      const t = el("table", "t");
      for (const [k, v] of [["effectif", o.n], ["moyenne", o.mean], ["écart type (échantillon)", o.std], ["variance", o.variance], ["minimum", o.min], ["1er quartile", o.q1], ["médiane", o.median], ["3e quartile", o.q3], ["maximum", o.max], ["textes ou vides", o.text_or_empty]]) {
        const tr = el("tr"); tr.append(el("td", "", k), el("td", "", fmt(v, 7))); t.append(tr);
      }
      $("st-out").replaceChildren(t);
    } catch (e) { fail($("st-out"), e); }
  });

  // ---------- trier, filtrer ----------
  $("so-from-sel").addEventListener("click", () => { $("so-range").value = selText(); $("so-col").value = colName(S.cur.c); });
  async function sortBy(desc) {
    try {
      const r = await call("sort", { cells: S.cells, range: $("so-range").value, column: $("so-col").value.trim(), descending: desc, header: $("so-head").checked });
      setCells(r.cells, "Plage triée (Ctrl+Z pour annuler).");
    } catch (e) { status(e.message, true); }
  }
  $("so-asc").addEventListener("click", () => sortBy(false));
  $("so-desc").addEventListener("click", () => sortBy(true));
  function clearFilter() { for (const tr of document.querySelectorAll("#grid-body tr.hidden-row")) tr.classList.remove("hidden-row"); $("fi-state").textContent = ""; }
  $("fi-clear").addEventListener("click", clearFilter);
  $("fi-go").addEventListener("click", () => {
    clearFilter();
    const c = colIndex($("fi-col").value.trim() || "A");
    const cond = $("fi-cond").value.trim();
    const m = /^(contient:|<=|>=|<>|<|>|=)?(.*)$/i.exec(cond);
    const op = (m[1] || "=").toLowerCase(), target = m[2].trim(), tn = Number(target.replace(",", "."));
    const test = (v) => {
      if (!v) return false;
      if (op === "contient:") return v[0].toLowerCase().includes(target.toLowerCase());
      if (v[1] === "n" && target !== "" && !Number.isNaN(tn)) {
        const x = Number(v[0]);
        return { "=": x === tn, "<>": x !== tn, "<": x < tn, ">": x > tn, "<=": x <= tn, ">=": x >= tn }[op];
      }
      const a = v[0].toLowerCase(), b = target.toLowerCase();
      return op === "<>" ? a !== b : op === "=" ? a === b : false;
    };
    let shown = 0, hidden = 0;
    const rows = document.querySelectorAll("#grid-body tr");
    let last = 0;
    for (const ref of Object.keys(S.cells)) { const p = parseRef(ref); if (p) last = Math.max(last, p.r); }
    rows.forEach((tr, r) => {
      if (r === 0 || r > last) return;   // la ligne 1 (titres) reste visible
      if (test(S.values[refName(c, r)])) shown += 1; else { tr.classList.add("hidden-row"); hidden += 1; }
    });
    $("fi-state").textContent = `${shown} ligne(s) affichée(s), ${hidden} masquée(s). Les formules continuent de voir toutes les lignes.`;
  });

  // ---------- onglets, thème ----------
  function setTab(tab) {
    for (const b of $("tabs").querySelectorAll("button")) b.setAttribute("aria-selected", String(b.dataset.tab === tab));
    for (const p of document.querySelectorAll(".pane")) p.hidden = p.dataset.pane !== tab;
    local.set("tab", tab);
  }
  $("tabs").addEventListener("click", (e) => { const b = e.target.closest("button[data-tab]"); if (b) setTab(b.dataset.tab); });
  document.documentElement.dataset.theme = local.get("theme", "dark");
  $("btn-theme").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next; local.set("theme", next); plot(lastPlot);
  });

  // ---------- exemples ----------
  const EXAMPLES = {
    "Chute libre (mesures et ajustement)": () => {
      const c = { A1: "t (s)", B1: "h mesurée (m)", C1: "h modèle (m)", E1: "g (m/s²)", F1: "9,81", E2: "h0 (m)", F2: "20",
        E4: "Essaie : Ajustement, X = A2:A12, Y = B2:B12, polynôme de degré 2 ; puis Valeur cible sur F1." };
      const noise = [0.02, -0.03, 0.01, 0.04, -0.02, 0.0, 0.03, -0.04, 0.02, -0.01, 0.01];
      for (let i = 0; i <= 10; i += 1) {
        const t = i / 5;
        c[`A${i + 2}`] = String(t).replace(".", ",");
        c[`B${i + 2}`] = (20 - 4.905 * t * t + noise[i]).toFixed(3).replace(".", ",");
        c[`C${i + 2}`] = `=$F$2-0.5*$F$1*A${i + 2}^2`;
      }
      c.A14 = "Écart moyen"; c.C14 = "=MOYENNE(C2:C12)-MOYENNE(B2:B12)";
      return c;
    },
    "Prêt immobilier (Monte-Carlo, valeur cible)": () => ({
      A1: "Capital emprunté", B1: "200000", A2: "Taux annuel", B2: "3,5%", A3: "Durée (années)", B3: "25",
      A5: "Mensualité", B5: "=B1*(B2/12)/(1-(1+B2/12)^(-B3*12))", A6: "Coût total du crédit", B6: "=B5*B3*12-B1",
      A8: "Monte-Carlo : entrée B2 en loi normale a = 0.035, b = 0.005 ; sortie B6 ; seuil 120000.",
      A9: "Valeur cible : B5 doit valoir 900 en changeant B1 (capital finançable).",
      A10: "Balayage : entrée B3 de 10 à 30, 21 valeurs, sorties B5 ; B6.",
    }),
    "Équations (RESOUDRE, DERIVEE, INTEGRALE)": () => ({
      A1: "Racine de x³ − 2x − 5", B1: '=RESOUDRE("x^3-2*x-5";2)', A2: "Vérification (doit valoir 0)", B2: "=B1^3-2*B1-5",
      A3: "Dérivée de x²·sin x en 1", B3: '=DERIVEE("x^2*SIN(x)";1)', A4: "Valeur exacte 2·sin 1 + cos 1", B4: "=2*SIN(1)+COS(1)",
      A5: "∫ e^(−x²) de 0 à 3", B5: '=INTEGRALE("EXP(-x^2)";0;3)', A6: "√π / 2 pour comparer", B6: "=RACINE(PI())/2",
      A8: "Paramètre a", B8: "2", A9: "Racine positive de a·x² − 3", B9: '=RESOUDRE("B8*x^2-3";1)', A10: "Exacte : √(3/a)", B10: "=RACINE(3/B8)",
      A12: "Change B8 : B9 suit. Balayage possible : entrée B8 de 1 à 10, sortie B9.",
    }),
    "Notes d'une classe (statistiques, tri, filtre)": () => {
      const names = ["Alice", "Bilal", "Chloé", "David", "Emma", "Farid", "Gaëlle", "Hugo", "Inès", "Jules", "Kenza", "Louis", "Maya", "Noé", "Océane"];
      const notes = [[14, 12, 16], [9, 11, 8], [17, 15, 18], [11, 13, 10], [15, 16, 14], [8, 7, 12], [13, 14, 15], [10, 9, 11], [18, 17, 19], [12, 10, 13], [16, 18, 15], [7, 9, 8], [14, 15, 13], [11, 12, 9], [15, 13, 17]];
      const c = { A1: "Élève", B1: "Maths", C1: "Physique", D1: "Chimie", E1: "Moyenne", F1: "Mention" };
      names.forEach((n, i) => {
        const r = i + 2;
        c[`A${r}`] = n; [c[`B${r}`], c[`C${r}`], c[`D${r}`]] = notes[i].map(String);
        c[`E${r}`] = `=ARRONDI(MOYENNE(B${r}:D${r});2)`;
        c[`F${r}`] = `=SI(E${r}>=16;"très bien";SI(E${r}>=14;"bien";SI(E${r}>=12;"assez bien";SI(E${r}>=10;"admis";"—"))))`;
      });
      Object.assign(c, { H1: "Moyenne de classe", I1: "=MOYENNE(E2:E16)", H2: "Admis (≥ 10)", I2: '=NB.SI(E2:E16;">=10")', H3: "Corrélation maths/physique", I3: "=COEFFICIENT.CORRELATION(B2:B16;C2:C16)" });
      return c;
    },
  };
  for (const name of Object.keys(EXAMPLES)) { const o = el("option", "", name); o.value = name; $("examples").append(o); }
  $("examples").addEventListener("change", () => {
    const name = $("examples").value;
    $("examples").value = "";
    if (!name) return;
    if (S.dirty && !confirm("Des modifications ne sont pas enregistrées. Ouvrir l'exemple quand même ?")) return;
    loadCells(EXAMPLES[name](), name.split(" (")[0].replace(/[^\w .-]/g, "").trim() || "exemple");
    S.dirty = true;
    status(`Exemple « ${name} » : les consignes sont dans la feuille.`);
  });

  // ---------- démarrage ----------
  async function init() {
    buildGrid();
    setTab(local.get("tab", "chart"));
    const ch = local.get("chart", null);
    if (ch) { $("ch-x").value = ch.x; $("ch-y").value = ch.y; $("ch-type").value = ch.type; }
    $("fit-deg").disabled = true;
    addMcRow();
    const draft = local.get("draft", null);
    if (draft && draft.cells && Object.keys(draft.cells).length) { loadCells(draft.cells, draft.name); status("Brouillon restauré (pense à enregistrer)."); }
    else { loadCells(EXAMPLES["Prêt immobilier (Monte-Carlo, valeur cible)"](), "pret"); status("Exemple chargé : prêt immobilier. Menu « Exemples » pour d'autres."); }
    S.dirty = false;
    show(lastPlot);
    refreshList();
    try { const fns = await call("functions"); $("fn-list").textContent = fns.join(" · "); } catch (e) { /* liste facultative */ }
    $("grid-wrap").focus();
  }
  init();
  window.AetherData = { call, setCells, select, S };
})();
