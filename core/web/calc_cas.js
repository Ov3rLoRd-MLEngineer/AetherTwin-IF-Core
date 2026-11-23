"use strict";
// Calculatrice à calcul formel (module calc_cas) : historique, graphes, tableur, délégation par le modèle local.
// Dépend de dashboard.js (chargé avant) : $, el, post, modulesByName.

const calc = {
  ready: false, inputs: [], cursor: -1, busy: false,
  curves: [{ kind: "y", expr: "x^3 - 3x" }, { kind: "y", expr: "" }],
  win: { xmin: -10, xmax: 10, ymin: -7, ymax: 7 }, plotted: [], marks: [], scatter: null, fit: null, timer: 0,
};
const CALC_COLORS = ["#0c8599", "#e8590c", "#7048e8", "#2f9e44", "#d6336c", "#1971c2", "#f08c00", "#495057"];
const STD_WINDOW = { xmin: -10, xmax: 10, ymin: -7, ymax: 7 };
const KEYS = [["√", "sqrt("], ["π", "pi"], ["e", "e"], ["i", "i"], ["∞", "oo"], ["^", "^"], [":=", " := "],
  ["=", " = "], ["diff", "diff("], ["∫", "integrate("], ["lim", "limit("], ["solve", "solve("], ["Σ", "sum("],
  ["det", "det("], ["[[ ]]", "[[1, 2], [3, 4]]"], ["≈", "approx("], ["ans", "ans"]];

async function calcCall(command, payload) {
  if (!modulesByName.calc_cas || !modulesByName.calc_cas.running) await post("/modules/calc_cas/activate");
  const reply = await post(`/modules/calc_cas/command/${command}`, payload || {});
  if (!reply.ok) throw new Error((reply.error || "erreur du module").replace(/^\w+Error: /, ""));
  return reply.result;
}

// ---------- affichage mathématique (MathML natif, filtré : seules les balises MathML sont gardées) ----------
const MATH_TAGS = new Set(["math", "mrow", "mi", "mn", "mo", "msup", "msub", "msubsup", "mfrac", "msqrt", "mroot",
  "mtext", "mspace", "mtable", "mtr", "mtd", "munder", "mover", "munderover", "mstyle", "mpadded", "mphantom"]);
function mathNode(mathml, fallback) {
  if (!mathml) return el("code", {}, fallback || "");
  const box = document.createElement("template");
  box.innerHTML = `<math display="inline">${mathml}</math>`;
  const root = box.content.firstElementChild;
  const nodes = root ? [root, ...root.querySelectorAll("*")] : [];
  if (!root || nodes.some((n) => !MATH_TAGS.has(n.localName))) return el("code", {}, fallback || "");
  for (const node of nodes) {
    for (const attr of [...node.attributes]) {
      if (!["display", "mathvariant", "stretchy", "fence", "separator", "columnalign"].includes(attr.name)) {
        node.removeAttribute(attr.name);
      }
    }
  }
  return root;
}

// ---------- calculatrice ----------
function entryNode(r) {
  const input = el("div", { class: "in", title: "Cliquer pour reprendre cette saisie" }, r.input);
  input.addEventListener("click", () => { $("calc-input").value = r.input; $("calc-input").focus(); });
  const node = el("div", { class: "calc-entry" }, input);
  if (!r.ok) {
    node.append(el("div", { class: "err" }, r.error || "erreur"));
    return node;
  }
  const out = el("div", { class: "out" });
  if (r.label) out.append(el("code", {}, `${r.label} :=`));
  out.append(mathNode(r.mathml, r.exact));
  if (r.approx) out.append(el("span", { class: "approx" }, "≈ ", mathNode(r.approx_mathml, r.approx)));
  node.append(out);
  if (r.warning) node.append(el("div", { class: "warn" }, r.warning));
  const tools = el("div", { class: "tools" });
  for (const [label, text] of [["texte", r.exact], ["LaTeX", r.latex]]) {
    const button = el("button", { type: "button", class: "ghost", title: `Copier en ${label}` }, label);
    button.addEventListener("click", () => navigator.clipboard?.writeText(text || "").catch(() => {}));
    tools.append(button);
  }
  node.append(tools);
  return node;
}

function showHistory(items) {
  const box = $("calc-history");
  box.replaceChildren(...items.map(entryNode));
  if (!items.length) box.append(el("p", { class: "muted calc-empty" }, "Aucun calcul pour l'instant."));
  box.scrollTop = box.scrollHeight;
}

