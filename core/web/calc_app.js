"use strict";
// Æther CAS : fenêtre de calculatrice du module calc_cas (Calculs, Graphes, Tableur, Programmes).
// Tout passe par l'API locale du Hub (même origine) ; aucune ressource externe.

const $ = (id) => document.getElementById(id);
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") node.className = v; else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children) if (c !== null && c !== undefined) node.append(c instanceof Node ? c : String(c));
  return node;
}
const store = {
  get(key, fallback) { try { const v = localStorage.getItem(`aecas.${key}`); return v === null ? fallback : JSON.parse(v); } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(`aecas.${key}`, JSON.stringify(value)); } catch { /* stockage indisponible */ } },
};
const COLORS = ["#0c8599", "#e8590c", "#7048e8", "#2f9e44", "#d6336c", "#1971c2"];
const STD = { xmin: -10, xmax: 10, ymin: -7, ymax: 7 };

const S = {
  app: store.get("app", "calc"), mode: store.get("mode", "auto"), angle: "rad", second: false, alpha: false,
  history: [], sel: -1, inputs: [], recall: -1, field: null, menu: null, busy: 0,
  graph: { fns: store.get("fns", null), win: store.get("win", { ...STD }), plotted: [], marks: [], trace: null,
           cur: 0, panel: null, timer: 0, sampling: false },
  sheet: { data: store.get("sheet", null), cols: ["l1", "l2", "l3", "l4"] },
  prog: { name: store.get("progName", ""), programs: {}, examples: {}, inputs: [], seed: 0, dirty: false, last: null },
};
if (!Array.isArray(S.graph.fns) || S.graph.fns.length !== 6) {
  S.graph.fns = Array.from({ length: 6 }, (_, i) => ({ kind: "y", expr: i === 0 ? "x^3 - 3x" : "", x: "", y: "", r: "",
    tmin: 0, tmax: 6.2832, on: true }));
}
if (!Array.isArray(S.sheet.data) || S.sheet.data.length !== 60) S.sheet.data = Array.from({ length: 60 }, () => ["", "", "", ""]);

// ---------- API ----------
let activated = false;
async function post(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(data.detail || `erreur ${r.status}`); e.status = r.status; throw e; }
  return data;
}
async function call(command, payload) {
  busy(1);
  try {
    if (!activated) { await post("/modules/calc_cas/activate"); activated = true; }
    let reply;
    try { reply = await post(`/modules/calc_cas/command/${command}`, payload); }
    catch (e) {
      if (e.status !== 409) throw e;  // module arrêté entre-temps : on le relance une fois
      await post("/modules/calc_cas/activate");
      reply = await post(`/modules/calc_cas/command/${command}`, payload);
    }
    if (!reply.ok) throw new Error((reply.error || "erreur du module").replace(/^\w+Error: /, ""));
    $("dot").className = "dot on";
    return reply.result;
  } catch (e) {
    $("dot").className = "dot err";
    if (e instanceof TypeError) throw new Error("Hub injoignable : lance AetherTwin, puis rouvre la calculatrice");
    throw e;
  } finally { busy(-1); }
}
function busy(d) {
  S.busy = Math.max(0, S.busy + d);
  if (S.busy > 0) $("dot").className = "dot busy"; else if ($("dot").className === "dot busy") $("dot").className = "dot on";
}
function toast(text, ms = 1800) {
  const t = el("div", { class: "toast" }, text);
  document.body.append(t);
  setTimeout(() => t.remove(), ms);
}

// ---------- MathML (filtré) ----------
const MATH_TAGS = new Set(["math", "mrow", "mi", "mn", "mo", "msup", "msub", "msubsup", "mfrac", "msqrt", "mroot",
  "mtext", "mspace", "mtable", "mtr", "mtd", "munder", "mover", "munderover", "mstyle", "mpadded", "mphantom"]);
function mathNode(mathml, fallback) {
  if (!mathml) return el("code", {}, fallback || "");
  const t = document.createElement("template");
  t.innerHTML = `<math display="inline">${mathml}</math>`;
  const root = t.content.firstElementChild;
  const nodes = root ? [root, ...root.querySelectorAll("*")] : [];
  if (!root || nodes.some((n) => !MATH_TAGS.has(n.localName))) return el("code", {}, fallback || "");
  for (const n of nodes) for (const a of [...n.attributes]) {
    if (!["display", "mathvariant", "stretchy", "fence", "separator", "columnalign"].includes(a.name)) n.removeAttribute(a.name);
  }
  return root;
}

// ---------- applications ----------
function showApp(app) {
  S.app = app; store.set("app", app);
  $("device").dataset.app = app;
  for (const b of document.querySelectorAll("#apps button")) b.setAttribute("aria-selected", String(b.dataset.app === app));
  for (const v of document.querySelectorAll(".view")) v.hidden = v.dataset.view !== app;
  S.field = null;
  if (app === "calc") $("line").focus();
  if (app === "graph") { requestAnimationFrame(() => { drawGraph(); if (!S.graph.plotted.length) plotAll(); }); }
  if (app === "geo") window.geoShow?.();
  if (app === "prog") { requestAnimationFrame(() => { syncGutter(); drawProgram(); }); if (!S.prog.loaded) loadPrograms(); }
}
const APPS = ["calc", "graph", "geo", "sheet", "prog"];

// ---------- saisie : champ actif ----------
document.addEventListener("focusin", (e) => {
  const t = e.target;
  if ((t.tagName === "INPUT" && t.type !== "checkbox") || t.tagName === "TEXTAREA") S.field = t;
});
function activeField() {
  if (S.field && document.contains(S.field) && !S.field.closest("[hidden]")) return S.field;
  return { calc: $("line"), prog: $("code"), graph: $("fns").querySelector(".fn.sel input[type=text]"),
           sheet: $("cells").querySelector("input") }[S.app] || $("line");
}
function insert(text) {
  const f = activeField();
  if (!f) return;
  f.focus();
  const a = f.selectionStart ?? f.value.length, b = f.selectionEnd ?? a;
  f.value = f.value.slice(0, a) + text + f.value.slice(b);
  const caret = text.endsWith("()") ? a + text.length - 1 : a + text.length;
  f.selectionStart = f.selectionEnd = caret;
  f.dispatchEvent(new Event("input", { bubbles: true }));
}
function backspace() {
  const f = activeField();
  if (!f) return;
  f.focus();
  let a = f.selectionStart ?? f.value.length; const b = f.selectionEnd ?? a;
  if (a === b && a > 0) a -= 1;
  f.value = f.value.slice(0, a) + f.value.slice(b);
  f.selectionStart = f.selectionEnd = a;
  f.dispatchEvent(new Event("input", { bubbles: true }));
}
function clearField() { const f = activeField(); if (f) { f.value = ""; f.dispatchEvent(new Event("input", { bubbles: true })); f.focus(); } }
function moveCaret(d) {
  const f = activeField();
  if (!f) return;
  f.focus();
  const p = Math.max(0, Math.min(f.value.length, (f.selectionStart ?? 0) + d));
  f.selectionStart = f.selectionEnd = p;
}

// ---------- Calculs ----------
// Résultat exact : image PNG du moteur (LaTeX dessiné par matplotlib), sinon dessin unicode de SymPy.
function pngUrl(r) {
  if (!r._url) {
    const bytes = Uint8Array.from(atob(r.png), (c) => c.charCodeAt(0));
    r._url = URL.createObjectURL(new Blob([bytes], { type: "image/png" }));  // CSP : img-src blob:
  }
  return r._url;
}
function resultNode(r) {
  if (r.png) {
    const img = el("img", { class: "tex", alt: r.exact, title: r.exact });
    img.addEventListener("load", () => { img.width = Math.round(img.naturalWidth / 2); }, { once: true });
    img.addEventListener("error", () => img.replaceWith(prettyNode(r)), { once: true });
    img.src = pngUrl(r);
    return img;
  }
  return prettyNode(r);
}
function prettyNode(r) {
  const text = r.pretty || r.exact || "";
  return text.includes("\n") ? el("pre", { class: "pretty" }, text) : el("code", { class: "pretty" }, text);
}
async function renderMissing(entries) {  // historique rechargé : images recalculées par paquets
  const todo = entries.filter((r) => r.ok && !r.png && r.latex);
  for (let k = 0; k < todo.length; k += 50) {
    const batch = todo.slice(k, k + 50);
    try {
      const pngs = await call("render", { latex: batch.map((r) => r.latex) });
      batch.forEach((r, i) => { r.png = pngs[i]; if (!r.png) r.png = null; });
    } catch { return; }
  }
  if (todo.length) renderHistory();
}
function entryNode(r, index) {
  const node = el("div", { class: "entry", "data-i": index }, el("div", { class: "in" }, r.input));
  node.addEventListener("click", () => { S.sel = index; markSel(); });
  node.addEventListener("dblclick", () => { pasteEntry(index); });
  if (!r.ok) { node.append(el("div", { class: "err" }, r.error || "erreur")); return node; }
  const out = el("div", { class: "out" });
  if (r.label) out.append(el("span", { class: "label" }, `${r.label} :=`));
  const approxFirst = S.mode === "approx" && r.approx;
  const main = approxFirst ? el("span", { class: "num" }, r.approx) : resultNode(r);
  out.append(el("span", { class: "main" }, main));
  if (S.mode === "auto" && r.approx) out.append(el("span", { class: "approx" }, `≈ ${r.approx}`));
  node.append(out);
  if (r.warning) node.append(el("div", { class: "warn" }, r.warning));
  return node;
}
function renderHistory() {
  const box = $("history");
  box.replaceChildren(...S.history.map(entryNode));
  if (!S.history.length) box.append(el("div", { class: "empty" }, "Tape un calcul puis Entrée. « menu » propose les fonctions, ▲▼ parcourent l'historique."));
  markSel();
  box.scrollTop = box.scrollHeight;
}
function markSel() {
  for (const n of $("history").querySelectorAll(".entry")) n.classList.toggle("sel", Number(n.dataset.i) === S.sel);
  const s = $("history").querySelector(".entry.sel");
  if (s) s.scrollIntoView({ block: "nearest" });
}
function pasteEntry(i, which = "input") {
  const r = S.history[i];
  if (!r) return;
  const text = which === "result" && r.ok ? (S.mode === "approx" && r.approx ? r.approx : r.exact) : r.input;
  $("line").focus(); S.field = $("line");
  insert(text.replace(/\*\*/g, "^"));
}
let queue = Promise.resolve();
function evaluate(text, approx = false) {
  text = text.trim();
  if (!text) return;
  if (approx) text = `approx(${text})`;
  $("line").value = "";
  S.inputs.push(text); S.recall = -1; S.sel = -1;
  queue = queue.then(async () => {
    let r;
    try { r = await call("eval", { text }); } catch (e) { r = { ok: false, input: text, error: e.message }; }
    S.history.push(r);
    if (S.history.length > 200) S.history.shift();
    renderHistory();
    if (r.definition) S.varsCache = null;
  });
}
function historyNav(d) {
  if (!S.history.length) return;
  S.sel = S.sel < 0 ? (d < 0 ? S.history.length - 1 : 0) : Math.max(0, Math.min(S.history.length - 1, S.sel + d));
  markSel();
}

