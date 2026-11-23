"use strict";
// Æther CAS : application Géométrie (construction dynamique). Chargé après calc_app.js, dont il reprend
// $, el, store, call, toast, drawPlot, css, fmt, mathNode, S (réglages), COLORS.
// Les objets se recalculent à chaque image : déplacer un point libre met à jour tout ce qui en dépend.
// Les mesures sont affichées en décimal, et en valeur exacte à la demande (moteur CAS, `geometry`).

const G = {
  objs: store.get("geo", []), tool: "move", pick: [], sel: null, hover: null, drag: null,
  snap: store.get("geoSnap", true), view: store.get("geoView", { cx: 0, cy: 0, s: 1 / 45 }), undo: [], solved: new Map(),
};
const GEO_TOOLS = [
  { id: "move", label: "Déplacer", need: [], hint: "glisser un point libre ; glisser le fond pour déplacer la vue" },
  { id: "pt", label: "Point", need: ["pt"], hint: "cliquer pour placer un point" },
  { id: "seg", label: "Segment", need: ["pt", "pt"], hint: "deux points" },
  { id: "line", label: "Droite", need: ["pt", "pt"], hint: "deux points" },
  { id: "circ", label: "Cercle", need: ["pt", "pt"], hint: "centre, puis un point du cercle" },
  { id: "poly", label: "Polygone", need: "poly", hint: "sommets, puis recliquer le premier (ou OK)" },
  { id: "mid", label: "Milieu", need: ["pt", "pt"], hint: "deux points (ou un segment)" },
  { id: "perp", label: "Perpendiculaire", need: ["ln", "pt"], hint: "une droite, puis un point" },
  { id: "par", label: "Parallèle", need: ["ln", "pt"], hint: "une droite, puis un point" },
  { id: "bis", label: "Médiatrice", need: ["pt", "pt"], hint: "deux points (ou un segment)" },
  { id: "inter", label: "Intersection", need: ["cu", "cu"], hint: "deux droites ou cercles" },
  { id: "circ3", label: "Cercle circonscrit", need: ["pt", "pt", "pt"], hint: "trois points" },
  { id: "len", label: "Longueur", need: ["pt", "pt"], hint: "deux points (ou un segment)" },
  { id: "angle", label: "Angle", need: ["pt", "pt", "pt"], hint: "A, sommet, C" },
  { id: "area", label: "Aire", need: "poly", hint: "un polygone, ou ses sommets puis OK" },
  { id: "eq", label: "Équation", need: ["cu"], hint: "une droite ou un cercle" },
  { id: "del", label: "Supprimer", need: ["any"], hint: "un objet (et ce qui en dépend)" },
];
const toolOf = (id) => GEO_TOOLS.find((t) => t.id === id);
let geoId = G.objs.reduce((m, o) => Math.max(m, o.id), 0);