function addEntry(result) {
  const box = $("calc-history");
  if (box.querySelector("p.muted")) box.replaceChildren();
  box.append(entryNode(result));
  box.scrollTop = box.scrollHeight;
}

async function refreshVars() {
  try {
    const vars = await calcCall("vars");
    $("calc-vars").replaceChildren(...(vars.length ? vars.map((v) => {
      const del = el("button", { type: "button", class: "ghost danger", title: `Supprimer ${v.name}` }, "×");
      del.addEventListener("click", async () => { await calcCall("delete", { name: v.name }).catch(() => {}); refreshVars(); });
      return el("li", {}, el("span", {}, v.source), del);
    }) : [el("li", { class: "muted" }, "aucune")]));
  } catch { /* module pas encore prêt */ }
}

async function evaluateInput(text) {
  if (!text.trim()) return;
  // File d'attente : une saisie validée pendant un calcul passe après lui, dans l'ordre.
  const input = $("calc-input");
  if (input.value === text) input.value = "";
  calc.inputs.push(text);
  calc.cursor = calc.inputs.length;
  calc.queue = (calc.queue || Promise.resolve()).then(async () => {
    $("calc-status").textContent = "Calcul…";
    try {
      const result = await calcCall("eval", { text });
      addEntry(result);
      if (result.definition) refreshVars();
      $("calc-status").textContent = result.elapsed_ms !== undefined ? `${result.elapsed_ms} ms` : "";
    } catch (error) {
      addEntry({ ok: false, input: text, error: error.message });
      $("calc-status").textContent = "";
    }
  });
}

function insertAtCursor(text) {
  const input = $("calc-input");
  const start = input.selectionStart ?? input.value.length;
  input.value = input.value.slice(0, start) + text + input.value.slice(input.selectionEnd ?? start);
  input.focus();
  input.selectionStart = input.selectionEnd = start + text.length;
}

async function startCalc() {
  if (calc.ready) return;
  calc.ready = true;
  $("calc-status").textContent = "Démarrage du moteur de calcul…";
  try {
    const [history, catalog] = await Promise.all([calcCall("history"), calcCall("examples")]);
    showHistory(history);
    calc.inputs = history.map((h) => h.input);
    calc.cursor = calc.inputs.length;
    $("calc-examples").replaceChildren(el("option", { value: "" }, "Choisir un exemple…"),
      ...catalog.examples.map((e) => el("option", { value: e.input }, `${e.title} : ${e.input}`)));
    calc.catalog = catalog;
    $("calc-question").placeholder = catalog.agent;
    $("calc-status").textContent = "";
    refreshVars();
    plotCurves();
  } catch (error) {
    calc.ready = false;
    $("calc-status").textContent = `Module indisponible : ${error.message}`;
  }
}

// ---------- graphes ----------
function curveRow(curve, index) {
  const color = el("span", { class: "swatch" });
  color.style.background = CALC_COLORS[index % CALC_COLORS.length];
  const kind = el("select", { "aria-label": "Type de courbe" },
    ...[["y", "y ="], ["param", "paramétrique"], ["polar", "polaire r ="]].map(([v, t]) => el("option", { value: v }, t)));
  kind.value = curve.kind;
  const row = el("div", { class: "calc-curve" }, color, kind);
  const field = (key, placeholder, cls = "") => {
    const input = el("input", { type: "text", placeholder, class: cls, spellcheck: "false", "aria-label": placeholder });
    input.value = curve[key] ?? "";
    input.addEventListener("change", () => { curve[key] = input.value; });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { curve[key] = input.value; plotCurves(); } });
    return input;
  };
  if (curve.kind === "y") row.append(field("expr", "x^2 - 2"));
  else if (curve.kind === "param") row.append(field("x", "x(t) = 3cos(t)"), field("y", "y(t) = 2sin(t)"));
  else row.append(field("r", "r(θ) = cos(4 theta)"));
  if (curve.kind !== "y") {
    curve.tmin ??= 0; curve.tmax ??= 6.2832;
    row.append(el("span", { class: "muted" }, curve.kind === "polar" ? "θ de" : "t de"),
      field("tmin", "min", "short"), el("span", { class: "muted" }, "à"), field("tmax", "max", "short"));
  }
  const remove = el("button", { type: "button", class: "ghost danger", title: "Retirer" }, "×");
  remove.addEventListener("click", () => { calc.curves.splice(index, 1); renderCurves(); plotCurves(); });
  kind.addEventListener("change", () => { curve.kind = kind.value; renderCurves(); });
  row.append(remove);
  if (curve.error) row.append(el("div", { class: "err" }, curve.error));
  return row;
}

