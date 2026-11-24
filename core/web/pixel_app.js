"use strict";
// Studio pixel Æther : fenêtre du module pixel_studio (sprites, animations, cartes en tuiles).
// Tout passe par l'API locale du Hub (même origine) ; aucune ressource externe. Les images des calques sont
// éditées en mémoire (ImageData) et enregistrées en PNG base64 dans le projet `.aether-pixel`.

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
const local = {
  get(key, fallback) { try { const v = localStorage.getItem(`aepix.${key}`); return v === null ? fallback : JSON.parse(v); } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(`aepix.${key}`, JSON.stringify(value)); } catch { /* stockage indisponible */ } },
};
const ZOOMS = [0.25, 0.5, 1, 2, 3, 4, 6, 8, 10, 12, 16, 20, 24, 32, 40, 48, 64];
const UNDO_MAX = 80;

// ---------- état ----------
let D = null;  // projet : {name, width, height, palette, layers, frames: [{duration, cels: [ImageData|null]}], tilemap}
const S = {
  mode: "sprite", tool: "pencil", mapTool: "paint", frame: 0, layer: 0, primary: "#0e1116", secondary: null,
  brush: 1, mirrorX: false, mirrorY: false, grid: local.get("grid", true), onion: false, palSel: -1,
  view: { sprite: { zoom: 8, x: 0, y: 0, fitted: false }, map: { zoom: 2, x: 0, y: 0, fitted: false } },
  stroke: null, hover: null, space: false, pan: null, playing: false, playTimer: 0,
  sel: null, float: null, clip: null, undo: [], redo: [], dirty: false, saveTimer: 0, savedOnce: false,
  loadedAs: "", tile: 0, mapLayer: "ground", showSolid: true, mapGrid: true, tiles: [],
  previewScale: local.get("previewScale", 2), previewBg: local.get("previewBg", 0), previewFrame: 0, previewTimer: 0,
  colorTarget: null, palettes: [], busy: 0,
};

// ---------- API ----------
let activated = false;
async function post(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(data.detail || `erreur ${r.status}`); e.status = r.status; throw e; }
  return data;
}
async function call(command, payload) {
  S.busy++; $("dot").className = "dot busy";
  try {
    if (!activated) { await post("/modules/pixel_studio/activate"); activated = true; }
    let reply;
    try { reply = await post(`/modules/pixel_studio/command/${command}`, payload); }
    catch (e) {
      if (e.status !== 409) throw e;  // module arrêté entre-temps : on le relance une fois
      await post("/modules/pixel_studio/activate");
      reply = await post(`/modules/pixel_studio/command/${command}`, payload);
    }
    if (!reply.ok) throw new Error((reply.error || "erreur du module").replace(/^\w+Error: /, ""));
    $("dot").className = "dot on";
    return reply.result;
  } catch (e) {
    $("dot").className = "dot err";
    if (e instanceof TypeError) throw new Error("Hub injoignable : lance AetherTwin, puis rouvre le studio");
    throw e;
  } finally { S.busy--; }
}

let toastTimer = 0;
function toast(message, error = false) {
  const t = $("toast");
  t.textContent = message; t.className = error ? "toast err" : "toast"; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, error ? 6000 : 2600);
}
const fail = (e) => toast(e.message || String(e), true);

// ---------- couleurs ----------
function rgbaOf(hex) {
  if (!hex) return [0, 0, 0, 0];
  return [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16), 255];
}
const hexOf = (r, g, b) => "#" + [r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("");
const luma = (hex) => { const [r, g, b] = rgbaOf(hex); return 0.299 * r + 0.587 * g + 0.114 * b; };
function cleanName(text) {
  return String(text || "").toLowerCase().replace(/œ/g, "oe").replace(/æ/g, "ae").normalize("NFKD")
    .replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9_-]+/g, "_").replace(/^[_-]+|[_-]+$/g, "").slice(0, 40);
}

// ---------- images des calques ----------
function canvasOf(w, h) { const c = document.createElement("canvas"); c.width = w; c.height = h; return c; }
const ctxOf = (c) => c.getContext("2d", { willReadFrequently: true });
const blankCel = () => new ImageData(D.width, D.height);
const copyCel = (img) => (img ? new ImageData(new Uint8ClampedArray(img.data), img.width, img.height) : null);
const VERSION = new WeakMap();
const CACHE = new WeakMap();
function touch(img) { if (img) VERSION.set(img, (VERSION.get(img) || 0) + 1); }
function celCanvas(img) {
  let entry = CACHE.get(img);
  const ver = VERSION.get(img) || 0;
  if (!entry) { entry = { cv: canvasOf(img.width, img.height), ver: -1 }; CACHE.set(img, entry); }
  if (entry.ver !== ver) { ctxOf(entry.cv).putImageData(img, 0, 0); entry.ver = ver; }
  return entry.cv;
}
function isEmpty(img) {
  if (!img) return true;
  const d = img.data;
  for (let i = 3; i < d.length; i += 4) if (d[i]) return false;
  return true;
}
function composeFrame(f, target) {
  const cv = target || canvasOf(D.width, D.height);
  const ctx = ctxOf(cv);
  ctx.clearRect(0, 0, cv.width, cv.height);
  D.layers.forEach((layer, l) => {
    const img = D.frames[f].cels[l];
    if (!layer.visible || !img) return;
    ctx.globalAlpha = layer.opacity;
    ctx.drawImage(celCanvas(img), 0, 0);
  });
  ctx.globalAlpha = 1;
  return cv;
}
function b64ToBytes(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}
async function decodeCel(b64, w, h) {
  const bitmap = await createImageBitmap(new Blob([b64ToBytes(b64)], { type: "image/png" }),
    { premultiplyAlpha: "none", colorSpaceConversion: "none" });
  const cv = canvasOf(w, h);
  const ctx = ctxOf(cv);
  ctx.drawImage(bitmap, 0, 0);
  return ctx.getImageData(0, 0, w, h);
}
function celToB64(img) {
  if (isEmpty(img)) return null;
  return celCanvas(img).toDataURL("image/png").split(",")[1];
}
function blobUrl(b64, type = "image/png") { return URL.createObjectURL(new Blob([b64ToBytes(b64)], { type })); }

function getPx(img, x, y) { const i = (y * img.width + x) * 4; return [img.data[i], img.data[i + 1], img.data[i + 2], img.data[i + 3]]; }
function setPx(img, x, y, c) {
  if (x < 0 || y < 0 || x >= img.width || y >= img.height) return;
  const i = (y * img.width + x) * 4;
  img.data[i] = c[0]; img.data[i + 1] = c[1]; img.data[i + 2] = c[2]; img.data[i + 3] = c[3];
}
const same = (a, b) => a[0] === b[0] && a[1] === b[1] && a[2] === b[2] && a[3] === b[3];

// ---------- projet ----------
function newDoc(name, width, height, palette, frames = 1) {
  return { name, width, height, palette: palette.slice(), layers: [{ name: "Calque 1", visible: true, opacity: 1 }],
           frames: Array.from({ length: frames }, () => ({ duration: 100, cels: [null] })), tilemap: null };
}
async function docFromServer(doc) {
  const frames = [];
  for (const frame of doc.frames) {
    const cels = await Promise.all(frame.cels.map((c) => (c ? decodeCel(c, doc.width, doc.height) : null)));
    frames.push({ duration: frame.duration, cels });
  }
  return { name: doc.name, width: doc.width, height: doc.height, palette: doc.palette.slice(),
           layers: doc.layers.map((l) => ({ ...l })), frames, tilemap: doc.tilemap ? JSON.parse(JSON.stringify(doc.tilemap)) : null };
}
function docToServer() {
  commitFloat();
  const out = { format: "aether-pixel", version: 1, name: D.name, width: D.width, height: D.height,
                palette: D.palette, layers: D.layers,
                frames: D.frames.map((f) => ({ duration: f.duration, cels: f.cels.map(celToB64) })) };
  if (D.tilemap) out.tilemap = D.tilemap;
  return out;
}
function snapshot() {
  return { name: D.name, width: D.width, height: D.height, palette: D.palette.slice(),
           layers: D.layers.map((l) => ({ ...l })),
           frames: D.frames.map((f) => ({ duration: f.duration, cels: f.cels.map(copyCel) })),
           tilemap: D.tilemap ? JSON.parse(JSON.stringify(D.tilemap)) : null, frame: S.frame, layer: S.layer };
}
function restore(snap) {
  D = { name: snap.name, width: snap.width, height: snap.height, palette: snap.palette.slice(),
        layers: snap.layers.map((l) => ({ ...l })),
        frames: snap.frames.map((f) => ({ duration: f.duration, cels: f.cels.map(copyCel) })),
        tilemap: snap.tilemap ? JSON.parse(JSON.stringify(snap.tilemap)) : null };
  S.frame = Math.min(snap.frame ?? S.frame, D.frames.length - 1);
  S.layer = Math.min(snap.layer ?? S.layer, D.layers.length - 1);
}

// ---------- annuler / rétablir ----------
function pushUndo(entry) {
  S.undo.push(entry);
  if (S.undo.length > UNDO_MAX) S.undo.shift();
  S.redo = [];
}
const undoCel = (f, l) => pushUndo({ kind: "cel", f, l, data: copyCel(D.frames[f].cels[l]) });
const undoDoc = () => pushUndo({ kind: "doc", data: snapshot() });
const undoMap = () => pushUndo({ kind: "map", data: JSON.parse(JSON.stringify(D.tilemap)) });
function capture(entry) {
  if (entry.kind === "cel") return { kind: "cel", f: entry.f, l: entry.l, data: copyCel(D.frames[entry.f].cels[entry.l]) };
  if (entry.kind === "map") return { kind: "map", data: JSON.parse(JSON.stringify(D.tilemap)) };
  return { kind: "doc", data: snapshot() };
}
function apply(entry) {
  if (entry.kind === "cel") {
    D.frames[entry.f].cels[entry.l] = copyCel(entry.data);
    S.frame = entry.f; S.layer = entry.l;
  } else if (entry.kind === "map") {
    D.tilemap = JSON.parse(JSON.stringify(entry.data));
  } else {
    restore(entry.data);
  }
}
function undo(redo = false) {
  commitFloat();
  const from = redo ? S.redo : S.undo;
  const to = redo ? S.undo : S.redo;
  const entry = from.pop();
  if (!entry) { toast(redo ? "Rien à rétablir" : "Rien à annuler"); return; }
  to.push(capture(entry));
  apply(entry);
  changed(true);
}