// ---------- menus ----------
const FN = (label, insert, hint) => ({ label, insert, hint });
const CALC_MENU = [
  { group: "Algèbre", items: [FN("Simplifier", "simplify()", "simplify(expr)"), FN("Développer", "expand()", "expand(expr)"),
    FN("Factoriser", "factor()", "factor(expr)"), FN("Réduire au même dénominateur", "together()", "together(expr)"),
    FN("Éléments simples", "apart()", "apart(expr)"), FN("Simplifier une fraction", "cancel()", "cancel(expr)"),
    FN("Résoudre", "solve()", "solve(éq, x) · solve([éq1, éq2], [x, y])"), FN("Résolution numérique", "nsolve()", "nsolve(éq, x, départ)"),
    FN("Substituer", "subs()", "subs(expr, x, valeur)"), FN("Simplifier (trigo)", "trigsimp()", "trigsimp(expr)")] },
  { group: "Analyse", items: [FN("Dériver", "diff()", "diff(f, x) · diff(f, x, n)"), FN("Intégrer", "integrate()", "integrate(f, x) · integrate(f, x, a, b)"),
    FN("Limite", "limit()", "limit(f, x, a) · limit(f, x, a, \"+\")"), FN("Somme", "sum()", "sum(terme, k, a, b)"),
    FN("Produit", "product()", "product(terme, k, a, b)"), FN("Développement de Taylor", "taylor()", "taylor(f, x, a, n)")] },
  { group: "Matrices", items: [FN("Matrice 2×2", "[[ , ], [ , ]]", "[[a, b], [c, d]]"), FN("Déterminant", "det()", "det(M)"),
    FN("Inverse", "inv()", "inv(M) · M^-1"), FN("Transposée", "transpose()", "transpose(M)"), FN("Valeurs propres", "eigenvals()", "eigenvals(M)"),
    FN("Vecteurs propres", "eigenvects()", "eigenvects(M)"), FN("Rang", "rank()", "rank(M)"), FN("Forme échelonnée", "rref()", "rref(M)"),
    FN("Identité", "eye()", "eye(n)"), FN("Produit scalaire", "dot()", "dot(u, v)"), FN("Produit vectoriel", "cross()", "cross(u, v)")] },
  { group: "Complexes", items: [FN("Partie réelle", "re()", "re(z)"), FN("Partie imaginaire", "im()", "im(z)"), FN("Module", "abs()", "abs(z)"),
    FN("Argument", "arg()", "arg(z)"), FN("Conjugué", "conj()", "conj(z)"), FN("Forme polaire", "polar()", "polar(z) → [module, argument]")] },
  { group: "Nombres", items: [FN("PGCD", "gcd()", "gcd(a, b)"), FN("PPCM", "lcm()", "lcm(a, b)"), FN("Premier ?", "isprime()", "isprime(n)"),
    FN("Décomposition en facteurs premiers", "factorint()", "factorint(n)"), FN("Diviseurs", "divisors()", "divisors(n)"),
    FN("Reste", "mod()", "mod(a, b)"), FN("Combinaisons", "binomial()", "binomial(n, k)"), FN("Factorielle", "!", "n!"),
    FN("Partie entière", "floor()", "floor(x)"), FN("Arrondi", "round()", "round(x, chiffres)")] },
  { group: "Listes et statistiques", items: [FN("Liste", "[ , , ]", "[1, 2, 3]"), FN("Moyenne", "mean()", "mean(liste)"),
    FN("Médiane", "median()", "median(liste)"), FN("Variance", "variance()", "variance(liste)"), FN("Écart type", "stdev()", "stdev(liste)"),
    FN("Minimum", "min()", "min(a, b, …)"), FN("Maximum", "max()", "max(a, b, …)"), FN("Effectif", "length()", "length(liste)")] },
  { group: "Valeurs et définitions", items: [FN("Valeur approchée", "approx()", "approx(expr, chiffres)"), FN("Définir", " := ", "a := 5 · f(x) := x^2"),
    FN("Stocker dans", " → ", "expr → nom"), FN("Dernier résultat", "ans", "ans")] },
];
const CATALOG = CALC_MENU.flatMap((g) => g.items.map((i) => ({ ...i, group: g.group })))
  .concat([["sin()", "sin(x)"], ["cos()", "cos(x)"], ["tan()", "tan(x)"], ["asin()", "asin(x)"], ["acos()", "acos(x)"], ["atan()", "atan(x)"],
    ["sinh()", "sinh(x)"], ["cosh()", "cosh(x)"], ["tanh()", "tanh(x)"], ["exp()", "exp(x)"], ["ln()", "ln(x)"], ["log()", "log(x, base)"],
    ["sqrt()", "sqrt(x)"], ["root()", "root(x, n)"], ["sign()", "sign(x)"], ["ceil()", "ceil(x)"], ["gamma()", "gamma(x)"]]
    .map(([ins, hint]) => FN(hint.split("(")[0], ins, hint)));

function openMenu(title, items, onPick) {
  closeMenu();
  const list = el("ul", { role: "listbox" });
  const search = el("input", { placeholder: "Rechercher…", "aria-label": "Rechercher" });
  const overlay = el("div", { class: "overlay" }, el("div", { class: "menu", role: "dialog", "aria-label": title },
    el("h3", {}, title, el("button", { type: "button", "aria-label": "Fermer" }, "✕")), search, list));
  let shown = [], sel = 0;
  const render = () => {
    const q = search.value.trim().toLowerCase();
    shown = items.filter((i) => i.group !== undefined && i.items === undefined ? true : true)
      .filter((i) => !q || i.isGroup || `${i.label} ${i.hint || ""}`.toLowerCase().includes(q));
    if (q) shown = shown.filter((i) => !i.isGroup);
    sel = Math.min(sel, Math.max(0, shown.filter((i) => !i.isGroup).length - 1));
    let k = 0;
    list.replaceChildren(...shown.map((i) => {
      if (i.isGroup) return el("li", { class: "group" }, el("span"), i.label);
      const idx = k++;
      const li = el("li", { class: idx === sel ? "sel" : "", role: "option" }, el("span", { class: "k" }, idx < 9 ? String(idx + 1) : ""),
        el("span", {}, i.label), i.hint ? el("small", {}, i.hint) : null);
      li.addEventListener("click", () => pick(idx));
      return li;
    }));
    list.querySelector(".sel")?.scrollIntoView({ block: "nearest" });
  };
  const choices = () => shown.filter((i) => !i.isGroup);
  const pick = (idx) => { const it = choices()[idx]; if (!it) return; closeMenu(); onPick(it); };
  S.menu = {
    move: (d) => { sel = Math.max(0, Math.min(choices().length - 1, sel + d)); render(); },
    ok: () => pick(sel), digit: (n) => pick(n - 1),
  };
  overlay.addEventListener("click", (e) => { if (e.target === overlay) closeMenu(); });
  overlay.querySelector("h3 button").addEventListener("click", closeMenu);
  search.addEventListener("input", () => { sel = 0; render(); });
  document.body.append(overlay);
  S.menu.node = overlay;
  render();
  search.focus();
}
function closeMenu() { if (S.menu) { S.menu.node.remove(); S.menu = null; activeField()?.focus(); } }
const grouped = (groups) => groups.flatMap((g) => [{ isGroup: true, label: g.group }, ...g.items]);