function renderCurves() {
  $("calc-curves").replaceChildren(...calc.curves.map(curveRow));
}

function activeCurves() {
  return calc.curves.map((c, i) => ({ ...c, index: i }))
    .filter((c) => (c.kind === "y" ? c.expr : c.kind === "param" ? c.x && c.y : c.r)?.toString().trim());
}

async function plotCurves() {
  const curves = activeCurves();
  calc.curves.forEach((c) => { delete c.error; });
  if (!curves.length && !calc.scatter) { calc.plotted = []; drawGraph(); return; }
  try {
    const result = curves.length ? await calcCall("plot", { curves: curves.map(({ index, error, ...c }) => ({
      ...c, tmin: Number(c.tmin ?? 0), tmax: Number(c.tmax ?? 6.2832) })), window: calc.win }) : { curves: [] };
    calc.plotted = result.curves.map((c, i) => ({ ...c, color: CALC_COLORS[curves[i].index % CALC_COLORS.length] }));
    result.curves.forEach((c, i) => { if (c.error) calc.curves[curves[i].index].error = c.error; });
    if (result.curves.some((c) => c.error)) renderCurves();
  } catch (error) {
    $("calc-coords").textContent = `Erreur : ${error.message}`;
  }
  drawGraph();
}

function schedulePlot() {
  clearTimeout(calc.timer);
  calc.timer = setTimeout(plotCurves, 120);
}

function niceStep(span, pixels) {
  const raw = span / Math.max(2, pixels / 70);
  const pow = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((m) => m * pow).find((s) => s >= raw) || raw;
}

function drawGraph() {
  const canvas = $("calc-canvas");
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const style = getComputedStyle(canvas.closest("[data-panel]"));
  const { xmin, xmax, ymin, ymax } = calc.win;
  const X = (x) => ((x - xmin) / (xmax - xmin)) * w;
  const Y = (y) => h - ((y - ymin) / (ymax - ymin)) * h;
  ctx.clearRect(0, 0, w, h);
  ctx.font = "11px Consolas, monospace";
  const sx = niceStep(xmax - xmin, w), sy = niceStep(ymax - ymin, h);
  ctx.lineWidth = 1;
  ctx.strokeStyle = style.getPropertyValue("--calc-grid");
  ctx.fillStyle = style.getPropertyValue("--calc-axis");
  const fmt = (v) => String(+v.toPrecision(6));
  for (let x = Math.ceil(xmin / sx) * sx; x <= xmax; x += sx) {
    ctx.beginPath(); ctx.moveTo(X(x), 0); ctx.lineTo(X(x), h); ctx.stroke();
    if (Math.abs(x) > sx / 2) ctx.fillText(fmt(x), X(x) + 2, Math.min(h - 4, Math.max(12, Y(0) + 12)));
  }
  for (let y = Math.ceil(ymin / sy) * sy; y <= ymax; y += sy) {
    ctx.beginPath(); ctx.moveTo(0, Y(y)); ctx.lineTo(w, Y(y)); ctx.stroke();
    if (Math.abs(y) > sy / 2) ctx.fillText(fmt(y), Math.min(w - 40, Math.max(2, X(0) + 3)), Y(y) - 2);
  }
  ctx.strokeStyle = style.getPropertyValue("--calc-axis");
  ctx.lineWidth = 1.5;
  if (ymin < 0 && ymax > 0) { ctx.beginPath(); ctx.moveTo(0, Y(0)); ctx.lineTo(w, Y(0)); ctx.stroke(); }
  if (xmin < 0 && xmax > 0) { ctx.beginPath(); ctx.moveTo(X(0), 0); ctx.lineTo(X(0), h); ctx.stroke(); }
  ctx.lineWidth = 2.2;
  ctx.lineJoin = "round";
  for (const curve of calc.plotted) {
    if (!curve.segments) continue;
    ctx.strokeStyle = curve.color;
    for (const seg of curve.segments) {
      ctx.beginPath();
      seg.forEach(([x, y], i) => (i ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y))));
      ctx.stroke();
    }
  }
  if (calc.scatter) {
    ctx.fillStyle = style.getPropertyValue("--calc");
    for (const [x, y] of calc.scatter) { ctx.beginPath(); ctx.arc(X(x), Y(y), 3.5, 0, 2 * Math.PI); ctx.fill(); }
  }
  for (const p of calc.marks) {
    if (p.y === null) continue;
    ctx.fillStyle = style.getPropertyValue("--text");
    ctx.beginPath(); ctx.arc(X(p.x), Y(p.y), 4.5, 0, 2 * Math.PI); ctx.fill();
    ctx.fillText(`(${p.x_exact || fmt(p.x)} ; ${p.y_exact || fmt(p.y)})`, X(p.x) + 7, Y(p.y) - 7);
  }
}