// ---------- vue ----------
const canvas = $("canvas");
const view = () => S.view[S.mode];
function areaSize() {
  if (S.mode === "map" && D.tilemap) return [D.tilemap.cols * D.width, D.tilemap.rows * D.height];
  return [D.width, D.height];
}
function fit() {
  const v = view();
  const [w, h] = areaSize();
  const box = $("stage").getBoundingClientRect();
  v.manual = false;
  if (box.width < 80 || box.height < 80) { v.fitted = false; render(); return; }  // pas encore mis en page
  let z = Math.min((box.width - 40) / w, (box.height - 40) / h);
  z = z >= 1 ? Math.max(1, Math.floor(z)) : Math.max(0.25, z);
  if (S.mode === "sprite") z = Math.min(z, 48);
  v.zoom = z;
  v.x = Math.round((box.width - w * z) / 2);
  v.y = Math.round((box.height - h * z) / 2);
  v.fitted = true;
  render();
}
function zoomAt(next, cx, cy) {
  const v = view();
  next = Math.max(ZOOMS[0], Math.min(ZOOMS[ZOOMS.length - 1], next));
  const px = (cx - v.x) / v.zoom, py = (cy - v.y) / v.zoom;
  v.zoom = next; v.manual = true;
  v.x = Math.round(cx - px * next); v.y = Math.round(cy - py * next);
  render();
}
function zoomStep(dir, cx, cy) {
  const z = view().zoom;
  const next = dir > 0 ? ZOOMS.find((v) => v > z + 1e-6) : [...ZOOMS].reverse().find((v) => v < z - 1e-6);
  const box = $("stage").getBoundingClientRect();
  zoomAt(next ?? z, cx ?? box.width / 2, cy ?? box.height / 2);
}
function toPixel(event) {
  const r = canvas.getBoundingClientRect();
  const v = view();
  return [Math.floor((event.clientX - r.left - v.x) / v.zoom), Math.floor((event.clientY - r.top - v.y) / v.zoom)];
}

// ---------- rendu ----------
let frameRequested = false;
function render() {
  if (frameRequested) return;
  frameRequested = true;
  requestAnimationFrame(() => { frameRequested = false; draw(); });
}
function checker(ctx, x, y, w, h) {
  const styles = getComputedStyle(document.documentElement);
  const a = styles.getPropertyValue("--check-a").trim(), b = styles.getPropertyValue("--check-b").trim();
  ctx.save();
  ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip();
  ctx.fillStyle = a; ctx.fillRect(x, y, w, h);
  ctx.fillStyle = b;
  const s = 8;
  for (let j = 0; j * s < h; j++) for (let i = j % 2; i * s < w; i += 2) ctx.fillRect(x + i * s, y + j * s, s, s);
  ctx.restore();
}
function draw() {
  if (!D) return;
  const dpr = window.devicePixelRatio || 1;
  const box = $("stage").getBoundingClientRect();
  if (canvas.width !== Math.round(box.width * dpr) || canvas.height !== Math.round(box.height * dpr)) {
    canvas.width = Math.round(box.width * dpr); canvas.height = Math.round(box.height * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, box.width, box.height);
  ctx.imageSmoothingEnabled = false;
  if (S.mode === "map") drawMap(ctx); else drawSprite(ctx);
  $("zoom-label").textContent = `${Math.round(view().zoom * 100)} %`;
}
function drawSprite(ctx) {
  const v = view(), z = v.zoom, W = D.width * z, H = D.height * z;
  checker(ctx, v.x, v.y, W, H);
  const frame = D.frames[S.frame];
  if (S.onion && D.frames.length > 1) {
    const prev = (S.frame - 1 + D.frames.length) % D.frames.length;
    const next = (S.frame + 1) % D.frames.length;
    ctx.globalAlpha = 0.28; ctx.drawImage(composeFrame(prev), v.x, v.y, W, H);
    if (next !== prev) { ctx.globalAlpha = 0.14; ctx.drawImage(composeFrame(next), v.x, v.y, W, H); }
  }
  D.layers.forEach((layer, l) => {
    if (!layer.visible) return;
    ctx.globalAlpha = layer.opacity;
    const img = frame.cels[l];
    if (img) ctx.drawImage(celCanvas(img), v.x, v.y, W, H);
    if (l === S.layer && S.float) {
      ctx.drawImage(celCanvas(S.float.img), v.x + S.float.x * z, v.y + S.float.y * z, S.float.img.width * z, S.float.img.height * z);
    }
    if (l === S.layer && S.stroke && S.stroke.preview) {
      for (const [x, y, c] of S.stroke.preview) {
        if (x < 0 || y < 0 || x >= D.width || y >= D.height) continue;
        if (c[3] === 0) { ctx.clearRect(v.x + x * z, v.y + y * z, z, z); continue; }
        ctx.fillStyle = `rgb(${c[0]},${c[1]},${c[2]})`; ctx.fillRect(v.x + x * z, v.y + y * z, z, z);
      }
    }
  });
  ctx.globalAlpha = 1;
  if (S.grid && z >= 6) {
    ctx.strokeStyle = "rgba(128,140,160,.22)"; ctx.lineWidth = 1; ctx.beginPath();
    for (let x = 1; x < D.width; x++) { ctx.moveTo(v.x + x * z + 0.5, v.y); ctx.lineTo(v.x + x * z + 0.5, v.y + H); }
    for (let y = 1; y < D.height; y++) { ctx.moveTo(v.x, v.y + y * z + 0.5); ctx.lineTo(v.x + W, v.y + y * z + 0.5); }
    ctx.stroke();
  }
  ctx.strokeStyle = "rgba(128,140,160,.6)"; ctx.strokeRect(v.x - 0.5, v.y - 0.5, W + 1, H + 1);
  if (S.mirrorX || S.mirrorY) {
    ctx.strokeStyle = "#f2a541"; ctx.setLineDash([6, 4]); ctx.beginPath();
    if (S.mirrorX) { ctx.moveTo(v.x + W / 2, v.y - 8); ctx.lineTo(v.x + W / 2, v.y + H + 8); }
    if (S.mirrorY) { ctx.moveTo(v.x - 8, v.y + H / 2); ctx.lineTo(v.x + W + 8, v.y + H / 2); }
    ctx.stroke(); ctx.setLineDash([]);
  }
  const sel = S.float ? { x: S.float.x, y: S.float.y, w: S.float.img.width, h: S.float.img.height } : S.sel;
  if (sel) {
    ctx.lineWidth = 1;
    ctx.strokeStyle = "#000"; ctx.strokeRect(v.x + sel.x * z + 0.5, v.y + sel.y * z + 0.5, sel.w * z - 1, sel.h * z - 1);
    ctx.strokeStyle = "#fff"; ctx.setLineDash([4, 4]); ctx.lineDashOffset = -(performance.now() / 60) % 8;
    ctx.strokeRect(v.x + sel.x * z + 0.5, v.y + sel.y * z + 0.5, sel.w * z - 1, sel.h * z - 1);
    ctx.setLineDash([]);
  }
  if (S.hover && !S.pan && ["pencil", "eraser", "dither", "shade"].includes(S.tool)) {
    const [hx, hy] = S.hover;
    const n = S.brush, o = Math.floor((n - 1) / 2);
    ctx.strokeStyle = "rgba(255,255,255,.8)"; ctx.lineWidth = 1;
    ctx.strokeRect(v.x + (hx - o) * z + 0.5, v.y + (hy - o) * z + 0.5, n * z - 1, n * z - 1);
  }
}
function drawMap(ctx) {
  const v = view(), z = v.zoom, tm = D.tilemap, tw = D.width * z, th = D.height * z;
  const W = tm.cols * tw, H = tm.rows * th;
  checker(ctx, v.x, v.y, W, H);
  for (const key of ["ground", "decor"]) {
    ctx.globalAlpha = key === "decor" && S.mapLayer === "ground" ? 0.55 : 1;
    tm[key].forEach((t, i) => {
      if (t < 0 || !S.tiles[t]) return;
      ctx.drawImage(S.tiles[t], v.x + (i % tm.cols) * tw, v.y + Math.floor(i / tm.cols) * th, tw, th);
    });
  }
  ctx.globalAlpha = 1;
  if (S.showSolid) {
    ctx.fillStyle = "rgba(229,72,77,.32)"; ctx.strokeStyle = "rgba(229,72,77,.9)";
    tm.solid.forEach((s, i) => {
      if (!s) return;
      const x = v.x + (i % tm.cols) * tw, y = v.y + Math.floor(i / tm.cols) * th;
      ctx.fillRect(x, y, tw, th);
      ctx.beginPath(); ctx.moveTo(x + 2, y + 2); ctx.lineTo(x + tw - 2, y + th - 2); ctx.stroke();
    });
  }
  if (S.mapGrid) {
    ctx.strokeStyle = "rgba(128,140,160,.3)"; ctx.beginPath();
    for (let c = 1; c < tm.cols; c++) { ctx.moveTo(v.x + c * tw + 0.5, v.y); ctx.lineTo(v.x + c * tw + 0.5, v.y + H); }
    for (let r = 1; r < tm.rows; r++) { ctx.moveTo(v.x, v.y + r * th + 0.5); ctx.lineTo(v.x + W, v.y + r * th + 0.5); }
    ctx.stroke();
  }
  ctx.strokeStyle = "rgba(128,140,160,.6)"; ctx.strokeRect(v.x - 0.5, v.y - 0.5, W + 1, H + 1);
  if (S.hover) {
    const [c, r] = [Math.floor(S.hover[0] / D.width), Math.floor(S.hover[1] / D.height)];
    if (c >= 0 && r >= 0 && c < tm.cols && r < tm.rows) {
      if (S.mapTool === "paint" && S.tiles[S.tile]) {
        ctx.globalAlpha = 0.6; ctx.drawImage(S.tiles[S.tile], v.x + c * tw, v.y + r * th, tw, th); ctx.globalAlpha = 1;
      }
      ctx.strokeStyle = "#2ec4d6"; ctx.lineWidth = 2; ctx.strokeRect(v.x + c * tw + 1, v.y + r * th + 1, tw - 2, th - 2); ctx.lineWidth = 1;
    }
  }
}

// ---------- outils de dessin ----------
function brushPoints(x, y) {
  const pts = [];
  const n = S.brush, o = Math.floor((n - 1) / 2);
  for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) pts.push([x - o + i, y - o + j]);
  const out = [];
  for (const [px, py] of pts) {
    out.push([px, py]);
    if (S.mirrorX) out.push([D.width - 1 - px, py]);
    if (S.mirrorY) out.push([px, D.height - 1 - py]);
    if (S.mirrorX && S.mirrorY) out.push([D.width - 1 - px, D.height - 1 - py]);
  }
  return out;
}
function linePoints(x0, y0, x1, y1) {
  const pts = [];
  const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
  let err = dx + dy;
  for (;;) {
    pts.push([x0, y0]);
    if (x0 === x1 && y0 === y1) break;
    const e2 = 2 * err;
    if (e2 >= dy) { err += dy; x0 += sx; }
    if (e2 <= dx) { err += dx; y0 += sy; }
  }
  return pts;
}
function rectPoints(x0, y0, x1, y1, filled) {
  const [a, b] = [Math.min(x0, x1), Math.max(x0, x1)], [c, d] = [Math.min(y0, y1), Math.max(y0, y1)];
  const pts = [];
  for (let y = c; y <= d; y++) for (let x = a; x <= b; x++) {
    if (filled || x === a || x === b || y === c || y === d) pts.push([x, y]);
  }
  return pts;
}
function ellipsePoints(x0, y0, x1, y1, filled) {
  const [a, b] = [Math.min(x0, x1), Math.max(x0, x1)], [c, d] = [Math.min(y0, y1), Math.max(y0, y1)];
  const cx = (a + b + 1) / 2, cy = (c + d + 1) / 2, rx = (b - a + 1) / 2, ry = (d - c + 1) / 2;
  const inside = (x, y) => x >= a && x <= b && y >= c && y <= d &&
    ((x + 0.5 - cx) / rx) ** 2 + ((y + 0.5 - cy) / ry) ** 2 <= 1.0001;
  const pts = [];
  for (let y = c; y <= d; y++) for (let x = a; x <= b; x++) {
    if (!inside(x, y)) continue;
    if (filled || !inside(x - 1, y) || !inside(x + 1, y) || !inside(x, y - 1) || !inside(x, y + 1)) pts.push([x, y]);
  }
  return pts;
}
function snap45(x0, y0, x1, y1) {
  const dx = x1 - x0, dy = y1 - y0;
  if (Math.abs(dx) > 2 * Math.abs(dy)) return [x1, y0];
  if (Math.abs(dy) > 2 * Math.abs(dx)) return [x0, y1];
  const m = Math.max(Math.abs(dx), Math.abs(dy));
  return [x0 + Math.sign(dx) * m, y0 + Math.sign(dy) * m];
}
function currentCel(create = true) {
  const cels = D.frames[S.frame].cels;
  if (!cels[S.layer] && create) cels[S.layer] = blankCel();
  return cels[S.layer];
}
function shadeOf(c, lighter) {
  // ton voisin dans la palette : plus clair (ou plus sombre) et le plus proche en couleur, pour rester dans la rampe
  const l = 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2];
  let best = null, bestDistance = Infinity;
  for (const hex of D.palette) {
    const d = luma(hex) - l;
    if (lighter ? d < 4 : d > -4) continue;
    const [r, g, b] = rgbaOf(hex);
    const distance = (r - c[0]) ** 2 + (g - c[1]) ** 2 + (b - c[2]) ** 2;
    if (distance < bestDistance) { best = hex; bestDistance = distance; }
  }
  return best ? rgbaOf(best) : c;
}
function paintAt(x, y) {
  const st = S.stroke, img = currentCel();
  for (const [px, py] of brushPoints(x, y)) {
    if (px < 0 || py < 0 || px >= D.width || py >= D.height) continue;
    const key = py * D.width + px;
    if (S.tool === "shade") {
      if (st.done.has(key)) continue;
      st.done.add(key);
      const c = getPx(img, px, py);
      if (c[3] === 0) continue;
      setPx(img, px, py, shadeOf(c, st.button === 0));
    } else if (S.tool === "eraser") {
      setPx(img, px, py, [0, 0, 0, 0]);
    } else if (S.tool === "dither") {
      const even = (px + py) % 2 === 0;
      setPx(img, px, py, rgbaOf((even === (st.button === 0)) ? S.primary : S.secondary));
    } else {
      setPx(img, px, py, st.color);
    }
  }
  touch(img);
}
function floodFill(x, y, color, global) {
  const img = currentCel();
  const target = getPx(img, x, y);
  if (same(target, color)) return;
  if (global) {
    for (let j = 0; j < D.height; j++) for (let i = 0; i < D.width; i++) if (same(getPx(img, i, j), target)) setPx(img, i, j, color);
  } else {
    const stack = [[x, y]], seen = new Uint8Array(D.width * D.height);
    while (stack.length) {
      const [px, py] = stack.pop();
      if (px < 0 || py < 0 || px >= D.width || py >= D.height) continue;
      const k = py * D.width + px;
      if (seen[k] || !same(getPx(img, px, py), target)) continue;
      seen[k] = 1;
      setPx(img, px, py, color);
      stack.push([px + 1, py], [px - 1, py], [px, py + 1], [px, py - 1]);
    }
  }
  touch(img);
}
function pickAt(x, y, button) {
  if (x < 0 || y < 0 || x >= D.width || y >= D.height) return;
  let hex = null;
  for (let l = D.layers.length - 1; l >= 0; l--) {
    const img = D.frames[S.frame].cels[l];
    if (!D.layers[l].visible || !img) continue;
    const c = getPx(img, x, y);
    if (c[3] > 0) { hex = hexOf(c[0], c[1], c[2]); break; }
  }
  if (button === 2) S.secondary = hex; else S.primary = hex;
  renderColors();
}