function contextMenu() {
  if (S.app === "calc") {
    const actions = { group: "Calculatrice", items: [
      { label: `Unité d'angle : passer en ${S.angle === "rad" ? "degrés" : "radians"}`, act: toggleAngle },
      { label: "Affichage : auto → exact → approché", act: cycleMode },
      { label: "Effacer l'historique et les variables", act: resetAll },
      { label: "Variables et fonctions définies", act: showVars }] };
    openMenu("Menu — Calculs", grouped([...CALC_MENU, actions]), runItem);
  } else if (S.app === "graph") {
    openMenu("Menu — Graphes", grouped([{ group: "Analyse", items: [
      { label: "Trace (◀ ▶ le long de la courbe, ▲ ▼ change de courbe)", act: () => graphTool("trace") },
      { label: "Zéros de la courbe choisie", act: () => graphTool("zeros") },
      { label: "Extrema (minimum, maximum)", act: () => graphTool("extrema") },
      { label: "Intersection de deux courbes", act: () => graphTool("intersections") },
      { label: "Tableau de valeurs", act: () => graphTool("table") }] },
    { group: "Fenêtre", items: [{ label: "Réglages de la fenêtre…", act: () => graphTool("window") },
      { label: "Zoom standard", act: () => graphTool("std") }, { label: "Zoom trigonométrique", act: () => graphTool("trig") },
      { label: "Repère orthonormé", act: () => graphTool("square") }, { label: "Zoom avant", act: () => zoom(0.5) },
      { label: "Zoom arrière", act: () => zoom(2) }, { label: "Afficher / masquer la liste des fonctions", act: () => graphTool("list") }] },
    { group: "Fonctions", items: [{ label: "Effacer toutes les fonctions", act: () => { S.graph.fns.forEach((f) => { f.expr = f.x = f.y = f.r = ""; }); renderFns(); plotAll(); } }] }]), runItem);
  } else if (S.app === "geo") {
    openMenu("Menu — Géométrie", grouped(geoMenuGroups()), runItem);
  } else if (S.app === "sheet") {
    openMenu("Menu — Tableur", grouped([{ group: "Statistiques", items: [
      { label: "Statistiques à une variable", act: () => sheetStats(false) }, { label: "Statistiques à deux variables", act: () => sheetStats(true) },
      ...["linear", "quadratic", "cubic", "exponential", "power", "logarithmic"].map((m) => ({ label: `Régression ${$("st-model").querySelector(`[value=${m}]`).textContent}`,
        act: () => { $("st-model").value = m; regress(); } }))] },
    { group: "Données", items: [{ label: "Envoyer les colonnes dans Calculs (l1 … l4)", act: sheetToCas },
      { label: "Charger l'exemple", act: sheetDemo }, { label: "Vider le tableur", act: sheetClear }] }]), runItem);
  } else {
    const ex = Object.keys(S.prog.examples).map((k) => ({ label: `Exemple : ${k}`, act: () => openProgram(k, S.prog.examples[k], true) }));
    const snip = [["for i in range(10):\n    ", "Boucle for"], ["while condition:\n    ", "Boucle while"], ["if condition:\n    \nelse:\n    ", "Si … sinon"],
      ["def f(x):\n    return ", "Fonction"], ["print()", "Afficher"], ["input(\"? \")", "Demander une valeur"], ["import math\n", "Module math"],
      ["from random import randint\n", "Hasard"], ["cas(\"\")", "Calcul exact (CAS)"], ["cas_value(\"\")", "Valeur d'une expression CAS"],
      ["plot(xs, ys)", "Tracer une ligne"], ["scatter(xs, ys)", "Nuage de points"], ["fplot(lambda x: x**2, -3, 3)", "Tracer une fonction"],
      ["text(0, 0, \"A\")", "Texte sur le dessin"]].map(([code, label]) => ({ label, insert: code, hint: code.split("\n")[0] }));
    openMenu("Menu — Programmes", grouped([{ group: "Programme", items: [{ label: "Exécuter (Ctrl+Entrée)", act: runProgram },
      { label: "Enregistrer (Ctrl+S)", act: saveProgram }, { label: "Nouveau programme", act: newProgram }, { label: "Aide du bac à sable", act: progHelp }] },
    { group: "Insérer", items: snip }, { group: "Exemples", items: ex }]), runItem);
  }
}
function runItem(it) { if (it.act) it.act(); else if (it.insert) insert(it.insert); }
function catalog() { openMenu("Catalogue des fonctions", CATALOG, runItem); }
async function showVars() {
  try {
    const vars = await call("vars");
    openMenu("Variables et fonctions", vars.length ? vars.map((v) => ({ label: v.name, hint: v.source, insert: v.name }))
      : [{ label: "Aucune définition (a := 5, f(x) := x^2 …)", act: () => {} }], runItem);
  } catch (e) { toast(e.message); }
}

// ---------- modes ----------
async function toggleAngle() {
  try { const r = await call("settings", { angle: S.angle === "rad" ? "deg" : "rad" }); S.angle = r.angle; badges(); toast(S.angle === "deg" ? "Degrés" : "Radians"); }
  catch (e) { toast(e.message); }
}
function cycleMode() { S.mode = { auto: "exact", exact: "approx", approx: "auto" }[S.mode]; store.set("mode", S.mode); badges(); renderHistory(); }
function badges() {
  $("badge-angle").textContent = S.angle === "deg" ? "DEG" : "RAD";
  $("badge-mode").textContent = { auto: "AUTO", exact: "EXACT", approx: "APPROX" }[S.mode];
  const m = $("badge-mod");
  m.hidden = !S.second && !S.alpha;
  m.textContent = S.second && S.alpha ? "ABC" : S.second ? "2nde" : "abc";
  m.className = `badge ${S.second ? "second" : "alpha"}`;
  for (const k of document.querySelectorAll(".key.mod-second")) k.classList.toggle("latched", S.second);
  for (const k of document.querySelectorAll(".key.mod-alpha")) k.classList.toggle("latched", S.alpha);
}
async function resetAll() {
  if (!confirm("Effacer l'historique, les variables et les fonctions ?")) return;
  try { await call("reset"); S.history = []; renderHistory(); toast("Effacé"); } catch (e) { toast(e.message); }
}

