"use strict";
// Labo de chimie Æther : tableau périodique, équations et stœchiométrie, solutions et pH, titrage simulé.
// Tous les calculs sont faits par le module chem_lab (Python exact) ; la page affiche, trace et anime.
(function () {
  const $ = (id) => document.getElementById(id);
  const SVG = "http://www.w3.org/2000/svg";
  const local = {
    get(key, fallback) { try { const v = localStorage.getItem(`chem.${key}`); return v === null ? fallback : JSON.parse(v); } catch (e) { return fallback; } },
    set(key, value) { try { localStorage.setItem(`chem.${key}`, JSON.stringify(value)); } catch (e) { /* stockage indisponible */ } },
  };
  const fmt = (x, d = 4) => (x === null || x === undefined ? "—" : Math.abs(x) >= 1e5 || (Math.abs(x) < 1e-3 && x !== 0)
    ? x.toExponential(3).replace(".", ",") : (+x.toFixed(d)).toString().replace(".", ","));
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };

  // ---------- Hub ----------
  let activated = false;
  let queue = Promise.resolve();
  async function post(path, body) {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(data.detail || `erreur ${r.status}`); e.status = r.status; throw e; }
    return data;
  }
  async function send(command, payload) {
    if (!activated) { await post("/modules/chem_lab/activate"); activated = true; }
    let reply;
    try { reply = await post(`/modules/chem_lab/command/${command}`, payload); }
    catch (e) {
      if (e instanceof TypeError) throw new Error("Hub injoignable : lance AetherTwin, puis rouvre le labo");
      if (e.status !== 409) throw e;
      await post("/modules/chem_lab/activate");
      reply = await post(`/modules/chem_lab/command/${command}`, payload);
    }
    if (!reply.ok) throw new Error((reply.error || "erreur du module").replace(/^\w+Error: /, ""));
    return reply.result;
  }
  function call(command, payload = {}) {   // une commande à la fois (le Hub les traite en série)
    const run = queue.then(() => send(command, payload));
    queue = run.catch(() => {});
    return run;
  }
  function status(text, bad = false) { $("status").textContent = text; $("status").classList.toggle("err", bad); }
  function fail(box, e) { box.replaceChildren(el("div", "err-box", e.message)); }

  // ---------- modes et thème ----------
  function setMode(mode) {
    for (const b of $("modes").querySelectorAll("button")) b.setAttribute("aria-selected", String(b.dataset.mode === mode));
    for (const v of document.querySelectorAll(".view")) v.hidden = v.dataset.view !== mode;
    local.set("mode", mode);
    if (mode === "titration") drawPlot();
  }
  $("modes").addEventListener("click", (e) => { const b = e.target.closest("button[data-mode]"); if (b) setMode(b.dataset.mode); });
  document.documentElement.dataset.theme = local.get("theme", "dark");
  $("btn-theme").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next; local.set("theme", next); drawPlot();
  });

  // ==================== tableau périodique ====================
  let ELEMENTS = [], CATS = {}, selected = null;
  const heat = (t) => `hsl(${(1 - t) * 220}, 70%, ${62 + 8 * Math.sin(t * Math.PI)}%)`;
  function position(e) {
    if (e.group === null) {   // lanthanides et actinides : deux lignes sous le tableau
      const row = e.z <= 71 ? 9 : 10;
      return [row, 3 + (e.z - (row === 9 ? 57 : 89))];
    }
    return [e.period, e.group];
  }
  function buildTable() {
    const grid = $("ptable");
    grid.replaceChildren();
    for (const e of ELEMENTS) {
      const [row, col] = position(e);
      const b = el("button", `el cat-${e.category}`);
      b.type = "button";
      b.style.gridRow = String(row); b.style.gridColumn = String(col);
      b.dataset.z = e.z;
      b.title = `${e.name} (${e.category_name})`;
      b.append(el("span", "z", e.z), el("span", "s", e.symbol), el("span", "m", e.radioactive_only ? `[${Math.round(e.mass)}]` : fmt(e.mass, 3)));
      b.addEventListener("click", () => showElement(e));
      grid.append(b);
    }
    for (const [row, text] of [[6, "57–71"], [7, "89–103"]]) {
      const g = el("div", "el gap", text); g.style.gridRow = String(row); g.style.gridColumn = "3"; grid.append(g);
    }
    paint();
  }
  function paint() {
    const mode = $("pt-color").value;
    const ens = ELEMENTS.map((e) => e.electronegativity).filter((x) => x !== null);
    const [lo, hi] = [Math.min(...ens), Math.max(...ens)];
    const legend = $("pt-legend");
    legend.replaceChildren();
    for (const b of $("ptable").querySelectorAll(".el[data-z]")) {
      const e = ELEMENTS[b.dataset.z - 1];
      b.style.background = "";
      if (mode === "en") b.style.background = e.electronegativity === null ? "#5d6470" : heat((e.electronegativity - lo) / (hi - lo));
      if (mode === "state") b.style.background = { gaz: "#8ec5f2", liquide: "#7fd6b5", solide: "#c9ced6", "?": "#6b7280" }[e.state];
      if (mode === "mass") b.style.background = heat(Math.min(1, e.mass / 300));
    }
    const items = mode === "category" ? Object.entries(CATS).map(([k, v]) => [`cat-${k}`, v, null])
      : mode === "en" ? [[null, `faible (${lo})`, heat(0)], [null, `forte (${hi})`, heat(1)], [null, "inconnue", "#5d6470"]]
      : mode === "state" ? [[null, "gaz", "#8ec5f2"], [null, "liquide", "#7fd6b5"], [null, "solide", "#c9ced6"], [null, "inconnu", "#6b7280"]]
      : [[null, "léger", heat(0)], [null, "lourd (≥ 300)", heat(1)]];
    for (const [cls, text, color] of items) {
      const s = el("span"); const i = el("i", cls || ""); if (color) i.style.background = color; s.append(i, text); legend.append(s);
    }
  }
  function showElement(e) {
    selected = e;
    for (const b of $("ptable").querySelectorAll(".el.sel")) b.classList.remove("sel");
    $("ptable").querySelector(`.el[data-z="${e.z}"]`)?.classList.add("sel");
    const card = el("div", "ecard");
    const big = el("div", "big");
    const tile = el("div", `tile cat-${e.category}`);
    tile.append(el("small", "", e.z), el("b", "", e.symbol));
    const title = el("div");
    title.append(el("h2", "", e.name), el("div", "muted", e.category_name));
    big.append(tile, title);
    const dl = el("dl");
    const rows = [
      ["Numéro atomique", e.z],
      ["Masse atomique", e.radioactive_only ? `[${e.mass}] (isotope le plus stable)` : `${fmt(e.mass, 4)} g/mol`],
      ["Période", e.period], ["Groupe", e.group === null ? (e.category === "la" ? "lanthanides" : "actinides") : e.group],
      ["Électronégativité", e.electronegativity === null ? "inconnue" : `${fmt(e.electronegativity, 2)} (Pauling)`],
      ["État à 20 °C", e.state === "?" ? "inconnu" : e.state],
      ["Électrons de valence", valence(e)],
    ];
    for (const [k, v] of rows) dl.append(el("dt", "", k), el("dd", "", String(v)));
    const use = el("button", "", "Utiliser dans une formule");
    use.type = "button";
    use.addEventListener("click", () => { setMode("equations"); $("mm-formula").value += e.symbol; $("mm-formula").focus(); });
    card.append(big, dl, el("div", "row tight"));
    card.lastChild.append(use);
    $("pt-card").replaceChildren(card);
  }
  function valence(e) {
    if (e.group === null || e.z >= 104) return "—";
    if (e.group <= 2) return e.group;
    if (e.group >= 13) return e.z === 2 ? 2 : e.group - 10;
    return "variable (métal de transition)";
  }
  $("pt-color").addEventListener("change", () => { local.set("ptColor", $("pt-color").value); paint(); });
  $("pt-search").addEventListener("input", () => {
    const q = $("pt-search").value.trim().toLowerCase();
    for (const b of $("ptable").querySelectorAll(".el[data-z]")) {
      const e = ELEMENTS[b.dataset.z - 1];
      const hit = !q || e.symbol.toLowerCase() === q || String(e.z) === q || e.name.toLowerCase().includes(q);
      b.classList.toggle("dim", !hit);
    }
    const exact = ELEMENTS.find((e) => e.symbol.toLowerCase() === q || String(e.z) === q || e.name.toLowerCase() === q);
    if (exact) showElement(exact);
  });

  // ==================== équations ====================
  const EXAMPLES = ["H2 + O2 -> H2O", "C3H8 + O2 -> CO2 + H2O", "Fe + O2 -> Fe2O3", "Al + H2SO4 -> Al2(SO4)3 + H2",
    "Cu + HNO3 -> Cu(NO3)2 + NO + H2O", "MnO4^- + Fe^2+ + H^+ -> Mn^2+ + Fe^3+ + H2O", "C6H12O6 + O2 -> CO2 + H2O"];
  for (const ex of EXAMPLES) {
    const b = el("button", "", ex); b.type = "button";
    b.addEventListener("click", () => { $("eq-text").value = ex; $("eq-form").requestSubmit(); });
    $("eq-examples").append(b);
  }
  $("mm-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const box = $("mm-out");
    try {
      const r = await call("molar_mass", { formula: $("mm-formula").value });
      const bars = el("div", "bars");
      for (const p of r.composition) {
        const row = el("div"); const b = el("span", "b"); b.style.width = `${p.percent}%`;
        const track = el("span"); track.append(b);
        row.append(el("code", "", `${p.element}${p.count > 1 ? p.count : ""}`), track, el("span", "", `${fmt(p.percent, 2)} %`));
        bars.append(row);
      }
      box.replaceChildren(el("div", "result", `M(${r.formula}) = ${fmt(r.molar_mass, 3)} g/mol`), bars);
      local.set("mm", $("mm-formula").value);
    } catch (e) { fail(box, e); }
  });

  let balanced = null;
  $("eq-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const box = $("eq-out");
    try {
      balanced = await call("balance", { equation: $("eq-text").value });
      const t = el("table", "t");
      const head = el("tr"); head.append(el("th", "", "élément"), el("th", "", "réactifs"), el("th", "", "produits"));
      t.append(head);
      for (const [elem, n] of Object.entries(balanced.check)) {
        const tr = el("tr"); tr.append(el("td", "", elem), el("td", "", n), el("td", "", n)); t.append(tr);
      }
      box.replaceChildren(el("div", "result", balanced.balanced), el("h3", "", "Conservation des atomes"), t);
      local.set("eq", $("eq-text").value);
      buildStoich();
    } catch (e) { balanced = null; $("st-card").hidden = true; fail(box, e); }
  });
  function buildStoich() {
    const box = $("st-inputs");
    box.replaceChildren();
    for (const r of balanced.reactants) {
      if (r.species.startsWith("e")) continue;
      const input = el("input", "field num"); input.type = "number"; input.step = "any"; input.min = "0"; input.dataset.species = r.species;
      const unit = el("select"); unit.dataset.species = r.species;
      for (const [v, t] of [["mass_g", "g"], ["mol", "mol"]]) { const o = el("option", "", t); o.value = v; unit.append(o); }
      box.append(el("b", "", `${r.coef > 1 ? r.coef + " " : ""}${r.species}`), input, unit);
    }
    $("st-card").hidden = false;
    $("st-out").replaceChildren();
  }
  $("st-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const quantities = {};
    for (const input of $("st-inputs").querySelectorAll("input")) {
      if (input.value === "") continue;
      const unit = $("st-inputs").querySelector(`select[data-species="${CSS.escape(input.dataset.species)}"]`).value;
      quantities[input.dataset.species] = { [unit]: Number(input.value) };
    }
    const box = $("st-out");
    try {
      const r = await call("stoichiometry", { equation: $("eq-text").value, quantities, yield_percent: Number($("st-yield").value) || 100 });
      const t = el("table", "t");
      const head = el("tr");
      for (const h of ["espèce", "M (g/mol)", "initial (mol)", "réagit / se forme (mol)", "masse (g)", "reste (mol)", "reste (g)"]) head.append(el("th", "", h));
      t.append(head);
      for (const x of r.reactants) {
        const tr = el("tr", x.species === r.limiting ? "limit" : "");
        for (const v of [x.species, fmt(x.molar_mass, 3), x.initial_mol === null ? "excès" : fmt(x.initial_mol), `− ${fmt(x.used_mol)}`, fmt(x.used_g, 3),
          x.left_mol === null ? "—" : fmt(x.left_mol), x.left_g === null ? "—" : fmt(x.left_g, 3)]) tr.append(el("td", "", v));
        t.append(tr);
      }
      for (const x of r.products) {
        const tr = el("tr");
        for (const v of [x.species, fmt(x.molar_mass, 3), "0", `+ ${fmt(x.formed_mol)}`, fmt(x.formed_g, 3), fmt(x.formed_mol), fmt(x.formed_g, 3)]) tr.append(el("td", "", v));
        t.append(tr);
      }
      box.replaceChildren(el("div", "result", `Réactif limitant : ${r.limiting} · avancement x = ${fmt(r.extent_mol)} mol`
        + (r.yield_percent < 100 ? ` (xmax = ${fmt(r.extent_max_mol)} mol, rendement ${fmt(r.yield_percent, 1)} %)` : "")), t);
    } catch (e) { fail(box, e); }
  });

  // ==================== solutions ====================
  const COUPLES = [
    ["acide éthanoïque / éthanoate", 4.76], ["acide méthanoïque / méthanoate", 3.75], ["acide benzoïque / benzoate", 4.2],
    ["acide lactique / lactate", 3.86], ["acide hypochloreux / hypochlorite", 7.53], ["ion ammonium / ammoniac", 9.25],
    ["ion méthylammonium / méthylamine", 10.64], ["acide fluorhydrique / fluorure", 3.17], ["dioxyde de carbone dissous / hydrogénocarbonate", 6.35],
  ];
  function fillCouples(select, target) {
    select.replaceChildren(el("option", "", "couples courants…"));
    select.firstChild.value = "";
    for (const [name, pka] of COUPLES) { const o = el("option", "", `${name} (pKa ${String(pka).replace(".", ",")})`); o.value = pka; select.append(o); }
    select.addEventListener("change", () => { if (select.value) $(target).value = select.value; });
  }
  fillCouples($("ph-preset"), "ph-pka");
  for (let p = 0; p <= 14; p += 1) { const b = el("b", "", p); b.style.left = `${(p / 14) * 100}%`; $("ph-scale").append(b); }
  const pkaNeeded = () => $("ph-kind").value.endsWith("faible");
  $("ph-kind").addEventListener("change", () => { $("ph-pka").disabled = !pkaNeeded(); $("ph-preset").disabled = !pkaNeeded(); });
  $("ph-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const box = $("ph-out");
    try {
      const r = await call("ph", { kind: $("ph-kind").value, concentration: Number($("ph-c").value), pka: pkaNeeded() ? Number($("ph-pka").value) : null });
      $("ph-mark").style.left = `${Math.max(0, Math.min(14, r.ph)) / 14 * 100}%`;
      const lines = [el("div", "result", `pH = ${fmt(r.ph, 2)}`),
        el("div", "", `[H₃O⁺] = ${fmt(r.h3o)} mol/L · [HO⁻] = ${fmt(r.oh)} mol/L`)];
      if (r.dissociation_percent !== undefined) lines.push(el("div", "muted", `Proportion ${$("ph-kind").value === "acide_faible" ? "dissociée" : "protonée"} : ${fmt(r.dissociation_percent, 2)} %`));
      lines.push(el("div", "muted small", "Calcul exact par l'électroneutralité, autoprotolyse de l'eau comprise (25 °C, pKe = 14)."));
      box.replaceChildren(...lines);
    } catch (e) { fail(box, e); }
  });
  $("buf-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      const r = await call("buffer", { acid: Number($("buf-a").value), base: Number($("buf-b").value), pka: Number($("buf-pka").value) });
      $("buf-out").replaceChildren(el("div", "result", `pH = ${fmt(r.ph, 2)}`),
        el("div", "muted", r.henderson === null ? "" : `Henderson-Hasselbalch (pKa + log [A⁻]/[HA]) : ${fmt(r.henderson, 2)}`));
    } catch (e) { fail($("buf-out"), e); }
  });
  $("dil-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const v = (id) => ($(id).value === "" ? null : Number($(id).value));
    try {
      const r = await call("dilution", { c1: v("dil-c1"), v1: v("dil-v1"), c2: v("dil-c2"), v2: v("dil-v2") });
      $(`dil-${r.found}`).value = +r[r.found].toPrecision(6);
      $("dil-out").replaceChildren(el("div", "result", `${r.found.toUpperCase()} = ${fmt(r[r.found])} · facteur de dilution ${fmt(r.factor, 3)}`),
        el("div", "muted small", "Mêmes unités de volume des deux côtés (mL ou L), mêmes unités de concentration."));
    } catch (e) { fail($("dil-out"), e); }
  });
  $("prep-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      const r = await call("preparation", { formula: $("prep-formula").value, concentration: Number($("prep-c").value),
        volume_L: Number($("prep-v").value) / 1000, purity_percent: Number($("prep-p").value) || 100 });
      $("prep-out").replaceChildren(el("div", "result", `Peser m = ${fmt(r.mass_g, 4)} g de ${r.formula}`),
        el("div", "muted", `n = ${fmt(r.mol)} mol · M = ${fmt(r.molar_mass, 3)} g/mol. Dissoudre dans une fiole jaugée de ${$("prep-v").value} mL, compléter au trait.`));
    } catch (e) { fail($("prep-out"), e); }
  });

  // ==================== titrage ====================
  const T = { data: null, v: 0, playing: false, raf: 0, indicators: [] };
  fillCouples($("ti-preset"), "ti-pka");
  function kindChanged() {
    const k = $("ti-kind").value;
    $("ti-pka").disabled = $("ti-preset").disabled = !k.endsWith("faible");
    $("ti-titrant-label").textContent = k.startsWith("acide") ? "C de la soude NaOH (mol/L)" : "C de l'acide HCl (mol/L)";
    if (k === "base_faible" && Number($("ti-pka").value) < 7) $("ti-pka").value = 9.25;
    if (k === "acide_faible" && Number($("ti-pka").value) > 7) $("ti-pka").value = 4.76;
  }
  $("ti-kind").addEventListener("change", kindChanged);
  function phAt(v) {
    const c = T.data.curve;
    if (v <= c[0][0]) return c[0][1];
    for (let i = 1; i < c.length; i += 1) {
      if (c[i][0] >= v) { const t = (v - c[i - 1][0]) / (c[i][0] - c[i - 1][0]); return c[i - 1][1] + t * (c[i][1] - c[i - 1][1]); }
    }
    return c[c.length - 1][1];
  }
  function mix(a, b, t) {
    const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16)), pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
    return `rgb(${pa.map((x, i) => Math.round(x + (pb[i] - x) * t)).join(",")})`;
  }
  function indicatorColor(ph) {
    const ind = T.indicators[Number($("ti-ind").value)];
    if (!ind) return "#dfe9f2";
    const t = Math.max(0, Math.min(1, (ph - ind.low) / (ind.high - ind.low)));
    return mix(ind.acid, ind.base, t);
  }
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function drawPlot() {
    const cv = $("ti-plot");
    const w = cv.clientWidth, h = cv.clientHeight;
    if (!w || !h) return;
    const dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    const g = cv.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const L = 48, R = 16, TOP = 16, B = 36;
    const vmax = T.data ? T.data.curve[T.data.curve.length - 1][0] : 40;
    const X = (v) => L + (v / vmax) * (w - L - R), Y = (p) => TOP + (1 - p / 14) * (h - TOP - B);
    g.font = "11px Segoe UI, sans-serif";
    g.strokeStyle = css("--line"); g.fillStyle = css("--muted"); g.lineWidth = 1;
    for (let p = 0; p <= 14; p += 2) {
      g.beginPath(); g.moveTo(L, Y(p)); g.lineTo(w - R, Y(p)); g.stroke();
      g.fillText(String(p), L - 22, Y(p) + 4);
    }
    const step = vmax > 60 ? 10 : vmax > 25 ? 5 : 2;
    for (let v = 0; v <= vmax + 1e-9; v += step) {
      g.beginPath(); g.moveTo(X(v), TOP); g.lineTo(X(v), h - B); g.stroke();
      g.fillText(String(v), X(v) - 6, h - B + 16);
    }
    g.fillText("pH", 8, TOP + 8);
    g.fillText("V versé (mL)", w - R - 80, h - 6);
    if (!T.data) { g.fillText("Règle le montage puis « Simuler le titrage ».", L + 20, TOP + 30); return; }
    const ind = T.indicators[Number($("ti-ind").value)];
    if (ind) {   // zone de virage de l'indicateur
      g.fillStyle = mix(ind.acid, ind.base, 0.5).replace("rgb", "rgba").replace(")", ",0.18)");
      g.fillRect(L, Y(ind.high), w - L - R, Y(ind.low) - Y(ind.high));
    }
    g.setLineDash([5, 4]); g.strokeStyle = css("--second");
    g.beginPath(); g.moveTo(X(T.data.v_eq_ml), TOP); g.lineTo(X(T.data.v_eq_ml), h - B); g.stroke();
    g.setLineDash([2, 4]);
    g.beginPath(); g.moveTo(X(T.data.v_half_ml), TOP); g.lineTo(X(T.data.v_half_ml), h - B); g.stroke();
    g.setLineDash([]);
    g.fillStyle = css("--second");
    g.fillText(`équivalence : ${fmt(T.data.v_eq_ml, 2)} mL, pH ${fmt(T.data.ph_eq, 2)}`, Math.min(X(T.data.v_eq_ml) + 6, w - 230), TOP + 14);
    if (T.data.analyte.endsWith("faible")) g.fillText(`½ équiv. : pH = ${fmt(T.data.ph_half, 2)} = pKa`, X(T.data.v_half_ml) + 6, TOP + 30);
    // courbe complète en pâle, partie déjà versée en couleur
    g.lineWidth = 1.5; g.strokeStyle = css("--line-2");
    g.beginPath(); T.data.curve.forEach(([v, p], i) => (i ? g.lineTo(X(v), Y(p)) : g.moveTo(X(v), Y(p)))); g.stroke();
    g.lineWidth = 2.5; g.strokeStyle = css("--accent");
    g.beginPath();
    let started = false;
    for (const [v, p] of T.data.curve) { if (v > T.v) break; if (started) g.lineTo(X(v), Y(p)); else { g.moveTo(X(v), Y(p)); started = true; } }
    g.lineTo(X(T.v), Y(phAt(T.v))); g.stroke();
    g.fillStyle = css("--accent"); g.beginPath(); g.arc(X(T.v), Y(phAt(T.v)), 5, 0, Math.PI * 2); g.fill();
  }
  function drawBench() {
    const svg = $("ti-bench");
    svg.replaceChildren();
    const node = (tag, attrs) => { const n = document.createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); svg.append(n); return n; };
    const vmax = T.data ? T.data.curve[T.data.curve.length - 1][0] : 40;
    const frac = T.data ? T.v / vmax : 0;
    const ph = T.data ? phAt(T.v) : 7;
    // support et burette
    node("rect", { x: 20, y: 4, width: 6, height: 246, rx: 2, fill: "#6b7686" });
    node("rect", { x: 10, y: 246, width: 200, height: 8, rx: 3, fill: "#6b7686" });
    node("rect", { x: 26, y: 40, width: 72, height: 5, fill: "#8792a2" });
    node("rect", { x: 98, y: 6, width: 16, height: 120, rx: 3, fill: "rgba(200,220,240,.18)", stroke: "#9fb0c4" });
    const level = 8 + 116 * frac;
    node("rect", { x: 100, y: level, width: 12, height: 124 - level, fill: T.data && T.data.titrant === "NaOH" ? "rgba(170,200,255,.55)" : "rgba(255,210,170,.55)" });
    for (let i = 0; i <= 10; i += 1) node("line", { x1: 98, x2: 104, y1: 8 + i * 11.6, y2: 8 + i * 11.6, stroke: "#9fb0c4" });
    node("path", { d: "M100 126 L112 126 L108 140 L104 140 Z", fill: "#9fb0c4" });
    if (T.playing) node("circle", { cx: 106, cy: 150, r: 2.5, fill: "rgba(170,200,255,.9)" });
    // bécher
    const fill = 0.35 + 0.35 * frac;
    node("path", { d: `M66 ${240 - 70 * fill} L146 ${240 - 70 * fill} L146 238 Q146 242 142 242 L70 242 Q66 242 66 238 Z`, fill: indicatorColor(ph), opacity: 0.85 });
    node("path", { d: "M62 160 L66 164 L66 238 Q66 244 72 244 L140 244 Q146 244 146 238 L146 164 L150 160", fill: "none", stroke: "#c6d2df", "stroke-width": 2 });
    node("ellipse", { cx: 106, cy: 236, rx: 14, ry: 3, fill: "#e8edf3", opacity: 0.8 });   // turbulent (barreau aimanté)
    const t = node("text", { x: 160, y: 200, fill: css("--second"), "font-size": 13, "font-family": "Consolas, monospace" });
    t.textContent = T.data ? `pH ${fmt(ph, 2)}` : "pH —";
  }
  function update() {
    if (!T.data) return;
    const vmax = T.data.curve[T.data.curve.length - 1][0];
    $("ti-v").value = String(Math.round((T.v / vmax) * 1000));
    $("ti-read").textContent = `V = ${fmt(T.v, 2)} mL · pH = ${fmt(phAt(T.v), 2)}`;
    drawPlot(); drawBench();
  }
  $("ti-v").addEventListener("input", () => {
    if (!T.data) return;
    T.v = (Number($("ti-v").value) / 1000) * T.data.curve[T.data.curve.length - 1][0];
    update();
  });
  $("ti-play").addEventListener("click", () => {
    if (!T.data) { $("ti-form").requestSubmit(); return; }
    T.playing = !T.playing;
    $("ti-play").textContent = T.playing ? "⏸ Pause" : "▶ Verser";
    if (T.playing && T.v >= T.data.curve[T.data.curve.length - 1][0] - 1e-9) T.v = 0;
    let last = performance.now();
    const tick = (now) => {
      if (!T.playing) return;
      const vmax = T.data.curve[T.data.curve.length - 1][0];
      const near = Math.abs(T.v - T.data.v_eq_ml) < vmax * 0.06;   // on ralentit près de l'équivalence, comme au labo
      T.v = Math.min(vmax, T.v + ((now - last) / 1000) * vmax / (near ? 60 : 14));
      last = now;
      update();
      if (T.v >= vmax) { T.playing = false; $("ti-play").textContent = "▶ Verser"; drawBench(); return; }
      T.raf = requestAnimationFrame(tick);
    };
    T.raf = requestAnimationFrame(tick);
  });
  $("ti-ind").addEventListener("change", () => { local.set("indicator", $("ti-ind").value); update(); drawPlot(); drawBench(); });
  $("ti-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const kind = $("ti-kind").value;
    try {
      T.data = await call("titration", { analyte: kind, c_analyte: Number($("ti-ca").value), v_analyte_ml: Number($("ti-va").value),
        c_titrant: Number($("ti-ct").value), pka: kind.endsWith("faible") ? Number($("ti-pka").value) : null });
      T.v = 0; T.playing = false; $("ti-play").textContent = "▶ Verser";
      if (!T.indicators.length) {
        T.indicators = T.data.all_indicators;
        T.indicators.forEach((ind, i) => { const o = el("option", "", `${ind.name} (${String(ind.low).replace(".", ",")}–${String(ind.high).replace(".", ",")})`); o.value = i; $("ti-ind").append(o); });
        $("ti-ind").value = String(local.get("indicator", 5));
      }
      const out = $("ti-out");
      const chips = el("div", "indic");
      for (const n of T.data.indicators) chips.append(el("span", "", n));
      out.replaceChildren(
        el("div", "result", `Véq = ${fmt(T.data.v_eq_ml, 2)} mL · pHéq = ${fmt(T.data.ph_eq, 2)}`),
        el("div", "muted", `pH initial ${fmt(T.data.ph_start, 2)} · saut de pH ${fmt(T.data.jump[0], 1)} → ${fmt(T.data.jump[1], 1)} autour de l'équivalence`),
        el("h3", "", "Indicateurs adaptés"), chips);
      update();
      status("Titrage simulé : fais glisser le curseur ou clique « Verser ».");
    } catch (e) { fail($("ti-out"), e); }
  });
  window.addEventListener("resize", () => { if (!$("ti-plot").closest(".view").hidden) drawPlot(); });

  // ---------- démarrage ----------
  async function init() {
    $("pt-color").value = local.get("ptColor", "category");
    $("mm-formula").value = local.get("mm", "CuSO4·5H2O");
    $("eq-text").value = local.get("eq", "C3H8 + O2 -> CO2 + H2O");
    kindChanged();
    $("ph-kind").dispatchEvent(new Event("change"));
    setMode(local.get("mode", "table"));
    drawBench();
    try {
      const r = await call("elements");
      ELEMENTS = r.elements; CATS = r.categories;
      buildTable();
      showElement(ELEMENTS[5]);
      status("Prêt — calculs exacts par le module chem_lab.");
    } catch (e) { status(e.message, true); }
  }
  init();
  window.AetherChem = { call, setMode };
})();