// ---------- calcul des objets ----------
function geoSolve() {
  const out = new Map();
  for (const o of G.objs) {
    let v = null;
    try { v = solveOne(o, out); } catch { v = null; }
    out.set(o.id, v);
  }
  G.solved = out;
  return out;
}
const near = (a, b) => Math.hypot(a.x - b.x, a.y - b.y) < 1e-12;
function lineThrough(a, b, seg) { return { k: "ln", x: a.x, y: a.y, dx: b.x - a.x, dy: b.y - a.y, seg, a, b }; }
function solveOne(o, R) {
  const get = (id, k) => { const v = R.get(id); return v && v.k === k ? v : null; };
  const P = (id) => get(id, "pt");
  switch (o.t) {
    case "pt": return { k: "pt", x: o.x, y: o.y, free: true };
    case "mid": { const a = P(o.a), b = P(o.b); return a && b ? { k: "pt", x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } : null; }
    case "inter": { const r = intersect(R.get(o.a), R.get(o.b))[o.i]; return r ? { k: "pt", x: r.x, y: r.y } : null; }
    case "seg": case "line": { const a = P(o.a), b = P(o.b); return a && b && !near(a, b) ? lineThrough(a, b, o.t === "seg") : null; }
    case "perp": case "par": {
      const l = get(o.l, "ln"), p = P(o.p);
      if (!l || !p) return null;
      const [dx, dy] = o.t === "perp" ? [-l.dy, l.dx] : [l.dx, l.dy];
      return lineThrough(p, { x: p.x + dx, y: p.y + dy }, false);
    }
    case "bis": {
      const a = P(o.a), b = P(o.b);
      if (!a || !b || near(a, b)) return null;
      const m = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      return lineThrough(m, { x: m.x - (b.y - a.y), y: m.y + (b.x - a.x) }, false);
    }
    case "circ": { const c = P(o.c), p = P(o.p); const r = c && p ? Math.hypot(p.x - c.x, p.y - c.y) : 0; return r > 1e-12 ? { k: "ci", x: c.x, y: c.y, r, c, p } : null; }
    case "circ3": {
      const [a, b, c] = [P(o.a), P(o.b), P(o.c)];
      if (!a || !b || !c) return null;
      const d = 2 * (a.x * (b.y - c.y) + b.x * (c.y - a.y) + c.x * (a.y - b.y));
      if (Math.abs(d) < 1e-12) return null;
      const s = (p) => p.x * p.x + p.y * p.y;
      const x = (s(a) * (b.y - c.y) + s(b) * (c.y - a.y) + s(c) * (a.y - b.y)) / d;
      const y = (s(a) * (c.x - b.x) + s(b) * (a.x - c.x) + s(c) * (b.x - a.x)) / d;
      return { k: "ci", x, y, r: Math.hypot(a.x - x, a.y - y), pts: [a, b, c] };
    }
    case "poly": { const pts = o.pts.map(P); return pts.every(Boolean) ? { k: "pg", pts } : null; }
    case "meas": return measureValue(o, R);
    default: return null;
  }
}
function intersect(u, v) {
  if (!u || !v) return [];
  if (u.k === "ci" && v.k === "ln") [u, v] = [v, u];
  const onSeg = (l, t) => !l.seg || (t > -1e-9 && t < 1 + 1e-9);
  if (u.k === "ln" && v.k === "ln") {
    const den = u.dx * v.dy - u.dy * v.dx;
    if (Math.abs(den) < 1e-12) return [];
    const t = ((v.x - u.x) * v.dy - (v.y - u.y) * v.dx) / den, s = ((v.x - u.x) * u.dy - (v.y - u.y) * u.dx) / den;
    return onSeg(u, t) && onSeg(v, s) ? [{ x: u.x + t * u.dx, y: u.y + t * u.dy }] : [];
  }
  if (u.k === "ln" && v.k === "ci") {
    const fx = u.x - v.x, fy = u.y - v.y, a = u.dx * u.dx + u.dy * u.dy, b = 2 * (fx * u.dx + fy * u.dy), c = fx * fx + fy * fy - v.r * v.r;
    const disc = b * b - 4 * a * c;
    if (disc < -1e-12) return [];
    const r = Math.sqrt(Math.max(0, disc));
    return [(-b - r) / (2 * a), (-b + r) / (2 * a)].map((t) => (onSeg(u, t) ? { x: u.x + t * u.dx, y: u.y + t * u.dy } : null));
  }
  if (u.k === "ci" && v.k === "ci") {
    const dx = v.x - u.x, dy = v.y - u.y, d = Math.hypot(dx, dy);
    if (d < 1e-12 || d > u.r + v.r + 1e-12 || d < Math.abs(u.r - v.r) - 1e-12) return [];
    const a = (u.r * u.r - v.r * v.r + d * d) / (2 * d), h = Math.sqrt(Math.max(0, u.r * u.r - a * a));
    const mx = u.x + (a * dx) / d, my = u.y + (a * dy) / d;
    return [{ x: mx - (h * dy) / d, y: my + (h * dx) / d }, { x: mx + (h * dy) / d, y: my - (h * dx) / d }];
  }
  return [];
}