// ---------- Graphes ----------
function renderFns() {
  const box = $("fns");
  box.replaceChildren(...S.graph.fns.map((f, i) => {
    const color = COLORS[i];
    const sw = el("button", { type: "button", class: `sw${f.on ? " on" : ""}`, title: f.on ? "Masquer" : "Afficher", "aria-label": `f${i + 1} visible` });
    sw.style.color = color;
    sw.addEventListener("click", () => { f.on = !f.on; saveFns(); renderFns(); plotAll(); });
    const kind = el("select", { "aria-label": `Type de f${i + 1}` }, ...[["y", "y="], ["param", "x(t),y(t)"], ["polar", "r(θ)"]].map(([v, t]) => el("option", { value: v }, t)));
    kind.value = f.kind;
    kind.addEventListener("change", () => { f.kind = kind.value; saveFns(); renderFns(); plotAll(); });
    const field = (key, ph) => {
      const inp = el("input", { type: "text", value: f[key] ?? "", placeholder: ph, spellcheck: "false", "aria-label": `f${i + 1} ${ph}` });
      inp.addEventListener("input", () => { f[key] = inp.value; saveFns(); });
      inp.addEventListener("change", plotAll);
      inp.addEventListener("focus", () => { S.graph.cur = i; markFn(); });
      inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); f[key] = inp.value; plotAll(); } });
      return inp;
    };
    const row = el("div", { class: `fn${i === S.graph.cur ? " sel" : ""}`, "data-i": i }, sw, el("span", { class: "name" }, `f${i + 1}`));
    row.querySelector(".name").addEventListener("click", () => { S.graph.cur = i; markFn(); });
    if (f.kind === "y") row.append(field("expr", i === 0 ? "x^2 - 2" : ""));
    else if (f.kind === "param") row.append(el("div", { class: "more" }, field("x", "x(t)"), field("y", "y(t)")));
    else row.append(field("r", "cos(4 theta)"));
    row.append(el("span"), kind);
    if (f.kind !== "y") row.append(el("div", { class: "more" }, field("tmin", "t min"), field("tmax", "t max")));
    if (S.graph.errors?.[i]) row.append(el("div", { class: "err" }, S.graph.errors[i]));
    return row;
  }));
}
function markFn() { for (const r of $("fns").querySelectorAll(".fn")) r.classList.toggle("sel", Number(r.dataset.i) === S.graph.cur); }
function saveFns() { store.set("fns", S.graph.fns); }
const filled = (f) => (f.kind === "y" ? f.expr : f.kind === "param" ? f.x && f.y : f.r)?.toString().trim();
async function plotAll() {
  const list = S.graph.fns.map((f, i) => ({ ...f, i })).filter((f) => f.on && filled(f));
  S.graph.errors = {};
  if (!list.length) { S.graph.plotted = []; drawGraph(); renderFns(); return; }
  try {
    const r = await call("plot", { window: S.graph.win, samples: 700, curves: list.map((f) => ({
      kind: f.kind, expr: f.expr, x: f.x, y: f.y, r: f.r, tmin: Number(f.tmin) || 0, tmax: Number(f.tmax) || 6.2832 })) });
    S.graph.plotted = r.curves.map((c, k) => ({ ...c, fn: list[k].i, color: COLORS[list[k].i] }));
    r.curves.forEach((c, k) => { if (c.error) S.graph.errors[list[k].i] = c.error; });
    if (Object.keys(S.graph.errors).length || $("fns").querySelector(".err")) renderFns();
  } catch (e) { $("graph-info").textContent = e.message; }
  drawGraph();
}
function schedulePlot() { clearTimeout(S.graph.timer); S.graph.timer = setTimeout(plotAll, 140); }
function niceStep(span, px) {
  const raw = span / Math.max(2, px / 70), p = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw) || raw;
}
const fmt = (v) => (Math.abs(+v) < 1e-10 ? "0" : String(+(+v).toPrecision(6)));
function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function drawPlot(canvas, win, layers, extras) {
  const dpr = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return null;
  canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const { xmin, xmax, ymin, ymax } = win;
  const X = (x) => ((x - xmin) / (xmax - xmin)) * w, Y = (y) => h - ((y - ymin) / (ymax - ymin)) * h;
  ctx.fillStyle = css("--screen"); ctx.fillRect(0, 0, w, h);
  ctx.font = "11px Consolas, monospace";
  const sx = niceStep(xmax - xmin, w), sy = niceStep(ymax - ymin, h);
  ctx.lineWidth = 1; ctx.strokeStyle = css("--grid"); ctx.fillStyle = css("--axis");
  for (let x = Math.ceil(xmin / sx) * sx; x <= xmax; x += sx) {
    ctx.beginPath(); ctx.moveTo(X(x), 0); ctx.lineTo(X(x), h); ctx.stroke();
    if (Math.abs(x) > sx / 2) ctx.fillText(fmt(x), X(x) + 2, Math.min(h - 4, Math.max(12, Y(0) + 12)));
  }
  for (let y = Math.ceil(ymin / sy) * sy; y <= ymax; y += sy) {
    ctx.beginPath(); ctx.moveTo(0, Y(y)); ctx.lineTo(w, Y(y)); ctx.stroke();
    if (Math.abs(y) > sy / 2) ctx.fillText(fmt(y), Math.min(w - 42, Math.max(2, X(0) + 3)), Y(y) - 2);
  }
  ctx.strokeStyle = css("--axis"); ctx.lineWidth = 1.4;
  if (ymin < 0 && ymax > 0) { ctx.beginPath(); ctx.moveTo(0, Y(0)); ctx.lineTo(w, Y(0)); ctx.stroke(); }
  if (xmin < 0 && xmax > 0) { ctx.beginPath(); ctx.moveTo(X(0), 0); ctx.lineTo(X(0), h); ctx.stroke(); }
  ctx.lineJoin = "round";
  for (const layer of layers) {
    ctx.strokeStyle = ctx.fillStyle = layer.color || COLORS[0];
    if (layer.type === "points") { for (const [x, y] of layer.points) { ctx.beginPath(); ctx.arc(X(x), Y(y), 3.2, 0, 7); ctx.fill(); } continue; }
    if (layer.type === "text") { ctx.fillStyle = css("--screen-ink"); ctx.font = "13px Segoe UI, sans-serif"; ctx.fillText(layer.text, X(layer.x), Y(layer.y)); ctx.font = "11px Consolas, monospace"; continue; }
    ctx.lineWidth = 2.2;
    for (const seg of layer.segments || [layer.points]) {
      ctx.beginPath(); let pen = false;
      for (const p of seg) { if (!p) { pen = false; continue; } if (pen) ctx.lineTo(X(p[0]), Y(p[1])); else { ctx.moveTo(X(p[0]), Y(p[1])); pen = true; } }
      ctx.stroke();
    }
  }
  if (extras) extras(ctx, X, Y, w, h);
  return { X, Y };
}
function drawGraph() {
  const g = S.graph;
  drawPlot($("plot"), g.win, g.plotted.filter((c) => c.segments).map((c) => ({ type: "line", segments: c.segments, color: c.color })), (ctx, X, Y, w, h) => {
    for (const p of g.marks) {
      if (p.y === null) continue;
      ctx.fillStyle = css("--screen-ink"); ctx.beginPath(); ctx.arc(X(p.x), Y(p.y), 4.5, 0, 7); ctx.fill();
      ctx.fillText(`${p.type} (${p.x_exact || fmt(p.x)} ; ${p.y_exact || fmt(p.y)})`, X(p.x) + 7, Y(p.y) - 7);
    }
    const t = tracePoint();
    if (t) {
      ctx.strokeStyle = t.color; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(X(t.x), 0); ctx.lineTo(X(t.x), h); ctx.moveTo(0, Y(t.y)); ctx.lineTo(w, Y(t.y)); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = t.color; ctx.beginPath(); ctx.arc(X(t.x), Y(t.y), 5, 0, 7); ctx.fill();
      $("coords").textContent = `f${t.fn + 1} : x = ${fmt(t.x)}   y = ${fmt(t.y)}`;
    }
  });
}
function traceCurves() { return S.graph.plotted.filter((c) => c.segments && c.segments.length); }
function tracePoint() {
  const tr = S.graph.trace;
  if (!tr) return null;
  const curves = traceCurves();
  if (!curves.length) return null;
  tr.c = ((tr.c % curves.length) + curves.length) % curves.length;
  const c = curves[tr.c], pts = c.segments.flat();
  tr.i = Math.max(0, Math.min(pts.length - 1, tr.i ?? Math.floor(pts.length / 2)));
  const [x, y] = pts[tr.i];
  return { x, y, fn: c.fn, color: c.color };
}
function zoom(f, cx, cy) {
  const w = S.graph.win;
  cx ??= (w.xmin + w.xmax) / 2; cy ??= (w.ymin + w.ymax) / 2;
  S.graph.win = { xmin: cx - (cx - w.xmin) * f, xmax: cx + (w.xmax - cx) * f, ymin: cy - (cy - w.ymin) * f, ymax: cy + (w.ymax - cy) * f };
  store.set("win", S.graph.win); drawGraph(); schedulePlot();
}
function pan(dx, dy) {
  const w = S.graph.win, sx = (w.xmax - w.xmin) * dx, sy = (w.ymax - w.ymin) * dy;
  S.graph.win = { xmin: w.xmin + sx, xmax: w.xmax + sx, ymin: w.ymin + sy, ymax: w.ymax + sy };
  store.set("win", S.graph.win); drawGraph(); schedulePlot();
}
function panel(title, ...content) {
  const p = $("graph-panel");
  if (!title) { p.hidden = true; S.graph.panel = null; return; }
  const close = el("button", { type: "button", class: "small" }, "✕");
  close.addEventListener("click", () => panel(null));
  p.replaceChildren(el("div", { class: "row" }, el("b", {}, title), " ", close), ...content);
  p.hidden = false; S.graph.panel = title;
}
function currentFn() {
  const f = S.graph.fns[S.graph.cur];
  if (f && f.kind === "y" && f.expr.trim()) return f;
  return S.graph.fns.find((g) => g.on && g.kind === "y" && g.expr.trim());
}
async function graphTool(tool) {
  const g = S.graph;
  if (tool === "std") { g.win = { ...STD }; } else if (tool === "trig") { g.win = { xmin: -2 * Math.PI, xmax: 2 * Math.PI, ymin: -4, ymax: 4 }; }
  else if (tool === "square") {
    const c = $("plot"), ratio = c.clientHeight / c.clientWidth, cy = (g.win.ymin + g.win.ymax) / 2, half = ((g.win.xmax - g.win.xmin) * ratio) / 2;
    g.win = { ...g.win, ymin: cy - half, ymax: cy + half };
  }
  if (["std", "trig", "square"].includes(tool)) { store.set("win", g.win); drawGraph(); plotAll(); return; }
  if (tool === "list") { $("fns").parentElement.classList.toggle("wide"); requestAnimationFrame(drawGraph); return; }
  if (tool === "trace") {
    g.trace = g.trace ? null : { c: 0, i: null };
    $("graph-info").textContent = g.trace ? "Trace : ◀ ▶ déplacer, ▲ ▼ changer de courbe, esc pour sortir" : "";
    if (!g.trace) $("coords").textContent = "";
    drawGraph(); return;
  }
  if (tool === "window") {
    const inputs = {};
    const grid = el("div", { class: "win" }, ...["xmin", "xmax", "ymin", "ymax"].flatMap((k) => {
      inputs[k] = el("input", { type: "text", value: fmt(g.win[k]), "aria-label": k });
      return [el("label", {}, k), inputs[k]];
    }));
    const apply = el("button", { type: "button", class: "small primary" }, "Appliquer");
    apply.addEventListener("click", () => {
      const v = Object.fromEntries(Object.entries(inputs).map(([k, i]) => [k, Number(i.value)]));
      if (Object.values(v).some((n) => !Number.isFinite(n)) || v.xmin >= v.xmax || v.ymin >= v.ymax) { toast("Fenêtre invalide : xmin < xmax, ymin < ymax"); return; }
      g.win = v; store.set("win", v); panel(null); drawGraph(); plotAll();
    });
    panel("Fenêtre", grid, el("div", { class: "row" }, apply));
    inputs.xmin.focus(); return;
  }
  const f = currentFn();
  if (!f) { toast("Il faut une fonction y = f(x)"); return; }
  if (tool === "table") {
    const start = el("input", { type: "text", value: fmt(Math.round(g.win.xmin)), "aria-label": "début" });
    const step = el("input", { type: "text", value: "1", "aria-label": "pas" });
    const body = el("tbody");
    const fill = async () => {
      try {
        const t = await call("table", { expr: f.expr, start: Number(start.value), step: Number(step.value), count: 25 });
        body.replaceChildren(...t.rows.map(([x, y]) => el("tr", {}, el("td", {}, fmt(x)), el("td", {}, y === null ? "—" : fmt(y)))));
      } catch (e) { body.replaceChildren(el("tr", {}, el("td", { colspan: 2 }, e.message))); }
    };
    start.addEventListener("change", fill); step.addEventListener("change", fill);
    panel(`Tableau de y = ${f.expr}`, el("div", { class: "win" }, el("label", {}, "début"), start, el("label", {}, "pas"), step),
      el("table", {}, el("thead", {}, el("tr", {}, el("th", {}, "x"), el("th", {}, "y"))), body));
    fill(); return;
  }
  const others = S.graph.fns.filter((o) => o !== f && o.on && o.kind === "y" && o.expr.trim());
  if (tool === "intersections" && !others.length) { toast("Il faut deux courbes y = f(x)"); return; }
  try {
    const r = await call("analyze", { what: tool, expr: f.expr, other: others[0]?.expr, xmin: g.win.xmin, xmax: g.win.xmax });
    g.marks = r.points;
    const both = (ex, v) => (ex && ex !== fmt(v) && !/^-?\d+$/.test(ex) ? `${ex} ≈ ${fmt(v)}` : ex && /^-?\d+$/.test(ex) ? ex : fmt(v));
    panel({ zeros: "Zéros", extrema: "Extrema", intersections: "Intersections" }[tool] + ` de y = ${r.expr}`,
      r.points.length ? el("table", {}, el("tbody", {}, ...r.points.map((p) => el("tr", {}, el("td", {}, p.type),
        el("td", {}, `x = ${both(p.x_exact, p.x)}`), el("td", {}, p.y === null ? "" : `y = ${both(p.y_exact, p.y)}`)))))
        : el("p", {}, "Aucun point dans la fenêtre."));
    drawGraph();
  } catch (e) { toast(e.message, 3000); }
}
function bindPlot() {
  const c = $("plot");
  let drag = null;
  const world = (e) => { const r = c.getBoundingClientRect(), w = S.graph.win;
    return [w.xmin + ((e.clientX - r.left) / r.width) * (w.xmax - w.xmin), w.ymax - ((e.clientY - r.top) / r.height) * (w.ymax - w.ymin)]; };
  c.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, win: { ...S.graph.win } }; c.setPointerCapture(e.pointerId); c.classList.add("drag"); });
  c.addEventListener("pointermove", (e) => {
    if (!S.graph.trace) { const [x, y] = world(e); $("coords").textContent = `x = ${x.toPrecision(5)}   y = ${y.toPrecision(5)}`; }
    if (!drag) return;
    const r = c.getBoundingClientRect(), w = drag.win;
    const dx = ((e.clientX - drag.x) / r.width) * (w.xmax - w.xmin), dy = ((e.clientY - drag.y) / r.height) * (w.ymax - w.ymin);
    S.graph.win = { xmin: w.xmin - dx, xmax: w.xmax - dx, ymin: w.ymin + dy, ymax: w.ymax + dy };
    drawGraph();
  });
  const end = () => { if (drag) { drag = null; c.classList.remove("drag"); store.set("win", S.graph.win); schedulePlot(); } };
  c.addEventListener("pointerup", end); c.addEventListener("pointercancel", end);
  c.addEventListener("wheel", (e) => { e.preventDefault(); const [x, y] = world(e); zoom(e.deltaY > 0 ? 1.25 : 0.8, x, y); }, { passive: false });
}