// ---------- sélection ----------
function selectionContains(x, y) {
  const s = S.float ? { x: S.float.x, y: S.float.y, w: S.float.img.width, h: S.float.img.height } : S.sel;
  return s && x >= s.x && y >= s.y && x < s.x + s.w && y < s.y + s.h;
}
function cutRegion(sel, clear) {
  const img = currentCel();
  const out = new ImageData(sel.w, sel.h);
  for (let j = 0; j < sel.h; j++) for (let i = 0; i < sel.w; i++) {
    const x = sel.x + i, y = sel.y + j;
    if (x < 0 || y < 0 || x >= D.width || y >= D.height) continue;
    setPx(out, i, j, getPx(img, x, y));
    if (clear) setPx(img, x, y, [0, 0, 0, 0]);
  }
  touch(img);
  return out;
}
function liftSelection() {
  if (S.float || !S.sel) return;
  undoCel(S.frame, S.layer);
  S.float = { img: cutRegion(S.sel, true), x: S.sel.x, y: S.sel.y };
}
function commitFloat() {
  if (!S.float) return;
  const img = currentCel();
  const f = S.float;
  for (let j = 0; j < f.img.height; j++) for (let i = 0; i < f.img.width; i++) {
    const c = getPx(f.img, i, j);
    if (c[3] > 0) setPx(img, f.x + i, f.y + j, c);
  }
  touch(img);
  S.sel = { x: f.x, y: f.y, w: f.img.width, h: f.img.height };
  S.float = null;
  changed();
}
function clipSel(sel) {
  const x = Math.max(0, sel.x), y = Math.max(0, sel.y);
  const w = Math.min(D.width, sel.x + sel.w) - x, h = Math.min(D.height, sel.y + sel.h) - y;
  return w > 0 && h > 0 ? { x, y, w, h } : null;
}
function copySelection(cut) {
  if (S.float) { S.clip = copyCel(S.float.img); if (cut) { S.float = null; S.sel = null; changed(); } return; }
  if (!S.sel) { toast("Sélectionne d'abord une zone (outil ⬚, M)"); return; }
  if (cut) undoCel(S.frame, S.layer);
  S.clip = cutRegion(S.sel, cut);
  if (cut) changed();
  toast(cut ? "Zone coupée" : "Zone copiée");
}
function pasteClip(img = S.clip, at = null) {
  if (!img) { toast("Presse-papiers vide"); return; }
  commitFloat();
  undoCel(S.frame, S.layer);
  currentCel();
  const pos = at || (S.sel ? { x: S.sel.x, y: S.sel.y } : { x: 0, y: 0 });
  S.float = { img: copyCel(img), x: pos.x, y: pos.y };
  setTool("select");
  render();
}
function flipSelection(vertical) {
  liftSelection();
  if (!S.float) { toast("Sélectionne d'abord une zone (outil ⬚, M)"); return; }
  const src = S.float.img, out = new ImageData(src.width, src.height);
  for (let j = 0; j < src.height; j++) for (let i = 0; i < src.width; i++) {
    setPx(out, vertical ? i : src.width - 1 - i, vertical ? src.height - 1 - j : j, getPx(src, i, j));
  }
  S.float.img = out;
  render();
}
function deleteSelection() {
  if (S.float) { S.float = null; S.sel = null; changed(); return; }
  if (!S.sel) return;
  undoCel(S.frame, S.layer);
  cutRegion(S.sel, true);
  changed();
}