// ---------- mesures ----------
function measureValue(o, R) {
  const pts = (o.refs || []).map((id) => R.get(id));
  if (pts.some((p) => !p || p.k !== "pt")) return null;
  if (o.m === "len") return { k: "ms", value: Math.hypot(pts[1].x - pts[0].x, pts[1].y - pts[0].y), at: mid(pts), pts };
  if (o.m === "angle") {
    const [a, b, c] = pts, u = [a.x - b.x, a.y - b.y], v = [c.x - b.x, c.y - b.y];
    const nu = Math.hypot(...u), nv = Math.hypot(...v);
    if (nu < 1e-12 || nv < 1e-12) return null;
    const ang = Math.acos(Math.max(-1, Math.min(1, (u[0] * v[0] + u[1] * v[1]) / (nu * nv))));
    return { k: "ms", value: S.angle === "deg" ? (ang * 180) / Math.PI : ang, angle: ang, at: b, pts };
  }
  if (o.m === "area") {
    let twice = 0;
    pts.forEach((p, i) => { const q = pts[(i + 1) % pts.length]; twice += p.x * q.y - q.x * p.y; });
    return { k: "ms", value: Math.abs(twice) / 2, at: mid(pts), pts };
  }
  if (o.m === "eq") {
    const c = R.get(o.c);
    if (!c) return null;
    return { k: "ms", text: equationText(c), at: c.k === "ln" ? { x: c.x + c.dx / 2, y: c.y + c.dy / 2 } : { x: c.x, y: c.y + c.r }, curve: c };
  }
  return null;
}
const mid = (pts) => ({ x: pts.reduce((s, p) => s + p.x, 0) / pts.length, y: pts.reduce((s, p) => s + p.y, 0) / pts.length });
function equationText(c) {
  const n = (v) => fmt(+v.toPrecision(6));
  if (c.k === "ci") return `(x − ${n(c.x)})² + (y − ${n(c.y)})² = ${n(c.r * c.r)}`.replace(/− -/g, "+ ");
  if (Math.abs(c.dx) < 1e-12) return `x = ${n(c.x)}`;
  const m = c.dy / c.dx, p = c.y - m * c.x;
  return `y = ${n(m)}x ${p < 0 ? "−" : "+"} ${n(Math.abs(p))}`;
}
function measureLabel(o, v) {
  const names = (o.refs || []).map(nameOf);
  if (o.m === "len") return `${names.join("")} = ${fmt(+v.value.toPrecision(6))}`;
  if (o.m === "angle") return `∠${names.join("")} = ${fmt(+v.value.toPrecision(6))}${S.angle === "deg" ? "°" : " rad"}`;
  if (o.m === "area") return `aire ${names.join("")} = ${fmt(+v.value.toPrecision(6))}`;
  return v.text;
}
function exactRequest(o) {
  const R = G.solved, xy = (p) => [+p.x.toPrecision(12), +p.y.toPrecision(12)];
  if (o.m === "len") return { what: "distance", points: o.refs.map((id) => xy(R.get(id))) };
  if (o.m === "angle") return { what: "angle", points: o.refs.map((id) => xy(R.get(id))), degrees: S.angle === "deg" };
  if (o.m === "area") return { what: "area", points: o.refs.map((id) => xy(R.get(id))) };
  const c = R.get(o.c);
  if (c.k === "ln") return { what: "line", points: [xy(c.a), xy(c.b)] };
  if (c.pts) return { what: "circumcircle", points: c.pts.map(xy) };
  return { what: "circle", points: [xy(c.c), xy(c.p)] };
}

