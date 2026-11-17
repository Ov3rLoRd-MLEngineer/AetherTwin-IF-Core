"use strict";
// Rendu HD-2D du jeu « Fuma & Inoue » : monde en pixel art (320×180) en perspective, effets HD par-dessus.
// Aucune bibliothèque : Canvas 2D seul. Le décor dépend du nom et de la description du lieu (mots-clés),
// la disposition de la graine et de l'identifiant du lieu : un même lieu se redessine toujours pareil.

(function () {
  const LW = 320, LH = 180, HORIZON = 72, FOCAL = 160, CAM_H = 10;

  // ---------- hasard reproductible ----------
  function hashString(text) {
    let h = 2166136261;
    for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }
  function rng(seed) {
    let s = seed >>> 0 || 1;
    return () => { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return ((s >>> 0) % 100000) / 100000; };
  }
  function hash2(x, y) {
    let h = Math.imul(x | 0, 374761393) + Math.imul(y | 0, 668265263);
    h = Math.imul(h ^ (h >>> 13), 1274126177);
    return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
  }

  // ---------- sprites en pixel art (lettre = couleur de la palette du sprite) ----------
  const SPRITES = {
    tree: { pal: { g: "#2f6b45", G: "#4f9a5e", L: "#7cc47a", t: "#4a3326", T: "#6b4a35" }, rows: [
      "......gggg......", "....gggGGggg....", "...ggGGLGGGgg...", "..gGGGGGGLGGGg..", "..gGGLGGGGGGGg..",
      ".gGGGGGGGGGLGGg.", ".gGGLGGGGGGGGGg.", "..gGGGGGLGGGGg..", "...ggGGGGGGgg...", ".....ggGGgg.....",
      ".......tT.......", ".......tT.......", ".......tT.......", "......ttTT......"] },
    pillar: { pal: { s: "#b9b4c9", S: "#e4e0ef", d: "#8a86a0" }, rows: [
      "dSSSSSSd", ".sSSSSs.", ".sSSSSs.", ".sSSSSs.", ".sSSSSs.", ".sSSSSs.", ".sSSSSs.", ".sSSSSs.",
      ".sSSSSs.", ".sSSSSs.", ".sSSSSs.", ".sSSSSs.", "dSSSSSSd", "dddddddd"] },
    crystal: { pal: { c: "#6fd3ff", C: "#c8f1ff", d: "#3a7fb8" }, rows: [
      "....C.....", "...cCc....", "...cCc..C.", "..dcCcc.cC", "..dcCCc.cc", ".ddcCCcdcc", ".ddcCCccdc",
      "ddddcCccdd"] },
    shelf: { pal: { w: "#6b4a35", W: "#8c6446", r: "#c0504d", b: "#4f7cc0", y: "#d9b44a", n: "#5e9e6a" }, rows: [
      "WWWWWWWWWWWWWW", "WrrbyynbbryyrW", "WrrbyynbbryyrW", "WWWWWWWWWWWWWW", "WnbbryybnnrbyW",
      "WnbbryybnnrbyW", "WWWWWWWWWWWWWW", "WyrnnbbryybnrW", "WyrnnbbryybnrW", "wwwwwwwwwwwwww"] },
    lantern: { pal: { m: "#3d3a4a", y: "#ffd76a", Y: "#fff3c4" }, rows: [
      "..m..", ".mmm.", "myYym", "mYYYm", "myYym", ".mmm.", "..m..", "..m..", "..m..", "..m..", "..m..",
      ".mmm."] },
    rock: { pal: { r: "#77738a", R: "#9d99b0", d: "#55526a" }, rows: [
      "...RRRR...", ".RRRrRRRr.", "RRrrRRrrrd", "drrrrrrrdd", ".dddddddd."] },
    flower: { pal: { p: "#ff8fc7", y: "#ffe27a", g: "#4f9a5e" }, rows: [".p.", "pyp", ".p.", ".g."] },
    tower: { pal: { w: "#e9e4f2", r: "#c0504d", d: "#8a86a0", y: "#fff3c4" }, rows: [
      "...yy...", "..dyyd..", "..dddd..", "..wwww..", "..rrrr..", "..wwww..", ".wwwwww.", ".rrrrrr.",
      ".wwwwww.", ".wwwwww.", "wrrrrrrw", "wwwwwwww", "dddddddd"] },
    scope: { pal: { b: "#4a4f6b", B: "#7b82a8", y: "#ffd76a" }, rows: [
      "......By", ".....BB.", "....BB..", "...BB...", "..bb....", "..b.b...", ".b...b..", "b.....b."] },
    stone: { pal: { s: "#8f8aa8", S: "#bdb8d6", g: "#9ff0ff" }, rows: [
      "..SSSS..", ".SSSSSS.", "SSgSgSSs", "SSSgSSSs", "SgSSgSSs", "SSSSSSss", "ssssssss"] },
    inoue: { pal: { y: "#f7d774", Y: "#fff1b8", f: "#ffe0cc", e: "#5a3d2b", w: "#f4f1ff", W: "#ffffff",
                    g: "#ffd76a", s: "#c9a45a" }, rows: [
      "....yyyy....", "...yYYYYy...", "..yYffffYy..", "..yfeffefy..", "..yffffffy..", "...yffffy...",
      "....wwww....", "...wWWWWw...", "..wWWggWWw..", "..wWWWWWWw..", "..fWWWWWWf..", "...WWWWWW...",
      "...WWWWWW...", "..wWWWWWWw..", "..WWWWWWWW..", "...ww..ww...", "...ss..ss..."] },
    fuma: { pal: { h: "#2b2140", H: "#4a3a6b", f: "#e8dcef", e: "#9f7bff", p: "#3b2d5c", P: "#5b4590",
                   s: "#1f1a2e" }, rows: [
      "....hhhh....", "...hHHHHh...", "..hHffffHh..", "..hfeffefh..", "..hffffffh..", "...hffffh...",
      "..pPPPPPPp..", ".pPPPPPPPPp.", ".pPPpPPpPPp.", ".pPPPPPPPPp.", ".fPPPPPPPPf.", "..PPPPPPPP..",
      "..PPPPPPPP..", ".pPPPPPPPPp.", ".PPPPPPPPPP.", "..pp....pp..", "..ss....ss.."] },
  };
  const spriteCanvas = {};
  function sprite(name) {
    if (spriteCanvas[name]) return spriteCanvas[name];
    const def = SPRITES[name];
    const c = document.createElement("canvas");
    c.width = def.rows[0].length; c.height = def.rows.length;
    const g = c.getContext("2d");
    def.rows.forEach((row, y) => [...row].forEach((ch, x) => {
      if (def.pal[ch]) { g.fillStyle = def.pal[ch]; g.fillRect(x, y, 1, 1); }
    }));
    return (spriteCanvas[name] = c);
  }

  // ---------- thèmes : mots du lieu -> ambiance ----------
  const THEMES = [
    { test: /lac|mar[ée]e|eau|phare|pont|reflet|pluie/i, floor: "water", sky: ["#1d2b5a", "#6f8fd6", "#ffd9a8"],
      props: ["rock", "lantern", "flower"], landmark: /phare/i, landmarkSprite: "tower", fog: "#9fb6e6" },
    { test: /biblioth|papier|livre|archive/i, floor: "wood", sky: ["#2a1a2e", "#6b4a6b", "#e9b98a"],
      props: ["shelf", "lantern", "shelf"], fog: "#c9a58a" },
    { test: /observatoire|[ée]toile|ciel|nuit|lune/i, floor: "stone", sky: ["#05061a", "#1b1f4a", "#4b4f9a"],
      props: ["pillar", "crystal", "lantern"], landmark: /observatoire/i, landmarkSprite: "scope", stars: true,
      fog: "#3b3f7a" },
    { test: /grotte|cristal|nacre|profond/i, floor: "cave", sky: ["#07080f", "#141826", "#283247"],
      props: ["crystal", "rock", "crystal"], fog: "#2a3550", dark: true },
    { test: /jardin|verger|serre|clairi[èe]re|fleur|for[êe]t|mousse/i, floor: "grass",
      sky: ["#24508a", "#8fc6ef", "#fff0c8"], props: ["tree", "flower", "tree", "lantern"], fog: "#cfe6f2" },
    { test: /sanctuaire|temple|cercle|pierre/i, floor: "stone", sky: ["#3a2c6b", "#a07ad6", "#ffd9b0"],
      props: ["pillar", "lantern", "flower"], circle: true, fog: "#d6c2f2" },
  ];
  const DEFAULT_THEME = { floor: "grass", sky: ["#2d3f7a", "#9fb6e6", "#ffe3c4"], props: ["tree", "rock", "flower"],
                          fog: "#c8d6f0" };
  function themeFor(view) {
    const text = `${view.place} ${view.description || ""}`;
    return THEMES.find((t) => t.test.test(view.place)) || THEMES.find((t) => t.test.test(text)) || DEFAULT_THEME;
  }

  function hexRgb(hex) { const n = parseInt(hex.slice(1), 16); return [n >> 16, (n >> 8) & 255, n & 255]; }
  const FLOORS = {
    grass(x, z, t) {
      const h = hash2(Math.floor(x), Math.floor(z));
      const flower = h > 0.985 ? [255, 160, 200] : null;
      return flower || [60 + h * 40, 120 + h * 50, 70 + h * 20];
    },
    stone(x, z) {
      const tx = Math.floor(x / 4), tz = Math.floor(z / 4);
      const edge = (x / 4 - tx < 0.08) || (z / 4 - tz < 0.08);
      const h = hash2(tx, tz);
      return edge ? [70, 66, 90] : [140 + h * 40, 134 + h * 40, 165 + h * 35];
    },
    wood(x, z) {
      const plank = Math.floor(x / 2);
      const h = hash2(plank, Math.floor(z / 9));
      const seam = (z % 9) < 0.3 || (x / 2 - plank) < 0.08;
      return seam ? [70, 45, 32] : [130 + h * 30, 88 + h * 20, 58 + h * 12];
    },
    water(x, z, t) {
      const w = Math.sin(x * 0.7 + t * 1.6) + Math.sin(z * 0.9 - t * 1.2);
      const spark = hash2(Math.floor(x * 2), Math.floor(z * 2 + t * 3)) > 0.995 ? 90 : 0;
      return [40 + w * 8 + spark, 90 + w * 12 + spark, 160 + w * 14 + spark];
    },
    cave(x, z) {
      const h = hash2(Math.floor(x / 2), Math.floor(z / 2));
      const glow = h > 0.97 ? [80, 180, 230] : null;
      return glow || [30 + h * 18, 32 + h * 18, 44 + h * 22];
    },
  };

  // ---------- disposition du lieu ----------
  const EXIT_POS = { nord: [0, 46], est: [17, 26], ouest: [-17, 26], haut: [9, 38], bas: [-9, 38], sud: [0, 16] };
  function layout(view, seed) {
    const theme = themeFor(view);
    const r = rng(hashString(`${seed}:${view.place_id}:${view.place}`));
    const props = [];
    const count = 14 + Math.floor(r() * 10);
    for (let i = 0; i < count; i++) {
      const side = r() < 0.5 ? -1 : 1;
      const x = side * (6 + r() * 30), z = 14 + r() * 60;
      if (Object.values(EXIT_POS).some(([ex, ez]) => Math.abs(ex - x) < 5 && Math.abs(ez - z) < 6)) continue;
      props.push({ name: theme.props[Math.floor(r() * theme.props.length)], x, z, flip: r() < 0.5 });
    }
    if (theme.circle) for (let a = 0; a < 6; a++) {
      props.push({ name: "pillar", x: Math.cos(a) * 14, z: 30 + Math.sin(a) * 9 });
    }
    if (theme.landmark && theme.landmark.test(view.place)) props.push({ name: theme.landmarkSprite, x: 22, z: 70, big: 2 });
    if (view.riddle) props.push({ name: "stone", x: -5, z: 20, glow: "#9ff0ff" });
    (view.items || []).forEach((item, i) => props.push({ name: "item", x: 4 + i * 3, z: 17, label: item }));
    const flies = Array.from({ length: theme.dark ? 26 : 16 }, () => ({ x: (r() - 0.5) * 60, y: 2 + r() * 8,
                                                                       z: 12 + r() * 50, p: r() * 6.28 }));
    const stars = theme.stars ? Array.from({ length: 70 }, () => [r() * LW, r() * HORIZON, r()]) : [];
    return { theme, props, flies, stars };
  }

  // ---------- rendu ----------
  function project(x, y, z, camX) {
    const dz = Math.max(0.5, z);
    return { sx: LW / 2 + (x - camX) * FOCAL / dz, sy: HORIZON + (CAM_H - y) * FOCAL / dz, k: FOCAL / dz };
  }

  function createScene(canvas, onExit) {
    const ctx = canvas.getContext("2d");
    const low = document.createElement("canvas");
    low.width = LW; low.height = LH;
    const lctx = low.getContext("2d");
    const floorImg = lctx.createImageData(LW, LH - HORIZON);
    let view = null, scene = null, seed = 0, hits = [], running = false, last = 0, arrivedAt = -1e9;
    const lights = [];

    function drawSky(t) {
      const [top, mid, low_] = scene.theme.sky;
      const g = lctx.createLinearGradient(0, 0, 0, HORIZON);
      g.addColorStop(0, top); g.addColorStop(0.7, mid); g.addColorStop(1, low_);
      lctx.fillStyle = g; lctx.fillRect(0, 0, LW, HORIZON + 1);
      for (const [x, y, b] of scene.stars) {
        lctx.fillStyle = `rgba(255,255,255,${0.4 + 0.6 * Math.abs(Math.sin(t * (0.5 + b) + x))})`;
        lctx.fillRect(x | 0, y | 0, 1, 1);
      }
      // collines lointaines (parallaxe)
      for (let layer = 0; layer < 2; layer++) {
        lctx.fillStyle = layer ? "rgba(40,30,70,.55)" : "rgba(70,60,110,.35)";
        lctx.beginPath(); lctx.moveTo(0, HORIZON);
        for (let x = 0; x <= LW; x += 4) {
          const h = 8 + layer * 6 + Math.sin(x * 0.03 + layer * 2 + seed) * 5 + Math.sin(x * 0.11 + layer) * 2;
          lctx.lineTo(x, HORIZON - h);
        }
        lctx.lineTo(LW, HORIZON); lctx.fill();
      }
    }

    function drawFloor(t, camX) {
      const data = floorImg.data, fog = hexRgb(scene.theme.fog), tex = FLOORS[scene.theme.floor];
      let i = 0;
      for (let y = HORIZON; y < LH; y++) {
        const dist = CAM_H * FOCAL / Math.max(1, y - HORIZON + 1);
        const f = Math.min(0.85, (dist / 160) ** 1.4);  // brume douce, jamais un mur blanc
        for (let x = 0; x < LW; x++) {
          const wx = (x - LW / 2) * dist / FOCAL + camX, wz = dist;
          const c = tex(wx, wz, t);
          data[i++] = c[0] * (1 - f) + fog[0] * f;
          data[i++] = c[1] * (1 - f) + fog[1] * f;
          data[i++] = c[2] * (1 - f) + fog[2] * f;
          data[i++] = 255;
        }
      }
      lctx.putImageData(floorImg, 0, HORIZON);
    }

    function drawSprite(name, x, z, camX, scale = 1, flip = false, bob = 0) {
      const img = sprite(name);
      const p = project(x, 0, z, camX);
      const w = img.width * p.k * 0.24 * scale, h = img.height * p.k * 0.24 * scale;
      // ombre portée
      lctx.fillStyle = "rgba(0,0,0,.25)";
      lctx.beginPath(); lctx.ellipse(p.sx, p.sy, w * 0.45, Math.max(1, h * 0.06), 0, 0, 6.28); lctx.fill();
      lctx.save();
      lctx.translate(p.sx, p.sy - h + bob);
      if (flip) lctx.scale(-1, 1);
      lctx.drawImage(img, -w / 2, 0, w, h);
      lctx.restore();
      return { x: p.sx, y: p.sy - h / 2, k: p.k };
    }

    function frame(time) {
      if (!running) return;
      requestAnimationFrame(frame);
      if (!view || !canvas.offsetParent || time - last < 33) return;  // ~30 i/s, rien si l'onglet est caché
      last = time;
      const t = time / 1000, camX = Math.sin(t * 0.25) * 1.5;
      lctx.imageSmoothingEnabled = false;
      drawSky(t);
      drawFloor(t, camX);
      const haze = lctx.createLinearGradient(0, HORIZON - 14, 0, HORIZON + 16);  // l'horizon se fond dans la brume
      const [fr, fg, fb] = hexRgb(scene.theme.fog);
      haze.addColorStop(0, `rgba(${fr},${fg},${fb},0)`);
      haze.addColorStop(0.45, `rgba(${fr},${fg},${fb},.55)`);
      haze.addColorStop(1, `rgba(${fr},${fg},${fb},0)`);
      lctx.fillStyle = haze; lctx.fillRect(0, HORIZON - 14, LW, 30);
      lights.length = 0;
      hits = [];
      // objets triés du plus loin au plus proche (peintre)
      const items = scene.props.map((p) => ({ ...p, kind: "prop" }));
      for (const [direction, target] of Object.entries(view.exits || {})) {
        const [x, z] = EXIT_POS[direction] || [0, 40];
        items.push({ kind: "exit", direction, known: Boolean(target), x, z });
      }
      items.sort((a, b) => b.z - a.z);
      for (const it of items) {
        if (it.kind === "exit") {
          const p = project(it.x, 0, it.z, camX);
          const r = Math.max(4, p.k * 1.1);
          lights.push({ x: p.sx, y: p.sy - r, r: r * 3.2, color: it.known ? "255,220,140" : "160,200,255",
                        a: 0.55 + 0.25 * Math.sin(t * 2 + it.x) });
          lctx.fillStyle = it.known ? "rgba(255,230,170,.85)" : "rgba(170,210,255,.75)";
          lctx.beginPath(); lctx.ellipse(p.sx, p.sy - r, r * 0.55, r, 0, 0, 6.28); lctx.fill();
          hits.push({ direction: it.direction, x: p.sx, y: p.sy - r, r: Math.max(r * 1.6, 8),
                      label: `${it.direction}${it.known ? "" : " ?"}` });
        } else if (it.name === "item") {
          const p = project(it.x, 0, it.z, camX);
          lights.push({ x: p.sx, y: p.sy - 2, r: 10, color: "255,255,200", a: 0.6 + 0.3 * Math.sin(t * 4 + it.x) });
          lctx.fillStyle = "#fff6c8"; lctx.fillRect(p.sx - 1, p.sy - 3, 2, 2);
        } else {
          const pos = drawSprite(it.name, it.x, it.z, camX, it.big || 1, it.flip);
          if (it.name === "lantern") lights.push({ x: pos.x, y: pos.y - 2, r: 6 + pos.k * 0.5, color: "255,215,120", a: 0.7 });
          if (it.name === "crystal") lights.push({ x: pos.x, y: pos.y, r: 5 + pos.k * 0.6, color: "120,210,255", a: 0.5 });
          if (it.glow) lights.push({ x: pos.x, y: pos.y, r: 12, color: "160,240,255", a: 0.5 + 0.3 * Math.sin(t * 3) });
        }
      }
      // les gardiens, au premier plan
      const bob = Math.sin(t * 2) * 0.8;
      const ino = drawSprite("inoue", -4.5, 21, camX * 0.3, 1.3, false, bob);
      drawSprite("fuma", 4.5, 21.5, camX * 0.3, 1.3, true, -bob);
      lights.push({ x: ino.x, y: ino.y + 6, r: 22 + view.energy * 1.5, color: "255,226,140",
                    a: 0.06 + 0.012 * view.energy });  // sa lumière suit son énergie
      // lucioles
      for (const f of scene.flies) {
        const p = project(f.x + Math.sin(t * 0.7 + f.p) * 2, f.y + Math.sin(t * 1.3 + f.p), f.z, camX);
        if (p.sx < 0 || p.sx > LW || p.sy < 0) continue;
        lights.push({ x: p.sx, y: p.sy, r: 3 + p.k * 0.15, color: "255,250,190", a: 0.5 + 0.5 * Math.sin(t * 3 + f.p) });
      }
      present();
    }

    function present() {
      const W = canvas.width, H = canvas.height, sx = W / LW, sy = H / LH;
      ctx.imageSmoothingEnabled = false;
      ctx.filter = "none"; ctx.globalAlpha = 1; ctx.globalCompositeOperation = "source-over";
      ctx.drawImage(low, 0, 0, W, H);
      // flou de profondeur (effet maquette) : haut et bas de l'image
      ctx.save();
      ctx.beginPath(); ctx.rect(0, 0, W, H * 0.3); ctx.rect(0, H * 0.9, W, H * 0.1); ctx.clip();
      ctx.imageSmoothingEnabled = true; ctx.filter = "blur(3px)";
      ctx.drawImage(low, 0, 0, W, H);
      ctx.restore();
      // halo (bloom léger)
      ctx.save();
      ctx.globalCompositeOperation = "lighter"; ctx.globalAlpha = scene.theme.dark ? 0.08 : 0.08;
      ctx.imageSmoothingEnabled = true; ctx.filter = "blur(10px)";
      ctx.drawImage(low, 0, 0, W, H);
      ctx.restore();
      // lumières
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      for (const l of lights) {
        const x = l.x * sx, y = l.y * sy, r = l.r * sx;
        const g = ctx.createRadialGradient(x, y, 0, x, y, r);
        g.addColorStop(0, `rgba(${l.color},${Math.max(0, l.a)})`);
        g.addColorStop(1, `rgba(${l.color},0)`);
        ctx.fillStyle = g; ctx.fillRect(x - r, y - r, r * 2, r * 2);
      }
      ctx.restore();
      // vignettage, plus sombre dans la grotte
      const v = ctx.createRadialGradient(W / 2, H * 0.55, H * 0.35, W / 2, H * 0.55, H * 0.95);
      v.addColorStop(0, "rgba(0,0,0,0)"); v.addColorStop(1, `rgba(0,0,0,${scene.theme.dark ? 0.75 : 0.45})`);
      ctx.fillStyle = v; ctx.fillRect(0, 0, W, H);
      // étiquettes des sorties, nettes
      ctx.font = `600 ${Math.round(13 * sx / 3)}px "Segoe UI", sans-serif`;
      ctx.textAlign = "center";
      for (const h of hits) {
        ctx.fillStyle = "rgba(10,10,25,.55)";
        const w = ctx.measureText(h.label).width + 12;
        ctx.fillRect(h.x * sx - w / 2, (h.y - h.r) * sy - 20, w, 18);
        ctx.fillStyle = "#fff"; ctx.fillText(h.label, h.x * sx, (h.y - h.r) * sy - 6);
      }
      // fondu d'arrivée dans un nouveau lieu
      const since = (performance.now() - arrivedAt) / 700;
      if (since < 1) {
        ctx.fillStyle = `rgba(8,8,20,${1 - since})`;
        ctx.fillRect(0, 0, W, H);
      }
      // nom du lieu
      ctx.font = `600 ${Math.round(18 * sx / 3)}px Georgia, serif`;
      ctx.textAlign = "left";
      ctx.fillStyle = "rgba(10,10,25,.5)"; ctx.fillRect(16, 14, ctx.measureText(view.place).width + 24, 34);
      ctx.fillStyle = "#fdf6e3"; ctx.fillText(view.place, 28, 38);
    }

    canvas.addEventListener("click", (event) => {
      const rect = canvas.getBoundingClientRect();
      const x = (event.clientX - rect.left) * LW / rect.width, y = (event.clientY - rect.top) * LH / rect.height;
      const hit = hits.find((h) => (h.x - x) ** 2 + (h.y - y) ** 2 <= h.r ** 2);
      if (hit && onExit) onExit(hit.direction);
    });
    canvas.addEventListener("mousemove", (event) => {
      const rect = canvas.getBoundingClientRect();
      const x = (event.clientX - rect.left) * LW / rect.width, y = (event.clientY - rect.top) * LH / rect.height;
      canvas.style.cursor = hits.some((h) => (h.x - x) ** 2 + (h.y - y) ** 2 <= h.r ** 2) ? "pointer" : "default";
    });

    return {
      update(next) {
        const key = `${next.place_id}|${next.place}|${(next.items || []).join(",")}|${next.riddle}`;
        if (!scene || key !== this.key) {
          if (scene && view && next.place_id !== view.place_id) arrivedAt = performance.now();  // changement de lieu
          scene = layout(next, next.seed || 0); this.key = key; seed = next.seed || 0;
        }
        view = next;
        if (!running) { running = true; requestAnimationFrame(frame); }
      },
      stop() { running = false; },
      // portails visibles, en coordonnées d'écran (pour l'accessibilité et les essais automatiques)
      portals() {
        const rect = canvas.getBoundingClientRect();
        return hits.map((h) => ({ direction: h.direction, x: rect.left + h.x * rect.width / LW,
                                  y: rect.top + h.y * rect.height / LH }));
      },
      themeName() { return scene ? scene.theme.floor : ""; },
    };
  }

  window.EtherScene = { create: createScene, themeFor };
})();