// ---------- pointeur ----------
function setTool(tool) {
  if (tool !== "select") commitFloat();
  S.tool = tool;
  document.querySelectorAll("[data-tool]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tool === tool)));
  const hints = {
    pencil: "Crayon : clic gauche couleur principale, clic droit secondaire", eraser: "Gomme",
    fill: "Pot : Maj pour remplacer la couleur partout dans le calque", picker: "Pipette : gauche → principale, droit → secondaire",
    line: "Ligne : Maj pour 45°", rect: "Rectangle : Maj pour plein", ellipse: "Ellipse : Maj pour pleine",
    select: "Sélection : glisser pour déplacer · Ctrl+C/X/V · H retourner · Suppr effacer · Échap valider",
    dither: "Tramage : damier des deux couleurs", shade: "Ombrage : gauche éclaircit, droit assombrit (suivant la palette)",
  };
  $("st-hint").textContent = hints[tool] || "";
  render();
}
function setMapTool(tool) {
  S.mapTool = tool;
  document.querySelectorAll("[data-maptool]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.maptool === tool)));
  const hints = { paint: "Poser la tuile choisie · clic droit efface", erase: "Effacer la case", fill: "Remplir la zone de même tuile",
                  pick: "Prendre la tuile d'une case", solid: "Case bloquante : gauche pose, droit enlève" };
  $("st-hint").textContent = hints[tool] || "";
}
canvas.addEventListener("contextmenu", (e) => e.preventDefault());
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  const r = canvas.getBoundingClientRect();
  if (e.ctrlKey || !e.shiftKey) zoomStep(e.deltaY < 0 ? 1 : -1, e.clientX - r.left, e.clientY - r.top);
  else { view().x -= e.deltaY; render(); }
}, { passive: false });
canvas.addEventListener("pointerdown", (e) => {
  if (!D) return;
  canvas.setPointerCapture(e.pointerId);
  if (e.button === 1 || S.space) {
    S.pan = { x: e.clientX, y: e.clientY, vx: view().x, vy: view().y };
    $("stage").classList.add("panning");
    return;
  }
  if (S.playing) togglePlay(false);
  const [x, y] = toPixel(e);
  if (S.mode === "map") { mapDown(e, x, y); return; }
  const tool = e.altKey ? "picker" : S.tool;
  if (tool === "picker") { pickAt(x, y, e.button); S.stroke = { tool, button: e.button }; return; }
  if (!D.layers[S.layer].visible) { toast("Calque masqué : rends-le visible pour dessiner", true); return; }
  if (tool === "select") {
    if (selectionContains(x, y)) {
      liftSelection();
      S.stroke = { tool, move: true, sx: x, sy: y, fx: S.float.x, fy: S.float.y };
    } else {
      commitFloat();
      S.sel = null;
      S.stroke = { tool, sx: x, sy: y };
    }
    render();
    return;
  }
  commitFloat();
  const color = rgbaOf(e.button === 2 ? S.secondary : S.primary);
  undoCel(S.frame, S.layer);
  S.stroke = { tool, button: e.button, color, sx: x, sy: y, lx: x, ly: y, done: new Set(), shift: e.shiftKey };
  if (tool === "fill") {
    if (x >= 0 && y >= 0 && x < D.width && y < D.height) floodFill(x, y, color, e.shiftKey);
    S.stroke = null;
    changed();
  } else if (["pencil", "eraser", "dither", "shade"].includes(tool)) {
    paintAt(x, y);
    render();
  } else {
    shapePreview(x, y, e.shiftKey);
  }
});
function shapePreview(x, y, shift) {
  const st = S.stroke;
  let pts;
  if (st.tool === "line") {
    const [ex, ey] = shift ? snap45(st.sx, st.sy, x, y) : [x, y];
    pts = linePoints(st.sx, st.sy, ex, ey);
  } else if (st.tool === "rect") pts = rectPoints(st.sx, st.sy, x, y, shift);
  else pts = ellipsePoints(st.sx, st.sy, x, y, shift);
  const out = [];
  for (const [px, py] of pts) {
    out.push([px, py, st.color]);
    if (S.mirrorX) out.push([D.width - 1 - px, py, st.color]);
    if (S.mirrorY) out.push([px, D.height - 1 - py, st.color]);
    if (S.mirrorX && S.mirrorY) out.push([D.width - 1 - px, D.height - 1 - py, st.color]);
  }
  st.preview = out;
  st.ex = x; st.ey = y; st.shift = shift;
  render();
}
canvas.addEventListener("pointermove", (e) => {
  if (!D) return;
  if (S.pan) {
    view().x = S.pan.vx + e.clientX - S.pan.x; view().y = S.pan.vy + e.clientY - S.pan.y; view().manual = true;
    render(); return;
  }
  const [x, y] = toPixel(e);
  S.hover = [x, y];
  const inside = S.mode === "map"
    ? D.tilemap && x >= 0 && y >= 0 && x < D.tilemap.cols * D.width && y < D.tilemap.rows * D.height
    : x >= 0 && y >= 0 && x < D.width && y < D.height;
  $("st-pos").textContent = !inside ? "—"
    : S.mode === "map" ? `case ${Math.floor(x / D.width)}, ${Math.floor(y / D.height)}` : `x ${x}  y ${y}`;
  const st = S.stroke;
  if (S.mode === "map") { if (st) mapMove(x, y); else render(); return; }
  if (!st) { render(); return; }
  if (st.tool === "picker") { pickAt(x, y, st.button); return; }
  if (st.tool === "select") {
    if (st.move) { S.float.x = st.fx + x - st.sx; S.float.y = st.fy + y - st.sy; }
    else {
      const a = Math.min(st.sx, x), b = Math.min(st.sy, y);
      S.sel = clipSel({ x: a, y: b, w: Math.abs(x - st.sx) + 1, h: Math.abs(y - st.sy) + 1 });
    }
    render(); return;
  }
  if (["pencil", "eraser", "dither", "shade"].includes(st.tool)) {
    for (const [px, py] of linePoints(st.lx, st.ly, x, y)) paintAt(px, py);
    st.lx = x; st.ly = y;
    render(); return;
  }
  if (["line", "rect", "ellipse"].includes(st.tool)) shapePreview(x, y, e.shiftKey);
});
function endStroke() {
  if (S.pan) { S.pan = null; $("stage").classList.remove("panning"); return; }
  const st = S.stroke;
  S.stroke = null;
  if (!st) return;
  if (S.mode === "map") { if (st.changed) changed(); return; }
  if (st.tool === "picker" || st.tool === "select") { render(); return; }
  if (st.preview) {
    const img = currentCel();
    for (const [x, y, c] of st.preview) setPx(img, x, y, c);
    touch(img);
  }
  changed();
}
canvas.addEventListener("pointerup", endStroke);
canvas.addEventListener("pointercancel", endStroke);
canvas.addEventListener("pointerleave", () => { S.hover = null; render(); });