// ---------- vue ----------
function geoWin() {
  const c = $("geo"), w = c.clientWidth || 1, h = c.clientHeight || 1, v = G.view;
  return { xmin: v.cx - (w / 2) * v.s, xmax: v.cx + (w / 2) * v.s, ymin: v.cy - (h / 2) * v.s, ymax: v.cy + (h / 2) * v.s };
}
function snapStep() {
  const raw = 14 * G.view.s, p = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw);
}
function toWorld(e) {
  const r = $("geo").getBoundingClientRect(), v = G.view;
  return { x: v.cx + (e.clientX - r.left - r.width / 2) * v.s, y: v.cy - (e.clientY - r.top - r.height / 2) * v.s };
}
function snapped(p) {
  if (!G.snap) return p;
  const s = snapStep();
  return { x: +(Math.round(p.x / s) * s).toPrecision(12), y: +(Math.round(p.y / s) * s).toPrecision(12) };
}
function geoDraw() {
  if (S.app !== "geo") return;
  const R = geoSolve(), names = pointNames();
  const picked = new Set(G.pick), sel = G.sel, hov = G.hover;
  drawPlot($("geo"), geoWin(), [], (ctx, X, Y, w, h) => {
    const px = 1 / G.view.s, ink = css("--screen-ink"), accent = css("--accent") || "#2ec4d6";
    const color = (o, base) => (picked.has(o.id) || sel === o.id ? "#e8590c" : hov === o.id ? accent : base);
    ctx.lineCap = "round";
    for (const o of G.objs) {  // remplissages et tracés d'abord, points ensuite
      const v = R.get(o.id);
      if (!v || o.hidden) continue;
      if (v.k === "pg") {
        ctx.beginPath(); v.pts.forEach((p, i) => (i ? ctx.lineTo(X(p.x), Y(p.y)) : ctx.moveTo(X(p.x), Y(p.y)))); ctx.closePath();
        ctx.fillStyle = color(o, "") ? "rgba(232, 89, 12, .18)" : "rgba(46, 196, 214, .16)"; ctx.fill();
      } else if (v.k === "ln") {
        const len = Math.hypot(v.dx, v.dy), far = (Math.hypot(w, h) * G.view.s * 2) / len;
        const [t0, t1] = v.seg ? [0, 1] : [-far, far];
        ctx.strokeStyle = color(o, o.t === "seg" ? ink : "#7048e8"); ctx.lineWidth = o.t === "seg" ? 2.2 : 1.6;
        ctx.beginPath(); ctx.moveTo(X(v.x + t0 * v.dx), Y(v.y + t0 * v.dy)); ctx.lineTo(X(v.x + t1 * v.dx), Y(v.y + t1 * v.dy)); ctx.stroke();
      } else if (v.k === "ci") {
        ctx.strokeStyle = color(o, "#2f9e44"); ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(X(v.x), Y(v.y), v.r * px, 0, 2 * Math.PI); ctx.stroke();
      }
    }
    ctx.font = "13px Segoe UI, sans-serif";
    for (const o of G.objs) {
      const v = R.get(o.id);
      if (!v || o.hidden) continue;
      if (v.k === "ms") {
        if (o.m === "angle") {
          const [a, b, c] = v.pts, a0 = Math.atan2(-(a.y - b.y), a.x - b.x), a1 = Math.atan2(-(c.y - b.y), c.x - b.x);
          let d = a1 - a0; while (d <= -Math.PI) d += 2 * Math.PI; while (d > Math.PI) d -= 2 * Math.PI;
          ctx.strokeStyle = "#e8590c"; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(X(b.x), Y(b.y), 22, a0, a0 + d, d < 0); ctx.stroke();
        }
        const text = measureLabel(o, v), tx = X(v.at.x) + 8, ty = Y(v.at.y) - 8;
        ctx.fillStyle = "rgba(255,255,255,.85)";
        if (document.documentElement.dataset.screen === "dark") ctx.fillStyle = "rgba(18,22,28,.85)";
        ctx.fillRect(tx - 3, ty - 13, ctx.measureText(text).width + 6, 17);
        ctx.fillStyle = color(o, "#e8590c"); ctx.fillText(text, tx, ty);
      } else if (v.k === "pt") {
        ctx.fillStyle = color(o, v.free ? accent : "#495057");
        ctx.beginPath(); ctx.arc(X(v.x), Y(v.y), v.free ? 5 : 4, 0, 2 * Math.PI); ctx.fill();
        ctx.strokeStyle = ink; ctx.lineWidth = 1; ctx.stroke();
        ctx.fillStyle = ink; ctx.fillText(names.get(o.id) || "", X(v.x) + 7, Y(v.y) - 7);
      }
    }
  });
}
function pointNames() {
  const m = new Map();
  for (const o of G.objs) if (o.name) m.set(o.id, o.name);
  return m;
}
const nameOf = (id) => G.objs.find((o) => o.id === id)?.name || "?";
function freshName() {
  const used = new Set(G.objs.map((o) => o.name).filter(Boolean));
  for (let k = 0; ; k += 1) for (const c of "ABCDEFGHIJKLMNOPQRSTUVWXYZ") { const n = k ? `${c}${k}` : c; if (!used.has(n)) return n; }
}

