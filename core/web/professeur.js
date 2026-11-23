"use strict";
// Le Professeur : programmes de l'année, cours, schémas, exercices corrigés et simulations.
// Dépend de dashboard.js (chargé avant) : $, el, api, post, modulesByName.

const SVG_NS = "http://www.w3.org/2000/svg";
const prof = { levels: [], level: "", subject: "", programme: null, chapter: "", lesson: null, prepTimer: 0 };

function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  for (const child of children) node.append(child instanceof Node ? child : String(child ?? ""));
  return node;
}

function remember(key, value) {
  try { if (value === undefined) return localStorage.getItem(`prof.${key}`) || ""; localStorage.setItem(`prof.${key}`, value); }
  catch { /* stockage indisponible : sans importance */ }
  return "";
}

// ---------- appels au module ----------
async function profCall(command, payload, button, box) {
  if (button) button.disabled = true;
  try {
    if (!modulesByName.genesis_lab || !modulesByName.genesis_lab.running) {
      await post("/modules/genesis_lab/activate");
    }
    const reply = await post(`/modules/genesis_lab/command/${command}`, payload || {});
    if (!reply.ok) throw new Error((reply.error || "erreur du module").replace(/^\w+Error: /, ""));
    return reply.result;
  } catch (error) {
    if (box) { box.hidden = false; box.replaceChildren(el("p", { class: "warn" }, `Erreur : ${error.message}`)); }
    return null;
  } finally {
    if (button) button.disabled = false;
  }
}