function zoom(factor, cx, cy) {
  const { xmin, xmax, ymin, ymax } = calc.win;
  cx ??= (xmin + xmax) / 2; cy ??= (ymin + ymax) / 2;
  calc.win = { xmin: cx - (cx - xmin) * factor, xmax: cx + (xmax - cx) * factor,
               ymin: cy - (cy - ymin) * factor, ymax: cy + (ymax - cy) * factor };
  drawGraph(); schedulePlot();
}

function canvasToWorld(event) {
  const rect = $("calc-canvas").getBoundingClientRect();
  const { xmin, xmax, ymin, ymax } = calc.win;
  return [xmin + ((event.clientX - rect.left) / rect.width) * (xmax - xmin),
          ymax - ((event.clientY - rect.top) / rect.height) * (ymax - ymin)];
}

function bindCanvas() {
  const canvas = $("calc-canvas");
  let drag = null;
  canvas.addEventListener("pointerdown", (e) => {
    drag = { x: e.clientX, y: e.clientY, win: { ...calc.win } };
    canvas.setPointerCapture(e.pointerId); canvas.classList.add("dragging");
  });
  canvas.addEventListener("pointermove", (e) => {
    const [wx, wy] = canvasToWorld(e);
    $("calc-coords").textContent = `x = ${wx.toPrecision(5)}   y = ${wy.toPrecision(5)}`;
    if (!drag) return;
    const rect = canvas.getBoundingClientRect();
    const dx = ((e.clientX - drag.x) / rect.width) * (drag.win.xmax - drag.win.xmin);
    const dy = ((e.clientY - drag.y) / rect.height) * (drag.win.ymax - drag.win.ymin);
    calc.win = { xmin: drag.win.xmin - dx, xmax: drag.win.xmax - dx, ymin: drag.win.ymin + dy, ymax: drag.win.ymax + dy };
    drawGraph();
  });
  const end = () => { if (drag) { drag = null; canvas.classList.remove("dragging"); schedulePlot(); } };
  canvas.addEventListener("pointerup", end);
  canvas.addEventListener("pointercancel", end);
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const [wx, wy] = canvasToWorld(e);
    zoom(e.deltaY > 0 ? 1.25 : 0.8, wx, wy);
  }, { passive: false });
  window.addEventListener("resize", drawGraph);
}

async function analyze(what) {
  const ys = calc.curves.filter((c) => c.kind === "y" && c.expr?.trim());
  if (!ys.length || (what === "intersections" && ys.length < 2)) {
    $("calc-analysis").replaceChildren(el("p", { class: "warn" },
      what === "intersections" ? "Il faut deux courbes y = f(x)." : "Il faut une courbe y = f(x)."));
    return;
  }
  try {
    const result = await calcCall("analyze", { what, expr: ys[0].expr, other: ys[1]?.expr,
      xmin: calc.win.xmin, xmax: calc.win.xmax });
    calc.marks = result.points;
    const labels = { zeros: "Zéros", extrema: "Extrema", intersections: "Intersections" };
    $("calc-analysis").replaceChildren(el("h3", {}, `${labels[what]} de y = ${result.expr} dans la fenêtre`),
      result.points.length ? el("table", { class: "calc-points" }, el("tbody", {}, ...result.points.map((p) =>
        el("tr", {}, el("td", {}, p.type), el("td", {}, "x = ", p.x_exact ? `${p.x_exact} ≈ ${p.x}` : String(p.x)),
          el("td", {}, "y = ", p.y === null ? "—" : p.y_exact ? `${p.y_exact} ≈ ${p.y}` : String(p.y))))))
        : el("p", { class: "muted" }, "Aucun point dans la fenêtre."));
    drawGraph();
  } catch (error) {
    $("calc-analysis").replaceChildren(el("p", { class: "warn" }, `Erreur : ${error.message}`));
  }
}