// ---------- sélection à la souris ----------
function hitTest(e, kinds) {
  const r = $("geo").getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top, s = G.view.s;
  const W = (p) => [r.width / 2 + (p.x - G.view.cx) / s, r.height / 2 - (p.y - G.view.cy) / s];
  let best = null, bestD = 11;
  const consider = (o, d, bonus) => { if (d - bonus < bestD) { best = o; bestD = d - bonus; } };
  for (const o of G.objs) {
    const v = G.solved.get(o.id);
    if (!v || o.hidden) continue;
    const kind = v.k === "pt" ? "pt" : v.k === "ln" ? "ln" : v.k === "ci" ? "ci" : v.k === "pg" ? "pg" : "ms";
    if (!kinds.includes(kind) && !(kinds.includes("cu") && (kind === "ln" || kind === "ci")) && !kinds.includes("any")) continue;
    if (v.k === "pt") { const [x, y] = W(v); consider(o, Math.hypot(mx - x, my - y), 4); }
    else if (v.k === "ln") {
      const [x0, y0] = W(v), [x1, y1] = W({ x: v.x + v.dx, y: v.y + v.dy }), dx = x1 - x0, dy = y1 - y0, l2 = dx * dx + dy * dy;
      let t = ((mx - x0) * dx + (my - y0) * dy) / l2;
      if (v.seg) t = Math.max(0, Math.min(1, t));
      consider(o, Math.hypot(mx - (x0 + t * dx), my - (y0 + t * dy)), 0);
    } else if (v.k === "ci") { const [x, y] = W(v); consider(o, Math.abs(Math.hypot(mx - x, my - y) - v.r / s), 0); }
    else if (v.k === "pg" && insidePoly(toWorld(e), v.pts)) consider(o, 8, 0);
  }
  return best;
}
function insidePoly(p, pts) {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i, i += 1) {
    const a = pts[i], b = pts[j];
    if ((a.y > p.y) !== (b.y > p.y) && p.x < ((b.x - a.x) * (p.y - a.y)) / (b.y - a.y) + a.x) inside = !inside;
  }
  return inside;
}

// ---------- modifications ----------
function saveGeo() { store.set("geo", G.objs); store.set("geoView", G.view); }
function snapshot() { G.undo.push(JSON.stringify(G.objs)); if (G.undo.length > 60) G.undo.shift(); }
function geoUndo() { const last = G.undo.pop(); if (last) { G.objs = JSON.parse(last); G.pick = []; G.sel = null; saveGeo(); geoDraw(); geoPanel(); } else toast("Rien à annuler"); }
function add(obj) { geoId += 1; const o = { id: geoId, ...obj }; G.objs.push(o); return o; }
function addPoint(p) { const q = snapped(p); return add({ t: "pt", x: q.x, y: q.y, name: freshName() }); }
function dependents(id) {
  const out = new Set([id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const o of G.objs) {
      if (out.has(o.id)) continue;
      const refs = [o.a, o.b, o.c, o.p, o.l, ...(o.pts || []), ...(o.refs || [])];
      if (refs.some((r) => out.has(r))) { out.add(o.id); grew = true; }
    }
  }
  return out;
}
function remove(id) { const gone = dependents(id); G.objs = G.objs.filter((o) => !gone.has(o.id)); }