// ---------- carte ----------
function ensureMap() {
  if (D.tilemap) return;
  undoDoc();
  const n = 16 * 12;
  D.tilemap = { cols: 16, rows: 12, ground: Array(n).fill(-1), decor: Array(n).fill(-1), solid: Array(n).fill(0) };
}
function cellOf(x, y) {
  const tm = D.tilemap, c = Math.floor(x / D.width), r = Math.floor(y / D.height);
  return c >= 0 && r >= 0 && c < tm.cols && r < tm.rows ? r * tm.cols + c : -1;
}
function mapApply(i, button) {
  const tm = D.tilemap, key = S.mapLayer;
  if (i < 0) return false;
  if (S.mapTool === "solid") { const v = button === 2 ? 0 : 1; if (tm.solid[i] === v) return false; tm.solid[i] = v; return true; }
  const value = S.mapTool === "erase" || button === 2 ? -1 : S.tile;
  if (tm[key][i] === value) return false;
  tm[key][i] = value;
  return true;
}
function mapDown(e, x, y) {
  const i = cellOf(x, y);
  if (i < 0) return;
  const tm = D.tilemap;
  if (S.mapTool === "pick") {
    const t = tm.decor[i] >= 0 && S.mapLayer === "decor" ? tm.decor[i] : tm[S.mapLayer][i] >= 0 ? tm[S.mapLayer][i] : tm.ground[i];
    if (t >= 0) { S.tile = t; renderTiles(); setMapTool("paint"); }
    return;
  }
  undoMap();
  if (S.mapTool === "fill") {
    const key = S.mapLayer, target = tm[key][i], value = e.button === 2 ? -1 : S.tile;
    if (target !== value) {
      const stack = [i], seen = new Set();
      while (stack.length) {
        const k = stack.pop();
        if (seen.has(k) || tm[key][k] !== target) continue;
        seen.add(k); tm[key][k] = value;
        const c = k % tm.cols, r = Math.floor(k / tm.cols);
        if (c > 0) stack.push(k - 1); if (c < tm.cols - 1) stack.push(k + 1);
        if (r > 0) stack.push(k - tm.cols); if (r < tm.rows - 1) stack.push(k + tm.cols);
      }
      changed();
    }
    return;
  }
  S.stroke = { map: true, button: e.button, changed: mapApply(i, e.button), c: i % tm.cols, r: Math.floor(i / tm.cols) };
  render();
}
function mapMove(x, y) {
  const st = S.stroke;
  if (!st.map) return;
  const c = Math.floor(x / D.width), r = Math.floor(y / D.height);
  for (const [cc, rr] of linePoints(st.c, st.r, c, r)) {  // glissé rapide : aucune case sautée
    if (cc >= 0 && rr >= 0 && cc < D.tilemap.cols && rr < D.tilemap.rows && mapApply(rr * D.tilemap.cols + cc, st.button)) st.changed = true;
  }
  st.c = c; st.r = r;
  render();
}
function buildTiles() { S.tiles = D.frames.map((_, f) => composeFrame(f)); }
function renderTiles() {
  const box = $("tiles");
  box.replaceChildren();
  S.tile = Math.min(S.tile, D.frames.length - 1);
  S.tiles.forEach((cv, t) => {
    const thumb = canvasOf(D.width, D.height);
    ctxOf(thumb).drawImage(cv, 0, 0);
    const b = el("button", { type: "button", class: t === S.tile ? "sel" : "", title: `Tuile ${t + 1} (image ${t + 1})` },
      thumb, el("span", {}, t + 1));
    b.addEventListener("click", () => { S.tile = t; renderTiles(); if (S.mapTool === "pick" || S.mapTool === "erase") setMapTool("paint"); });
    box.append(b);
  });
  $("map-cols").value = D.tilemap.cols; $("map-rows").value = D.tilemap.rows;
  document.querySelectorAll("#map-layer button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.layer === S.mapLayer)));
}
function resizeMap(cols, rows) {
  const tm = D.tilemap;
  cols = Math.max(1, Math.min(128, cols | 0)); rows = Math.max(1, Math.min(128, rows | 0));
  if (cols === tm.cols && rows === tm.rows) return;
  undoMap();
  const grid = (arr, fill) => {
    const out = Array(cols * rows).fill(fill);
    for (let r = 0; r < Math.min(rows, tm.rows); r++) for (let c = 0; c < Math.min(cols, tm.cols); c++) out[r * cols + c] = arr[r * tm.cols + c];
    return out;
  };
  D.tilemap = { cols, rows, ground: grid(tm.ground, -1), decor: grid(tm.decor, -1), solid: grid(tm.solid, 0) };
  changed(true);
  fit();
}
function setMode(mode) {
  commitFloat();
  if (S.playing) togglePlay(false);
  S.mode = mode;
  if (mode === "map") { ensureMap(); buildTiles(); renderTiles(); setMapTool(S.mapTool); }
  else setTool(S.tool);
  $("studio").classList.toggle("map-mode", mode === "map");
  $("sprite-tools").hidden = mode === "map"; $("map-tools").hidden = mode !== "map";
  $("tiles-panel").hidden = mode !== "map"; $("layers-panel").hidden = mode === "map";
  document.querySelectorAll("#modes button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.mode === mode)));
  if (!view().fitted) fit(); else render();
  renderStatus();
}

// ---------- panneaux ----------
function swatchStyle(node, hex) {
  node.classList.toggle("transparent", !hex);
  node.style.backgroundColor = hex || "";
}
function renderColors() {
  swatchStyle($("chip-primary"), S.primary); swatchStyle($("chip-secondary"), S.secondary);
  $("hex-primary").textContent = S.primary || "transparent";
  const box = $("swatches");
  box.replaceChildren();
  const tr = el("button", { type: "button", class: "swatch transparent", title: "Transparent" });
  tr.addEventListener("click", () => { S.primary = null; renderColors(); });
  tr.addEventListener("contextmenu", (e) => { e.preventDefault(); S.secondary = null; renderColors(); });
  box.append(tr);
  D.palette.forEach((hex, i) => {
    const cls = ["swatch", i === S.palSel ? "sel" : "", hex === S.primary ? "prim" : "", hex === S.secondary ? "sec" : ""];
    const b = el("button", { type: "button", class: cls.join(" ").trim(), title: `${hex} — indice ${i}` });
    swatchStyle(b, hex);
    b.addEventListener("click", () => { S.primary = hex; S.palSel = i; renderColors(); });
    b.addEventListener("contextmenu", (e) => { e.preventDefault(); S.secondary = hex; S.palSel = i; renderColors(); });
    b.addEventListener("dblclick", () => editColor({ kind: "swatch", index: i }, hex));
    box.append(b);
  });
}
function editColor(target, hex) {
  S.colorTarget = target;
  const input = $("color-input");
  input.value = hex || "#000000";
  input.click();
}
$("color-input").addEventListener("change", () => {
  const hex = $("color-input").value.toLowerCase(), t = S.colorTarget;
  if (!t) return;
  if (t.kind === "primary") S.primary = hex;
  else if (t.kind === "secondary") S.secondary = hex;
  else {
    const old = D.palette[t.index];
    if (old === hex) return;
    undoDoc();
    D.palette[t.index] = hex;
    const from = rgbaOf(old), to = rgbaOf(hex);
    let count = 0;
    for (const frame of D.frames) for (const img of frame.cels) {
      if (!img) continue;
      for (let i = 0; i < img.data.length; i += 4) {
        if (img.data[i + 3] && img.data[i] === from[0] && img.data[i + 1] === from[1] && img.data[i + 2] === from[2]) {
          img.data[i] = to[0]; img.data[i + 1] = to[1]; img.data[i + 2] = to[2]; count++;
        }
      }
      touch(img);
    }
    if (S.primary === old) S.primary = hex;
    if (S.secondary === old) S.secondary = hex;
    if (count) toast(`${count} pixel(s) recoloré(s)`);
    changed(true);
  }
  renderColors();
});
function renderLayers() {
  const list = $("layers");
  list.replaceChildren();
  for (let l = D.layers.length - 1; l >= 0; l--) {
    const layer = D.layers[l];
    const thumb = canvasOf(D.width, D.height);
    const img = D.frames[S.frame].cels[l];
    if (img) ctxOf(thumb).drawImage(celCanvas(img), 0, 0);
    const eye = el("button", { type: "button", class: layer.visible ? "eye" : "eye off", title: "Afficher ou masquer" }, "👁");
    eye.addEventListener("click", (e) => { e.stopPropagation(); undoDoc(); layer.visible = !layer.visible; changed(true); });
    const name = el("span", { class: "lname", title: "Double-clic pour renommer" }, layer.name);
    const li = el("li", { class: l === S.layer ? "cur" : "" }, eye, thumb, name);
    li.addEventListener("click", () => { commitFloat(); S.layer = l; renderLayers(); renderStatus(); });
    name.addEventListener("dblclick", () => {
      const input = el("input", { value: layer.name, maxlength: "40", "aria-label": "Nom du calque" });
      name.replaceWith(input); input.focus(); input.select();
      const done = () => { const v = input.value.trim(); if (v && v !== layer.name) { undoDoc(); layer.name = v; changed(true); } else renderLayers(); };
      input.addEventListener("keydown", (ev) => { ev.stopPropagation(); if (ev.key === "Enter") input.blur(); if (ev.key === "Escape") { input.value = layer.name; input.blur(); } });
      input.addEventListener("blur", done, { once: true });
    });
    list.append(li);
  }
  const op = Math.round(D.layers[S.layer].opacity * 100);
  $("layer-opacity").value = op; $("opacity-label").textContent = `${op} %`;
}
function renderFrames() {
  const box = $("frames");
  box.replaceChildren();
  D.frames.forEach((frame, f) => {
    const b = el("button", { type: "button", class: f === S.frame ? "cur" : "", title: `Image ${f + 1} — ${frame.duration} ms` },
      composeFrame(f), el("span", {}, `${f + 1} · ${frame.duration}`));
    b.addEventListener("click", () => goFrame(f));
    box.append(b);
  });
  $("frame-duration").value = D.frames[S.frame].duration;
  box.children[S.frame]?.scrollIntoView({ block: "nearest", inline: "nearest" });
}
function renderStatus() {
  $("st-size").textContent = `${D.width}×${D.height} px`;
  $("st-frame").textContent = S.mode === "map" && D.tilemap
    ? `carte ${D.tilemap.cols}×${D.tilemap.rows} · ${D.frames.length} tuile(s)`
    : `image ${S.frame + 1}/${D.frames.length} · calque ${S.layer + 1}/${D.layers.length} « ${D.layers[S.layer].name} »`;
  if (document.activeElement !== $("doc-name")) $("doc-name").value = D.name;
  document.title = `${D.name} — Studio pixel Æther`;
}
function renderAll() { renderColors(); renderLayers(); renderFrames(); renderStatus(); if (S.mode === "map") { buildTiles(); renderTiles(); } render(); }
function goFrame(f) {
  commitFloat();
  S.frame = (f + D.frames.length) % D.frames.length;
  renderFrames(); renderLayers(); renderStatus(); render();
}

// aperçu animé
function tickPreview() {
  clearTimeout(S.previewTimer);
  if (!D) return;
  const cv = $("preview"), s = S.previewScale;
  if (cv.width !== D.width * s || cv.height !== D.height * s) { cv.width = D.width * s; cv.height = D.height * s; }
  const ctx = cv.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  ctx.clearRect(0, 0, cv.width, cv.height);
  const bg = ["", "#0f1216", "#ffffff"][S.previewBg];
  if (bg) { ctx.fillStyle = bg; ctx.fillRect(0, 0, cv.width, cv.height); } else checker(ctx, 0, 0, cv.width, cv.height);
  S.previewFrame %= D.frames.length;
  ctx.drawImage(composeFrame(S.previewFrame), 0, 0, cv.width, cv.height);
  $("preview-info").textContent = D.frames.length > 1 ? `image ${S.previewFrame + 1}/${D.frames.length}` : "";
  const delay = D.frames[S.previewFrame].duration;
  S.previewFrame = (S.previewFrame + 1) % D.frames.length;
  S.previewTimer = setTimeout(tickPreview, Math.max(30, delay));
}

// ---------- modifications et enregistrement ----------
function changed(structure = false) {
  S.dirty = true;
  $("saved").textContent = "modifié";
  if (structure) { renderLayers(); renderFrames(); renderColors(); }
  else { renderLayers(); updateFrameThumb(S.frame); }
  if (S.mode === "map") { buildTiles(); renderTiles(); }
  renderStatus();
  render();
  clearTimeout(S.saveTimer);
  if (S.savedOnce) S.saveTimer = setTimeout(() => save(false), 1500);
}
function updateFrameThumb(f) {
  const b = $("frames").children[f];
  if (!b) { renderFrames(); return; }
  composeFrame(f, b.querySelector("canvas"));
}
async function save(explicit = true) {
  clearTimeout(S.saveTimer);
  const name = cleanName(D.name);
  if (!name) { toast("Donne un nom au projet (en haut à gauche)", true); $("doc-name").focus(); return false; }
  D.name = name;
  try {
    if (explicit && name !== S.loadedAs) {
      const list = await call("projects", {});
      if (list.some((p) => p.name === name) && !confirm(`Un projet « ${name} » existe déjà. Le remplacer ?`)) return false;
    }
    const result = await call("project_save", { project: docToServer() });
    S.dirty = false; S.savedOnce = true; S.loadedAs = result.name;
    local.set("last", result.name);
    $("saved").textContent = `enregistré ${new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}`;
    renderStatus();
    if (explicit) toast(`Projet « ${result.name} » enregistré`);
    return true;
  } catch (e) { fail(e); $("saved").textContent = "non enregistré"; return false; }
}
async function openProject(name) {
  try {
    if (S.dirty && S.savedOnce) await save(false);
    const doc = await call("project_load", { name });
    setDoc(await docFromServer(doc), true);
    toast(`Projet « ${doc.name} » ouvert`);
  } catch (e) { fail(e); }
}
function setDoc(doc, saved) {
  if (S.playing) togglePlay(false);
  D = doc;
  S.frame = 0; S.layer = 0; S.sel = null; S.float = null; S.undo = []; S.redo = []; S.palSel = -1;
  S.dirty = false; S.savedOnce = saved; S.loadedAs = saved ? doc.name : "";
  S.view.sprite.fitted = false; S.view.map.fitted = false;
  if (!D.palette.includes(S.primary)) S.primary = D.palette[0] || "#000000";
  if (S.secondary && !D.palette.includes(S.secondary)) S.secondary = null;
  $("saved").textContent = saved ? "enregistré" : "pas encore enregistré";
  if (saved) local.set("last", doc.name);
  setMode(S.mode === "map" && !doc.tilemap ? "sprite" : S.mode);
  renderAll();
  fit();
  S.previewFrame = 0; tickPreview();
}

// ---------- calques ----------
function layerAction(action) {
  commitFloat();
  const l = S.layer;
  if (action === "add" || action === "dup") {
    if (D.layers.length >= 32) { toast("32 calques au plus", true); return; }
    undoDoc();
    const src = D.layers[l];
    D.layers.splice(l + 1, 0, action === "dup" ? { ...src, name: `${src.name} (copie)`.slice(0, 40) }
      : { name: `Calque ${D.layers.length + 1}`, visible: true, opacity: 1 });
    for (const f of D.frames) f.cels.splice(l + 1, 0, action === "dup" ? copyCel(f.cels[l]) : null);
    S.layer = l + 1;
  } else if (action === "del") {
    if (D.layers.length === 1) { toast("Un calque au moins", true); return; }
    undoDoc();
    D.layers.splice(l, 1);
    for (const f of D.frames) f.cels.splice(l, 1);
    S.layer = Math.max(0, l - 1);
  } else if (action === "up" || action === "down") {
    const k = action === "up" ? l + 1 : l - 1;
    if (k < 0 || k >= D.layers.length) return;
    undoDoc();
    [D.layers[l], D.layers[k]] = [D.layers[k], D.layers[l]];
    for (const f of D.frames) [f.cels[l], f.cels[k]] = [f.cels[k], f.cels[l]];
    S.layer = k;
  } else if (action === "merge") {
    if (l === 0) { toast("Pas de calque en dessous", true); return; }
    undoDoc();
    for (const f of D.frames) {
      const top = f.cels[l];
      if (!top) continue;
      const cv = canvasOf(D.width, D.height), ctx = ctxOf(cv);
      if (f.cels[l - 1]) ctx.drawImage(celCanvas(f.cels[l - 1]), 0, 0);
      ctx.globalAlpha = D.layers[l].opacity;
      if (D.layers[l].visible) ctx.drawImage(celCanvas(top), 0, 0);
      f.cels[l - 1] = ctx.getImageData(0, 0, D.width, D.height);
    }
    D.layers.splice(l, 1);
    for (const f of D.frames) f.cels.splice(l, 1);
    S.layer = l - 1;
  }
  changed(true);
}

// ---------- images ----------
function frameAction(action) {
  commitFloat();
  const f = S.frame;
  if (action === "add" || action === "dup") {
    if (D.frames.length >= 256) { toast("256 images au plus", true); return; }
    undoDoc();
    const src = D.frames[f];
    D.frames.splice(f + 1, 0, action === "dup" ? { duration: src.duration, cels: src.cels.map(copyCel) }
      : { duration: src.duration, cels: D.layers.map(() => null) });
    S.frame = f + 1;
  } else if (action === "del") {
    if (D.frames.length === 1) { toast("Une image au moins", true); return; }
    undoDoc();
    D.frames.splice(f, 1);
    if (D.tilemap) for (const key of ["ground", "decor"]) D.tilemap[key] = D.tilemap[key].map((t) => (t === f ? -1 : t > f ? t - 1 : t));
    S.frame = Math.max(0, f - 1);
  } else if (action === "left" || action === "right") {
    const k = action === "left" ? f - 1 : f + 1;
    if (k < 0 || k >= D.frames.length) return;
    undoDoc();
    [D.frames[f], D.frames[k]] = [D.frames[k], D.frames[f]];
    if (D.tilemap) for (const key of ["ground", "decor"]) D.tilemap[key] = D.tilemap[key].map((t) => (t === f ? k : t === k ? f : t));
    S.frame = k;
  }
  changed(true);
}
function togglePlay(on = !S.playing) {
  S.playing = on;
  $("play").textContent = on ? "⏸" : "▶";
  clearTimeout(S.playTimer);
  if (!on) return;
  commitFloat();
  const step = () => {
    if (!S.playing) return;
    S.frame = (S.frame + 1) % D.frames.length;
    renderFrames(); renderStatus(); render();
    S.playTimer = setTimeout(step, D.frames[S.frame].duration);
  };
  S.playTimer = setTimeout(step, D.frames[S.frame].duration);
}

// ---------- palettes ----------
async function loadPalettes() {
  try {
    S.palettes = await call("palettes", {});
    const select = $("palette-select");
    select.replaceChildren(...S.palettes.map((p) => el("option", { value: p.id }, `${p.label} (${p.colors.length})`)));
    select.value = "aether32";
  } catch (e) { fail(e); }
}
async function addRamp() {
  if (!S.primary) { toast("Choisis d'abord une couleur principale", true); return; }
  try {
    const colors = await call("palette_ramp", { base: S.primary, count: 5 });
    undoDoc();
    for (const c of colors) if (!D.palette.includes(c) && D.palette.length < 256) D.palette.push(c);
    changed(true);
    toast(`Rampe de ${colors.length} tons ajoutée`);
  } catch (e) { fail(e); }
}
function fileToB64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(new Error("fichier illisible"));
    reader.readAsDataURL(file);
  });
}