// ---------- tableur et statistiques ----------
function addRows(count, values = []) {
  const body = $("calc-sheet");
  for (let i = 0; i < count; i += 1) {
    const n = body.rows.length + 1;
    const row = el("tr", {}, el("td", { class: "n" }, String(n)));
    for (let c = 0; c < 3; c += 1) {
      const input = el("input", { type: "text", inputmode: "decimal", "aria-label": `ligne ${n}, colonne ${c + 1}` });
      input.value = values[i]?.[c] ?? "";
      row.append(el("td", {}, input));
    }
    body.append(row);
  }
}

function sheetData() {
  const rows = [...$("calc-sheet").rows].map((r) => [1, 2, 3].map((c) => r.cells[c].firstChild.value.trim()))
    .filter((cells) => cells[0] || cells[1]);
  return { x: rows.map((r) => r[0]), y: rows.map((r) => r[1]), freq: rows.some((r) => r[2]) ? rows.map((r) => r[2] || "0") : null };
}

const STAT_LABELS = { n: "n", mean: "moyenne x̄", sum: "Σx", sum_sq: "Σx²", sx: "sx (n−1)", sigma: "σx (n)",
  variance: "variance (n)", min: "min", q1: "Q1", median: "médiane", q3: "Q3", max: "max", range: "étendue",
  mean_x: "x̄", mean_y: "ȳ", sy: "sy (n−1)", sigma_x: "σx", sigma_y: "σy", sum_xy: "Σxy", cov: "covariance", r: "r" };
function statsGrid(stats) {
  return el("div", { class: "calc-stats" }, ...Object.entries(stats).map(([k, v]) =>
    el("div", {}, el("span", { class: "muted" }, STAT_LABELS[k] || k), el("b", {}, v === null ? "—" : String(v)))));
}

async function runStats(two) {
  const data = sheetData();
  try {
    const payload = { x: data.x };
    if (data.freq && !two) payload.freq = data.freq;
    if (two) payload.y = data.y;
    const result = await calcCall("stats", payload);
    const parts = [el("h3", {}, "Une variable (X)"), statsGrid(result.one_var)];
    if (result.two_var) parts.push(el("h3", {}, "Deux variables"), statsGrid(result.two_var));
    $("calc-stats-out").replaceChildren(...parts);
  } catch (error) {
    $("calc-stats-out").replaceChildren(el("p", { class: "warn" }, `Erreur : ${error.message}`));
  }
}

async function runRegression() {
  const data = sheetData();
  try {
    const result = await calcCall("regress", { x: data.x, y: data.y, model: $("calc-model").value });
    const numbers = (list) => list.map(Number).filter(Number.isFinite);
    const xs = numbers(data.x), ysv = numbers(data.y);
    calc.scatter = xs.length === ysv.length ? xs.map((x, i) => [x, ysv[i]]) : null;
    if (calc.scatter?.length) {  // fenêtre ajustée aux points
      const pad = (a, b) => { const d = (b - a) || 1; return [a - d * 0.15, b + d * 0.15]; };
      const [x0, x1] = pad(Math.min(...xs), Math.max(...xs));
      const [y0, y1] = pad(Math.min(...ysv), Math.max(...ysv));
      calc.win = { xmin: x0, xmax: x1, ymin: y0, ymax: y1 };
    }
    calc.curves = [{ kind: "y", expr: result.expr }];
    calc.marks = [];
    renderCurves();
    plotCurves();
    $("calc-stats-out").replaceChildren(el("h3", {}, "Régression"),
      el("p", {}, el("b", {}, result.equation)),
      el("p", { class: "muted" }, `r² = ${result.r2}` + (result.r !== undefined ? `   ·   r = ${result.r}` : "")
        + "   ·   courbe tracée dans « Graphes »"));
  } catch (error) {
    $("calc-stats-out").replaceChildren(el("p", { class: "warn" }, `Erreur : ${error.message}`));
  }
}

