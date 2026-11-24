"use strict";
// Atelier circuits Æther, onglet « Banc logique » : éditeur de circuits (SVG), simulation pas à pas et chronogramme.
// Le simulateur est dans logic_sim.js (window.AetherLogic). Poser une pièce : clic dans la palette. Câbler : cliquer
// une sortie (à droite d'une pièce) puis une entrée (à gauche), ou l'inverse. Suppr efface la pièce ou le fil choisi.
(function () {
  const L = window.AetherLogic;
  const $ = (id) => document.getElementById(id);
  const SVG = "http://www.w3.org/2000/svg";
  const STORE = "circuit.logic.doc";
  const WORLD = { w: 1600, h: 900 };
  const GRID = 8;
  const COLORS = ["rouge", "vert", "ambre", "bleu"];
  const SEGS = [ // a b c d e f g dp (afficheur de 44 × 70, coin haut gauche en 0,0)
    "8,4 36,4 32,9 12,9", "37,6 41,9 39,32 34,30 35,10", "39,38 41,61 37,64 33,60 34,40", "8,66 36,66 32,61 12,61",
    "3,61 5,38 10,40 9,60 6,64", "3,9 7,6 10,10 9,30 4,32", "8,35 12,31 32,31 36,35 32,39 12,39", "42,62 45,62 45,65 42,65",
  ];

  const ui = { doc: null, sim: null, sel: null, pending: null, drag: null, running: false, acc: 0, last: 0,
               els: null, started: false, exampleKey: "" };
  const snap = (v) => Math.round(v / GRID) * GRID;
  const el = (name, attrs, parent, text) => {
    const node = document.createElementNS(SVG, name);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
    if (text !== undefined) node.textContent = text;
    if (parent) parent.appendChild(node);
    return node;
  };
  const say = (text, bad) => { const s = $("status"); if (s) { s.textContent = text || ""; s.classList.toggle("err", Boolean(bad)); } };
  const nameOf = (p) => p.label || L.TYPES[p.type].label;

  // ---------- montage courant ----------
  function save() { try { localStorage.setItem(STORE, JSON.stringify({ doc: ui.doc, example: ui.exampleKey })); } catch (e) { /* stockage indisponible */ } }
  function restore() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE) || "null");
      if (saved && saved.doc && Array.isArray(saved.doc.parts)) { ui.exampleKey = saved.example || ""; return saved.doc; }
    } catch (e) { /* montage illisible : on repart de l'exemple */ }
    ui.exampleKey = "compteur";
    return L.EXAMPLES.compteur.build();
  }
  function use(doc, key) {
    ui.doc = doc;
    ui.exampleKey = key || "";
    ui.sel = null; ui.pending = null;
    const pick = $("logic-example");
    if (pick && pick.options.length > 1) pick.value = ui.exampleKey;
    reload();
  }
  // Après un changement de câblage ou de pièces, la simulation repart de zéro.
  function reload() {
    try { ui.sim = new L.Sim(ui.doc); }
    catch (e) { say(e.message, true); ui.doc = { version: 1, parts: [], wires: [] }; ui.sim = new L.Sim(ui.doc); }
    save();
    rebuild();
    info();
  }
  const freeId = () => { let n = ui.doc.parts.length + 1; while (ui.doc.parts.some((p) => p.id === `p${n}`)) n++; return `p${n}`; };

  // ---------- dessin ----------
  function wirePath(w) {
    const a = ui.doc.parts.find((p) => p.id === w.from[0]), b = ui.doc.parts.find((p) => p.id === w.to[0]);
    if (!a || !b) return "";
    const o = L.TYPES[a.type].outs.indexOf(w.from[1]), i = L.TYPES[b.type].inNames.indexOf(w.to[1]);
    if (o < 0 || i < 0) return "";
    const p = L.pinPos(a, "out", o), q = L.pinPos(b, "in", i);
    if (q.x - p.x >= 24) {
      // Les fils parallèles ne descendent pas tous au même endroit : léger décalage selon l'entrée visée.
      const mid = Math.max(p.x + 8, Math.min(q.x - 8, snap((p.x + q.x) / 2) + ((i % 5) - 2) * 4));
      return `M${p.x},${p.y} H${mid} V${q.y} H${q.x}`;
    }
    // Fil qui revient en arrière (rebouclage) : il contourne par-dessous les pièces.
    const ha = L.size(L.TYPES[a.type]).h, hb = L.size(L.TYPES[b.type]).h;
    const low = Math.max(a.y + ha, b.y + hb) + 12;
    return `M${p.x},${p.y} H${p.x + 12} V${low} H${q.x - 12} V${q.y} H${q.x}`;
  }

  function drawPart(g, p) {
    const def = L.TYPES[p.type];
    const { w, h } = L.size(def);
    const t = p.type;
    const cls = `lg-body cat-${def.cat === "Portes" ? "gate" : def.cat === "Blocs" || def.cat === "Bascules" ? "block" : "io"}`;
    el("rect", { x: 0, y: 0, width: w, height: h, rx: t === "led" || t === "probe" ? 14 : 5, class: cls }, g);
    const refs = {};
    if (def.cat === "Portes") {
      el("text", { x: w / 2, y: h / 2 + 5, class: "lg-symbol" }, g, def.symbol);
      if (["not", "nand", "nor", "xnor"].includes(t)) el("circle", { cx: w + 4, cy: h / 2, r: 4, class: "lg-bubble" }, g);
    } else if (t === "switch") {
      el("rect", { x: 12, y: h / 2 - 7, width: 32, height: 14, rx: 7, class: "lg-track" }, g);
      refs.knob = el("circle", { cx: 19, cy: h / 2, r: 5, class: "lg-knob" }, g);
    } else if (t === "button") {
      refs.cap = el("circle", { cx: w / 2 - 2, cy: h / 2, r: 9, class: "lg-cap" }, g);
    } else if (t === "clock") {
      el("path", { d: `M10,${h / 2 + 6} h8 v-12 h8 v12 h8 v-12 h8`, class: "lg-wave" }, g);
    } else if (t === "led") {
      refs.led = el("circle", { cx: w / 2 - 2, cy: h / 2, r: 9, class: `lg-led c-${p.props.color || "rouge"}` }, g);
    } else if (t === "probe") {
      refs.led = el("path", { d: `M${w / 2 - 2},${h / 2 - 8} l8,8 l-8,8 l-8,-8 z`, class: "lg-probe" }, g);
    } else if (t === "hex7" || t === "seg7") {
      const box = el("g", { transform: `translate(${w - 52},${(h - 70) / 2})` }, g);
      refs.segs = SEGS.map((pts) => el("polygon", { points: pts, class: "lg-seg" }, box));
    } else {
      el("text", { x: w / 2, y: 11, class: "lg-title" }, g, def.short || def.label);
      if (["counter4", "reg4"].includes(t)) refs.value = el("text", { x: w / 2, y: h - 7, class: "lg-value" }, g, "0");
    }
    // Broches et leurs noms.
    refs.ins = def.ins.map((n, k) => {
      const q = L.pinPos({ type: t, x: 0, y: 0 }, "in", k);
      if (def.cat === "Blocs" || def.cat === "Bascules" || t === "hex7" || t === "seg7") {
        el("text", { x: 7, y: q.y + 3, class: "lg-pin-name" }, g, def.inNames[k]);
      }
      return el("circle", { cx: q.x, cy: q.y, r: 4, class: "lg-pin in", "data-part": p.id, "data-pin": def.inNames[k] }, g);
    });
    refs.outs = def.outs.map((n, k) => {
      const q = L.pinPos({ type: t, x: 0, y: 0 }, "out", k);
      if (def.cat === "Blocs" || def.cat === "Bascules") el("text", { x: w - 7, y: q.y + 3, class: "lg-pin-name end" }, g, n);
      return el("circle", { cx: q.x + (["not", "nand", "nor", "xnor"].includes(t) ? 8 : 0), cy: q.y, r: 4,
                            class: "lg-pin out", "data-part": p.id, "data-pin": n }, g);
    });
    if (p.label) el("text", { x: w / 2, y: -5, class: "lg-label" }, g, p.label);
    return refs;
  }

  function rebuild() {
    const svg = $("logic-svg");
    svg.replaceChildren();
    svg.setAttribute("viewBox", `0 0 ${WORLD.w} ${WORLD.h}`);
    svg.setAttribute("width", WORLD.w); svg.setAttribute("height", WORLD.h);
    const defs = el("defs", {}, svg);
    const pat = el("pattern", { id: "lg-grid", width: 16, height: 16, patternUnits: "userSpaceOnUse" }, defs);
    el("circle", { cx: 1, cy: 1, r: 1, class: "lg-dot" }, pat);
    el("rect", { x: 0, y: 0, width: WORLD.w, height: WORLD.h, fill: "url(#lg-grid)", class: "lg-bg" }, svg);
    const wires = el("g", {}, svg), parts = el("g", {}, svg);
    ui.els = { wires: [], parts: new Map(), temp: el("path", { class: "lg-temp", d: "" }, svg) };
    ui.doc.wires.forEach((w, k) => {
      const hit = el("path", { d: wirePath(w), class: "lg-wire-hit", "data-wire": k }, wires);
      const line = el("path", { d: wirePath(w), class: "lg-wire" }, wires);
      ui.els.wires.push({ hit, line, w });
    });
    for (const p of ui.doc.parts) {
      const g = el("g", { transform: `translate(${p.x},${p.y})`, class: `lg-part t-${p.type}`, "data-part": p.id }, parts);
      ui.els.parts.set(p.id, { g, refs: drawPart(g, p), p });
    }
    paint();
  }

  // Couleurs des fils, LED, afficheurs et valeurs, d'après la simulation.
  function paint() {
    const sim = ui.sim;
    if (!ui.els || !sim) return;
    for (const item of ui.els.wires) {
      const v = sim.outputs(item.w.from[0])[L.TYPES[sim.part(item.w.from[0]).def.type].outs.indexOf(item.w.from[1])];
      item.line.classList.toggle("on", v === 1);
      const selected = ui.sel && ui.sel.wire === item.w;
      item.line.classList.toggle("sel", Boolean(selected));
    }
    for (const [id, { g, refs, p }] of ui.els.parts) {
      g.classList.toggle("sel", Boolean(ui.sel && ui.sel.part === id));
      const ins = sim.inputs(id), outs = sim.outputs(id);
      refs.ins.forEach((c, k) => c.classList.toggle("on", ins[k] === 1));
      refs.outs.forEach((c, k) => c.classList.toggle("on", outs[k] === 1));
      if (refs.knob) { refs.knob.setAttribute("cx", outs[0] ? 37 : 19); refs.knob.classList.toggle("on", outs[0] === 1); }
      if (refs.cap) refs.cap.classList.toggle("on", outs[0] === 1);
      if (refs.led) refs.led.classList.toggle("on", ins[0] === 1);
      if (refs.segs) { const m = sim.segments(id); refs.segs.forEach((s, k) => s.classList.toggle("on", Boolean((m >> k) & 1))); }
      if (refs.value) refs.value.textContent = sim.stateOf(id).v.toString(16).toUpperCase();
      if (ui.pending && ui.pending.part === id) {
        for (const c of [...refs.ins, ...refs.outs]) c.classList.toggle("pending", c.dataset.pin === ui.pending.pin);
      } else for (const c of [...refs.ins, ...refs.outs]) c.classList.remove("pending");
      void p;
    }
    chrono();
    $("logic-time").textContent = `t = ${sim.t}`;
    $("logic-stable").textContent = sim.unstable ? "⚠ instable : le circuit oscille (une boucle sans bascule ?)" : "stable";
    $("logic-stable").classList.toggle("warn", sim.unstable);
  }

  // ---------- chronogramme ----------
  function chrono() {
    const canvas = $("logic-chrono");
    const box = canvas.parentElement.getBoundingClientRect();
    const sim = ui.sim, rows = sim.traced();
    const dpr = window.devicePixelRatio || 1;
    const rowH = 22, head = 86;
    const width = Math.max(200, Math.floor(box.width)), height = Math.max(40, rows.length * rowH + 10);
    if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
      canvas.width = width * dpr; canvas.height = height * dpr;
      canvas.style.width = `${width}px`; canvas.style.height = `${height}px`;
    }
    const css = getComputedStyle(document.documentElement);
    const ink = css.getPropertyValue("--ink").trim(), muted = css.getPropertyValue("--muted").trim();
    const accent = css.getPropertyValue("--accent").trim(), line = css.getPropertyValue("--line").trim();
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.font = `11px ${css.getPropertyValue("--mono")}`;
    const cell = 12, room = Math.floor((width - head - 6) / cell);
    const hist = sim.history.slice(-room);
    ctx.strokeStyle = line; ctx.lineWidth = 1;
    hist.forEach((s, k) => {
      if (s.t % 4) return;
      const x = head + k * cell + 0.5;
      ctx.beginPath(); ctx.moveTo(x, 2); ctx.lineTo(x, height - 4); ctx.stroke();
    });
    rows.forEach((p, r) => {
      const y0 = 6 + r * rowH, hi = y0 + 3, lo = y0 + rowH - 5;
      ctx.fillStyle = r % 2 ? muted : ink;
      ctx.fillText((p.src.label || p.def.label).slice(0, 11), 4, y0 + 14);
      ctx.strokeStyle = accent; ctx.lineWidth = 1.6;
      ctx.beginPath();
      let prev = null;
      hist.forEach((s, k) => {
        const v = s.v[r];
        const x = head + k * cell, y = v ? hi : lo;
        if (prev === null) ctx.moveTo(x, y); else if (prev !== v) ctx.lineTo(x, y);
        ctx.lineTo(x + cell, y);
        prev = v;
      });
      ctx.stroke();
    });
    if (!rows.length) { ctx.fillStyle = muted; ctx.fillText("Pose une horloge, un interrupteur, une LED ou une sonde : leurs signaux s'affichent ici.", 6, 24); }
  }

  // ---------- panneau de la pièce choisie ----------
  function info() {
    const box = $("logic-props");
    box.replaceChildren();
    const add = (tag, text, cls) => { const n = document.createElement(tag); if (text) n.textContent = text; if (cls) n.className = cls; box.appendChild(n); return n; };
    const sel = ui.sel;
    if (sel && sel.wire) {
      const w = sel.wire;
      const pa = ui.doc.parts.find((p) => p.id === w.from[0]), pb = ui.doc.parts.find((p) => p.id === w.to[0]);
      add("h3", "Fil");
      add("p", `${nameOf(pa)} · ${w.from[1]} → ${nameOf(pb)} · ${w.to[1]}`);
      const del = add("button", "Supprimer le fil", "ghost danger");
      del.addEventListener("click", removeSelected);
    } else if (sel && sel.part) {
      const p = ui.doc.parts.find((q) => q.id === sel.part);
      const def = L.TYPES[p.type];
      add("h3", def.label);
      const lab = document.createElement("label");
      lab.textContent = "Nom ";
      const input = document.createElement("input");
      input.value = p.label || ""; input.maxLength = 12; input.className = "lg-name";
      input.addEventListener("change", () => { p.label = input.value.trim(); save(); rebuild(); });
      lab.appendChild(input); box.appendChild(lab);
      if (p.type === "clock") {
        const l2 = document.createElement("label");
        l2.textContent = "Demi-période (pas) ";
        const n = document.createElement("input");
        n.type = "number"; n.min = 1; n.max = 32; n.value = p.props.half || 1; n.className = "lg-num";
        n.addEventListener("change", () => { p.props.half = Math.min(32, Math.max(1, n.value | 0)); reload(); });
        l2.appendChild(n); box.appendChild(l2);
      }
      if (p.type === "led") {
        const l2 = document.createElement("label");
        l2.textContent = "Couleur ";
        const s = document.createElement("select");
        for (const c of COLORS) { const o = document.createElement("option"); o.value = c; o.textContent = c; s.appendChild(o); }
        s.value = p.props.color || "rouge";
        s.addEventListener("change", () => { p.props.color = s.value; save(); rebuild(); });
        l2.appendChild(s); box.appendChild(l2);
      }
      if (p.type === "rom") {
        add("p", "Contenu (16 octets en hexadécimal, adresse 0 à F) :", "muted small");
        const grid = add("div", "", "lg-rom");
        const data = p.props.data || new Array(16).fill(0);
        data.forEach((v, k) => {
          const cell = document.createElement("input");
          cell.value = (v & 0xff).toString(16).toUpperCase().padStart(2, "0");
          cell.maxLength = 2; cell.title = `adresse ${k.toString(16).toUpperCase()}`;
          cell.addEventListener("change", () => {
            const n = parseInt(cell.value, 16);
            data[k] = Number.isFinite(n) ? n & 0xff : 0;
            p.props.data = data; reload();
          });
          grid.appendChild(cell);
        });
      }
      const hint = {
        switch: "Clique l'interrupteur pour le basculer.",
        button: "Garde le bouton enfoncé : sa sortie vaut 1 tant que tu appuies.",
        clock: "Change d'état tous les N pas. Un front montant (0 → 1) fait avancer les bascules et les compteurs.",
        dff: "Au front montant de CLK, Q prend la valeur de D. R (remise à zéro) agit tout de suite.",
        tff: "Au front montant de CLK, Q s'inverse si T = 1 (T vaut 1 si rien n'y est branché).",
        jkff: "Au front montant : J seul met à 1, K seul remet à 0, J et K ensemble inversent Q.",
        srlatch: "S met Q à 1, R le remet à 0 ; sans signal, Q garde sa valeur (mémoire d'un bit).",
        counter4: "Avance de 1 à chaque front montant si EN = 1. CH charge D0 à D3, RAZ remet à 0 tout de suite. RET vaut 1 à 15.",
        reg4: "Au front montant de CLK, garde D0 à D3 si CH = 1 (CH vaut 1 si rien n'y est branché).",
        rom: "Lit l'octet rangé à l'adresse A0 à A3 (A0 = bit de poids faible).",
        hex7: "Affiche en hexadécimal le nombre formé par D0 à D3.",
        mux4b: "SEL = 0 : Y recopie A ; SEL = 1 : Y recopie B.",
        add4: "S = A + B + Ri ; Ro est la retenue de sortie.",
      }[p.type];
      if (hint) add("p", hint, "muted small");
      const st = ui.sim.stateOf(p.id);
      if (st.q !== undefined) add("p", `Q = ${st.q}`, "lg-state");
      if (st.v !== undefined && !["switch", "button", "clock"].includes(p.type)) add("p", `Valeur = ${st.v} (${st.v.toString(2).padStart(4, "0")})`, "lg-state");
      const del = add("button", "Supprimer la pièce", "ghost danger");
      del.addEventListener("click", removeSelected);
    } else {
      add("p", "Clique une pièce ou un fil pour le régler. Pour câbler : clique une sortie (à droite), puis une entrée (à gauche).", "muted small");
    }
    const ex = L.EXAMPLES[ui.exampleKey];
    const pick = $("logic-example");
    if (pick.options.length > 1 && pick.value !== ui.exampleKey) pick.value = ui.exampleKey;
    $("logic-about").textContent = ex ? `${ex.title} : ${ex.text}` : "Montage personnel.";
    const probs = ui.sim.problems;
    $("logic-count").textContent = `${ui.doc.parts.length} pièces, ${ui.doc.wires.length} fils${probs.length ? ` · ${probs.join(" ; ")}` : ""}`;
  }

  function removeSelected() {
    const sel = ui.sel;
    if (!sel) return;
    if (sel.wire) ui.doc.wires = ui.doc.wires.filter((w) => w !== sel.wire);
    if (sel.part) {
      ui.doc.parts = ui.doc.parts.filter((p) => p.id !== sel.part);
      ui.doc.wires = ui.doc.wires.filter((w) => w.from[0] !== sel.part && w.to[0] !== sel.part);
    }
    ui.sel = null; ui.exampleKey = "";
    reload();
  }
  function select(sel) { ui.sel = sel; paint(); info(); }

  // ---------- souris ----------
  function point(e) {
    const svg = $("logic-svg");
    const r = svg.getBoundingClientRect();
    return { x: (e.clientX - r.left) * (WORLD.w / r.width), y: (e.clientY - r.top) * (WORLD.h / r.height) };
  }
  function connect(a, b) {
    // a et b : {part, pin, side}. Un fil va toujours d'une sortie vers une entrée.
    if (a.side === b.side) { say("Un fil relie une sortie (à droite d'une pièce) à une entrée (à gauche).", true); return; }
    const out = a.side === "out" ? a : b, inp = a.side === "in" ? a : b;
    ui.doc.wires = ui.doc.wires.filter((w) => !(w.to[0] === inp.part && w.to[1] === inp.pin));
    ui.doc.wires.push({ from: [out.part, out.pin], to: [inp.part, inp.pin] });
    ui.exampleKey = "";
    say(`Fil posé : ${out.pin} → ${inp.pin}.`);
    reload();
  }
  function pinAt(target) {
    const c = target.closest && target.closest(".lg-pin");
    return c ? { part: c.dataset.part, pin: c.dataset.pin, side: c.classList.contains("out") ? "out" : "in", node: c } : null;
  }
  function pinXY(pin) {
    const p = ui.doc.parts.find((q) => q.id === pin.part);
    const def = L.TYPES[p.type];
    const k = pin.side === "out" ? def.outs.indexOf(pin.pin) : def.inNames.indexOf(pin.pin);
    return L.pinPos(p, pin.side, k);
  }
  function onDown(e) {
    if (e.button !== 0) return;
    const pin = pinAt(e.target);
    if (pin) {
      e.preventDefault();
      if (ui.pending && (ui.pending.part !== pin.part || ui.pending.pin !== pin.pin)) { const a = ui.pending; ui.pending = null; connect(a, pin); return; }
      ui.pending = pin;
      ui.drag = { kind: "wire", start: point(e), moved: false };
      paint();
      return;
    }
    const wire = e.target.closest && e.target.closest(".lg-wire-hit");
    if (wire) { ui.pending = null; select({ wire: ui.doc.wires[Number(wire.dataset.wire)] }); return; }
    const g = e.target.closest && e.target.closest(".lg-part");
    if (g) {
      e.preventDefault();
      const p = ui.doc.parts.find((q) => q.id === g.dataset.part);
      const at = point(e);
      ui.drag = { kind: "part", p, dx: at.x - p.x, dy: at.y - p.y, moved: false, start: at };
      if (p.type === "button") ui.sim.setInput(p.id, 1);
      ui.pending = null;
      select({ part: p.id });
      $("logic-svg").setPointerCapture(e.pointerId);
      return;
    }
    ui.pending = null;
    ui.els.temp.setAttribute("d", "");
    select(null);
  }
  function onMove(e) {
    const d = ui.drag;
    if (!d) return;
    const at = point(e);
    if (Math.abs(at.x - d.start.x) + Math.abs(at.y - d.start.y) > 4) d.moved = true;
    if (d.kind === "part" && d.moved) {
      d.p.x = Math.max(0, Math.min(WORLD.w - 80, snap(at.x - d.dx)));
      d.p.y = Math.max(16, Math.min(WORLD.h - 60, snap(at.y - d.dy)));
      const item = ui.els.parts.get(d.p.id);
      item.g.setAttribute("transform", `translate(${d.p.x},${d.p.y})`);
      for (const wv of ui.els.wires) if (wv.w.from[0] === d.p.id || wv.w.to[0] === d.p.id) {
        const path = wirePath(wv.w); wv.line.setAttribute("d", path); wv.hit.setAttribute("d", path);
      }
    } else if (d.kind === "wire" && ui.pending) {
      const a = pinXY(ui.pending);
      ui.els.temp.setAttribute("d", `M${a.x},${a.y} L${at.x},${at.y}`);
    }
  }
  function onUp(e) {
    const d = ui.drag;
    ui.drag = null;
    if (!d) return;
    if (d.kind === "part") {
      if (d.p.type === "button") ui.sim.setInput(d.p.id, 0);
      if (d.moved) save();
      else if (d.p.type === "switch") ui.sim.setInput(d.p.id, ui.sim.outputs(d.p.id)[0] ? 0 : 1);
      paint(); info();
    } else if (d.kind === "wire") {
      ui.els.temp.setAttribute("d", "");
      const under = document.elementFromPoint(e.clientX, e.clientY);
      const pin = under ? pinAt(under) : null;
      if (d.moved && pin && ui.pending && (pin.part !== ui.pending.part || pin.pin !== ui.pending.pin)) {
        const a = ui.pending; ui.pending = null; connect(a, pin);
      } else if (d.moved) { ui.pending = null; paint(); }
      else say("Choisis maintenant l'autre bout du fil (Échap pour annuler).");
    }
  }

  // ---------- palette ----------
  function palette() {
    const box = $("logic-palette");
    box.replaceChildren();
    const groups = {};
    for (const def of Object.values(L.TYPES)) (groups[def.cat] = groups[def.cat] || []).push(def);
    for (const [cat, defs] of Object.entries(groups)) {
      const h = document.createElement("h3"); h.textContent = cat; box.appendChild(h);
      const list = document.createElement("div"); list.className = "lg-palette";
      for (const def of defs) {
        const b = document.createElement("button");
        b.type = "button"; b.className = "ghost small"; b.textContent = def.label; b.dataset.type = def.type;
        b.addEventListener("click", () => addPart(def.type));
        list.appendChild(b);
      }
      box.appendChild(list);
    }
  }
  function addPart(type) {
    const stage = $("logic-stage");
    const svg = $("logic-svg").getBoundingClientRect(), s = stage.getBoundingClientRect();
    const k = WORLD.w / Math.max(1, svg.width);
    let x = snap((s.left - svg.left + s.width / 2) * k - 30), y = snap((s.top - svg.top + s.height / 2) * k - 20);
    while (ui.doc.parts.some((p) => p.x === x && p.y === y)) { x += 24; y += 24; }
    const p = { id: freeId(), type, x: Math.max(8, x), y: Math.max(24, y), label: "", props: {} };
    ui.doc.parts.push(p);
    ui.exampleKey = "";
    ui.sel = { part: p.id };
    reload();
    say(`${L.TYPES[type].label} posé(e) : glisse-le à sa place, puis câble ses broches.`);
  }

  // ---------- simulation ----------
  function step() { ui.sim.step(); paint(); if (ui.sel && ui.sel.part) info(); }
  function setRunning(on) {
    ui.running = on;
    $("logic-run").textContent = on ? "⏸ Pause" : "▶ Lancer";
    $("logic-run").classList.toggle("primary", !on);
    ui.last = performance.now(); ui.acc = 0;
  }
  function frame(now) {
    if (ui.running && visible()) {
      const rate = Number($("logic-speed").value);
      ui.acc += Math.min(250, now - ui.last) * rate / 1000;
      let n = 0;
      while (ui.acc >= 1 && n < 60) { ui.sim.step(); ui.acc -= 1; n++; }
      if (n) { paint(); if (ui.sel && ui.sel.part) info(); }
    }
    ui.last = now;
    requestAnimationFrame(frame);
  }
  const visible = () => !$("logic-view").hidden;

  function exportDoc() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(ui.doc, null, 1)], { type: "application/json" }));
    const a = document.createElement("a"); a.href = url; a.download = `${ui.exampleKey || "montage"}.logique.json`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    say("Montage exporté.");
  }
  async function importDoc(file) {
    try {
      const doc = JSON.parse(await file.text());
      if (!Array.isArray(doc.parts) || !Array.isArray(doc.wires)) throw new Error("ce fichier n'est pas un montage du banc logique");
      for (const p of doc.parts) if (!L.TYPES[p.type]) throw new Error(`pièce inconnue : ${p.type}`);
      use(doc, "");
      say(`${file.name} chargé.`);
    } catch (e) { say(`${file.name} : ${e.message}`, true); }
  }

  function start() {
    if (ui.started) return;
    ui.started = true;
    palette();
    const pick = $("logic-example");
    for (const [key, ex] of Object.entries(L.EXAMPLES)) {
      const o = document.createElement("option"); o.value = key; o.textContent = ex.title; pick.appendChild(o);
    }
    use(restore(), ui.exampleKey);
    pick.value = ui.exampleKey || "";
    const svg = $("logic-svg");
    svg.addEventListener("pointerdown", onDown);
    svg.addEventListener("pointermove", onMove);
    svg.addEventListener("pointerup", onUp);
    svg.addEventListener("pointercancel", onUp);
    pick.addEventListener("change", () => {
      const ex = L.EXAMPLES[pick.value];
      if (!ex) return;
      setRunning(false);
      use(ex.build(), pick.value);
      say(`Montage chargé : ${ex.title}.`);
    });
    $("logic-run").addEventListener("click", () => setRunning(!ui.running));
    $("logic-step").addEventListener("click", () => { setRunning(false); step(); });
    $("logic-reset").addEventListener("click", () => { reload(); say("Simulation remise à zéro."); });
    $("logic-new").addEventListener("click", () => {
      if (ui.doc.parts.length && !confirm("Effacer le montage en cours ?")) return;
      setRunning(false); use({ version: 1, parts: [], wires: [] }, ""); pick.value = "";
    });
    $("logic-export").addEventListener("click", exportDoc);
    $("logic-import").addEventListener("click", () => $("logic-file").click());
    $("logic-file").addEventListener("change", (e) => { const f = e.target.files[0]; if (f) importDoc(f); e.target.value = ""; });
    window.addEventListener("keydown", (e) => {
      if (!visible() || (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName))) return;
      if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); removeSelected(); }
      else if (e.key === "Escape") { ui.pending = null; ui.els.temp.setAttribute("d", ""); paint(); say(""); }
      else if (e.key === " ") { e.preventDefault(); setRunning(false); step(); }
    });
    window.addEventListener("resize", () => { if (visible()) chrono(); });
    requestAnimationFrame(frame);
  }
  document.addEventListener("circuit-mode", (e) => { if (e.detail === "logic") { start(); requestAnimationFrame(() => paint()); } else setRunning(false); });
  // La page a pu afficher cet onglet avant le chargement de ce script (dernier onglet mémorisé).
  if (!$("logic-view").hidden) { start(); requestAnimationFrame(() => document.dispatchEvent(new CustomEvent("circuit-mode", { detail: "logic" }))); }
  window.AetherLogicApp = { get sim() { return ui.sim; }, get doc() { return ui.doc; }, step, start, connect, addPart,
                            load: (key) => use(L.EXAMPLES[key].build(), key) };
})();