// ---------- import ----------
async function importImage(file) {
  try {
    const bitmap = await createImageBitmap(file, { premultiplyAlpha: "none", colorSpaceConversion: "none" });
    const w = Math.min(512, bitmap.width), h = Math.min(512, bitmap.height);
    const cv = canvasOf(w, h), ctx = ctxOf(cv);
    ctx.drawImage(bitmap, 0, 0);
    const img = ctx.getImageData(0, 0, w, h);
    const empty = D.frames.length === 1 && D.layers.length === 1 && isEmpty(D.frames[0].cels[0]);
    if (empty && (w !== D.width || h !== D.height)) {
      undoDoc();
      D.width = w; D.height = h; D.frames[0].cels = [img];
      S.view.sprite.fitted = false;
      changed(true); fit();
      toast(`Image importée : la toile passe à ${w}×${h}`);
      return;
    }
    if (S.mode === "map") setMode("sprite");
    pasteClip(img, { x: 0, y: 0 });
    toast("Image collée en sélection flottante : glisse-la, puis Échap pour la poser");
  } catch (e) { fail(new Error(`image illisible (${e.message})`)); }
}

// ---------- dialogues ----------
function dialog(title, ...content) {
  closeDialog();
  const close = el("button", { type: "button", title: "Fermer (Échap)" }, "✕");
  const overlay = el("div", { class: "overlay", id: "overlay" },
    el("div", { class: "dialog", role: "dialog", "aria-label": title },
      el("header", {}, el("span", {}, title), el("span", { class: "grow" }), close), el("div", { class: "body" }, ...content)));
  close.addEventListener("click", closeDialog);
  overlay.addEventListener("pointerdown", (e) => { if (e.target === overlay) closeDialog(); });
  document.body.append(overlay);
  return overlay;
}
function closeDialog() { document.querySelectorAll(".overlay").forEach((o) => o.remove()); }
const field = (label, input) => el("label", { class: "field" }, el("span", {}, label), input);