// Un travail du modèle local (rédaction, correction…) : on suit son état jusqu'au résultat.
async function waitJob(job, statusBox) {
  let current = job;
  while (current && current.en_cours) {
    if (statusBox) {
      statusBox.hidden = false;
      statusBox.replaceChildren(el("p", { class: "muted" },
        `${current.libelle}… ${Math.round(current.duree || 0)} s (le modèle local travaille ; un cours complet `
        + "peut prendre quelques minutes)"));
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
    current = await profCall("travail", { cle: current.cle }, null, statusBox);
  }
  if (!current) return null;
  if (current.erreur) {
    if (statusBox) { statusBox.hidden = false; statusBox.replaceChildren(el("p", { class: "warn" }, `Erreur : ${current.erreur}`)); }
    return null;
  }
  if (statusBox) statusBox.replaceChildren();
  return current.resultat;
}

// ---------- niveaux, matières, programme ----------
async function profInit() {
  if (prof.levels.length) return;
  const result = await profCall("niveaux", {}, null, $("prof-programme"));
  if (!result) return;
  prof.levels = result.niveaux;
  $("prof-level").replaceChildren(...prof.levels.map((n) => el("option", { value: n.id }, `${n.nom} (${n.cycle})`)));
  const saved = remember("level");
  if (prof.levels.some((n) => n.id === saved)) $("prof-level").value = saved;
  fillSubjects();
  if (!result.modele) {
    $("prof-status").textContent = "Modèle local injoignable : les cours déjà préparés restent lisibles.";
  }
}

function fillSubjects() {
  const level = prof.levels.find((n) => n.id === $("prof-level").value) || prof.levels[0];
  if (!level) return;
  $("prof-subject").replaceChildren(...level.matieres.map((m) => el("option", { value: m.id }, `${m.nom} (${m.chapitres} chap.)`)));
  const saved = remember("subject");
  if (level.matieres.some((m) => m.id === saved)) $("prof-subject").value = saved;
  loadProgramme();
}

async function loadProgramme() {
  prof.level = $("prof-level").value;
  prof.subject = $("prof-subject").value;
  remember("level", prof.level);
  remember("subject", prof.subject);
  const box = $("prof-programme");
  const data = await profCall("programme", { niveau: prof.level, matiere: prof.subject }, null, box);
  if (!data) return;
  prof.programme = data;
  renderProgramme(data);
}

const STATUS_CLASS = { acquis: "good", "à revoir": "badans", "en cours": "warn" };

function renderProgramme(data) {
  const box = $("prof-programme");
  const prep = data.preparation;
  let prepText = `${data.prepares} cours préparés sur ${data.chapitres}, ${data.acquis} chapitres acquis.`;
  if (prep && prep.en_cours) prepText += ` Préparation de l'année : ${prep.faits}/${prep.total}…`;
  else if (prep && prep.total) prepText += ` Préparation terminée (${prep.faits}/${prep.total}${prep.erreurs.length ? `, ${prep.erreurs.length} échec(s)` : ""}).`;
  $("prof-status").textContent = prepText;
  clearTimeout(prof.prepTimer);
  if (prep && prep.en_cours) prof.prepTimer = setTimeout(loadProgramme, 15000);
  const blocks = [el("p", { class: "muted" }, `${data.niveau_nom} — ${data.matiere_nom}. ${data.source || ""}`)];
  for (const term of data.trimestres) {
    blocks.push(el("h3", {}, `${term.nom} (${term.mois}, semaines ${term.semaines})`));
    const rows = term.chapitres.map((c) => {
      const p = c.progression || {};
      const state = p.statut
        ? el("span", { class: STATUS_CLASS[p.statut] || "" }, `${p.statut} (${Math.round(100 * (p.dernier_taux || 0))} %)`)
        : el("span", { class: "muted" }, c.prepare ? "cours prêt" : "à préparer");
      const open = el("button", { type: "button", class: c.prepare ? "small" : "small ghost" }, c.prepare ? "Ouvrir" : "Préparer");
      open.addEventListener("click", () => openLesson(c.id, {}, open));
      const sims = (c.simulations || []).length ? el("span", { class: "muted" }, " · simulation") : "";
      return el("tr", {}, el("td", { class: "nowrap muted" }, `sem. ${c.semaines}`),
        el("td", {}, el("b", {}, `${c.numero}. ${c.titre}`), sims, el("br"), el("span", { class: "muted" }, c.notions)),
        el("td", { class: "nowrap" }, state), el("td", {}, open));
    });
    blocks.push(el("table", { class: "prog" }, el("tbody", {}, ...rows)));
  }
  box.hidden = false;
  box.replaceChildren(...blocks);
}

// ---------- le cours ----------
async function openLesson(chapterId, options = {}, button = null) {
  prof.chapter = chapterId;
  const section = $("prof-lesson-box");
  section.hidden = false;
  const status = $("prof-lesson-status");
  const result = await profCall("cours", { chapitre: chapterId, ...options }, button, status);
  if (!result) return;
  let lesson = result.cours;
  if (!result.pret) {
    $("prof-lesson").replaceChildren();
    section.scrollIntoView({ behavior: "smooth", block: "start" });
    lesson = await waitJob(result.travail, status);
    if (!lesson) return;
    loadProgramme();
  }
  showLesson(lesson);
  section.scrollIntoView({ behavior: "smooth", block: "start" });
}

function paragraphs(text) {
  return String(text || "").split(/\n+/).filter(Boolean).map((line) => el("p", {}, line));
}

function showLesson(data) {
  prof.lesson = data;
  const c = data.chapitre;
  const l = data.lecon;
  $("prof-lesson-status").replaceChildren();
  $("prof-prev").disabled = !c.precedent;
  $("prof-next").disabled = !c.suivant;
  const parts = [
    el("h2", {}, l.titre),
    el("p", { class: "muted" }, `${c.niveau_nom} — ${c.matiere_nom} — chapitre ${c.numero} — version ${data.version}`
      + (data.simple ? " (version simplifiée)" : "")),
  ];
  if (l.objectifs.length) parts.push(el("h3", {}, "Objectifs"), el("ul", {}, ...l.objectifs.map((o) => el("li", {}, o))));
  if (l.prerequis.length) parts.push(el("h3", {}, "Ce qu'il faut déjà savoir"), el("ul", {}, ...l.prerequis.map((o) => el("li", {}, o))));
  for (const s of l.sections) parts.push(el("h3", { class: "lesson-h" }, s.titre), ...paragraphs(s.texte));
  if (l.schema) parts.push(el("h3", {}, `Schéma : ${l.schema.titre || ""}`), renderSchema(l.schema));
  if (l.a_retenir.length) {
    parts.push(el("div", { class: "retenir" }, el("b", {}, "À retenir"), el("ul", {}, ...l.a_retenir.map((o) => el("li", {}, o)))));
  }
  if (l.exemple && l.exemple.enonce) {
    parts.push(el("h3", {}, "Exemple corrigé"), ...paragraphs(l.exemple.enonce),
      el("details", {}, el("summary", {}, "Voir la solution"), ...paragraphs(l.exemple.solution)));
  }
  if (l.vocabulaire.length) {
    parts.push(el("h3", {}, "Vocabulaire"),
      el("dl", { class: "vocab" }, ...l.vocabulaire.flatMap((v) => [el("dt", {}, v.mot), el("dd", {}, v.definition)])));
  }
  if ((data.simulations || []).length) {
    const row = el("div", { class: "row" }, el("span", { class: "muted" }, "Simulations :"));
    for (const sim of data.simulations) {
      const b = el("button", { type: "button", class: "ghost" }, sim.titre);
      b.addEventListener("click", () => showSim(sim.id, sim.titre));
      row.append(b);
    }
    parts.push(row);
  }
  parts.push(el("h3", {}, "Exercices"), exerciseForm(l.exercices, "Corriger"));
  for (const serie of data.series || []) {
    parts.push(el("h3", {}, `Série ${serie.numero + 1} (difficulté ${serie.difficulte})`), exerciseForm(serie.exercices, "Corriger la série"));
  }
  if (l.pour_aller_plus_loin) parts.push(el("h3", {}, "Pour aller plus loin"), ...paragraphs(l.pour_aller_plus_loin));
  if ((data.sources || []).length) {
    const list = el("ul", { class: "muted" });
    for (const s of data.sources) {
      list.append(el("li", {}, s.url ? el("a", { href: s.url, target: "_blank", rel: "noopener noreferrer" }, s.title || s.url) : s.title,
        ` — ${s.origine || ""}${s.license ? `, ${s.license}` : ""}`));
    }
    parts.push(el("h3", {}, "Sources"), list);
  }
  if (data.verification) {
    const v = data.verification;
    parts.push(el("details", { class: "verif" }, el("summary", { class: v.correct ? "good" : "warn" },
      v.correct ? "Relu par Hermes : correct" : "Relu par Hermes : corrections signalées (prises en compte à la prochaine réécriture)"),
    ...paragraphs(v.texte)));
  }
  if ((data.notes || []).length) parts.push(el("p", { class: "muted" }, `${data.notes.length} remarque(s) prise(s) en compte pour améliorer ce cours.`));
  if (data.progression && data.progression.statut) {
    const p = data.progression;
    parts.push(el("p", { class: STATUS_CLASS[p.statut] || "" }, `Progression : ${p.statut} — dernier score ${Math.round(100 * p.dernier_taux)} %, `
      + `${p.essais} essai(s), difficulté conseillée ${p.difficulte}/3.`));
  }
  $("prof-lesson").replaceChildren(...parts);
  $("sim-chapter-label").textContent = `rattacher au chapitre « ${c.titre} »`;
  $("sim-chapter-row").hidden = false;
}

// ---------- exercices ----------
function exerciseForm(exercises, label) {
  const form = el("form", { class: "exercises" });
  exercises.forEach((ex, i) => {
    const block = el("div", { class: "exercise", "data-id": ex.id, "data-type": ex.type },
      el("p", { class: "question" }, `${i + 1}. `, ex.enonce, el("span", { class: "muted" }, `  (${"★".repeat(ex.difficulte || 1)})`)));
    if (ex.type === "qcm") {
      ex.choix.forEach((choice, k) => {
        block.append(el("label", { class: "choice" }, el("input", { type: "radio", name: `q-${ex.id}`, value: String(k) }), ` ${choice}`));
      });
    } else if (ex.type === "redaction") {
      block.append(el("textarea", { rows: "4", name: `q-${ex.id}`, placeholder: "Ta réponse rédigée" }));
    } else {
      block.append(el("div", { class: "row" }, el("input", { name: `q-${ex.id}`, autocomplete: "off",
        placeholder: ex.type === "nombre" ? "Un nombre" : "Ta réponse" }), el("span", { class: "muted" }, ex.unite || "")));
    }
    block.append(el("div", { class: "feedback" }));
    form.append(block);
  });
  const submit = el("button", { type: "submit" }, label);
  const result = el("div", { class: "answer", hidden: "" });
  form.append(el("div", { class: "row" }, submit), result);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const answers = {};
    for (const block of form.querySelectorAll(".exercise")) {
      const id = block.dataset.id;
      const field = block.dataset.type === "qcm"
        ? form.querySelector(`input[name="q-${id}"]:checked`) : form.querySelector(`[name="q-${id}"]`);
      if (field && field.value.trim() !== "") answers[id] = block.dataset.type === "qcm" ? Number(field.value) : field.value;
    }
    if (!Object.keys(answers).length) { result.hidden = false; result.textContent = "Réponds à au moins une question."; return; }
    const started = await profCall("corriger", { chapitre: prof.chapter, reponses: answers }, submit, result);
    if (!started) return;
    const graded = await waitJob(started.travail, result);
    if (!graded) return;
    for (const r of graded.resultats) {
      const block = form.querySelector(`.exercise[data-id="${r.id}"] .feedback`);
      if (!block) continue;
      block.replaceChildren(
        el("p", { class: r.juste ? "good" : "badans" }, r.juste ? "Juste !" : (r.score > 0 ? `En partie (${Math.round(100 * r.score)} %)` : "Pas encore")),
        r.juste ? "" : el("p", {}, `Réponse attendue : ${r.attendu}`),
        r.commentaire ? el("p", {}, r.commentaire) : "",
        r.explication ? el("p", { class: "muted" }, r.explication) : "");
    }
    result.hidden = false;
    result.replaceChildren(el("b", {}, `Score : ${Math.round(100 * graded.taux)} %`), el("p", {}, graded.conseil));
    loadProgramme();
  });
  return form;
}