// ---------- Tableur ----------
function renderSheet() {
  $("cells-head").replaceChildren(el("tr", {}, el("th", {}, "#"), ...S.sheet.cols.map((c) => el("th", {}, c))));
  $("cells").replaceChildren(...S.sheet.data.map((row, r) => el("tr", {}, el("td", { class: "n" }, String(r + 1)), ...row.map((v, c) => {
    const inp = el("input", { type: "text", value: v, inputmode: "decimal", "data-r": r, "data-c": c, "aria-label": `${S.sheet.cols[c]} ligne ${r + 1}` });
    inp.addEventListener("input", () => { S.sheet.data[r][c] = inp.value; store.set("sheet", S.sheet.data); });
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); cellMove(1, 0); } });
    return el("td", {}, inp);
  }))));
  for (const [id, def] of [["col-x", 0], ["col-y", 1], ["col-f", -1]]) {
    const s = $(id), keep = s.value;
    s.replaceChildren(...(id === "col-f" ? [el("option", { value: "-1" }, "—")] : []), ...S.sheet.cols.map((c, i) => el("option", { value: String(i) }, c)));
    s.value = keep || String(def);
  }
}
function cellMove(dr, dc) {
  const f = document.activeElement;
  if (!f?.dataset?.r) { $("cells").querySelector("input")?.focus(); return; }
  const r = Math.max(0, Math.min(59, Number(f.dataset.r) + dr)), c = Math.max(0, Math.min(3, Number(f.dataset.c) + dc));
  $("cells").querySelector(`input[data-r="${r}"][data-c="${c}"]`)?.focus();
}
function column(i) { return S.sheet.data.map((r) => r[i].trim()); }
function pairs() {
  const xi = Number($("col-x").value), yi = Number($("col-y").value), fi = Number($("col-f").value);
  const rows = S.sheet.data.filter((r) => r[xi].trim() || r[yi].trim());
  return { x: rows.map((r) => r[xi].trim()), y: rows.map((r) => r[yi].trim()), f: fi >= 0 ? rows.map((r) => r[fi].trim() || "0") : null };
}
const LABELS = { n: "n", mean: "x̄", sum: "Σx", sum_sq: "Σx²", sx: "sx", sigma: "σx", variance: "variance", min: "min", q1: "Q1",
  median: "médiane", q3: "Q3", max: "max", range: "étendue", mean_x: "x̄", mean_y: "ȳ", sy: "sy", sigma_x: "σx", sigma_y: "σy",
  sum_xy: "Σxy", cov: "cov", r: "r" };
const statGrid = (o) => el("div", { class: "grid" }, ...Object.entries(o).map(([k, v]) => el("div", {}, el("span", {}, LABELS[k] || k), el("b", {}, v === null ? "—" : String(v)))));
async function sheetStats(two) {
  const d = pairs();
  try {
    const r = await call("stats", { x: d.x.filter((v) => v), ...(two ? { y: d.y } : {}), ...(d.f && !two ? { freq: d.f } : {}) });
    $("st-out").replaceChildren(el("b", {}, "Une variable"), statGrid(r.one_var), ...(r.two_var ? [el("b", {}, "Deux variables"), statGrid(r.two_var)] : []));
  } catch (e) { $("st-out").replaceChildren(el("span", { class: "err" }, e.message)); }
}
async function regress() {
  const d = pairs();
  try {
    const r = await call("regress", { x: d.x, y: d.y, model: $("st-model").value });
    const plotIt = el("button", { type: "button", class: "small primary" }, "Tracer dans Graphes");
    plotIt.addEventListener("click", () => {
      const xs = d.x.map(Number), ys = d.y.map(Number);
      const slot = S.graph.fns.findIndex((f) => !filled(f));
      const i = slot >= 0 ? slot : 5;
      S.graph.fns[i] = { kind: "y", expr: r.expr, x: "", y: "", r: "", tmin: 0, tmax: 6.2832, on: true };
      if (xs.every(Number.isFinite) && ys.every(Number.isFinite) && xs.length) {
        const pad = (a, b) => { const s = (b - a) || 1; return [a - s * 0.15, b + s * 0.15]; };
        const [x0, x1] = pad(Math.min(...xs), Math.max(...xs)), [y0, y1] = pad(Math.min(...ys), Math.max(...ys));
        S.graph.win = { xmin: x0, xmax: x1, ymin: y0, ymax: y1 };
        S.graph.scatter = xs.map((x, k) => [x, ys[k]]);
      }
      saveFns(); store.set("win", S.graph.win); renderFns(); showApp("graph"); plotAll();
    });
    $("st-out").replaceChildren(el("b", {}, r.equation), el("div", {}, `r² = ${r.r2}` + (r.r !== undefined ? `   ·   r = ${r.r}` : "")), plotIt);
  } catch (e) { $("st-out").replaceChildren(el("span", { class: "err" }, e.message)); }
}
async function sheetToCas() {
  let n = 0;
  for (let c = 0; c < 4; c += 1) {
    const vals = column(c).filter((v) => v);
    if (vals.length) { evaluate(`${S.sheet.cols[c]} := [${vals.join(", ")}]`); n += 1; }
  }
  toast(n ? `${n} liste(s) définie(s) dans Calculs` : "Tableur vide");
}
function sheetDemo() {
  const x = [0, 1, 2, 3, 4, 5], y = [2, 3.1, 4.4, 6.9, 10.2, 15.1];
  S.sheet.data = Array.from({ length: 60 }, (_, i) => (i < 6 ? [String(x[i]), String(y[i]), "", ""] : ["", "", "", ""]));
  store.set("sheet", S.sheet.data); renderSheet(); $("st-model").value = "exponential";
}
function sheetClear() { if (confirm("Vider le tableur ?")) { S.sheet.data = Array.from({ length: 60 }, () => ["", "", "", ""]); store.set("sheet", S.sheet.data); renderSheet(); } }