function newDialog() {
  const name = el("input", { value: "sprite", maxlength: "40", spellcheck: "false" });
  const width = el("input", { type: "number", min: "1", max: "512", value: String(D ? D.width : 32) });
  const height = el("input", { type: "number", min: "1", max: "512", value: String(D ? D.height : 32) });
  const frames = el("input", { type: "number", min: "1", max: "64", value: "1" });
  const pal = el("select", {}, ...S.palettes.map((p) => el("option", { value: p.id }, p.label)),
    el("option", { value: "_current" }, "Palette du projet ouvert"));
  pal.value = "aether32";
  const presets = el("div", { class: "presets" }, ...[8, 16, 24, 32, 48, 64, 128].map((n) => {
    const b = el("button", { type: "button", class: "small" }, `${n}×${n}`);
    b.addEventListener("click", () => { width.value = n; height.value = n; });
    return b;
  }));
  const ok = el("button", { type: "button", class: "primary" }, "Créer");
  const cancel = el("button", { type: "button" }, "Annuler");
  dialog("Nouveau projet",
    el("p", {}, "Sprite, tuile ou personnage : la carte (onglet Carte) utilise les images du projet comme tuiles."),
    field("Nom", name), field("Largeur (px)", width), field("Hauteur (px)", height), presets,
    field("Images", frames), field("Palette", pal), el("div", { class: "actions" }, cancel, ok));
  name.focus(); name.select();
  cancel.addEventListener("click", closeDialog);
  ok.addEventListener("click", async () => {
    const n = cleanName(name.value);
    const w = Math.round(+width.value), h = Math.round(+height.value), k = Math.round(+frames.value);
    if (!n) { toast("Nom invalide (lettres, chiffres, « _ », « - »)", true); return; }
    if (!(w >= 1 && w <= 512 && h >= 1 && h <= 512)) { toast("Taille de 1 à 512 pixels", true); return; }
    if (S.dirty && S.savedOnce) await save(false);
    const colors = pal.value === "_current" && D ? D.palette : (S.palettes.find((p) => p.id === pal.value)?.colors || ["#000000", "#ffffff"]);
    closeDialog();
    setDoc(newDoc(n, w, h, colors, Math.max(1, Math.min(64, k || 1))), false);
    S.primary = colors[0];
    renderColors();
    save(true);
  });
}
async function projectsDialog() {
  const grid = el("div", { class: "projects" }, el("p", {}, "Chargement…"));
  dialog("Projets", el("p", {}, "Enregistrés dans data/pixel_studio/projects. Les sprites créés par les agents (MCP) apparaissent ici."), grid);
  try {
    const list = await call("projects", {});
    grid.replaceChildren();
    if (!list.length) grid.append(el("p", {}, "Aucun projet pour l'instant : « Nouveau » puis « Enregistrer »."));
    for (const p of list) {
      const thumb = el("div", { class: "thumb" });
      if (p.thumb) { const img = el("img", { alt: "" }); img.src = blobUrl(p.thumb); thumb.append(img); }
      else thumb.append(el("small", {}, `${p.width}×${p.height}`));
      const del = el("button", { type: "button", class: "del", title: "Supprimer le projet" }, "Supprimer");
      const card = el("div", { class: "card", role: "button", tabindex: "0", title: `Ouvrir ${p.name}` }, thumb, el("b", {}, p.name),
        el("small", {}, `${p.width}×${p.height} · ${p.frames} image(s) · ${p.layers} calque(s)${p.map ? " · carte" : ""}`), del);
      card.addEventListener("click", () => { closeDialog(); openProject(p.name); });
      card.addEventListener("keydown", (e) => { if (e.key === "Enter") { closeDialog(); openProject(p.name); } });
      del.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm(`Supprimer définitivement le projet « ${p.name} » ?`)) return;
        try { await call("project_delete", { name: p.name }); card.remove(); if (S.loadedAs === p.name) { S.savedOnce = false; S.loadedAs = ""; } }
        catch (err) { fail(err); }
      });
      grid.append(card);
    }
  } catch (e) { grid.replaceChildren(el("p", {}, e.message)); }
}
function download(b64, filename, mime) {
  const url = blobUrl(b64, mime);
  const a = el("a", { href: url, download: filename });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
function exportDialog() {
  commitFloat();
  const kinds = [
    ["png", "PNG", "l'image courante"], ["sheet", "Planche", "toutes les images + JSON"],
    ["gif", "GIF animé", "en boucle, durées gardées"], ["map", "Carte", "image de la carte + JSON"],
  ];
  let kind = S.mode === "map" ? "map" : D.frames.length > 1 ? "gif" : "png";
  const buttons = kinds.map(([id, label, info]) => {
    const b = el("button", { type: "button", "aria-pressed": String(id === kind), disabled: id === "map" && !D.tilemap },
      el("b", {}, label), el("small", {}, id === "map" && !D.tilemap ? "pas de carte dans ce projet" : info));
    b.addEventListener("click", () => { kind = id; buttons.forEach((x, i) => x.setAttribute("aria-pressed", String(kinds[i][0] === id))); cols.parentElement.hidden = id !== "sheet"; });
    return b;
  });
  const scale = el("select", {}, ...[1, 2, 3, 4, 6, 8, 10, 12, 16].map((n) => el("option", { value: String(n) }, `×${n}`)));
  scale.value = String(local.get("exportScale", 4));
  const cols = el("input", { type: "number", min: "0", max: "256", value: "0", title: "0 = une seule ligne" });
  const colsField = field("Colonnes", cols);
  colsField.hidden = kind !== "sheet";
  const ok = el("button", { type: "button", class: "primary" }, "Exporter");
  const folder = el("button", { type: "button" }, "Ouvrir le dossier");
  const info = el("p", {}, "Le fichier est téléchargé et gardé dans data/pixel_studio/exports.");
  dialog("Exporter", el("div", { class: "kinds" }, ...buttons), field("Agrandissement", scale), colsField, info,
    el("div", { class: "actions" }, folder, ok));
  folder.addEventListener("click", () => call("exports_open", {}).catch(fail));
  ok.addEventListener("click", async () => {
    local.set("exportScale", +scale.value);
    ok.disabled = true;
    try {
      const r = await call("export", { project: docToServer(), kind, scale: +scale.value, frame: S.frame, columns: +cols.value || 0 });
      download(r.data, r.filename, r.mime);
      if (r.meta) download(btoa(unescape(encodeURIComponent(JSON.stringify(r.meta, null, 1)))), r.meta_filename, "application/json");
      info.textContent = `${r.filename} (${(r.bytes / 1024).toFixed(1)} Ko) exporté${r.meta ? ` avec ${r.meta_filename}` : ""}.`;
    } catch (e) { fail(e); } finally { ok.disabled = false; }
  });
}
async function gameDialog() {
  if (!(await save(!S.savedOnce))) return;
  try {
    const r = await call("game_export", { name: D.name });
    const code = [
      "import jeu", "jeu.fenetre(480, 360, \"Démo\")", "x, n = 200, 0",
      "while jeu.image(30):",
      "    if jeu.touche(\"gauche\"): x -= 3",
      "    if jeu.touche(\"droite\"): x += 3",
      "    jeu.effacer(\"noir\")",
      ...(r.map ? [`    jeu.carte("${r.name}", 0, 0, echelle=2)`] : []),
      `    jeu.sprite("${r.name}", x, 160, echelle=3, image=(n // 4) % ${r.frames})`,
      "    n += 1",
    ].join("\n");
    dialog("Prêt pour les jeux de la calculatrice",
      el("p", {}, `Sprite « ${r.name} » (${r.frames} image(s)${r.map ? ", avec sa carte" : ""}) écrit dans data/pixel_studio/sprites.`),
      el("p", {}, "Dans Æther CAS → Programmes → mode jeu, par exemple :"), el("pre", {}, code),
      el("p", {}, "jeu.bloque(nom, px, py, x, y, echelle) dit si le point (px, py) tombe sur une case bloquante de la carte dessinée en (x, y)."));
  } catch (e) { fail(e); }
}
function resizeDialog() {
  const width = el("input", { type: "number", min: "1", max: "512", value: String(D.width) });
  const height = el("input", { type: "number", min: "1", max: "512", value: String(D.height) });
  const anchor = el("select", {}, el("option", { value: "tl" }, "en haut à gauche"), el("option", { value: "c" }, "au centre"));
  const ok = el("button", { type: "button", class: "primary" }, "Appliquer");
  dialog("Taille de la toile", el("p", {}, "Agrandir ajoute du transparent ; réduire coupe les bords (annulable)."),
    field("Largeur", width), field("Hauteur", height), field("Contenu", anchor), el("div", { class: "actions" }, ok));
  ok.addEventListener("click", () => {
    const w = Math.round(+width.value), h = Math.round(+height.value);
    if (!(w >= 1 && w <= 512 && h >= 1 && h <= 512)) { toast("Taille de 1 à 512 pixels", true); return; }
    commitFloat(); undoDoc();
    const dx = anchor.value === "c" ? Math.floor((w - D.width) / 2) : 0, dy = anchor.value === "c" ? Math.floor((h - D.height) / 2) : 0;
    for (const f of D.frames) f.cels = f.cels.map((img) => {
      if (!img) return null;
      const cv = canvasOf(w, h), ctx = ctxOf(cv);
      ctx.drawImage(celCanvas(img), dx, dy);
      return ctx.getImageData(0, 0, w, h);
    });
    D.width = w; D.height = h; S.sel = null;
    closeDialog(); changed(true); fit();
  });
}
function helpDialog() {
  const keys = [
    ["B / E / G / I", "crayon, gomme, pot, pipette (Alt : pipette temporaire)"], ["L / R / O", "ligne, rectangle, ellipse (Maj : 45° ou plein)"],
    ["M / D / S", "sélection, tramage, ombrage"], ["X", "échanger les couleurs"], ["[ et ]", "taille du pinceau"],
    ["Ctrl+Z / Ctrl+Y", "annuler / rétablir (aussi Ctrl+Maj+Z)"], ["Ctrl+C / X / V", "copier, couper, coller la sélection"],
    ["Ctrl+A", "tout sélectionner"], ["H / Maj+H", "retourner la sélection (horizontal / vertical)"], ["Flèches", "déplacer la sélection d'un pixel"],
    ["Suppr", "effacer la sélection"], ["Échap", "poser la sélection flottante, désélectionner"], [", et .", "image précédente / suivante"],
    ["Entrée", "lire l'animation"], ["Ctrl+D", "dupliquer l'image"], ["Maj+G", "grille"], ["+ / − / 0", "zoom, ajuster"],
    ["Espace + glisser, clic milieu", "déplacer la vue"], ["Molette", "zoom (Maj : défilement)"], ["Ctrl+S / Ctrl+O / Ctrl+E", "enregistrer, projets, exporter"],
    ["Ctrl+Alt+N", "nouveau projet"], ["Carte : B / E / G / I / K", "poser, effacer, remplir, prendre, bloquant"],
  ];
  dialog("Raccourcis clavier", el("div", { class: "keys" }, ...keys.flatMap(([k, v]) => [el("kbd", {}, k), el("span", {}, v)])),
    el("p", {}, "Double-clic sur une couleur de la palette : la modifier partout dans le projet. Double-clic sur un calque : le renommer. Clic sur la taille (barre du bas) : redimensionner la toile."));
}

// ---------- clavier ----------
document.addEventListener("keydown", (e) => {
  if (e.target.closest && e.target.closest("input, select, textarea")) {
    if (e.key === "Escape") e.target.blur();
    return;
  }
  if (document.querySelector(".overlay")) { if (e.key === "Escape") closeDialog(); return; }
  if (!D) return;
  const k = e.key.toLowerCase(), ctrl = e.ctrlKey || e.metaKey;
  if (ctrl && k === "z") { e.preventDefault(); undo(e.shiftKey); return; }
  if (ctrl && k === "y") { e.preventDefault(); undo(true); return; }
  if (ctrl && k === "s") { e.preventDefault(); save(true); return; }
  if (ctrl && k === "o") { e.preventDefault(); projectsDialog(); return; }
  if (ctrl && k === "e") { e.preventDefault(); exportDialog(); return; }
  if (ctrl && e.altKey && k === "n") { e.preventDefault(); newDialog(); return; }
  if (e.key === "F1") { e.preventDefault(); helpDialog(); return; }
  if (e.key === " ") { e.preventDefault(); S.space = true; return; }
  if (e.key === "+" || e.key === "=") { zoomStep(1); return; }
  if (e.key === "-") { zoomStep(-1); return; }
  if (e.key === "0") { fit(); return; }
  if (S.mode === "map") {
    const map = { b: "paint", e: "erase", g: "fill", i: "pick", k: "solid" };
    if (!ctrl && map[k]) setMapTool(map[k]);
    return;
  }
  if (ctrl && k === "c") { e.preventDefault(); copySelection(false); return; }
  if (ctrl && k === "x") { e.preventDefault(); copySelection(true); return; }
  if (ctrl && k === "v") { e.preventDefault(); pasteClip(); return; }
  if (ctrl && k === "a") { e.preventDefault(); commitFloat(); S.sel = { x: 0, y: 0, w: D.width, h: D.height }; setTool("select"); return; }
  if (ctrl && k === "d") { e.preventDefault(); frameAction("dup"); return; }
  if (ctrl) return;
  const tools = { b: "pencil", e: "eraser", g: "fill", i: "picker", l: "line", r: "rect", o: "ellipse", m: "select", d: "dither", s: "shade" };
  if (k === "g" && e.shiftKey) { toggleGrid(); return; }
  if (tools[k]) { setTool(tools[k]); return; }
  if (k === "x") { [S.primary, S.secondary] = [S.secondary, S.primary]; renderColors(); return; }
  if (k === "h") { flipSelection(e.shiftKey); return; }
  if (e.key === "[") { setBrush(S.brush - 1); return; }
  if (e.key === "]") { setBrush(S.brush + 1); return; }
  if (e.key === ",") { goFrame(S.frame - 1); return; }
  if (e.key === ".") { goFrame(S.frame + 1); return; }
  if (e.key === "Enter") { togglePlay(); return; }
  if (e.key === "Delete" || e.key === "Backspace") { deleteSelection(); return; }
  if (e.key === "Escape") { if (S.float) commitFloat(); else { S.sel = null; render(); } return; }
  const arrows = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
  if (arrows[e.key] && (S.sel || S.float)) {
    e.preventDefault();
    liftSelection();
    S.float.x += arrows[e.key][0]; S.float.y += arrows[e.key][1];
    render();
  }
});
document.addEventListener("keyup", (e) => { if (e.key === " ") S.space = false; });

function setBrush(n) {
  S.brush = Math.max(1, Math.min(8, n));
  $("brush").value = S.brush; $("brush-label").textContent = S.brush;
  render();
}
function toggleGrid() {
  S.grid = !S.grid; local.set("grid", S.grid);
  $("toggle-grid").setAttribute("aria-pressed", String(S.grid));
  render();
}
function toggleButton(id, key, after) {
  $(id).addEventListener("click", () => {
    S[key] = !S[key];
    $(id).setAttribute("aria-pressed", String(S[key]));
    if (after) after();
    render();
  });
  $(id).setAttribute("aria-pressed", String(S[key]));
}

// ---------- branchements ----------
function wire() {
  document.querySelectorAll("[data-tool]").forEach((b) => b.addEventListener("click", () => setTool(b.dataset.tool)));
  document.querySelectorAll("[data-maptool]").forEach((b) => b.addEventListener("click", () => setMapTool(b.dataset.maptool)));
  document.querySelectorAll("#modes button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  document.querySelectorAll("#map-layer button").forEach((b) => b.addEventListener("click", () => {
    S.mapLayer = b.dataset.layer; renderTiles(); render();
  }));
  toggleButton("mirror-x", "mirrorX"); toggleButton("mirror-y", "mirrorY");
  toggleButton("toggle-onion", "onion"); toggleButton("toggle-solid-view", "showSolid"); toggleButton("toggle-map-grid", "mapGrid");
  $("toggle-grid").setAttribute("aria-pressed", String(S.grid));
  $("toggle-grid").addEventListener("click", toggleGrid);
  $("brush").addEventListener("input", () => setBrush(+$("brush").value));
  $("zoom-in").addEventListener("click", () => zoomStep(1));
  $("zoom-out").addEventListener("click", () => zoomStep(-1));
  $("zoom-fit").addEventListener("click", fit);
  $("btn-new").addEventListener("click", newDialog);
  $("btn-projects").addEventListener("click", projectsDialog);
  $("btn-save").addEventListener("click", () => save(true));
  $("btn-export").addEventListener("click", exportDialog);
  $("btn-game").addEventListener("click", gameDialog);
  $("btn-help").addEventListener("click", helpDialog);
  $("btn-import").addEventListener("click", () => $("file-image").click());
  $("file-image").addEventListener("change", () => { const f = $("file-image").files[0]; $("file-image").value = ""; if (f) importImage(f); });
  $("btn-theme").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next; local.set("theme", next); render();
  });
  $("doc-name").addEventListener("change", () => {
    const n = cleanName($("doc-name").value);
    if (!n) { $("doc-name").value = D.name; toast("Nom invalide (lettres, chiffres, « _ », « - »)", true); return; }
    D.name = n; $("doc-name").value = n; S.savedOnce = false;
    $("saved").textContent = "nouveau nom : Ctrl+S pour enregistrer";
    renderStatus();
  });
  $("chip-primary").addEventListener("click", () => editColor({ kind: "primary" }, S.primary));
  $("chip-secondary").addEventListener("click", () => editColor({ kind: "secondary" }, S.secondary));
  $("swap-colors").addEventListener("click", () => { [S.primary, S.secondary] = [S.secondary, S.primary]; renderColors(); });
  $("pal-load").addEventListener("click", () => {
    const p = S.palettes.find((x) => x.id === $("palette-select").value);
    if (!p) return;
    undoDoc(); D.palette = p.colors.slice(); S.palSel = -1; changed(true);
    toast(`Palette « ${p.label} » chargée (les pixels déjà dessinés ne changent pas)`);
  });
  $("pal-add").addEventListener("click", () => {
    if (!S.primary || D.palette.includes(S.primary)) { toast("Couleur déjà dans la palette (ou transparente)"); return; }
    if (D.palette.length >= 256) { toast("256 couleurs au plus", true); return; }
    undoDoc(); D.palette.push(S.primary); changed(true);
  });
  $("pal-remove").addEventListener("click", () => {
    if (S.palSel < 0 || S.palSel >= D.palette.length) { toast("Clique d'abord une couleur de la palette"); return; }
    undoDoc(); D.palette.splice(S.palSel, 1); S.palSel = -1; changed(true);
  });
  $("pal-ramp").addEventListener("click", addRamp);
  $("pal-image").addEventListener("click", () => $("file-palette").click());
  $("file-palette").addEventListener("change", async () => {
    const f = $("file-palette").files[0]; $("file-palette").value = "";
    if (!f) return;
    try {
      const colors = await call("palette_from_image", { data: await fileToB64(f), count: 16 });
      undoDoc(); D.palette = colors; S.palSel = -1; changed(true);
      toast(`Palette de ${colors.length} couleurs tirée de ${f.name}`);
    } catch (e) { fail(e); }
  });
  $("preview-scale").textContent = `×${S.previewScale}`;
  $("preview-scale").addEventListener("click", () => {
    S.previewScale = { 1: 2, 2: 4, 4: 8, 8: 1 }[S.previewScale] || 2; local.set("previewScale", S.previewScale);
    $("preview-scale").textContent = `×${S.previewScale}`; tickPreview();
  });
  const bgNames = ["Damier", "Sombre", "Clair"];
  $("preview-bg").textContent = bgNames[S.previewBg];
  $("preview-bg").addEventListener("click", () => {
    S.previewBg = (S.previewBg + 1) % 3; local.set("previewBg", S.previewBg);
    $("preview-bg").textContent = bgNames[S.previewBg]; tickPreview();
  });
  $("layer-opacity").addEventListener("pointerdown", () => undoDoc());
  $("layer-opacity").addEventListener("input", () => {
    D.layers[S.layer].opacity = +$("layer-opacity").value / 100;
    $("opacity-label").textContent = `${$("layer-opacity").value} %`;
    render();
  });
  $("layer-opacity").addEventListener("change", () => changed(true));
  for (const [id, action] of [["layer-add", "add"], ["layer-dup", "dup"], ["layer-del", "del"], ["layer-up", "up"], ["layer-down", "down"], ["layer-merge", "merge"]]) {
    $(id).addEventListener("click", () => layerAction(action));
  }
  for (const [id, action] of [["frame-add", "add"], ["frame-dup", "dup"], ["frame-del", "del"], ["frame-left", "left"], ["frame-right", "right"]]) {
    $(id).addEventListener("click", () => frameAction(action));
  }
  $("play").addEventListener("click", () => togglePlay());
  $("frame-duration").addEventListener("change", () => {
    const v = Math.max(10, Math.min(10000, Math.round(+$("frame-duration").value) || 100));
    undoDoc(); D.frames[S.frame].duration = v; changed(true);
  });
  $("duration-all").addEventListener("click", () => {
    const v = D.frames[S.frame].duration;
    undoDoc(); D.frames.forEach((f) => { f.duration = v; }); changed(true);
    toast(`${v} ms pour toutes les images`);
  });
  $("map-resize").addEventListener("click", () => resizeMap(+$("map-cols").value, +$("map-rows").value));
  $("map-clear").addEventListener("click", () => {
    if (!confirm("Vider toute la carte (sol, décor, cases bloquantes) ?")) return;
    undoMap();
    const n = D.tilemap.cols * D.tilemap.rows;
    Object.assign(D.tilemap, { ground: Array(n).fill(-1), decor: Array(n).fill(-1), solid: Array(n).fill(0) });
    changed(true);
  });
  $("st-size").addEventListener("click", resizeDialog);
  $("st-size").title = "Clic : taille de la toile";
  new ResizeObserver(() => { if (!view().fitted || !view().manual) fit(); else render(); }).observe($("stage"));
  setInterval(() => { if (S.sel || S.float) render(); }, 120);  // pointillés animés de la sélection
}

async function start() {
  const theme = local.get("theme", "dark");
  document.documentElement.dataset.theme = theme;
  wire();
  setTool("pencil"); setMapTool("paint");
  setDoc(newDoc("sprite", 32, 32, ["#0e1116", "#3b4250", "#8f98a8", "#eef1f5"]), false);
  await loadPalettes();
  const a32 = S.palettes.find((p) => p.id === "aether32");
  if (a32 && !S.savedOnce) { D.palette = a32.colors.slice(); S.primary = D.palette[0]; renderColors(); }
  const last = local.get("last", "");
  if (last) {
    try { setDoc(await docFromServer(await call("project_load", { name: last })), true); }
    catch { local.set("last", ""); }
  }
}
start().catch(fail);