// ---------- schémas (dessinés ici, à partir des données vérifiées par le Hub) ----------
function wrapLines(text, width) {
  const words = String(text || "").split(/\s+/);
  const lines = [];
  let line = "";
  for (const word of words) {
    if ((line + " " + word).trim().length > width && line) { lines.push(line); line = word; }
    else line = (line + " " + word).trim();
  }
  if (line) lines.push(line);
  return lines.slice(0, 5);
}

function svgText(x, y, text, width, attrs = {}) {
  const lines = wrapLines(text, width);
  const node = svg("text", { x, y: y - (lines.length - 1) * 8, "text-anchor": "middle", ...attrs });
  lines.forEach((line, i) => node.append(svg("tspan", { x, dy: i ? 16 : 0 }, line)));
  return node;
}

function arrow(x1, y1, x2, y2) {
  return svg("line", { x1, y1, x2, y2, class: "arrow", "marker-end": "url(#prof-arrow)" });
}

function defs() {
  return svg("defs", {}, svg("marker", { id: "prof-arrow", viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "7",
    markerHeight: "7", orient: "auto-start-reverse" }, svg("path", { d: "M0,0 L10,5 L0,10 z", class: "arrow-head" })));
}

function renderSchema(s) {
  if (s.type === "comparaison") {
    return el("table", { class: "schema-table" }, el("thead", {}, el("tr", {}, ...s.colonnes.map((c) => el("th", {}, c)))),
      el("tbody", {}, ...s.lignes.map((row) => el("tr", {}, ...row.map((cell) => el("td", {}, cell))))));
  }
  const W = 860;
  if (s.type === "etapes") {
    const perRow = Math.min(4, s.etapes.length), bw = 170, gap = (W - perRow * bw) / (perRow + 1);
    const rows = Math.ceil(s.etapes.length / perRow), H = rows * 130 + 20;
    const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "schema" }, defs());
    s.etapes.forEach((step, i) => {
      const r = Math.floor(i / perRow), k = i % perRow, x = gap + k * (bw + gap), y = 20 + r * 130;
      root.append(svg("rect", { x, y, width: bw, height: 90, rx: 10 }), svg("text", { x: x + 14, y: y + 20, class: "num" }, String(i + 1)),
        svgText(x + bw / 2, y + 50, step, 20));
      if (i + 1 < s.etapes.length) {
        if (k + 1 < perRow) root.append(arrow(x + bw + 4, y + 45, x + bw + gap - 4, y + 45));
        else {
          root.append(svg("path", { d: `M${x + bw / 2},${y + 92} V${y + 110} H${gap + bw / 2} V${y + 126}`, class: "arrow",
            "marker-end": "url(#prof-arrow)" }));
        }
      }
    });
    return root;
  }
  if (s.type === "cycle") {
    const n = s.etapes.length, H = 460, cx = W / 2, cy = H / 2, R = 170;
    const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "schema" }, defs());
    const pts = s.etapes.map((_, i) => [cx + R * 1.5 * Math.cos(-Math.PI / 2 + 2 * Math.PI * i / n), cy + R * Math.sin(-Math.PI / 2 + 2 * Math.PI * i / n)]);
    pts.forEach(([x, y], i) => {
      const [nx, ny] = pts[(i + 1) % n];
      const mx = (x + nx) / 2 + (cx - (x + nx) / 2) * -0.25, my = (y + ny) / 2 + (cy - (y + ny) / 2) * -0.25;
      const shrink = (ax, ay, bx, by, d) => { const L = Math.hypot(bx - ax, by - ay) || 1; return [ax + (bx - ax) * d / L, ay + (by - ay) * d / L]; };
      const [sx, sy] = shrink(x, y, mx, my, 62), [ex, ey] = shrink(nx, ny, mx, my, 62);
      root.append(svg("path", { d: `M${sx},${sy} Q${mx},${my} ${ex},${ey}`, class: "arrow", "marker-end": "url(#prof-arrow)" }));
    });
    pts.forEach(([x, y], i) => root.append(svg("rect", { x: x - 80, y: y - 38, width: 160, height: 76, rx: 38 }), svgText(x, y + 5, s.etapes[i], 18)));
    return root;
  }
  if (s.type === "frise") {
    const n = s.evenements.length, H = 300, y = 150, x0 = 40, x1 = W - 40;
    const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "schema" }, defs(), arrow(x0, y, x1 + 20, y));
    s.evenements.forEach((e, i) => {
      const x = x0 + 30 + i * (x1 - x0 - 60) / Math.max(1, n - 1), up = i % 2 === 0;
      root.append(svg("circle", { cx: x, cy: y, r: 7, class: "dot" }), svg("line", { x1: x, y1: y, x2: x, y2: up ? y - 40 : y + 40, class: "thin" }),
        svg("text", { x, y: up ? y - 48 : y + 58, "text-anchor": "middle", class: "num" }, e.date),
        svgText(x, up ? y - 92 : y + 92, e.texte, 16, { class: "small" }));
    });
    return root;
  }
  if (s.type === "parties") {
    const n = s.parties.length, H = 480, cx = W / 2, cy = H / 2;
    const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "schema" });
    s.parties.forEach((p, i) => {
      const a = -Math.PI / 2 + 2 * Math.PI * i / n, x = cx + 300 * Math.cos(a), y = cy + 170 * Math.sin(a);
      root.append(svg("line", { x1: cx, y1: cy, x2: x, y2: y, class: "thin" }), svg("rect", { x: x - 105, y: y - 42, width: 210, height: 84, rx: 10 }),
        svg("text", { x, y: y - 18, "text-anchor": "middle", class: "num" }, p.nom), svgText(x, y + 12, p.role, 26, { class: "small" }));
    });
    root.append(svg("circle", { cx, cy, r: 70, class: "centre" }), svgText(cx, cy + 5, s.centre, 14, { class: "num" }));
    return root;
  }
  if (s.type === "fonction") return plotFunction(s);
  return el("p", { class: "muted" }, "(schéma non reconnu)");
}