function cancelPick() {  // abandonne une construction commencée, y compris les points créés pour elle
  if (!G.pick.length) return false;
  const last = G.undo.pop();
  if (last) { G.objs = JSON.parse(last); saveGeo(); }
  G.pick = [];
  return true;
}
function setTool(id) {
  cancelPick(); G.tool = id; G.sel = null;
  for (const b of $("geo-tools").querySelectorAll("button")) b.setAttribute("aria-pressed", String(b.dataset.tool === id));
  hint(); geoDraw();
}
function hint(extra) {
  const t = toolOf(G.tool);
  $("geo-info").textContent = extra || `${t.label} : ${t.hint}${G.pick.length ? ` (${G.pick.length} choisi${G.pick.length > 1 ? "s" : ""})` : ""}`;
}
function clickTool(e) {
  const t = toolOf(G.tool), p = toWorld(e);
  if (t.need === "poly") {
    const poly = G.tool === "area" ? hitTest(e, ["pg"]) : null;
    if (poly && !G.pick.length) { snapshot(); add({ t: "meas", m: "area", refs: [...G.objs.find((o) => o.id === poly.id).pts] }); return finish(); }
    const hit = hitTest(e, ["pt"]);
    if (hit && G.pick.length >= 3 && hit.id === G.pick[0]) return closePoly();
    if (!G.pick.length) snapshot();
    G.pick.push(hit ? hit.id : addPoint(p).id);
    hint(); geoDraw(); return null;
  }
  const want = t.need[G.pick.length];
  if (want === "pt" && ["len", "mid", "bis"].includes(G.tool) && !G.pick.length) {  // un segment vaut ses deux extrémités
    const seg = hitTest(e, ["pt", "ln"]);
    if (seg && seg.t === "seg") { snapshot(); G.pick = [seg.a, seg.b]; return complete(); }
  }
  const kinds = want === "pt" ? ["pt"] : want === "ln" ? ["ln"] : want === "cu" ? ["cu"] : ["any"];
  const hit = hitTest(e, kinds);
  if (!G.pick.length) snapshot();
  if (want !== "pt" && hit && G.pick.includes(hit.id)) { hint(`${t.label} : choisir un autre objet`); return null; }
  if (want === "pt") G.pick.push(hit ? hit.id : addPoint(p).id);
  else if (hit) G.pick.push(hit.id);
  else { if (!G.pick.length) G.undo.pop(); hint(`${t.label} : choisir ${want === "ln" ? "une droite ou un segment" : want === "cu" ? "une droite ou un cercle" : "un objet"}`); return null; }
  if (G.tool === "inter") G.clickAt = p;
  if (G.pick.length === t.need.length) return complete();
  hint(); geoDraw(); return null;
}
function closePoly() {
  if (G.pick.length < 3) { toast("Il faut au moins trois sommets"); return null; }
  if (G.tool === "area") add({ t: "meas", m: "area", refs: [...G.pick] });
  else {
    add({ t: "poly", pts: [...G.pick] });
    G.pick.forEach((a, i) => add({ t: "seg", a, b: G.pick[(i + 1) % G.pick.length] }));  // côtés cliquables
  }
  return finish();
}
function complete() {
  const [a, b, c] = G.pick;
  switch (G.tool) {
    case "pt": break;
    case "seg": case "line": if (a === b) return reject("Deux points distincts"); add({ t: G.tool, a, b }); break;
    case "circ": if (a === b) return reject("Le centre et le point doivent différer"); add({ t: "circ", c: a, p: b }); break;
    case "mid": add({ t: "mid", a, b, name: freshName() }); break;
    case "perp": case "par": add({ t: G.tool, l: a, p: b }); break;
    case "bis": if (a === b) return reject("Deux points distincts"); add({ t: "bis", a, b }); break;
    case "circ3": add({ t: "circ3", a, b, c }); break;
    case "len": add({ t: "meas", m: "len", refs: [a, b] }); break;
    case "angle": add({ t: "meas", m: "angle", refs: [a, b, c] }); break;
    case "eq": add({ t: "meas", m: "eq", c: a }); break;
    case "del": remove(a); break;
    case "inter": {
      const found = intersect(G.solved.get(a), G.solved.get(b));
      const idx = found.map((q, i) => [q, i]).filter(([q]) => q);
      if (!idx.length) return reject("Pas d'intersection");
      const click = G.clickAt || { x: 0, y: 0 };
      idx.sort((u, v) => Math.hypot(u[0].x - click.x, u[0].y - click.y) - Math.hypot(v[0].x - click.x, v[0].y - click.y));
      add({ t: "inter", a, b, i: idx[0][1], name: freshName() });
      break;
    }
    default: break;
  }
  return finish();
}
function reject(msg) { toast(msg); G.pick = []; geoUndo(); return null; }
function finish() { G.pick = []; saveGeo(); hint(); geoDraw(); geoPanel(); return true; }