// ---------- Programmes ----------
async function loadPrograms() {
  try {
    const r = await call("programs");
    S.prog.programs = r.programs; S.prog.examples = r.examples; S.prog.games = r.games || {}; S.prog.loaded = true;
    if (!S.prog.name || !(S.prog.name in r.programs)) {
      const first = Object.keys(r.programs)[0];
      if (first) openProgram(first, r.programs[first]);
      else if (!$("code").value) openProgram("syracuse", r.examples.suite_syracuse, true);
    } else openProgram(S.prog.name, r.programs[S.prog.name]);
    renderProgList();
  } catch (e) { consoleLine(e.message, "err"); }
}
function renderProgList() {
  const mk = (name, code, example) => {
    const b = el("button", { type: "button", class: !example && name === S.prog.name ? "sel" : "", title: name }, name);
    b.addEventListener("click", () => openProgram(example ? name : name, code, example));
    return b;
  };
  $("prog-list").replaceChildren(el("h4", {}, "Mes programmes"),
    ...(Object.keys(S.prog.programs).length ? Object.entries(S.prog.programs).sort().map(([n, c]) => mk(n, c, false)) : [el("span", { class: "empty" }, "aucun")]),
    el("h4", {}, "Exemples"), ...Object.entries(S.prog.examples).map(([n, c]) => mk(n, c, true)),
    el("h4", {}, "Jeux"), ...Object.entries(S.prog.games || {}).map(([n, c]) => mk(n, c, true)));
}
function openProgram(name, code, example = false) {
  if (S.prog.dirty && !confirm("Le programme en cours n'est pas enregistré. Continuer ?")) return;
  S.prog.name = example ? name.replace(/^suite_/, "") : name;
  $("prog-name").value = S.prog.name; $("code").value = code || "";
  S.prog.dirty = example; store.set("progName", example ? "" : name);
  syncGutter(); renderProgList(); status(example ? "exemple (non enregistré)" : "prêt");
}
function newProgram() {
  if (S.prog.dirty && !confirm("Le programme en cours n'est pas enregistré. Continuer ?")) return;
  S.prog.dirty = false; S.prog.name = ""; $("prog-name").value = ""; $("code").value = "# Nouveau programme\n";
  syncGutter(); renderProgList(); $("prog-name").focus();
}
async function saveProgram() {
  const name = $("prog-name").value.trim();
  if (!/^[A-Za-zÀ-ÿ][\wÀ-ÿ]{0,40}$/.test(name)) { toast("Nom : lettres, chiffres et _ (sans espace)"); $("prog-name").focus(); return; }
  try {
    await call("program_save", { name, code: $("code").value });
    S.prog.programs[name] = $("code").value; S.prog.name = name; S.prog.dirty = false; store.set("progName", name);
    renderProgList(); status("enregistré"); toast(`« ${name} » enregistré`);
  } catch (e) { toast(e.message, 3000); }
}
async function deleteProgram() {
  const name = $("prog-name").value.trim();
  if (!(name in S.prog.programs) || !confirm(`Supprimer « ${name} » ?`)) return;
  try { await call("program_delete", { name }); delete S.prog.programs[name]; S.prog.dirty = false; newProgram(); } catch (e) { toast(e.message); }
}
function status(text) { $("prog-status").textContent = text; }
function consoleLine(text, cls) { $("console").append(el("span", { class: cls || "" }, text)); }
const usesGame = (code) => /^\s*(import\s+jeu\b|from\s+jeu\s+import)/m.test(code);
async function runProgram(continuing = false) {
  if (!continuing && usesGame($("code").value)) { playProgram(); return; }
  if (!continuing) { S.prog.inputs = []; S.prog.seed = Math.floor(Math.random() * 1e9); }
  status("exécution…");
  try {
    const r = await call("program_run", { code: $("code").value, inputs: S.prog.inputs, seed: S.prog.seed });
    S.prog.last = r;
    $("console").replaceChildren(el("span", {}, r.output || ""));
    if (r.needs_input) {
      const inp = el("input", { "aria-label": r.prompt || "valeur" });
      const form = el("form", {}, el("span", { class: "note" }, r.prompt || "? "), inp);
      form.addEventListener("submit", (e) => { e.preventDefault(); S.prog.inputs.push(inp.value); runProgram(true); });
      $("console").append(form); inp.focus(); S.field = inp; status("en attente d'une saisie");
    } else if (!r.ok) { consoleLine(`\n${r.error}\n`, "err"); status(r.timeout ? "interrompu (délai)" : "erreur"); }
    else { consoleLine(`\n— terminé en ${r.elapsed_ms} ms —\n`, "note"); status("terminé"); }
    $("console").scrollTop = $("console").scrollHeight;
    drawProgram();
  } catch (e) { consoleLine(`\n${e.message}\n`, "err"); status("erreur"); }
}
function drawProgram() {
  const d = S.prog.last?.drawings || [];
  $("draw-box").hidden = !d.length;
  $("out-split").classList.toggle("with-draw", d.length > 0);
  if (!d.length) return;
  const pts = d.flatMap((x) => (x.type === "text" ? [[x.x, x.y]] : x.points.filter(Boolean)));
  let [x0, x1, y0, y1] = [Math.min(...pts.map((p) => p[0])), Math.max(...pts.map((p) => p[0])), Math.min(...pts.map((p) => p[1])), Math.max(...pts.map((p) => p[1]))];
  const pad = (a, b) => { const s = (b - a) || 1; return [a - s * 0.08, b + s * 0.08]; };
  [x0, x1] = pad(x0, x1); [y0, y1] = pad(y0, y1);
  requestAnimationFrame(() => drawPlot($("draw"), { xmin: x0, xmax: x1, ymin: y0, ymax: y1 }, d.map((x, i) => ({ ...x, color: x.color || COLORS[i % COLORS.length] }))));
}
function syncGutter() {
  const n = $("code").value.split("\n").length;
  $("gutter").textContent = Array.from({ length: n }, (_, i) => i + 1).join("\n");
  $("gutter").scrollTop = $("code").scrollTop;
}
// ---------- mode jeu ----------
async function playProgram() {
  status("lancement du jeu…");
  try {
    const r = await call("game_run", { code: $("code").value });
    if (!r.ok) { $("console").replaceChildren(el("span", { class: "err" }, r.error)); status("refusé"); return; }
    const stop = el("button", { type: "button", class: "small" }, "Arrêter le jeu");
    stop.addEventListener("click", () => call("game_stop").catch(() => {}));
    $("console").replaceChildren(el("span", { class: "note" }, "Jeu lancé dans sa fenêtre (Échap ou fermer la fenêtre pour quitter).\n"), stop);
    status("jeu en cours");
    clearInterval(S.prog.gameTimer);
    S.prog.gameTimer = setInterval(async () => {
      let st;
      try { st = await call("game_status"); } catch { clearInterval(S.prog.gameTimer); return; }
      if (st.running) return;
      clearInterval(S.prog.gameTimer);
      const failed = Boolean(st.exit_code) && !st.stopped;
      const end = st.stopped ? "— partie arrêtée —" : failed ? "— le jeu s'est arrêté sur une erreur —" : "— partie terminée —";
      $("console").replaceChildren(el("span", { class: failed ? "err" : "" }, st.output || ""), el("span", { class: "note" }, `\n${end}\n`));
      status(st.stopped ? "arrêté" : failed ? "erreur" : "terminé");
    }, 1000);
  } catch (e) { consoleLine(`\n${e.message}\n`, "err"); status("erreur"); }
}

// ---------- import / export ----------
function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = el("a", { href: url, download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
function exportProgram(kind) {
  const name = ($("prog-name").value.trim() || "programme").replace(/[^\wÀ-ÿ-]/g, "_");
  const code = $("code").value;
  if (kind === "py") { download(`${name}.py`, code, "text/x-python"); return; }
  const pack = { format: "aether-programme", version: 1, nom: name, cree: new Date().toISOString(),
                 application: "Æther CAS", jeu: usesGame(code), code };
  download(`${name}.aether`, JSON.stringify(pack, null, 2), "application/json");
}
function importProgram(file) {
  if (!file) return;
  if (file.size > 200000) { toast("Fichier trop gros (200 Ko au plus)"); return; }
  file.text().then((text) => {
    let name = file.name.replace(/\.(py|aether|json|txt)$/i, ""), code = text;
    if (/\.(aether|json)$/i.test(file.name)) {
      try {
        const pack = JSON.parse(text);
        if (pack.format !== "aether-programme" || typeof pack.code !== "string") throw new Error("format");
        code = pack.code; name = String(pack.nom || name);
      } catch { toast("Fichier .aether illisible", 3000); return; }
    }
    name = name.replace(/[^\wÀ-ÿ]/g, "_").replace(/^[^A-Za-zÀ-ÿ]+/, "").slice(0, 40) || "importe";
    openProgram(name, code, true);
    status("importé (non enregistré)");
  });
}
function fileMenu() {
  openMenu("Fichier", [
    { label: "Importer un programme", hint: ".py ou .aether", act: () => { $("prog-import").value = ""; $("prog-import").click(); } },
    { label: "Exporter en .py", hint: "le code seul", act: () => exportProgram("py") },
    { label: "Exporter en .aether", hint: "code + informations (JSON)", act: () => exportProgram("aether") },
  ], runItem);
}

// ---------- émulateurs externes ----------
function dialog(title, ...content) {
  closeMenu();
  const close = el("button", { type: "button", "aria-label": "Fermer" }, "✕");
  const overlay = el("div", { class: "overlay" }, el("div", { class: "menu dialog", role: "dialog", "aria-label": title },
    el("h3", {}, title, close), el("div", { class: "body" }, ...content)));
  close.addEventListener("click", closeMenu);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) closeMenu(); });
  document.body.append(overlay);
  S.menu = { node: overlay, move() {}, ok() {}, digit() {} };
}
async function emulatorsDialog() {
  let cat;
  try { cat = await call("emulators"); } catch (e) { toast(e.message, 3000); return; }
  const installed = cat.emulators.filter((x) => x.path);
  const sys = Object.fromEntries(cat.systems.map((s) => [s.id, s]));
  const names = (ids) => ids.map((s) => sys[s]?.label || s).join(" / ");
  const roms = cat.roms.map((rom) => {
    const able = installed.filter((x) => x.systems.some((s) => rom.systems.includes(s)));
    const pick = el("select", { "aria-label": "Émulateur" }, ...able.map((x) => el("option", { value: x.id }, x.label)));
    const go = el("button", { type: "button", class: "small" }, "Lancer");
    go.disabled = !able.length;
    go.addEventListener("click", async () => {
      try { await call("emulator_launch", { emulator: pick.value, rom: rom.file }); toast(`${rom.file} lancé`); }
      catch (e) { toast(e.message, 3500); }
    });
    return el("tr", {}, el("td", {}, rom.file), el("td", {}, names(rom.systems)),
      el("td", {}, able.length ? pick : "aucun émulateur installé"), el("td", {}, go));
  });
  const emus = cat.emulators.map((x) => el("tr", {}, el("td", {}, x.label),
    el("td", {}, x.systems.length > 6 ? "tous (cœurs RetroArch)" : names(x.systems)),
    el("td", { class: x.path ? "ok" : "no" }, x.path ? "installé" : "non trouvé")));
  const tiers = cat.systems.map((s) => el("tr", {}, el("td", {}, s.label), el("td", {}, s.extensions.join(" ")), el("td", {}, s.tier)));
  const folder = el("button", { type: "button", class: "small" }, "Ouvrir le dossier des ROM");
  folder.addEventListener("click", () => call("roms_open").catch((e) => toast(e.message)));
  const refresh = el("button", { type: "button", class: "small" }, "Actualiser");
  refresh.addEventListener("click", emulatorsDialog);
  dialog("Émulateurs externes",
    el("p", {}, "Aucune ROM ni aucun BIOS n'est fourni. Mets dans le dossier des ROM uniquement des jeux libres (homebrew) ou des copies de tes propres jeux."),
    el("div", { class: "row" }, folder, refresh),
    el("h4", {}, `Fichiers du dossier (${cat.roms.length})`),
    cat.roms.length ? el("table", {}, el("tbody", {}, ...roms)) : el("p", {}, `Dossier vide : ${cat.folder}`),
    el("h4", {}, `Émulateurs (${installed.length} installé${installed.length > 1 ? "s" : ""})`),
    el("table", {}, el("tbody", {}, ...emus)),
    el("p", {}, "Installé ailleurs ? Indique son chemin dans config/local.yaml : calc_cas → emulators → id: chemin du .exe."),
    el("h4", {}, "Systèmes et puissance demandée (repère : téléphone type Galaxy S10+)"),
    el("table", {}, el("tbody", {}, ...tiers)));
}