// Analyseur d'expressions sûr (aucun eval) : nombres, x, pi, + - * / ^, parenthèses, fonctions usuelles.
function compileExpression(source) {
  const text = String(source).replace(/,/g, ".").replace(/\s+/g, "");
  let pos = 0;
  const FUN = { sin: Math.sin, cos: Math.cos, tan: Math.tan, exp: Math.exp, ln: Math.log, sqrt: Math.sqrt, abs: Math.abs };
  const peek = () => text[pos];
  function primary() {
    if (peek() === "(") { pos++; const v = sum(); if (text[pos++] !== ")") throw new Error(")"); return v; }
    const num = /^\d+(\.\d+)?/.exec(text.slice(pos));
    if (num) { pos += num[0].length; const value = Number(num[0]); return () => value; }
    const word = /^[a-z]+/.exec(text.slice(pos));
    if (!word) throw new Error(`caractère inattendu en ${pos}`);
    const name = word[0];
    if (name === "x") { pos += 1; return (x) => x; }
    if (name === "pi") { pos += 2; return () => Math.PI; }
    const fn = Object.keys(FUN).find((f) => name.startsWith(f));
    if (!fn) throw new Error(`fonction inconnue : ${name}`);
    pos += fn.length;
    const arg = primary();  // sin(x)^2 = (sin x)^2
    return (x) => FUN[fn](arg(x));
  }
  function power() {
    const base = primary();
    if (peek() === "^") { pos++; const exp = unary(); return (x) => Math.pow(base(x), exp(x)); }
    return base;
  }
  function implicit() {  // 2x^2 = 2·(x^2), 3(x+1), 2sin(x)
    let left = power();
    while (pos < text.length && /[a-z(0-9.]/.test(peek())) { const l = left, r = power(); left = (x) => l(x) * r(x); }
    return left;
  }
  function unary() {
    if (peek() === "-") { pos++; const v = unary(); return (x) => -v(x); }
    if (peek() === "+") { pos++; return unary(); }
    return implicit();
  }
  function product() {
    let left = unary();
    while (peek() === "*" || peek() === "/") {
      const op = text[pos++], l = left, r = unary();
      left = op === "*" ? (x) => l(x) * r(x) : (x) => l(x) / r(x);
    }
    return left;
  }
  function sum() {
    let left = product();
    while (peek() === "+" || peek() === "-") {
      const op = text[pos++], l = left, r = product();
      left = op === "+" ? (x) => l(x) + r(x) : (x) => l(x) - r(x);
    }
    return left;
  }
  const f = sum();
  if (pos !== text.length) throw new Error(`reste illisible : ${text.slice(pos)}`);
  return f;
}

function niceStep(span) {
  const raw = span / 8, mag = 10 ** Math.floor(Math.log10(raw)), n = raw / mag;
  return (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10) * mag;
}

function plotFunction(s) {
  let f;
  try { f = compileExpression(s.expression); } catch (error) { return el("p", { class: "muted" }, `(courbe illisible : ${error.message})`); }
  const W = 860, H = 420, pad = 40, xmin = s.xmin, xmax = s.xmax;
  const xs = [], ys = [];
  for (let i = 0; i <= 400; i++) { const x = xmin + (xmax - xmin) * i / 400, y = f(x); xs.push(x); ys.push(Number.isFinite(y) ? y : NaN); }
  const finite = ys.filter(Number.isFinite).sort((a, b) => a - b);
  if (!finite.length) return el("p", { class: "muted" }, "(courbe vide sur cet intervalle)");
  let ymin = finite[Math.floor(finite.length * 0.02)], ymax = finite[Math.ceil(finite.length * 0.98) - 1];
  if (ymin > 0) ymin = Math.min(0, ymin); if (ymax < 0) ymax = Math.max(0, ymax);
  if (ymax - ymin < 1e-9) { ymin -= 1; ymax += 1; }
  const m = (ymax - ymin) * 0.08; ymin -= m; ymax += m;
  const X = (x) => pad + (x - xmin) / (xmax - xmin) * (W - 2 * pad), Y = (y) => H - pad - (y - ymin) / (ymax - ymin) * (H - 2 * pad);
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "schema" });
  const sx = niceStep(xmax - xmin), sy = niceStep(ymax - ymin);
  for (let x = Math.ceil(xmin / sx) * sx; x <= xmax + 1e-9; x += sx) {
    root.append(svg("line", { x1: X(x), y1: pad / 2, x2: X(x), y2: H - pad / 2, class: "grid" }),
      svg("text", { x: X(x), y: Math.min(H - 8, Math.max(14, Y(0) + 16)), "text-anchor": "middle", class: "small" }, +x.toFixed(6)));
  }
  for (let y = Math.ceil(ymin / sy) * sy; y <= ymax + 1e-9; y += sy) {
    root.append(svg("line", { x1: pad / 2, y1: Y(y), x2: W - pad / 2, y2: Y(y), class: "grid" }),
      svg("text", { x: Math.min(W - 20, Math.max(24, X(0) - 6)), y: Y(y) + 4, "text-anchor": "end", class: "small" }, +y.toFixed(6)));
  }
  if (xmin <= 0 && xmax >= 0) root.append(svg("line", { x1: X(0), y1: pad / 2, x2: X(0), y2: H - pad / 2, class: "axis" }));
  if (ymin <= 0 && ymax >= 0) root.append(svg("line", { x1: pad / 2, y1: Y(0), x2: W - pad / 2, y2: Y(0), class: "axis" }));
  let d = "", pen = false;
  xs.forEach((x, i) => {
    const y = ys[i];
    if (!Number.isFinite(y) || y < ymin - (ymax - ymin) || y > ymax + (ymax - ymin)) { pen = false; return; }
    d += `${pen ? "L" : "M"}${X(x).toFixed(1)},${Y(Math.max(ymin, Math.min(ymax, y))).toFixed(1)} `;
    pen = true;
  });
  root.append(svg("path", { d, class: "curve" }), svg("text", { x: W - pad, y: 22, "text-anchor": "end", class: "num" }, `f(x) = ${s.expression}`));
  return root;
}