// ---------- panneau des mesures ----------
function geoPanel() {
  const box = $("geo-panel");
  if (box.hidden) return;
  const R = G.solved, rows = G.objs.filter((o) => o.t === "meas" && R.get(o.id));
  const close = el("button", { type: "button", class: "small" }, "✕");
  close.addEventListener("click", () => { box.hidden = true; });
  const list = rows.map((o) => {
    const out = el("td", { class: "exact" });
    const btn = el("button", { type: "button", class: "small" }, "exact");
    btn.addEventListener("click", async () => {
      try {
        const r = await call("geometry", exactRequest(o));
        out.replaceChildren(mathNode(r.mathml, r.exact), r.approx ? el("small", {}, ` ≈ ${r.approx}`) : "");
      } catch (e) { out.replaceChildren(el("span", { class: "err" }, e.message)); }
    });
    return el("tr", {}, el("td", {}, measureLabel(o, R.get(o.id))), el("td", {}, btn), out);
  });
  const pts = G.objs.filter((o) => R.get(o.id)?.k === "pt").map((o) => { const v = R.get(o.id); return el("tr", {}, el("td", {}, `${o.name} (${fmt(+v.x.toPrecision(6))} ; ${fmt(+v.y.toPrecision(6))})`)); });
  box.replaceChildren(el("div", { class: "row" }, el("b", {}, "Mesures"), " ", close),
    rows.length ? el("table", {}, el("tbody", {}, ...list)) : el("p", {}, "Aucune mesure : outils Longueur, Angle, Aire, Équation."),
    el("b", {}, "Points"), el("table", {}, el("tbody", {}, ...pts)));
}

// ---------- interactions ----------
function bindGeo() {
  const c = $("geo");
  $("geo-tools").replaceChildren(...GEO_TOOLS.map((t) => {
    const b = el("button", { type: "button", class: "small", "data-tool": t.id, "aria-pressed": String(t.id === G.tool), title: t.hint }, t.label);
    b.addEventListener("click", () => setTool(t.id));
    return b;
  }));
  c.addEventListener("pointerdown", (e) => {
    c.setPointerCapture(e.pointerId);
    geoSolve();
    if (G.tool === "move") {
      const hit = hitTest(e, ["pt"]);
      const free = hit && hit.t === "pt";
      if (hit) G.sel = hit.id;
      if (free) snapshot();
      G.drag = free ? { id: hit.id, moved: false } : { pan: true, x: e.clientX, y: e.clientY, view: { ...G.view } };
      c.classList.add("drag");
      geoDraw();
    } else clickTool(e);
  });
  c.addEventListener("pointermove", (e) => {
    const p = toWorld(e);
    $("geo-coords").textContent = `x = ${fmt(+p.x.toPrecision(4))}   y = ${fmt(+p.y.toPrecision(4))}`;
    if (G.drag?.pan) {
      G.view = { ...G.drag.view, cx: G.drag.view.cx - (e.clientX - G.drag.x) * G.view.s, cy: G.drag.view.cy + (e.clientY - G.drag.y) * G.view.s };
      geoDraw(); return;
    }
    if (G.drag) {
      const o = G.objs.find((q) => q.id === G.drag.id), q = snapped(p);
      if (o && (o.x !== q.x || o.y !== q.y)) { o.x = q.x; o.y = q.y; G.drag.moved = true; geoDraw(); geoPanel(); }
      return;
    }
    const kinds = G.tool === "move" ? ["pt"] : ["any"];
    const hov = hitTest(e, kinds)?.id ?? null;
    if (hov !== G.hover) { G.hover = hov; geoDraw(); }
  });
  const end = () => {
    if (G.drag && !G.drag.pan && !G.drag.moved) G.undo.pop();
    if (G.drag) saveGeo();
    G.drag = null; c.classList.remove("drag");
  };
  c.addEventListener("pointerup", end); c.addEventListener("pointercancel", end);
  c.addEventListener("wheel", (e) => {
    e.preventDefault();
    const before = toWorld(e), f = e.deltaY > 0 ? 1.2 : 1 / 1.2;
    G.view.s = Math.min(5, Math.max(1e-4, G.view.s * f));
    const after = toWorld(e);
    G.view.cx += before.x - after.x; G.view.cy += before.y - after.y;
    saveGeo(); geoDraw();
  }, { passive: false });
  $("geo-measures").addEventListener("click", () => { const p = $("geo-panel"); p.hidden = !p.hidden; geoPanel(); });
  $("geo-undo").addEventListener("click", geoUndo);
  $("geo-snap").addEventListener("click", () => { G.snap = !G.snap; store.set("geoSnap", G.snap); geoSnapLabel(); });
  geoSnapLabel();
}
function geoSnapLabel() { $("geo-snap").setAttribute("aria-pressed", String(G.snap)); }
function geoClear() {
  if (!G.objs.length || !confirm("Effacer toute la figure ?")) return;
  snapshot(); G.objs = []; G.pick = []; G.sel = null; saveGeo(); geoDraw(); geoPanel();
}
function geoReset() { G.view = { cx: 0, cy: 0, s: 1 / 45 }; saveGeo(); geoDraw(); }
function geoZoom(f) { G.view.s = Math.min(5, Math.max(1e-4, G.view.s * f)); saveGeo(); geoDraw(); }