function progHelp() {
  openMenu("Bac à sable Python", [
    { label: "print(…), input(\"question\")", hint: "input : la question s'affiche dans la console" },
    { label: "import math, cmath, random, statistics", hint: "les seuls modules disponibles" },
    { label: "cas(\"integrate(x^2, x)\")", hint: "résultat exact du moteur, en texte" },
    { label: "cas_value(\"sqrt(2)\")", hint: "valeur numérique Python" },
    { label: "plot(xs, ys) · scatter(xs, ys) · fplot(f, a, b) · text(x, y, s)", hint: "dessin à droite de la console" },
    { label: "Interdit : fichiers, réseau, os/sys, classes, noms « _… »", hint: `délai ${10} s, mémoire bornée` },
    { isGroup: true, label: "Mode jeu : import jeu (bouton Jouer)" },
    { label: "jeu.fenetre(480, 360, \"titre\")", hint: "ouvre la fenêtre de jeu" },
    { label: "while jeu.image(30):", hint: "une image (30 par seconde) ; faux quand on ferme ou Échap" },
    { label: "jeu.effacer(c) · rect(x, y, l, h, c) · cercle(x, y, r, c)", hint: "c = « rouge », (r, g, b) ou « #rrggbb »" },
    { label: "jeu.ligne(x1, y1, x2, y2, c) · polygone(points, c) · texte(x, y, s, c, taille)", hint: "dessin" },
    { label: "jeu.touche(\"gauche\") · jeu.appuyee(\"espace\")", hint: "maintenue / enfoncée à cette image" },
    { label: "jeu.souris() · jeu.temps() · jeu.largeur() · jeu.hauteur()", hint: "(x, y, bouton), secondes écoulées" },
    { label: "Exemples : Programmes → Jeux", hint: "snake, pong, tetris, labyrinthe_3d" },
  ], () => {});
}

// ---------- clavier ----------
// [principal, secondaire (2nde), action principale, action secondaire, classe]
const I = (t) => ({ ins: t });
const SYS = [
  ["2nde", "", { mod: "second" }, null, "mod-second small-text"], ["abc", "ABC", { mod: "alpha" }, null, "mod-alpha small-text"],
  ["esc", "", { fn: "esc" }, null, "small-text"], ["menu", "catalogue", { fn: "menu" }, { fn: "catalog" }, "small-text"],
  ["tab", "◂ tab", { fn: "tab" }, { fn: "tabBack" }, "small-text"], ["⌫", "effacer", { fn: "del" }, { fn: "clear" }, "small-text"],
];
const NAV_LEFT = [["var", "sto→", { fn: "vars" }, I(" → "), "small-text"], ["mode", "deg/rad", { fn: "mode" }, { fn: "angle" }, "small-text"]];
const NAV_RIGHT = [["ans", "rappel", I("ans"), { fn: "recall" }, "small-text"], ["x,t,θ", "y", { fn: "xvar" }, I("y"), "small-text"]];
const MAIN = [
  ["=", ":=", I("="), I(" := "), "op"], ["sin", "sin⁻¹", I("sin()"), I("asin()"), "small-text"], ["cos", "cos⁻¹", I("cos()"), I("acos()"), "small-text"],
  ["tan", "tan⁻¹", I("tan()"), I("atan()"), "small-text"], ["π", "e", I("pi"), I("e"), ""], ["i", "∞", I("i"), I("oo"), ""],
  ["x²", "√", I("^2"), I("sqrt()"), ""], ["^", "ⁿ√", I("^"), I("root()"), ""], ["7", "", I("7"), null, "num"], ["8", "", I("8"), null, "num"],
  ["9", "", I("9"), null, "num"], ["÷", "mod", I("/"), I("mod()"), "op"],
  ["eˣ", "ln", I("e^()"), I("ln()"), ""], ["10ˣ", "log", I("10^()"), I("log()"), ""], ["4", "", I("4"), null, "num"], ["5", "", I("5"), null, "num"],
  ["6", "", I("6"), null, "num"], ["×", "!", I("*"), I("!"), "op"],
  ["(", "[", I("("), I("["), ""], [")", "]", I(")"), I("]"), ""], ["1", "", I("1"), null, "num"], ["2", "", I("2"), null, "num"],
  ["3", "", I("3"), null, "num"], ["−", "<", I("-"), I("<"), "op"],
  [",", ";", I(", "), I("; "), ""], ["|x|", "\"", I("abs()"), I("\""), "small-text"], ["0", "", I("0"), null, "num"], [".", "EE", I("."), I("*10^"), "num"],
  ["(−)", "≈", I("-"), { fn: "approx" }, "num small-text"], ["+", ">", I("+"), I(">"), "op"],
  ["d/dx", "∫", I("diff()"), I("integrate()"), "small-text"], ["Σ", "lim", I("sum()"), I("limit()"), ""], ["solve", "factor", I("solve()"), I("factor()"), "small-text"],
  ["[[ ]]", "det", I("[[ , ], [ , ]]"), I("det()"), "small-text"], ["entrée", "≈", { fn: "enter" }, { fn: "approx" }, "enter"],
];
const LETTERS = "abcdefghijklmnopqrstuvwxyz".split("").concat(["θ", "_", "\"", ":", "␣", "→", "'", "?", "%", "#"]);