// ---------- délégation par le modèle local ----------
async function askModel() {
  const question = $("calc-question").value.trim() || $("calc-question").placeholder;
  const box = $("calc-answer");
  box.hidden = false;
  box.replaceChildren(el("p", { class: "muted" }, "Le modèle local réfléchit et fait calculer le moteur…"));
  $("calc-ask").disabled = true;
  try {
    const result = await calcCall("ask", { question });
    box.replaceChildren(el("div", { class: "answer" }, result.answer),
      ...(result.calls.length ? [el("h3", {}, `${result.calls.length} calcul(s) délégué(s) au moteur`),
        el("ul", { class: "calc-calls" }, ...result.calls.map((c) => el("li", {},
          `${c.expression} → ${c.result.ok ? c.result.exact + (c.result.approx ? ` ≈ ${c.result.approx}` : "") : c.result.error}`)))]
        : [el("p", { class: "muted" }, "Aucun calcul délégué.")]));
  } catch (error) {
    box.replaceChildren(el("p", { class: "warn" }, `Erreur : ${error.message}`));
  } finally {
    $("calc-ask").disabled = false;
  }
}

// ---------- branchements ----------
(function bindCalc() {
  if (!$("calc-form")) return;
  $("calc-form").addEventListener("submit", (e) => { e.preventDefault(); evaluateInput($("calc-input").value); });
  $("calc-input").addEventListener("keydown", (e) => {
    if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
    e.preventDefault();
    calc.cursor = Math.max(0, Math.min(calc.inputs.length, calc.cursor + (e.key === "ArrowUp" ? -1 : 1)));
    $("calc-input").value = calc.inputs[calc.cursor] ?? "";
  });
  $("calc-keys").replaceChildren(...KEYS.map(([label, text]) => {
    const b = el("button", { type: "button", class: "ghost" }, label);
    b.addEventListener("click", () => insertAtCursor(text));
    return b;
  }));
  $("calc-examples").addEventListener("change", (e) => {
    if (e.target.value) { evaluateInput(e.target.value); e.target.value = ""; }
  });
  $("calc-reset").addEventListener("click", async () => {
    if (!confirm("Effacer l'historique, les variables et les fonctions ?")) return;
    await calcCall("reset").catch(() => {});
    showHistory([]); refreshVars();
  });
  $("calc-add-curve").addEventListener("click", () => { calc.curves.push({ kind: "y", expr: "" }); renderCurves(); });
  $("calc-plot").addEventListener("click", () => {
    for (const input of $("calc-curves").querySelectorAll("input")) input.dispatchEvent(new Event("change"));
    calc.marks = []; plotCurves();
  });
  $("calc-zoom-in").addEventListener("click", () => zoom(0.5));
  $("calc-zoom-out").addEventListener("click", () => zoom(2));
  $("calc-zoom-std").addEventListener("click", () => { calc.win = { ...STD_WINDOW }; calc.scatter = null; drawGraph(); plotCurves(); });
  $("calc-zeros").addEventListener("click", () => analyze("zeros"));
  $("calc-extrema").addEventListener("click", () => analyze("extrema"));
  $("calc-inter").addEventListener("click", () => analyze("intersections"));
  addRows(10);
  $("calc-rows").addEventListener("click", () => addRows(5));
  $("calc-sheet-clear").addEventListener("click", () => { $("calc-sheet").replaceChildren(); addRows(10); calc.scatter = null; });
  $("calc-sheet-demo").addEventListener("click", () => {
    const demo = calc.catalog?.stats || { x: [0, 1, 2, 3, 4, 5], y: [2, 3.1, 4.4, 6.9, 10.2, 15.1], model: "exponential" };
    $("calc-sheet").replaceChildren();
    addRows(Math.max(10, demo.x.length), demo.x.map((x, i) => [x, demo.y[i], ""]));
    $("calc-model").value = demo.model;
  });
  $("calc-stats1").addEventListener("click", () => runStats(false));
  $("calc-stats2").addEventListener("click", () => runStats(true));
  $("calc-regress").addEventListener("click", runRegression);
  $("calc-ask").addEventListener("click", askModel);
  bindCanvas();
  renderCurves();
  const tab = document.querySelector('#tabs button[data-tab="calcul"]');
  tab?.addEventListener("click", () => { startCalc(); requestAnimationFrame(drawGraph); });
  if ((location.hash || "").slice(1) === "calcul") setTimeout(() => { startCalc(); drawGraph(); }, 300);
})();