// ---------- simulations ----------
function showSim(id, title) {
  $("sim-view").hidden = false;
  $("sim-title").textContent = title || id;
  $("sim-frame").src = `/prof/sims/${encodeURIComponent(id)}`;
  $("sim-newtab").href = `/prof/sims/${encodeURIComponent(id)}`;
  $("sim-view").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadSims() {
  const box = $("sim-list");
  const data = await profCall("simulations", {}, null, $("sim-result"));
  if (!data) return;
  const groups = {};
  for (const sim of data.simulations) (groups[sim.origine] ||= []).push(sim);
  const blocks = [];
  for (const [origin, sims] of Object.entries(groups)) {
    const row = el("div", { class: "sim-grid" });
    for (const sim of sims) {
      const open = el("button", { type: "button", class: "sim-card", title: sim.description || "" }, el("b", {}, sim.titre), el("span", { class: "muted" }, sim.description || ""));
      open.addEventListener("click", () => showSim(sim.id, sim.titre));
      row.append(open);
    }
    blocks.push(el("h3", {}, origin === "intégrée" ? "Intégrées" : `Créées (${origin})`), row);
  }
  if ((data.demandes_claude || []).length) {
    blocks.push(el("h3", {}, "Demandes au Claude Code local"), el("ul", {}, ...data.demandes_claude.map((d) =>
      el("li", {}, `${d.titre} : `, el("span", { class: d.statut === "importée" ? "good" : d.statut === "refusée" ? "badans" : "warn" }, d.statut),
        d.raison ? ` (${d.raison})` : ""))));
  }
  for (const job of data.travaux || []) blocks.push(el("p", { class: "muted" }, `${job.libelle} : en cours depuis ${Math.round(job.duree)} s…`));
  box.replaceChildren(...blocks);
  $("sim-engine").querySelector('option[value="claude"]').disabled = !data.claude_local;
  $("sim-open-claude").hidden = !data.claude_lanceur;
  if (!data.modele) $("sim-engine").querySelector('option[value="local"]').disabled = true;
}

async function createSim(event) {
  event.preventDefault();
  const result = $("sim-result");
  const level = prof.levels.find((n) => n.id === $("prof-level").value);
  const payload = {
    sujet: $("sim-subject").value, details: $("sim-details").value, moteur: $("sim-engine").value,
    niveau: level ? level.nom : "", chapitre: $("sim-link").checked && prof.chapter ? prof.chapter : "",
  };
  const started = await profCall("creer_simulation", payload, event.submitter, result);
  if (!started) return;
  if (started.demande) {
    result.hidden = false;
    result.replaceChildren(el("p", {}, "Demande écrite pour le Claude Code local. Ouvre-le (bouton ci-dessous) et dis-lui :"),
      el("p", {}, el("code", {}, started.demande.consigne)),
      el("p", { class: "muted" }, "La simulation apparaîtra ici dès qu'il l'aura écrite (contrôle automatique avant import)."));
    loadSims();
    return;
  }
  const sim = await waitJob(started.travail, result);
  if (!sim) return;
  result.hidden = false;
  result.replaceChildren(el("p", { class: "good" }, `Simulation « ${sim.titre} » créée et contrôlée.`));
  loadSims();
  showSim(sim.id, sim.titre);
}

// ---------- liaisons ----------
$("prof-level").addEventListener("change", fillSubjects);
$("prof-subject").addEventListener("change", loadProgramme);
$("prof-prepare").addEventListener("click", async (event) => {
  const state = await profCall("preparer", { niveau: prof.level, matiere: prof.subject }, event.currentTarget, $("prof-programme"));
  if (state) loadProgramme();
});
$("prof-prev").addEventListener("click", () => {
  const c = prof.lesson && prof.lesson.chapitre;
  if (c && c.numero > 1) openLesson(`${c.niveau}/${c.matiere}/${c.numero - 1}`);
});
$("prof-next").addEventListener("click", () => {
  const c = prof.lesson && prof.lesson.chapitre;
  if (c && c.suivant) openLesson(`${c.niveau}/${c.matiere}/${c.numero + 1}`);
});
$("prof-simpler").addEventListener("click", (event) => prof.chapter && openLesson(prof.chapter, { simple: true }, event.currentTarget));
$("prof-rewrite").addEventListener("click", (event) => prof.chapter && openLesson(prof.chapter, { regenerer: true }, event.currentTarget));
$("prof-more").addEventListener("click", async (event) => {
  if (!prof.chapter) return;
  const status = $("prof-lesson-status");
  const started = await profCall("exercices", { chapitre: prof.chapter, difficulte: Number($("prof-difficulty").value) }, event.currentTarget, status);
  if (!started) return;
  if (await waitJob(started.travail, status)) openLesson(prof.chapter);
});
$("prof-verify").addEventListener("click", async (event) => {
  if (!prof.chapter) return;
  const status = $("prof-lesson-status");
  const started = await profCall("verifier", { chapitre: prof.chapter }, event.currentTarget, status);
  if (!started) return;
  if (await waitJob(started.travail, status)) openLesson(prof.chapter);
});
$("prof-feedback").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!prof.chapter) return;
  const status = $("prof-lesson-status");
  const started = await profCall("remarque", { chapitre: prof.chapter, genre: $("prof-feedback-kind").value,
    texte: $("prof-feedback-text").value }, event.submitter, status);
  if (!started) return;
  $("prof-feedback-text").value = "";
  const lesson = await waitJob(started.travail, status);
  if (lesson) showLesson(lesson);
});
$("sim-form").addEventListener("submit", createSim);
$("sim-refresh").addEventListener("click", loadSims);
$("sim-open-claude").addEventListener("click", (event) => profCall("ouvrir_claude", {}, event.currentTarget, $("sim-result")));
$("sim-close").addEventListener("click", () => { $("sim-frame").removeAttribute("src"); $("sim-view").hidden = true; });

// Chargé à la première ouverture de l'onglet.
let profStarted = false;
function profMaybeStart() {
  if (profStarted || (location.hash || "").slice(1) !== "professeur") return;
  profStarted = true;
  profInit();
  loadSims();
}
window.addEventListener("hashchange", profMaybeStart);
for (const tab of document.querySelectorAll("#tabs button")) tab.addEventListener("click", () => setTimeout(profMaybeStart, 0));
profMaybeStart();