function keyButton([main, sec, act, sact, cls]) {
  const b = el("button", { type: "button", class: `key ${cls || ""}`, "aria-label": sec ? `${main} (2nde : ${sec})` : main },
    sec ? el("span", { class: "sec" }, sec) : null, el("span", {}, main));
  b.addEventListener("pointerdown", (e) => e.preventDefault());  // garde le curseur dans le champ actif
  b.addEventListener("click", () => press(act, sact));
  return b;
}
function renderKeys() {
  $("keys-sys").replaceChildren(...SYS.map(keyButton));
  $("nav-left").replaceChildren(...NAV_LEFT.map(keyButton));
  $("nav-right").replaceChildren(...NAV_RIGHT.map(keyButton));
  if (S.alpha) {
    $("keys-main").replaceChildren(...LETTERS.map((l) => keyButton([S.second ? l.toUpperCase() : l, "", I(l === "␣" ? " " : S.second ? l.toUpperCase() : l), null, "num"])));
  } else $("keys-main").replaceChildren(...MAIN.map(keyButton));
  badges();
}
function press(act, sact) {
  if (act.mod === "second") { S.second = !S.second; renderKeys(); return; }
  if (act.mod === "alpha") { S.alpha = !S.alpha; if (S.second) S.second = false; renderKeys(); return; }
  const a = S.second && sact ? sact : act;
  const wasSecond = S.second;
  if (S.second) { S.second = false; renderKeys(); }
  if (a.ins !== undefined) {
    if (S.menu || (S.app === "geo" && !S.field)) return;
    insert(a.ins);
    if (S.alpha && !wasSecond) { /* abc reste verrouillé : esc ou abc pour sortir */ }
    return;
  }
  ACTIONS[a.fn]?.();
}
const ACTIONS = {
  esc() {
    if (S.menu) { closeMenu(); return; }
    if (S.alpha) { S.alpha = false; renderKeys(); return; }
    if (S.app === "graph") { if (S.graph.panel) panel(null); else if (S.graph.trace) graphTool("trace"); else { S.graph.marks = []; drawGraph(); } return; }
    if (S.app === "calc") { S.sel = -1; markSel(); clearField(); }
    if (S.app === "geo") geoEsc();
  },
  menu: contextMenu, catalog,
  tab() { showApp(APPS[(APPS.indexOf(S.app) + 1) % APPS.length]); },
  tabBack() { showApp(APPS[(APPS.indexOf(S.app) + APPS.length - 1) % APPS.length]); },
  del() { if (S.app === "geo") geoDeleteSelected(); else backspace(); }, clear: clearField, vars: showVars, mode: cycleMode, angle: toggleAngle,
  recall() { const last = S.inputs[S.inputs.length - 1]; if (last) { $("line").value = last; $("line").focus(); } },
  xvar() {
    const f = S.graph.fns[S.graph.cur];
    insert(S.app === "graph" && f?.kind === "param" ? "t" : S.app === "graph" && f?.kind === "polar" ? "theta" : "x");
  },
  enter() {
    if (S.menu) { S.menu.ok(); return; }
    if (S.app === "calc") { if (S.sel >= 0 && !$("line").value.trim()) { pasteEntry(S.sel); S.sel = -1; markSel(); } else evaluate($("line").value); }
    else if (S.app === "graph") plotAll();
    else if (S.app === "sheet") cellMove(1, 0);
    else if (S.app === "geo") geoNav("ok");
    else if (S.app === "prog") { if (document.activeElement === $("code") || S.field === $("code")) insertNewline(); else runProgram(); }
  },
  approx() { if (S.app === "calc") evaluate($("line").value, true); else if (S.app === "prog") runProgram(); },
};
function nav(dir) {
  if (S.menu) { if (dir === "up") S.menu.move(-1); else if (dir === "down") S.menu.move(1); else if (dir === "ok") S.menu.ok(); return; }
  if (S.app === "calc") {
    if (dir === "up") historyNav(-1); else if (dir === "down") historyNav(1);
    else if (dir === "left") moveCaret(-1); else if (dir === "right") moveCaret(1);
    else if (dir === "ok") { if (S.sel >= 0) { pasteEntry(S.sel, S.second ? "result" : "input"); S.sel = -1; markSel(); } else evaluate($("line").value); }
  } else if (S.app === "graph") {
    const tr = S.graph.trace;
    if (tr) {
      if (dir === "left" || dir === "right") tr.i = (tr.i ?? 0) + (dir === "left" ? -1 : 1) * (S.second ? 20 : 3);
      else if (dir === "up" || dir === "down") { tr.c += dir === "up" ? -1 : 1; tr.i = null; }
      else if (dir === "ok") { const p = tracePoint(); if (p) toast(`f${p.fn + 1}(${fmt(p.x)}) = ${fmt(p.y)}`); }
      drawGraph();
    } else ({ left: () => pan(-0.1, 0), right: () => pan(0.1, 0), up: () => pan(0, 0.1), down: () => pan(0, -0.1), ok: plotAll })[dir]();
  } else if (S.app === "sheet") ({ up: () => cellMove(-1, 0), down: () => cellMove(1, 0), left: () => cellMove(0, -1), right: () => cellMove(0, 1), ok: () => cellMove(1, 0) })[dir]();
  else if (S.app === "geo") geoNav(dir);
  else if (S.app === "prog") { if (dir === "left") moveCaret(-1); else if (dir === "right") moveCaret(1); else if (dir === "ok") runProgram(); }
}
function insertNewline() {
  const t = $("code"), a = t.selectionStart, line = t.value.slice(0, a).split("\n").pop();
  let indent = line.match(/^\s*/)[0];
  if (/:\s*$/.test(line)) indent += "    ";
  S.field = t; insert(`\n${indent}`);
}

// ---------- clavier physique ----------
document.addEventListener("keydown", (e) => {
  if (S.menu) {
    if (e.key === "Escape") { e.preventDefault(); closeMenu(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); S.menu.move(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); S.menu.move(-1); }
    else if (e.key === "Enter") { e.preventDefault(); S.menu.ok(); }
    else if (/^[1-9]$/.test(e.key) && e.altKey) { e.preventDefault(); S.menu.digit(Number(e.key)); }
    return;
  }
  if (e.ctrlKey && /^[1-5]$/.test(e.key)) { e.preventDefault(); showApp(APPS[Number(e.key) - 1]); return; }
  if (e.key === "F2") { e.preventDefault(); toggleKeys(); return; }
  if (e.key === "F1" || (e.ctrlKey && e.key.toLowerCase() === "m")) { e.preventDefault(); contextMenu(); return; }
  if (e.ctrlKey && e.key.toLowerCase() === "k") { e.preventDefault(); catalog(); return; }
  if (e.key === "Escape") { e.preventDefault(); ACTIONS.esc(); return; }
  const t = e.target;
  if (S.app === "calc" && t === $("line")) {
    if (e.key === "ArrowUp") { e.preventDefault(); historyNav(-1); }
    else if (e.key === "ArrowDown") { e.preventDefault(); historyNav(1); }
    else if (e.key === "Enter") { e.preventDefault(); ACTIONS.enter(); if (e.shiftKey) { /* déjà traité */ } }
    return;
  }
  if (S.app === "prog") {
    if (e.ctrlKey && e.key === "Enter") { e.preventDefault(); runProgram(); return; }
    if (e.ctrlKey && e.key.toLowerCase() === "s") { e.preventDefault(); saveProgram(); return; }
    if (t === $("code") && e.key === "Tab") { e.preventDefault(); S.field = t; insert("    "); return; }
    if (t === $("code") && e.key === "Enter") { e.preventDefault(); insertNewline(); return; }
  }
  if (S.app === "geo" && !["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) {
    if (e.ctrlKey && e.key.toLowerCase() === "z") { e.preventDefault(); geoUndo(); return; }
    if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); geoDeleteSelected(); return; }
    if (e.key.startsWith("Arrow")) { e.preventDefault(); geoNav(e.key.slice(5).toLowerCase()); return; }
  }
  if (S.app === "graph" && S.graph.trace && !["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) && e.key.startsWith("Arrow")) {
    e.preventDefault(); nav(e.key.slice(5).toLowerCase());
  }
  if (S.app === "graph" && t.tagName !== "INPUT" && (e.key === "+" || e.key === "-")) { e.preventDefault(); zoom(e.key === "+" ? 0.8 : 1.25); }
});
// Maj+Entrée dans la ligne de calcul : valeur approchée
$("line").addEventListener("keydown", (e) => { if (e.key === "Enter" && e.shiftKey) { e.stopPropagation(); e.preventDefault(); evaluate($("line").value, true); } }, true);

function toggleKeys() {
  const d = $("device"); d.classList.toggle("no-keys"); $("pad").hidden = d.classList.contains("no-keys");
  store.set("keys", !d.classList.contains("no-keys"));
  requestAnimationFrame(() => { drawGraph(); drawProgram(); if (S.app === "geo") geoDraw(); });
}

// ---------- démarrage ----------
(async function start() {
  if (store.get("keys", true) === false) { $("device").classList.add("no-keys"); $("pad").hidden = true; }
  if (store.get("dark", false)) document.documentElement.dataset.screen = "dark";
  renderKeys(); renderFns(); renderSheet(); bindPlot();
  for (const b of document.querySelectorAll("#apps button")) b.addEventListener("click", () => showApp(b.dataset.app));
  for (const b of document.querySelectorAll("[data-nav]")) {
    b.addEventListener("pointerdown", (e) => e.preventDefault());
    b.addEventListener("click", () => nav(b.dataset.nav));
  }
  for (const b of document.querySelectorAll("[data-g]")) b.addEventListener("click", () => graphTool(b.dataset.g));
  $("line-form").addEventListener("submit", (e) => { e.preventDefault(); evaluate($("line").value); });
  $("badge-angle").addEventListener("click", toggleAngle);
  $("badge-mode").addEventListener("click", cycleMode);
  $("toggle-keys").addEventListener("click", toggleKeys);
  $("toggle-screen").addEventListener("click", () => {
    const dark = document.documentElement.dataset.screen !== "dark";
    if (dark) document.documentElement.dataset.screen = "dark"; else delete document.documentElement.dataset.screen;
    store.set("dark", dark); drawGraph(); drawProgram(); if (S.app === "geo") geoDraw();
  });
  $("st-1").addEventListener("click", () => sheetStats(false)); $("st-2").addEventListener("click", () => sheetStats(true));
  $("st-reg").addEventListener("click", regress); $("st-cas").addEventListener("click", sheetToCas);
  $("st-demo").addEventListener("click", sheetDemo); $("st-clear").addEventListener("click", sheetClear);
  $("prog-run").addEventListener("click", () => runProgram()); $("prog-save").addEventListener("click", saveProgram);
  $("prog-new").addEventListener("click", newProgram); $("prog-del").addEventListener("click", deleteProgram);
  $("prog-help").addEventListener("click", progHelp);
  $("prog-play").addEventListener("click", playProgram);
  $("prog-file").addEventListener("click", fileMenu);
  $("prog-emu").addEventListener("click", emulatorsDialog);
  $("prog-import").addEventListener("change", (e) => importProgram(e.target.files[0]));
  $("code").addEventListener("input", () => { S.prog.dirty = true; syncGutter(); status("modifié"); });
  $("code").addEventListener("scroll", () => { $("gutter").scrollTop = $("code").scrollTop; });
  new ResizeObserver(() => { if (S.app === "graph") drawGraph(); if (S.app === "geo") geoDraw(); if (S.app === "prog") drawProgram(); }).observe($("device"));
  window.addEventListener("beforeunload", (e) => { if (S.prog.dirty && $("code").value.trim() && S.prog.name in S.prog.programs) e.preventDefault(); });
  showApp(APPS.includes(S.app) ? S.app : "calc");
  badges();
  try {
    const [hist, settings] = await Promise.all([call("history"), call("settings", {})]);
    S.history = hist; S.inputs = hist.map((h) => h.input); S.angle = settings.angle || "rad";
    renderHistory(); badges(); renderMissing(S.history);
  } catch (e) { $("history").replaceChildren(el("div", { class: "empty" }, e.message)); }
})();