// appelés par calc_app.js
function geoShow() { requestAnimationFrame(() => { geoDraw(); hint(); }); }
function geoEsc() {
  if (cancelPick()) { geoDraw(); hint(); return; }
  if (!$("geo-panel").hidden) { $("geo-panel").hidden = true; return; }
  if (G.tool !== "move") setTool("move"); else { G.sel = null; geoDraw(); }
}
function geoNav(dir) {
  const o = G.objs.find((q) => q.id === G.sel && q.t === "pt");
  const step = G.snap ? snapStep() : G.view.s * 4;
  const d = { left: [-1, 0], right: [1, 0], up: [0, 1], down: [0, -1] }[dir];
  if (dir === "ok") { if (G.tool === "poly" || G.tool === "area") closePoly(); return; }
  if (o) { snapshot(); o.x = +(o.x + d[0] * step).toPrecision(12); o.y = +(o.y + d[1] * step).toPrecision(12); saveGeo(); geoDraw(); geoPanel(); return; }
  G.view.cx += d[0] * 40 * G.view.s; G.view.cy += d[1] * 40 * G.view.s; saveGeo(); geoDraw();
}
function geoDeleteSelected() { if (G.sel) { snapshot(); remove(G.sel); G.sel = null; saveGeo(); geoDraw(); geoPanel(); } }
function geoMenuGroups() {
  return [{ group: "Construire", items: GEO_TOOLS.slice(0, 12).map((t) => ({ label: t.label, hint: t.hint, act: () => setTool(t.id) })) },
    { group: "Mesurer", items: GEO_TOOLS.slice(12).map((t) => ({ label: t.label, hint: t.hint, act: () => setTool(t.id) })) },
    { group: "Figure", items: [
      { label: "Panneau des mesures (valeurs exactes)", act: () => { $("geo-panel").hidden = false; geoPanel(); } },
      { label: `Grille magnétique : ${G.snap ? "désactiver" : "activer"}`, act: () => $("geo-snap").click() },
      { label: "Annuler (Ctrl+Z)", act: geoUndo }, { label: "Zoom avant", act: () => geoZoom(1 / 1.5) },
      { label: "Zoom arrière", act: () => geoZoom(1.5) }, { label: "Vue initiale", act: geoReset },
      { label: "Effacer la figure", act: geoClear }] }];
}
bindGeo();
if (S.app === "geo") geoShow();
