"use strict";
// Rendu du jeu « Fuma & Inoue » : RPG 16 bits vu de dessus (tuiles de 16 px, 320×180 agrandi ×3), lumières
// douces par-dessus. Tout est dessiné par le code (aucune image, aucune bibliothèque) : style inspiré des RPG
// de l'ère 16 bits, sans rien en reprendre. Le décor dépend du nom du lieu (ambiance), la disposition de la
// graine et de l'identifiant du lieu : un même lieu se redessine toujours pareil.
// Fuma (chat sombre, gardien du repos) se dirige au clavier ou à la souris ; Inoue (chatte dorée, gardienne de
// la lumière) le suit. Marcher sur un chemin de bord, un escalier ou un objet envoie l'action au jeu.

(function () {
  const T = 16, VW = 320, VH = 180, COLS = 26, ROWS = 18, SCALE = 3, SPEED = 5.5;
  const MW = COLS * T, MH = ROWS * T;
  const OPPOSITE = { nord: "sud", sud: "nord", est: "ouest", ouest: "est", haut: "bas", bas: "haut" };
  const DIRS = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };

  // ---------- hasard reproductible ----------
  function hashString(text) {
    let h = 2166136261;
    for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }
  function rng(seed) {
    let s = seed >>> 0 || 1;
    return () => { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return ((s >>> 0) % 1000003) / 1000003; };
  }
  function hash2(x, y, salt = 0) {
    let h = Math.imul(x | 0, 374761393) + Math.imul(y | 0, 668265263) + Math.imul(salt | 0, 2147483647);
    h = Math.imul(h ^ (h >>> 13), 1274126177);
    return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
  }
  function canvas2d(w, h) {
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    const g = c.getContext("2d");
    g.imageSmoothingEnabled = false;
    return [c, g];
  }
  const px = (g, x, y, w, h, color) => { g.fillStyle = color; g.fillRect(x, y, w, h); };
  function disc(g, cx, cy, r, color) {
    g.fillStyle = color;
    for (let y = -r; y <= r; y++) {
      const w = Math.floor(Math.sqrt(r * r - y * y) + 0.35);
      g.fillRect(Math.round(cx - w), Math.round(cy + y), 2 * w + 1, 1);
    }
  }

  // ---------- ambiances : mots du lieu -> décor ----------
  const BIOMES = [
    { key: "beach", test: /phare|plage|mer\b|marée|rivage|coquill|écume|vague/i },
    { key: "bridge", test: /\bpont|passerelle|rivière|ruisseau/i },
    { key: "lake", test: /\blac|étang|eau|reflet|source|bassin|pluie|larme/i },
    { key: "library", test: /biblioth|livre|archive|papier|parchemin|grimoire/i },
    { key: "sky", test: /observatoire|étoile|ciel|constellation|astre|comète/i },
    { key: "cave", test: /grotte|caverne|cristal|nacre|profond|souterrain|mine/i },
    { key: "greenhouse", test: /serre|verrière/i },
    { key: "orchard", test: /verger|fruit|pommier/i },
    { key: "forest", test: /forêt|clairière|bois|mousse|sous-bois|fougère/i },
    { key: "garden", test: /jardin|fleur|pétale|roseraie|prairie|pré\b/i },
    { key: "sanctuary", test: /sanctuaire|temple|cercle|pierre|autel/i },
  ];
  function biomeFor(view) {
    // le mot qui vient en premier l'emporte : « Jardin des Larmes de Lune » est un jardin, pas un lac
    const first = (text) => {
      let best = null;
      for (const b of BIOMES) {
        const m = text.match(b.test);
        if (m && (!best || m.index < best.index)) best = { key: b.key, index: m.index };
      }
      return best && best.key;
    };
    return first(view.place || "") || first(view.description || "") || "garden";
  }
  function moodFor(view, biome) {
    const text = `${view.place || ""} ${view.description || ""}`;
    if (biome === "cave") return "cave";
    if (biome === "sky" || /lune|nuit|nocturne|minuit|lucioles|étoil/i.test(text)) return "night";
    if (/crépuscule|soir|couchant|aube|ambr/i.test(text)) return "dusk";
    return "day";
  }

  // couleurs du sol par ambiance
  const PAL = {
    garden: { g: ["#5dab4f", "#4a9443", "#7fc766"], p: ["#d8b87e", "#c09a5f", "#ead3a2"] },
    forest: { g: ["#3f8846", "#2f7139", "#5aa257"], p: ["#a88555", "#8c6b40", "#c3a372"] },
    orchard: { g: ["#6db553", "#58a047", "#8fd06a"], p: ["#d4b27a", "#bb955c", "#e7cf9f"] },
    lake: { g: ["#58a65a", "#47904b", "#78c070"], p: ["#d2b783", "#b99b64", "#e6d2a6"] },
    beach: { g: ["#e8d49a", "#d6bf82", "#f5e6b8"], p: ["#d9c08a", "#c4a86f", "#ecdcac"] },
    bridge: { g: ["#5aa851", "#489244", "#7cc468"], p: ["#cdb07a", "#b3945d", "#e2cb9b"] },
    library: { g: ["#a8764e", "#8c5c3c", "#c08c60"], p: ["#9b3b4a", "#7e2e3b", "#e0b050"] },
    sky: { g: ["#9c98ba", "#827ea2", "#b9b5d6"], p: ["#b8b3d2", "#9e99bc", "#d4d0ea"] },
    cave: { g: ["#565c78", "#474c63", "#6c7392"], p: ["#646b88", "#535a75", "#7a82a2"] },
    greenhouse: { g: ["#cfc8ac", "#b6af93", "#e2dcc2"], p: ["#b9b29a", "#a29b83", "#d2ccb4"] },
    sanctuary: { g: ["#62ad55", "#4f9647", "#83c96c"], p: ["#c9c3dc", "#ada6c6", "#e4e0f0"] },
  };
  const INDOOR = new Set(["library", "cave", "greenhouse"]);

  // ---------- les chats (pixel art, lettre = couleur) ----------
  const FRONT = ["........", "..oo....", "..ono...", "..obnooo", "..obbbbb", ".obbbbbb", ".obeEbbb", ".obeebbb",
                 ".obbbbwn", "..obbwww", "...occcg", "..obbbww", "..obbbww", "..obbbbw", "..obbobb", "...oo.oo"];
  const BACK = ["........", "..oo....", "..obo...", "..obbooo", "..obbbbb", ".obbbbbb", ".obbbbbb", ".obbbbbb",
                ".obbbbbb", "..obbbbb", "...occcc", "..obbbbb", "..obbbbb", "..obbbbb", "..obbobb", "...oo.oo"];
  const SIDE = ["................", ".oo..oo.........", ".ono.ono........", ".obboobbo.......", "obbbbbbbbo......",
                "obEebbbbbo......", "obeebbbbbo....o.", "nwwbbbbbbo...obo", "owwwbbbbbbooobo.", ".occcgbbbbbbbbo.",
                "..owwbbbbbbbbbo.", "..owwbbbbbbbbbo.", "..obbbbbbbbbbbo.", "..obobbooobobbo.", "..ob.ob...ob.ob.",
                "..oo.oo...oo.oo."];
  const SIDE_WALK = { 13: "..obbobooobbobo.", 14: "...obo.....obo..", 15: "...oo......oo..." };
  const FRONT_WALK = { 14: "..obbobbbbobbo..", 15: "...oo......oo..." };
  const TAIL_BACK = [[12, 13, "t"], [11, 14, "t"], [10, 14, "t"], [9, 14, "t"], [8, 14, "t"], [7, 13, "g"],
                     [11, 15, "o"], [10, 15, "o"], [9, 15, "o"], [8, 15, "o"], [7, 14, "o"], [6, 13, "o"],
                     [7, 12, "o"]];
  const CATS = {
    fuma: { o: "#17121f", b: "#3d3355", e: "#b78dff", E: "#f6efff", n: "#d98aa6", w: "#5d5179", c: "#7d6bd6",
            g: "#e9e6ff", t: "#3d3355" },
    inoue: { o: "#7a5532", b: "#f2d49b", e: "#3f8fd8", E: "#ffffff", n: "#ff9fb0", w: "#fff7e8", c: "#e0574f",
             g: "#ffd34d", t: "#f2d49b" },
  };
  const mirrorHalf = (rows) => rows.map((r) => r + [...r].reverse().join(""));
  function catFrames(name) {
    const pal = CATS[name];
    const paint = (rows, patch = []) => {
      const [c, g] = canvas2d(16, 16);
      const grid = rows.map((r) => [...r.padEnd(16, ".").slice(0, 16)]);
      for (const [y, x, ch] of patch) grid[y][x] = ch;
      grid.forEach((row, y) => row.forEach((ch, x) => { if (pal[ch]) px(g, x, y, 1, 1, pal[ch]); }));
      return c;
    };
    const withRows = (rows, changes) => rows.map((r, i) => changes[i] || r);
    const front = mirrorHalf(FRONT), back = mirrorHalf(BACK);
    const left = [paint(SIDE), paint(withRows(SIDE, SIDE_WALK))];
    const right = left.map((src) => {
      const [c, g] = canvas2d(16, 16);
      g.translate(16, 0); g.scale(-1, 1); g.drawImage(src, 0, 0);
      return c;
    });
    return {
      down: [paint(front), paint(withRows(front, FRONT_WALK))],
      up: [paint(back, TAIL_BACK), paint(withRows(back, FRONT_WALK), TAIL_BACK)],
      left, right,
    };
  }

  // ---------- objets du décor (petites toiles mises en cache) ----------
  const objectCache = {};
  function objectSprite(kind, variant, biome) {
    const key = `${kind}:${variant}:${biome}`;
    if (objectCache[key]) return objectCache[key];
    let w = 16, h = 16, ox = 0, oy = 0;
    const r = rng(hashString(key));
    let c, g;
    const make = (cw, ch, cox, coy) => { [c, g] = canvas2d(cw, ch); w = cw; h = ch; ox = cox; oy = coy; };
    switch (kind) {
      case "tree": case "fruit": {
        make(32, 40, -8, -26);
        const dark = biome === "forest" ? "#1f5a31" : "#2b6b3a", mid = biome === "forest" ? "#2f7a40" : "#3f8c48";
        const light = biome === "forest" ? "#4c9a52" : "#62b35a";
        px(g, 13, 26, 6, 12, "#5a3a24"); px(g, 14, 26, 2, 12, "#7a5134"); px(g, 12, 37, 8, 2, "#4a2f1c");
        disc(g, 16, 15, 12, "#163d22");
        disc(g, 16, 15, 11, dark); disc(g, 10, 17, 7, mid); disc(g, 21, 16, 7, mid); disc(g, 15, 10, 8, mid);
        disc(g, 12, 9, 4, light); disc(g, 19, 8, 3, light);
        for (let i = 0; i < 14; i++) px(g, 6 + r() * 20 | 0, 4 + r() * 20 | 0, 1, 1, light);
        if (kind === "fruit") {
          const fruitColor = ["#e0483e", "#f29b38", "#f2d04b"][variant % 3];
          for (let i = 0; i < 7; i++) {
            const fx = 7 + r() * 18 | 0, fy = 7 + r() * 16 | 0;
            px(g, fx, fy, 2, 2, fruitColor); px(g, fx, fy, 1, 1, "#fff2c8");
          }
        }
        break;
      }
      case "pine": {
        make(24, 40, -4, -26);
        px(g, 10, 30, 4, 9, "#5a3a24");
        for (let i = 0; i < 4; i++) {
          const y = 4 + i * 7, half = 4 + i * 2.5;
          for (let row = 0; row < 9; row++) {
            const wdt = Math.round((row / 9) * half);
            px(g, 12 - wdt, y + row, 2 * wdt, 1, row < 2 ? "#3f8a4e" : row % 3 ? "#245c34" : "#2f7140");
          }
        }
        px(g, 11, 2, 2, 3, "#3f8a4e");
        break;
      }
      case "bush": {
        make(16, 16, 0, -4);
        disc(g, 8, 10, 6, "#1d4a2a"); disc(g, 5, 10, 4, "#3a8445"); disc(g, 11, 9, 4, "#3a8445");
        disc(g, 8, 7, 4, "#4f9e55"); px(g, 6, 5, 2, 1, "#7cc46f");
        if (variant % 2) for (let i = 0; i < 4; i++) px(g, 3 + r() * 10 | 0, 5 + r() * 8 | 0, 1, 1, "#ff9fc7");
        break;
      }
      case "rock": {
        make(16, 16, 0, -2);
        const base = biome === "cave" ? ["#2f3346", "#4d5370", "#6c7392"] : ["#5e5a70", "#8a86a0", "#b3afc6"];
        disc(g, 8, 10, 6, base[0]); disc(g, 7, 9, 5, base[1]); px(g, 4, 6, 4, 2, base[2]); px(g, 5, 5, 2, 1, base[2]);
        break;
      }
      case "hedge": {
        make(16, 22, 0, -6);
        px(g, 0, 2, 16, 20, "#1f5229"); px(g, 1, 0, 14, 20, "#3a8445"); px(g, 1, 0, 14, 3, "#5aa85a");
        for (let i = 0; i < 10; i++) px(g, 1 + r() * 13 | 0, 3 + r() * 15 | 0, 2, 1, "#2c6b37");
        break;
      }
      case "pillar": {
        make(16, 34, 0, -20);
        px(g, 2, 30, 12, 4, "#7b7694"); px(g, 3, 4, 10, 27, "#c9c4dc"); px(g, 3, 4, 3, 27, "#e8e4f4");
        px(g, 11, 4, 2, 27, "#9c97b6"); px(g, 1, 0, 14, 5, "#b0abc8"); px(g, 1, 0, 14, 1, "#efeaff");
        break;
      }
      case "shelf": {
        make(16, 30, 0, -14);
        px(g, 0, 0, 16, 30, "#4a2c1c"); px(g, 1, 1, 14, 28, "#6b4128");
        const spines = ["#c0504d", "#4f7cc0", "#d9b44a", "#5e9e6a", "#9a6cc0", "#e0e0d0"];
        for (const y of [2, 10, 18]) {
          px(g, 1, y + 7, 14, 1, "#3a2216");
          for (let x = 2; x < 14;) {
            const bw = 1 + (r() * 2 | 0), bh = 5 + (r() * 2 | 0);
            px(g, x, y + 7 - bh, bw, bh, spines[r() * spines.length | 0]);
            x += bw + (r() < 0.2 ? 1 : 0);
          }
        }
        break;
      }
      case "crystal": {
        make(16, 20, 0, -6);
        const cols = [["#3a7fb8", "#6fd3ff", "#d5f6ff"], ["#7a4fc0", "#b98cff", "#efe0ff"],
                      ["#3aa88a", "#6ff0c8", "#dcfff2"]][variant % 3];
        const shard = (x, top, wdt) => {
          for (let y = top; y < 18; y++) {
            const k = Math.min(wdt, Math.floor((y - top) / 2) + 1);
            px(g, x - k, y, k, 1, cols[0]); px(g, x, y, k, 1, cols[1]);
          }
          px(g, x, top + 1, 1, 3, cols[2]);
        };
        shard(8, 2, 3); shard(4, 8, 2); shard(12, 7, 2);
        break;
      }
      case "lamp": {
        make(16, 28, 0, -14);
        px(g, 7, 6, 2, 21, "#3d3a4a"); px(g, 5, 26, 6, 2, "#2d2a38");
        px(g, 4, 1, 8, 7, "#3d3a4a"); px(g, 5, 2, 6, 5, "#ffd76a"); px(g, 6, 3, 3, 2, "#fff3c4");
        break;
      }
      case "candle": {
        make(16, 18, 0, -4);
        px(g, 3, 9, 10, 8, "#6b4128"); px(g, 3, 9, 10, 2, "#8c5a3a");
        px(g, 6, 4, 3, 5, "#f4ecd8"); px(g, 7, 1, 1, 3, "#ffcf5a"); px(g, 7, 2, 1, 1, "#fff3c4");
        break;
      }
      case "stele": {
        make(16, 26, 0, -12);
        px(g, 1, 22, 14, 4, "#5e5a70"); px(g, 2, 2, 12, 21, "#8f8aa8"); px(g, 3, 0, 10, 3, "#8f8aa8");
        px(g, 2, 2, 3, 21, "#b5b0cf"); px(g, 12, 2, 2, 21, "#6f6a88");
        for (let y = 5; y < 20; y += 3) px(g, 5 + (y % 2), y, 5 - (y % 4 ? 1 : 0), 1, "#9ff0ff");
        break;
      }
      case "telescope": {
        make(32, 32, -8, -18);
        px(g, 15, 18, 2, 12, "#4a4f6b"); px(g, 9, 29, 14, 3, "#3a3f58"); px(g, 10, 22, 2, 8, "#4a4f6b");
        px(g, 20, 22, 2, 8, "#4a4f6b");
        for (let i = 0; i < 18; i++) px(g, 6 + i, 18 - i * 0.7 | 0, 4, 4, i > 14 ? "#f0d27a" : "#c9a45a");
        px(g, 22, 3, 5, 5, "#7b82a8");
        break;
      }
      case "lighthouse": {
        make(32, 64, -8, -50);
        for (let y = 10; y < 60; y++) {
          const half = 6 + (y - 10) * 0.12 | 0;
          px(g, 16 - half, y, 2 * half, 1, Math.floor((y - 10) / 8) % 2 ? "#c0504d" : "#f2eee6");
          px(g, 16 + half - 2, y, 2, 1, "rgba(0,0,0,0.18)");
        }
        px(g, 9, 4, 14, 7, "#3d3a4a"); px(g, 11, 5, 10, 5, "#fff0a8"); px(g, 10, 1, 12, 3, "#c0504d");
        px(g, 6, 58, 20, 6, "#8a86a0");
        break;
      }
      case "fountain": {
        make(32, 32, 0, -10);
        disc(g, 16, 20, 14, "#8a86a0"); disc(g, 16, 19, 12, "#4f86d6"); disc(g, 16, 19, 9, "#6aa4ec");
        px(g, 14, 4, 4, 15, "#b9b4c9"); px(g, 11, 4, 10, 3, "#d6d2e4"); px(g, 15, 0, 2, 4, "#9fd0ff");
        break;
      }
      case "planter": {
        make(16, 22, 0, -8);
        px(g, 1, 14, 14, 8, "#8c5a3a"); px(g, 1, 14, 14, 2, "#a87048");
        disc(g, 8, 9, 6, "#3f8c48"); disc(g, 5, 8, 3, "#5aa85a"); disc(g, 11, 7, 3, "#5aa85a");
        if (variant % 2) for (let i = 0; i < 4; i++) px(g, 3 + r() * 10 | 0, 3 + r() * 9 | 0, 2, 2, "#ff8fc7");
        break;
      }
      case "reeds": {
        make(16, 20, 0, -6);
        for (let i = 0; i < 6; i++) {
          const x = 2 + i * 2 + (r() * 2 | 0), top = 2 + (r() * 8 | 0);
          px(g, x, top, 1, 20 - top, "#4f8a3a"); px(g, x, top, 1, 3, "#8a6a3a");
        }
        break;
      }
      case "railing": {
        make(16, 16, 0, -6);
        px(g, 0, 4, 16, 2, "#c9c4dc"); px(g, 0, 4, 16, 1, "#efeaff");
        for (const x of [1, 7, 13]) px(g, x, 5, 2, 10, "#9c97b6");
        break;
      }
      default: make(16, 16, 0, 0);
    }
    return (objectCache[key] = { canvas: c, ox, oy, w, h });
  }

  // ---------- génération de la carte d'un lieu ----------
  const EXIT_TILES = { nord: [[12, 0], [13, 0]], sud: [[12, ROWS - 1], [13, ROWS - 1]], ouest: [[0, 8], [0, 9]],
                       est: [[COLS - 1, 8], [COLS - 1, 9]], haut: [[5, 4]], bas: [[20, 13]] };
  const SPAWN = { nord: [12, 1, "down"], sud: [12, ROWS - 2, "up"], ouest: [1, 8, "right"],
                  est: [COLS - 2, 8, "left"], haut: [5, 5, "down"], bas: [20, 12, "up"] };
  const CENTER = [12, 9];

  function buildMap(view, biome, mood) {
    const R = rng(hashString(`${view.seed}:${view.place_id}`));
    const N = COLS * ROWS;
    const at = (x, y) => y * COLS + x;
    const inside = (x, y) => x >= 0 && y >= 0 && x < COLS && y < ROWS;
    const ground = new Array(N).fill({ library: "f", cave: "c", greenhouse: "k", beach: "s" }[biome] || "g");
    const solid = new Uint8Array(N), keep = new Uint8Array(N), taken = new Uint8Array(N);
    const objects = [], decos = [], lights = [], exitAt = {};
    const setSolid = (x, y, kind) => { if (inside(x, y)) { solid[at(x, y)] = 1; ground[at(x, y)] = kind; } };
    const indoor = INDOOR.has(biome);

    // bords : murs (intérieur) ou végétation (extérieur)
    for (let y = 0; y < ROWS; y++) {
      for (let x = 0; x < COLS; x++) {
        const edge = Math.min(x, y, COLS - 1 - x, ROWS - 1 - y);
        let wall = edge === 0;
        if (biome === "cave") wall = edge === 0 || (edge === 1 && hash2(x, y, 3) < 0.55) || (edge === 2 && hash2(x, y, 4) < 0.18);
        if (biome === "forest") wall = edge === 0 || (edge === 1 && hash2(x, y, 5) < 0.6);
        if (wall) {
          if (indoor) setSolid(x, y, "W");
          else { solid[at(x, y)] = 1; taken[at(x, y)] = 1; }
        }
      }
    }
    if (biome === "sky") for (let x = 0; x < COLS; x++) for (let y = 0; y < 3; y++) setSolid(x, y, "V");

    // chemins : du centre vers chaque sortie (deux tuiles de large)
    const pathKind = biome === "library" ? "f" : biome === "cave" ? "c" : biome === "greenhouse" ? "k" : "p";
    const carve = (x, y) => {
      for (const [dx, dy] of [[0, 0], [1, 0], [0, 1], [1, 1]]) {
        const X = x + dx, Y = y + dy;
        if (!inside(X, Y)) continue;
        solid[at(X, Y)] = 0; taken[at(X, Y)] = 0; keep[at(X, Y)] = 1;
        if (ground[at(X, Y)] !== "b") ground[at(X, Y)] = pathKind;
      }
    };
    const carveTo = (tx, ty) => {
      let [x, y] = CENTER;
      const horizontalFirst = R() < 0.5;
      const stepX = () => { while (x !== tx) { x += Math.sign(tx - x); carve(Math.min(x, COLS - 2), y); } };
      const stepY = () => { while (y !== ty) { y += Math.sign(ty - y); carve(x, Math.min(y, ROWS - 2)); } };
      carve(x, y);
      if (horizontalFirst) { stepX(); stepY(); } else { stepY(); stepX(); }
    };
    const exits = Object.keys(view.exits || {});
    for (const dir of exits) {
      const [ex, ey] = EXIT_TILES[dir][0];
      carveTo(Math.min(ex, COLS - 2), Math.min(ey, ROWS - 2));
      for (const [x, y] of EXIT_TILES[dir]) {
        solid[at(x, y)] = 0; taken[at(x, y)] = 0; keep[at(x, y)] = 1;
        ground[at(x, y)] = dir === "haut" ? "U" : dir === "bas" ? "D" : pathKind;
        exitAt[at(x, y)] = dir;
      }
      if (dir === "nord" && biome === "sky") for (let y = 0; y < 3; y++) { carve(12, y); }
      const [sx, sy] = SPAWN[dir];
      carve(Math.min(sx, COLS - 2), Math.min(sy, ROWS - 2));  // la case d'arrivée reste libre
    }
    carve(CENTER[0], CENTER[1]);

    const free = (x, y) => inside(x, y) && !solid[at(x, y)] && !keep[at(x, y)] && !taken[at(x, y)];
    const put = (kind, x, y, variant = 0, block = true) => {
      objects.push({ kind, x, y, variant });
      taken[at(x, y)] = 1;
      if (block) solid[at(x, y)] = 1;
    };

    // particularités de chaque ambiance
    if (biome === "lake" || biome === "bridge" || biome === "beach") {
      const water = (x, y) => {
        if (!inside(x, y) || exitAt[at(x, y)]) return;
        if (keep[at(x, y)]) { ground[at(x, y)] = "b"; return; }
        ground[at(x, y)] = "w"; solid[at(x, y)] = 1; taken[at(x, y)] = 1;
      };
      if (biome === "lake") {
        let best = null;
        for (let i = 0; i < 8; i++) {
          const cx = 5 + R() * 16, cy = 4 + R() * 10, rx = 4 + R() * 3, ry = 3 + R() * 2;
          let cost = 0;
          for (let y = 1; y < ROWS - 1; y++) for (let x = 1; x < COLS - 1; x++) {
            if (((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 < 1 && keep[at(x, y)]) cost++;
          }
          if (!best || cost < best.cost) best = { cx, cy, rx, ry, cost };
        }
        for (let y = 1; y < ROWS - 1; y++) for (let x = 1; x < COLS - 1; x++) {
          const d = ((x - best.cx) / best.rx) ** 2 + ((y - best.cy) / best.ry) ** 2;
          if (d < 1) water(x, y);
          else if (d < 1.6 && !keep[at(x, y)] && !solid[at(x, y)]) ground[at(x, y)] = "s";
        }
      } else if (biome === "bridge") {
        const vertical = !(exits.includes("nord") || exits.includes("sud"));
        for (let i = 1; i < (vertical ? ROWS : COLS) - 1; i++) {
          for (let k = 0; k < 3; k++) vertical ? water(17 + k, i) : water(i, 5 + k);
        }
      } else {
        for (let y = 12; y < ROWS; y++) for (let x = 0; x < COLS; x++) water(x, y);
        for (let x = 0; x < COLS; x++) if (!keep[at(x, 11)]) ground[at(x, 11)] = "s";
        if (/phare/i.test(view.place)) {
          for (const [x, y] of [[21, 4], [22, 4], [21, 5], [22, 5]]) if (free(x, y)) { taken[at(x, y)] = 1; solid[at(x, y)] = 1; }
          objects.push({ kind: "lighthouse", x: 21, y: 5, variant: 0 });
          lights.push({ x: 22 * T, y: 5 * T - 44, r: 60, color: "255,240,170" });
        }
      }
      for (let i = 0; i < 10; i++) {
        const x = 1 + R() * (COLS - 2) | 0, y = 1 + R() * (ROWS - 2) | 0;
        const nearWater = [[1, 0], [-1, 0], [0, 1], [0, -1]].some(([dx, dy]) => inside(x + dx, y + dy) && ground[at(x + dx, y + dy)] === "w");
        if (nearWater && free(x, y) && biome !== "beach") put("reeds", x, y, i, false);
      }
    }
    if (biome === "library") {
      for (let x = 1; x < COLS - 1; x++) if (!keep[at(x, 1)]) put("shelf", x, 1, x);
      for (const y of [4, 13]) for (let x = 3; x < COLS - 3; x++) if (x !== 11 && x !== 14 && free(x, y)) put("shelf", x, y, x + y);
      for (let y = 7; y <= 11; y++) for (let x = 8; x <= 17; x++) if (!solid[at(x, y)]) ground[at(x, y)] = "r";
      for (const [x, y] of [[4, 7], [21, 7], [4, 11], [21, 11]]) if (free(x, y)) { put("candle", x, y); lights.push({ x: x * T + 8, y: y * T + 2, r: 34, color: "255,200,120" }); }
    }
    if (biome === "greenhouse") {
      for (const y of [4, 13]) for (let x = 3; x < COLS - 3; x += 2) if (free(x, y)) put("planter", x, y, x);
    }
    if (biome === "orchard") {
      for (const y of [3, 6, 12, 15]) for (const x of [3, 6, 9, 16, 19, 22]) if (free(x, y)) put("fruit", x, y, x + y);
    }
    if (biome === "sanctuary") {
      for (let y = 1; y < ROWS - 1; y++) for (let x = 1; x < COLS - 1; x++) {
        const d = Math.hypot(x - 12.5, y - 9.5);
        if (d > 3.2 && d < 4.4 && !solid[at(x, y)]) ground[at(x, y)] = "t";
      }
      for (let k = 0; k < 8; k++) {
        const a = k * Math.PI / 4 + Math.PI / 8;
        const x = Math.round(12.5 + Math.cos(a) * 5.6), y = Math.round(9.5 + Math.sin(a) * 4.6);
        if (free(x, y)) put("pillar", x, y);
      }
    }
    if (biome === "sky") {
      for (let x = 0; x < COLS; x++) if (!keep[at(x, 3)] && !solid[at(x, 3)]) put("railing", x, 3);
      for (let y = 4; y < ROWS - 1; y++) for (let x = 1; x < COLS - 1; x++) if (!solid[at(x, y)] && !keep[at(x, y)]) ground[at(x, y)] = "t";
      if (free(18, 7) && free(19, 7)) { put("telescope", 18, 7); taken[at(19, 7)] = 1; solid[at(19, 7)] = 1; }
      for (const [x, y] of [[4, 6], [21, 13], [4, 14]]) if (free(x, y)) put("pillar", x, y);
    }
    if (biome === "garden") {
      const [fx, fy] = [7, 5];
      if ([[0, 0], [1, 0], [0, 1], [1, 1]].every(([dx, dy]) => free(fx + dx, fy + dy))) {
        for (const [dx, dy] of [[0, 0], [1, 0], [0, 1], [1, 1]]) { taken[at(fx + dx, fy + dy)] = 1; solid[at(fx + dx, fy + dy)] = 1; }
        objects.push({ kind: "fountain", x: fx, y: fy + 1, variant: 0 });
      }
    }

    // végétation et rochers semés
    const SCATTER = {
      garden: [["tree", 0.035], ["bush", 0.05], ["hedge", 0.015]],
      forest: [["tree", 0.11], ["pine", 0.07], ["bush", 0.05], ["rock", 0.015]],
      orchard: [["bush", 0.03], ["rock", 0.008]],
      lake: [["tree", 0.05], ["bush", 0.03], ["rock", 0.02]],
      beach: [["rock", 0.025]],
      bridge: [["tree", 0.06], ["bush", 0.04], ["rock", 0.015]],
      library: [],
      sky: [["crystal", 0.012]],
      cave: [["rock", 0.05], ["crystal", 0.035]],
      greenhouse: [["planter", 0.03], ["bush", 0.02]],
      sanctuary: [["tree", 0.035], ["bush", 0.04], ["rock", 0.01]],
    }[biome] || [];
    for (let y = 1; y < ROWS - 1; y++) {
      for (let x = 1; x < COLS - 1; x++) {
        if (!free(x, y)) continue;
        // pas d'obstacle collé au chemin du centre : on circule à l'aise
        if (Math.abs(x - 12.5) < 3 && Math.abs(y - 9.5) < 3) continue;
        let roll = hash2(x, y, view.seed + 11);
        for (const [kind, p] of SCATTER) {
          if (roll < p) { put(kind, x, y, (hash2(x, y, 9) * 6) | 0); break; }
          roll -= p;
        }
      }
    }
    // bordure vivante des lieux en plein air : arbres, haies, rochers sur les cases de bord
    if (!indoor) {
      const borderKind = { garden: ["tree", "hedge"], forest: ["pine", "tree"], orchard: ["fruit", "tree"],
                           lake: ["tree", "pine"], beach: ["rock", "rock"], bridge: ["tree", "pine"],
                           sky: [null, null], sanctuary: ["tree", "pine"] }[biome] || ["tree", "bush"];
      for (let y = 0; y < ROWS; y++) for (let x = 0; x < COLS; x++) {
        const i = at(x, y);
        if (!solid[i] || keep[i] || ground[i] === "w" || ground[i] === "V" || objects.some((o) => o.x === x && o.y === y)) continue;
        const edge = Math.min(x, y, COLS - 1 - x, ROWS - 1 - y);
        if (edge > 1) continue;
        const kind = borderKind[hash2(x, y, 21) < 0.65 ? 0 : 1];
        if (kind && (edge === 0 || hash2(x, y, 22) < 0.8)) objects.push({ kind, x, y, variant: (hash2(x, y, 23) * 6) | 0 });
      }
    }
    // fleurs, touffes, coquillages : décor plat
    const decoKinds = { garden: ["flower", "flower", "tuft"], forest: ["tuft", "mushroom", "tuft"],
                        orchard: ["flower", "tuft"], lake: ["tuft", "flower"], beach: ["shell", "pebble"],
                        bridge: ["tuft", "flower"], sky: ["star"], cave: ["pebble", "glowmoss"],
                        greenhouse: ["leaf"], sanctuary: ["flower", "tuft"], library: [] }[biome] || ["tuft"];
    for (let y = 1; y < ROWS - 1; y++) for (let x = 1; x < COLS - 1; x++) {
      const i = at(x, y);
      if (solid[i] || taken[i] || !decoKinds.length) continue;
      if (hash2(x, y, view.seed + 31) < (keep[i] ? 0.03 : 0.16)) decos.push({ kind: decoKinds[(hash2(x, y, 32) * decoKinds.length) | 0], x, y });
    }
    // réverbères le long des chemins, la nuit
    if (!indoor && mood !== "day") {
      let n = 0;
      for (let y = 2; y < ROWS - 2 && n < 6; y++) for (let x = 2; x < COLS - 2 && n < 6; x++) {
        const nextToPath = keep[at(x + 1, y)] || keep[at(x - 1, y)];
        if (free(x, y) && nextToPath && hash2(x, y, 41) < 0.06) {
          put("lamp", x, y); lights.push({ x: x * T + 8, y: y * T - 10, r: 46, color: "255,214,130" }); n++;
        }
      }
    }
    for (const o of objects) {
      if (o.kind === "crystal") lights.push({ x: o.x * T + 8, y: o.y * T + 2, r: 44, color: ["120,210,255", "190,150,255", "120,250,210"][o.variant % 3] });
    }

    // cases atteignables depuis le centre : objets et stèle n'y sont posés que là
    const reach = new Uint8Array(N);
    const queue = [at(CENTER[0], CENTER[1])];
    reach[queue[0]] = 1;
    while (queue.length) {
      const i = queue.shift();
      const x = i % COLS, y = (i / COLS) | 0;
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const X = x + dx, Y = y + dy;
        if (inside(X, Y) && !solid[at(X, Y)] && !reach[at(X, Y)]) { reach[at(X, Y)] = 1; queue.push(at(X, Y)); }
      }
    }
    const spots = [];
    for (let y = 2; y < ROWS - 2; y++) for (let x = 2; x < COLS - 2; x++) {
      const i = at(x, y);
      if (reach[i] && !exitAt[i] && !(x === CENTER[0] && y === CENTER[1]) && Math.hypot(x - 12.5, y - 9.5) > 1.5) spots.push([x, y]);
    }
    const pick = () => spots.splice((R() * spots.length) | 0, 1)[0];
    let stele = null;
    if (view.riddle) {
      const candidates = spots.filter(([x, y]) => [[0, 1], [1, 0], [-1, 0]].some(([dx, dy]) => reach[at(x + dx, y + dy)]));
      const spot = candidates.find(([x, y]) => x === 15 && y === 6) || candidates[(R() * candidates.length) | 0];
      if (spot) {
        stele = { x: spot[0], y: spot[1] };
        spots.splice(spots.findIndex(([x, y]) => x === spot[0] && y === spot[1]), 1);
        solid[at(spot[0], spot[1])] = 1;
        lights.push({ x: spot[0] * T + 8, y: spot[1] * T - 4, r: 28, color: "160,240,255" });
      }
    }
    const items = (view.items || []).slice(0, 6).map((name) => {
      const spot = pick() || CENTER;
      return { name, x: spot[0], y: spot[1] };
    });
    return { ground, solid, objects, decos, lights, exitAt, stele, items, at, inside, biome, mood, indoor };
  }

  // ---------- tuiles du sol ----------
  function paintGround(map) {
    const [c, g] = canvas2d(MW, MH);
    const pal = PAL[map.biome] || PAL.garden;
    const { ground, at, inside } = map;
    const kindAt = (x, y) => (inside(x, y) ? ground[at(x, y)] : null);
    for (let y = 0; y < ROWS; y++) for (let x = 0; x < COLS; x++) {
      const k = ground[at(x, y)], X = x * T, Y = y * T;
      const h = (s) => hash2(x, y, s);
      const base = k === "s" ? ["#e8d49a", "#d6bf82", "#f5e6b8"] : pal.g;
      if (k === "g" || k === "s" || k === "w" || k === "b" || k === "U" || k === "D") {
        px(g, X, Y, T, T, base[0]);
        for (let i = 0; i < 7; i++) px(g, X + (h(i) * 15 | 0), Y + (h(i + 9) * 15 | 0), 1, 1 + (k === "g" ? 1 : 0), base[1]);
        for (let i = 0; i < 3; i++) px(g, X + (h(i + 20) * 15 | 0), Y + (h(i + 30) * 15 | 0), 1, 1, base[2]);
      }
      if (k === "p" || (k === "k" && map.biome !== "greenhouse")) {
        px(g, X, Y, T, T, pal.p[0]);
        for (let i = 0; i < 5; i++) px(g, X + (h(i) * 14 | 0), Y + (h(i + 5) * 14 | 0), 2, 1, pal.p[1]);
        for (let i = 0; i < 2; i++) px(g, X + (h(i + 40) * 14 | 0), Y + (h(i + 50) * 14 | 0), 1, 1, pal.p[2]);
        // bord adouci : quelques brins du sol voisin débordent sur le chemin
        for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
          const n = kindAt(x + dx, y + dy);
          if (n && n !== "p" && n !== "b" && n !== "U" && n !== "D") {
            for (let i = 0; i < 6; i++) {
              const t = h(60 + i + dx * 7 + dy * 13) * 16 | 0;
              const ex = dx === 1 ? X + 15 : dx === -1 ? X : X + t, ey = dy === 1 ? Y + 15 : dy === -1 ? Y : Y + t;
              px(g, dx ? ex : ex, dy ? ey : (dx ? Y + t : ey), 1, 1, pal.g[0]);
            }
          }
        }
      }
      if (k === "f") {
        px(g, X, Y, T, T, pal.g[0]);
        for (let row = 0; row < 4; row++) {
          px(g, X, Y + row * 4 + 3, T, 1, pal.g[1]);
          px(g, X + ((h(row) * 16) | 0), Y + row * 4, 1, 3, pal.g[1]);
          if (h(row + 7) < 0.5) px(g, X + 2, Y + row * 4 + 1, 5, 1, pal.g[2]);
        }
      }
      if (k === "r") {
        px(g, X, Y, T, T, "#9b3b4a");
        for (let i = 0; i < 4; i++) px(g, X + (h(i) * 15 | 0), Y + (h(i + 3) * 15 | 0), 1, 1, "#b04d5c");
        const border = (dx, dy) => kindAt(x + dx, y + dy) !== "r";
        if (border(0, -1)) px(g, X, Y + 1, T, 2, "#e0b050");
        if (border(0, 1)) px(g, X, Y + 13, T, 2, "#e0b050");
        if (border(-1, 0)) px(g, X + 1, Y, 2, T, "#e0b050");
        if (border(1, 0)) px(g, X + 13, Y, 2, T, "#e0b050");
      }
      if (k === "t") {
        px(g, X, Y, T, T, pal.p[0]);
        px(g, X, Y, T, 1, pal.p[1]); px(g, X, Y, 1, T, pal.p[1]);
        px(g, X + 8, Y + (y % 2 ? 0 : 8), 1, 8, pal.p[1]);
        px(g, X + 2, Y + 2, 4, 1, pal.p[2]);
      }
      if (k === "c" || (map.biome === "cave" && k === "g")) {
        px(g, X, Y, T, T, pal.g[0]);
        for (let i = 0; i < 6; i++) px(g, X + (h(i) * 15 | 0), Y + (h(i + 6) * 15 | 0), 1, 1, pal.g[1]);
        if (h(70) < 0.25) { const cx = X + (h(71) * 10 | 0); px(g, cx, Y + 6, 4, 1, pal.g[1]); px(g, cx + 3, Y + 7, 3, 1, pal.g[1]); }
        px(g, X + (h(72) * 14 | 0), Y + (h(73) * 14 | 0), 1, 1, pal.g[2]);
      }
      if (k === "k" && map.biome === "greenhouse") {
        px(g, X, Y, T, T, pal.g[0]);
        px(g, X + ((x + y) % 2 ? 0 : 8), Y, 8, 8, pal.g[1]); px(g, X + ((x + y) % 2 ? 8 : 0), Y + 8, 8, 8, pal.g[1]);
      }
      if (k === "b") {
        px(g, X, Y, T, T, "#9c6b3f");
        for (let i = 0; i < 4; i++) px(g, X + i * 4 + 3, Y, 1, T, "#6b4527");
        px(g, X, Y, T, 1, "#c08a55");
      }
      if (k === "W") {
        const below = kindAt(x, y + 1);
        const face = below && below !== "W";
        if (map.biome === "library") {
          px(g, X, Y, T, T, face ? "#5a3a50" : "#2e1f2c");
          if (face) { px(g, X, Y + 12, T, 4, "#3e2737"); px(g, X, Y + 2, T, 1, "#7a5a70"); }
        } else if (map.biome === "greenhouse") {
          px(g, X, Y, T, T, face ? "#9fd8e0" : "#6aa8b4");
          px(g, X, Y, T, 1, "#e8f6f6"); px(g, X, Y, 1, T, "#e8f6f6"); px(g, X + 8, Y, 1, T, "#d0eaec");
          if (face) px(g, X + 2, Y + 3, 4, 6, "rgba(255,255,255,0.35)");
        } else {
          px(g, X, Y, T, T, face ? "#3b3f54" : "#1d2030");
          if (face) { px(g, X, Y + 11, T, 5, "#2a2d3d"); px(g, X + (h(1) * 10 | 0), Y + 4, 5, 2, "#555a70"); }
          else px(g, X + (h(2) * 12 | 0), Y + (h(3) * 12 | 0), 3, 2, "#2a2d40");
        }
      }
      if (k === "U" || k === "D") {
        const up = k === "U";
        px(g, X + 1, Y + 1, 14, 14, up ? "#b9b4c9" : "#1d1a28");
        for (let s = 0; s < 4; s++) px(g, X + 1, Y + 1 + s * 3 + (up ? 0 : 2), 14, 1, up ? "#7b7694" : "#4a4660");
        px(g, X + 1, Y + 1, 14, 1, up ? "#efeaff" : "#2d2a3a");
      }
      if (k === "V") px(g, X, Y, T, T, "#0b0d24");
    }
    for (const d of map.decos) {
      const X = d.x * T + (hash2(d.x, d.y, 80) * 10 | 0), Y = d.y * T + (hash2(d.x, d.y, 81) * 10 | 0);
      const pick = hash2(d.x, d.y, 82);
      if (d.kind === "flower") {
        const col = ["#ff8fc7", "#ffe27a", "#ffffff", "#9fb8ff"][(pick * 4) | 0];
        px(g, X + 1, Y, 1, 1, col); px(g, X, Y + 1, 3, 1, col); px(g, X + 1, Y + 2, 1, 1, col);
        px(g, X + 1, Y + 1, 1, 1, "#ffd34d"); px(g, X + 1, Y + 3, 1, 2, "#3f8a3e");
      } else if (d.kind === "tuft") {
        px(g, X, Y + 1, 1, 3, pal.g[1]); px(g, X + 2, Y, 1, 4, pal.g[1]); px(g, X + 4, Y + 1, 1, 3, pal.g[1]);
      } else if (d.kind === "mushroom") {
        px(g, X, Y, 4, 2, "#d0503f"); px(g, X + 1, Y, 1, 1, "#fff"); px(g, X + 1, Y + 2, 2, 2, "#efe4d0");
      } else if (d.kind === "shell") {
        px(g, X, Y + 1, 4, 2, "#f6d7d0"); px(g, X + 1, Y, 2, 1, "#f6d7d0"); px(g, X + 1, Y + 1, 1, 2, "#d9a99f");
      } else if (d.kind === "pebble") {
        px(g, X, Y, 3, 2, "#8a86a0"); px(g, X, Y, 1, 1, "#b3afc6");
      } else if (d.kind === "glowmoss") {
        px(g, X, Y, 3, 1, "#5fe0b0"); px(g, X + 1, Y + 1, 3, 1, "#3fb090");
      } else if (d.kind === "leaf") {
        px(g, X, Y, 3, 1, "#5aa85a"); px(g, X + 1, Y + 1, 2, 1, "#3f8c48");
      } else if (d.kind === "star") {
        px(g, X, Y, 1, 1, "#e9e6ff");
      }
    }
    return c;
  }

  // ---------- la scène ----------
  function createScene(canvas, onAction, hooks = {}) {
    const ctx = canvas.getContext("2d");
    const [buffer, g] = canvas2d(VW, VH);
    const [shade, sg] = canvas2d(VW, VH);
    const frames = { fuma: catFrames("fuma"), inoue: catFrames("inoue") };
    let view = null, map = null, groundLayer = null, running = true, last = performance.now(), time = 0;
    let fade = 1, state = "play", pending = null, banner = { text: "", sub: "", t: 0 };
    let dialog = { text: "", t: 0, shown: 0 }, showMap = true, particles = [];
    const keys = new Set();
    let path = [], queued = null;
    const cat = (x, y, face) => ({ x, y, fx: x * T, fy: y * T, face, moving: false, from: [x, y], to: [x, y], p: 0, frame: 0 });
    let fuma = cat(CENTER[0], CENTER[1], "down"), inoue = cat(CENTER[0] + 1, CENTER[1], "down");
    canvas.tabIndex = 0;

    const walkable = (x, y) => map && map.inside(x, y) && !map.solid[map.at(x, y)];

    function spawnAt(dir) {
      const s = dir && SPAWN[dir] && view.exits[dir] !== undefined ? SPAWN[dir] : [...CENTER, "down"];
      fuma = cat(s[0], s[1], s[2]);
      const [fx, fy] = DIRS[s[2]];
      // Inoue juste à côté : derrière, sinon sur un flanc, sinon devant
      const spots = [[-fx, -fy], [fy, fx], [-fy, -fx], [fx, fy]].map(([dx, dy]) => [s[0] + dx, s[1] + dy]);
      const spot = spots.find(([x, y]) => walkable(x, y) && !map.exitAt[map.at(x, y)]) || [s[0], s[1]];
      inoue = cat(spot[0], spot[1], s[2]);
      path = [];
    }

    function startMove(who, tx, ty) {
      const dx = tx - who.x, dy = ty - who.y;
      who.face = dx > 0 ? "right" : dx < 0 ? "left" : dy > 0 ? "down" : "up";
      who.from = [who.x, who.y]; who.to = [tx, ty]; who.p = 0; who.moving = true;
    }

    function tryStep(dir) {
      const [dx, dy] = DIRS[dir];
      fuma.face = dir;
      const tx = fuma.x + dx, ty = fuma.y + dy;
      if (!walkable(tx, ty)) return false;
      const oldX = fuma.x, oldY = fuma.y;
      startMove(fuma, tx, ty);
      if (inoue.x !== oldX || inoue.y !== oldY) startMove(inoue, oldX, oldY);
      return true;
    }

    function arrive() {
      const i = map.at(fuma.x, fuma.y);
      const exit = map.exitAt[i];
      if (exit) { leave(exit); return; }
      const item = map.items.find((it) => it.x === fuma.x && it.y === fuma.y && !it.taken);
      if (item) { item.taken = true; pending = { kind: "item" }; onAction(`prendre ${item.name}`); }
    }

    function leave(direction) {
      state = "leaving"; pending = { kind: "move", direction, from: view.place_id, back: [...fuma.from] };
      keys.clear(); path = []; queued = null;
      onAction(direction);
    }

    function facing() { const [dx, dy] = DIRS[fuma.face]; return [fuma.x + dx, fuma.y + dy]; }
    function interact() {
      const [x, y] = facing();
      if (map.stele && map.stele.x === x && map.stele.y === y) { onAction("regarder"); if (hooks.riddle) hooks.riddle(); return; }
      if (inoue.x === x && inoue.y === y) { onAction("parler à Inoue"); return; }
      onAction("regarder");
    }

    function findPath(tx, ty) {
      if (!map.inside(tx, ty)) return [];
      const N = COLS * ROWS, prev = new Int32Array(N).fill(-1), start = map.at(fuma.x, fuma.y), goal = map.at(tx, ty);
      const q = [start]; prev[start] = start;
      while (q.length) {
        const i = q.shift();
        if (i === goal) break;
        const x = i % COLS, y = (i / COLS) | 0;
        for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
          const X = x + dx, Y = y + dy;
          if (map.inside(X, Y) && prev[map.at(X, Y)] < 0 && (walkable(X, Y) || map.at(X, Y) === goal)) { prev[map.at(X, Y)] = i; q.push(map.at(X, Y)); }
        }
      }
      if (prev[goal] < 0) return [];
      const out = [];
      for (let i = goal; i !== start; i = prev[i]) out.unshift([i % COLS, (i / COLS) | 0]);
      if (!walkable(tx, ty)) out.pop();  // stèle, objet solide : on s'arrête devant
      return out;
    }

    // ----- entrées -----
    const KEYMAP = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right", z: "up", w: "up",
                     s: "down", q: "left", a: "left", d: "right" };
    canvas.addEventListener("keydown", (event) => {
      const dir = KEYMAP[event.key] || KEYMAP[event.key.toLowerCase()];
      if (dir) {
        keys.add(dir); path = []; event.preventDefault();
        if (state === "play" && !fuma.moving && map) tryStep(dir);  // une pression brève fait au moins un pas
        else queued = dir;  // pendant un pas : le suivant est retenu
        return;
      }
      if (event.key === " " || event.key === "Enter" || event.key.toLowerCase() === "e") { event.preventDefault(); if (state === "play" && !fuma.moving) interact(); }
      if (event.key.toLowerCase() === "m") { showMap = !showMap; if (hooks.map) hooks.map(showMap); }
    });
    canvas.addEventListener("keyup", (event) => {
      const dir = KEYMAP[event.key] || KEYMAP[event.key.toLowerCase()];
      if (dir) keys.delete(dir);
    });
    canvas.addEventListener("blur", () => keys.clear());
    canvas.addEventListener("click", (event) => {
      canvas.focus();
      if (!map || state !== "play") return;
      const rect = canvas.getBoundingClientRect();
      const cam = camera();
      const wx = (event.clientX - rect.left) * VW / rect.width + cam[0];
      const wy = (event.clientY - rect.top) * VH / rect.height + cam[1];
      const tx = Math.floor(wx / T), ty = Math.floor(wy / T);
      if (Math.abs(inoue.fx - (wx - 8)) < 10 && Math.abs(inoue.fy - (wy - 8)) < 12) { onAction("parler à Inoue"); return; }
      const isStele = map.stele && map.stele.x === tx && map.stele.y === ty;
      path = findPath(tx, ty);
      if (isStele) {
        const done = () => { fuma.face = tx > fuma.x ? "right" : tx < fuma.x ? "left" : ty > fuma.y ? "down" : "up"; interact(); };
        if (!path.length && Math.abs(tx - fuma.x) + Math.abs(ty - fuma.y) === 1) done();
        else if (path.length) fuma.afterPath = done;
      }
    });

    function camera() {
      const cx = Math.max(0, Math.min(MW - VW, fuma.fx + 8 - VW / 2));
      const cy = Math.max(0, Math.min(MH - VH, fuma.fy + 8 - VH / 2));
      return [Math.round(cx), Math.round(cy)];
    }

    // ----- mise à jour -----
    function stepCat(who, dt) {
      if (!who.moving) { who.fx = who.x * T; who.fy = who.y * T; return false; }
      who.p += dt * SPEED;
      who.frame += dt * SPEED * 2;
      if (who.p >= 1) {
        who.x = who.to[0]; who.y = who.to[1]; who.moving = false; who.p = 0;
        who.fx = who.x * T; who.fy = who.y * T;
        return true;
      }
      who.fx = (who.from[0] + (who.to[0] - who.from[0]) * who.p) * T;
      who.fy = (who.from[1] + (who.to[1] - who.from[1]) * who.p) * T;
      return false;
    }

    function tick(dt) {
      time += dt;
      if (!map) return;
      if (state === "play" && !fuma.moving) {
        if (path.length) {
          const [nx, ny] = path.shift();
          const dir = nx > fuma.x ? "right" : nx < fuma.x ? "left" : ny > fuma.y ? "down" : "up";
          if (!tryStep(dir)) path = [];
        } else if (fuma.afterPath) {
          const after = fuma.afterPath; fuma.afterPath = null; after();
        } else {
          const dir = [...keys].pop() || queued;
          queued = null;
          if (dir) tryStep(dir);
        }
      }
      if (stepCat(fuma, dt) && state === "play") arrive();
      stepCat(inoue, dt);
      if (state === "leaving") fade = Math.min(1, fade + dt * 3);
      else fade = Math.max(0, fade - dt * 2.5);
      if (banner.t > 0) banner.t -= dt;
      if (dialog.t > 0) { dialog.t -= dt; dialog.shown = Math.min(dialog.text.length, dialog.shown + dt * 60); }
      updateParticles(dt);
    }

    function updateParticles(dt) {
      const want = { garden: 14, forest: 16, orchard: 12, lake: 10, beach: 10, bridge: 10, library: 14, sky: 0,
                     cave: 12, greenhouse: 10, sanctuary: 12 }[map.biome] || 8;
      while (particles.length < want) {
        particles.push({ x: Math.random() * VW, y: Math.random() * VH, vx: (Math.random() - 0.5) * 8,
                         vy: (Math.random() - 0.5) * 6 + (map.biome === "cave" ? 14 : 0), life: 2 + Math.random() * 5,
                         phase: Math.random() * 6 });
      }
      for (const p of particles) {
        p.x += p.vx * dt + Math.sin(time + p.phase) * 0.15; p.y += p.vy * dt; p.life -= dt;
        if (map.biome === "garden" || map.biome === "orchard") p.vy = 6;
        if (map.biome === "forest" && map.mood === "day") p.vy = 9;
      }
      particles = particles.filter((p) => p.life > 0 && p.y < VH + 4 && p.x > -4 && p.x < VW + 4);
    }

    // ----- dessin -----
    function drawWater(cam) {
      const x0 = Math.floor(cam[0] / T), y0 = Math.floor(cam[1] / T);
      for (let y = y0; y <= y0 + 12 && y < ROWS; y++) for (let x = x0; x <= x0 + 20 && x < COLS; x++) {
        if (map.ground[map.at(x, y)] !== "w") continue;
        const X = x * T - cam[0], Y = y * T - cam[1];
        px(g, X, Y, T, T, map.biome === "cave" ? "#1f3a5c" : "#3d7fd6");
        const t = time * 1.4 + hash2(x, y, 5) * 6;
        px(g, X + ((t * 3 + hash2(x, y, 6) * 16) % 14 | 0), Y + 4 + (Math.sin(t) * 2 | 0), 3, 1, "#7fb6f2");
        px(g, X + ((t * 2 + hash2(x, y, 7) * 16) % 13 | 0), Y + 11 + (Math.cos(t) * 2 | 0), 2, 1, "#a8d0ff");
        for (const [dx, dy] of [[0, -1], [-1, 0], [1, 0], [0, 1]]) {
          if (!map.inside(x + dx, y + dy) || map.ground[map.at(x + dx, y + dy)] === "w") continue;
          const foam = (Math.sin(time * 2 + x + y) + 1) / 2 > 0.3 ? "#e8f4ff" : "#c8e2ff";
          if (dy === -1) px(g, X, Y, T, 1, foam);
          if (dy === 1) px(g, X, Y + 15, T, 1, foam);
          if (dx === -1) px(g, X, Y, 1, T, foam);
          if (dx === 1) px(g, X + 15, Y, 1, T, foam);
        }
      }
    }

    function drawSky(cam) {
      if (map.biome !== "sky") return;
      for (let i = 0; i < 70; i++) {
        const x = hash2(i, 1, 90) * MW - cam[0], y = hash2(i, 2, 90) * 3 * T - cam[1];
        const tw = (Math.sin(time * 2 + i) + 1) / 2;
        if (y < 3 * T - cam[1]) px(g, x | 0, y | 0, 1, 1, `rgba(233,230,255,${0.35 + tw * 0.65})`);
      }
      const mx = 6 * T - cam[0], my = 1 * T - cam[1];
      disc(g, mx, my + 6, 7, "#f6f0d6"); disc(g, mx + 3, my + 4, 6, "#0b0d24");
    }

    function drawCat(who, frameSet, cam, bob) {
      const X = Math.round(who.fx - cam[0]), Y = Math.round(who.fy - cam[1]);
      g.fillStyle = "rgba(0,0,0,0.28)";
      g.beginPath(); g.ellipse(X + 8, Y + 15, 6, 2, 0, 0, Math.PI * 2); g.fill();
      const frame = who.moving ? (Math.floor(who.frame) % 2) : 0;
      const lift = who.moving && frame === 1 ? 1 : (bob ? Math.round(Math.sin(time * 2.2) * 0.6) : 0);
      g.drawImage(frameSet[who.face][frame], X, Y - 2 - lift);
    }

    function drawScene() {
      const cam = camera();
      g.fillStyle = "#000"; g.fillRect(0, 0, VW, VH);
      g.drawImage(groundLayer, -cam[0], -cam[1]);
      drawWater(cam);
      drawSky(cam);
      // portails des sorties inexplorées : lueur qui respire
      for (const [i, dir] of Object.entries(map.exitAt)) {
        const x = (i % COLS) * T - cam[0], y = ((i / COLS) | 0) * T - cam[1];
        const known = Boolean(view.exits[dir]);
        const a = 0.25 + (Math.sin(time * 3) + 1) * (known ? 0.06 : 0.14);
        g.fillStyle = known ? `rgba(255,240,200,${a})` : `rgba(160,220,255,${a})`;
        g.fillRect(x + 2, y + 2, 12, 12);
      }
      // objets, stèle, objets à ramasser et chats triés par profondeur
      const drawables = [];
      for (const o of map.objects) {
        const s = objectSprite(o.kind, o.variant, map.biome);
        drawables.push({ y: o.y * T + 15, draw: () => g.drawImage(s.canvas, o.x * T + s.ox - cam[0], o.y * T + s.oy - cam[1]) });
      }
      if (map.stele) {
        const s = objectSprite("stele", 0, map.biome);
        drawables.push({ y: map.stele.y * T + 15, draw: () => g.drawImage(s.canvas, map.stele.x * T + s.ox - cam[0], map.stele.y * T + s.oy - cam[1]) });
      }
      for (const it of map.items) {
        if (it.taken) continue;
        drawables.push({ y: it.y * T + 8, draw: () => {
          const X = it.x * T - cam[0], Y = it.y * T - cam[1], b = Math.sin(time * 4 + it.x) * 1.5;
          px(g, X + 6, Y + 6 + b, 4, 4, "#fff3c4"); px(g, X + 7, Y + 3 + b, 2, 10, "rgba(255,240,180,0.8)");
          px(g, X + 3, Y + 7 + b, 10, 2, "rgba(255,240,180,0.8)");
        } });
      }
      drawables.push({ y: inoue.fy + 15.5, draw: () => drawCat(inoue, frames.inoue, cam, true) });
      drawables.push({ y: fuma.fy + 15.6, draw: () => drawCat(fuma, frames.fuma, cam, false) });
      drawables.sort((a, b) => a.y - b.y);
      for (const d of drawables) d.draw();
      // particules : pétales, feuilles, poussière, gouttes, lucioles
      for (const p of particles) {
        const night = map.mood !== "day";
        const color = night ? "rgba(220,255,150,0.9)" : { garden: "#ffc0dc", orchard: "#ffe0a0", forest: "#8fcf6a",
          library: "rgba(255,240,200,0.6)", cave: "#9fd8ff", lake: "rgba(255,255,255,0.7)", beach: "rgba(255,255,255,0.7)",
          bridge: "rgba(255,255,255,0.6)", greenhouse: "#c8f0a0", sanctuary: "#e8dcff" }[map.biome] || "#fff";
        px(g, p.x | 0, p.y | 0, 1, night && Math.sin(time * 5 + p.phase) < 0 ? 0 : 1, color);
      }
      // lumière : obscurité trouée par les sources (nuit, grotte), lueur additive
      const dark = { night: "rgba(12,16,48,0.55)", cave: "rgba(6,8,20,0.5)", dusk: null, day: null }[map.mood];
      const lights = map.lights.map((l) => ({ ...l, x: l.x - cam[0], y: l.y - cam[1] }));
      const energy = view.energy / (view.max_energy || 10);
      lights.push({ x: inoue.fx - cam[0] + 8, y: inoue.fy - cam[1] + 6, r: 26 + 30 * energy, color: "255,224,140" });
      if (dark) {
        sg.globalCompositeOperation = "source-over"; sg.clearRect(0, 0, VW, VH);
        sg.fillStyle = dark; sg.fillRect(0, 0, VW, VH);
        sg.globalCompositeOperation = "destination-out";
        for (const l of lights) {
          const grad = sg.createRadialGradient(l.x, l.y, 0, l.x, l.y, l.r);
          grad.addColorStop(0, "rgba(0,0,0,1)"); grad.addColorStop(1, "rgba(0,0,0,0)");
          sg.fillStyle = grad; sg.fillRect(l.x - l.r, l.y - l.r, l.r * 2, l.r * 2);
        }
        g.drawImage(shade, 0, 0);
      }
      if (map.mood === "dusk") { g.fillStyle = "rgba(255,140,80,0.14)"; g.fillRect(0, 0, VW, VH); }
      g.globalCompositeOperation = "lighter";
      for (const l of lights) {
        const grad = g.createRadialGradient(l.x, l.y, 0, l.x, l.y, l.r * 0.8);
        grad.addColorStop(0, `rgba(${l.color},${dark ? 0.22 : 0.1})`); grad.addColorStop(1, `rgba(${l.color},0)`);
        g.fillStyle = grad; g.fillRect(l.x - l.r, l.y - l.r, l.r * 2, l.r * 2);
      }
      g.globalCompositeOperation = "source-over";
      if (fade > 0) { g.fillStyle = `rgba(0,0,0,${fade})`; g.fillRect(0, 0, VW, VH); }
    }

    // ----- interface par-dessus, en pleine résolution -----
    function windowBox(x, y, w, h) {
      const grad = ctx.createLinearGradient(0, y, 0, y + h);
      grad.addColorStop(0, "rgba(40,52,140,0.92)"); grad.addColorStop(1, "rgba(16,20,70,0.92)");
      ctx.fillStyle = grad; ctx.fillRect(x, y, w, h);
      ctx.strokeStyle = "#e8ecff"; ctx.lineWidth = 3; ctx.strokeRect(x + 1.5, y + 1.5, w - 3, h - 3);
      ctx.strokeStyle = "rgba(120,140,220,0.9)"; ctx.lineWidth = 1; ctx.strokeRect(x + 5.5, y + 5.5, w - 11, h - 11);
    }
    function wrapText(text, width) {
      const words = text.split(/\s+/), lines = [];
      let line = "";
      for (const w of words) {
        const test = line ? `${line} ${w}` : w;
        if (ctx.measureText(test).width > width && line) { lines.push(line); line = w; } else line = test;
      }
      if (line) lines.push(line);
      return lines;
    }

    function drawOverlay() {
      const W = canvas.width, H = canvas.height;
      ctx.textBaseline = "top";
      // énergie d'Inoue : petites lueurs
      const max = view.max_energy || 10;
      for (let i = 0; i < max; i++) {
        const on = i < view.energy;
        ctx.fillStyle = on ? "#ffd34d" : "rgba(255,255,255,0.18)";
        ctx.beginPath(); ctx.arc(26 + i * 18, 24, on ? 6 : 4, 0, Math.PI * 2); ctx.fill();
      }
      // étiquettes des sorties
      const cam = camera();
      ctx.font = "bold 15px sans-serif";
      const seen = new Set();
      for (const [i, dir] of Object.entries(map.exitAt)) {
        if (seen.has(dir)) continue;
        seen.add(dir);
        const x = ((i % COLS) * T - cam[0] + (dir === "nord" || dir === "sud" ? 16 : 8)) * SCALE;
        const y = (((i / COLS) | 0) * T - cam[1] + 8) * SCALE;
        if (x < -40 || y < -20 || x > W + 40 || y > H + 20) continue;
        const label = view.exits[dir] ? dir : `${dir} ?`;
        const w = ctx.measureText(label).width + 12;
        const lx = Math.max(6, Math.min(W - w - 6, x - w / 2)), ly = Math.max(40, Math.min(H - 30, y - 34));
        ctx.fillStyle = "rgba(10,12,30,0.7)"; ctx.fillRect(lx, ly, w, 22);
        ctx.fillStyle = view.exits[dir] ? "#fff3c4" : "#bfe6ff"; ctx.fillText(label, lx + 6, ly + 4);
      }
      // bannière du lieu
      if (banner.t > 0) {
        const a = Math.min(1, banner.t, 3.6 - banner.t + 0.4);
        ctx.globalAlpha = Math.max(0, a);
        ctx.font = "bold 24px Georgia, serif";
        const w = Math.max(ctx.measureText(banner.text).width, 160) + 40;
        windowBox(W / 2 - w / 2, 44, w, banner.sub ? 70 : 52);
        ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.fillText(banner.text, W / 2, 58);
        if (banner.sub) { ctx.font = "13px sans-serif"; ctx.fillStyle = "#c8d0ff"; ctx.fillText(banner.sub, W / 2, 88); }
        ctx.textAlign = "left"; ctx.globalAlpha = 1;
      }
      // minicarte
      if (showMap && view.map && view.pos) drawMinimap(W);
      if (state === "leaving" && fade > 0.9) {
        ctx.font = "italic 20px Georgia, serif"; ctx.fillStyle = `rgba(232,236,255,${0.6 + Math.sin(time * 3) * 0.3})`;
        ctx.textAlign = "center";
        ctx.fillText("Les gardiens avancent… (un lieu nouveau peut demander quelques secondes au modèle local)", W / 2, H / 2 - 10);
        ctx.textAlign = "left";
      }
      // fenêtre de dialogue
      if (dialog.t > 0 && dialog.text) {
        ctx.font = "19px sans-serif";
        const lines = wrapText(dialog.text.slice(0, Math.floor(dialog.shown)), W - 100);
        const shown = lines.slice(-3);
        ctx.globalAlpha = Math.min(1, dialog.t * 2);
        windowBox(30, H - 30 - 24 - shown.length * 26, W - 60, 24 + shown.length * 26);
        ctx.fillStyle = "#fff";
        shown.forEach((line, k) => ctx.fillText(line, 50, H - 30 - 12 - shown.length * 26 + k * 26));
        ctx.globalAlpha = 1;
      }
    }

    function drawMinimap(W) {
      const [px0, py0, pz] = view.pos;
      const cell = 16, cols = 9, rows = 7, mw = cols * cell + 16, mh = rows * cell + 34;
      const x0 = W - mw - 14, y0 = 14;
      ctx.fillStyle = "rgba(8,10,30,0.72)"; ctx.fillRect(x0, y0, mw, mh);
      ctx.strokeStyle = "rgba(232,236,255,0.8)"; ctx.lineWidth = 2; ctx.strokeRect(x0 + 1, y0 + 1, mw - 2, mh - 2);
      ctx.font = "bold 12px sans-serif"; ctx.fillStyle = "#c8d0ff";
      ctx.fillText(pz ? `Carte — niveau ${pz > 0 ? "+" : ""}${pz}` : "Carte (M)", x0 + 8, y0 + 7);
      const cx = x0 + 8 + Math.floor(cols / 2) * cell, cy = y0 + 24 + Math.floor(rows / 2) * cell;
      const STUB = { nord: [0, -1], sud: [0, 1], est: [1, 0], ouest: [-1, 0] };
      for (const p of view.map) {
        if (!p.pos || p.pos[2] !== pz) continue;
        const dx = p.pos[0] - px0, dy = p.pos[1] - py0;
        if (Math.abs(dx) > cols / 2 || Math.abs(dy) > rows / 2) continue;
        const X = cx + dx * cell, Y = cy + dy * cell;
        ctx.strokeStyle = "rgba(200,210,255,0.7)"; ctx.lineWidth = 2;
        for (const [dir, known] of Object.entries(p.exits)) {
          const s = STUB[dir];
          if (!s) continue;
          ctx.globalAlpha = known ? 1 : 0.5;
          ctx.beginPath(); ctx.moveTo(X + 8, Y + 8); ctx.lineTo(X + 8 + s[0] * (known ? 8 : 6), Y + 8 + s[1] * (known ? 8 : 6)); ctx.stroke();
        }
        ctx.globalAlpha = 1;
        const here = p.id === view.place_id;
        ctx.fillStyle = here ? `rgba(255,211,77,${0.7 + Math.sin(time * 4) * 0.3})` : "#6f7fd6";
        ctx.fillRect(X + 3, Y + 3, 10, 10);
        if (p.riddle) { ctx.fillStyle = "#9ff0ff"; ctx.fillRect(X + 6, Y + 6, 4, 4); }
        if (p.exits.haut !== undefined || p.exits.bas !== undefined) { ctx.fillStyle = "#fff"; ctx.fillRect(X + 11, Y + 3, 2, 2); }
      }
    }

    function frame(now) {
      if (!running) return;
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      tick(dt);
      if (map) {
        drawScene();
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(buffer, 0, 0, canvas.width, canvas.height);
        drawOverlay();
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);

    return {
      update(next) {
        const previous = view;
        view = next;
        const changed = !previous || previous.place_id !== next.place_id;
        if (changed) {
          const biome = biomeFor(next), mood = moodFor(next, biome);
          map = buildMap(next, biome, mood);
          groundLayer = paintGround(map);
          particles = [];
          let from = null;
          if (pending && pending.kind === "move") from = OPPOSITE[pending.direction];
          else if (previous) from = Object.keys(next.exits).find((d) => next.exits[d] === previous.place_id) || null;
          spawnAt(from);
          fade = 1; state = "play"; pending = null;
          banner = { text: next.place, sub: next.origin === "modèle local" ? "lieu inventé par le modèle local" : "", t: 3.6 };
        } else {
          if (pending && pending.kind === "move") {  // le jeu a refusé d'avancer (repos nécessaire) : on recule
            const [bx, by] = pending.back;
            startMove(fuma, bx, by);
            state = "play";
          }
          pending = null;
          const names = new Set(next.items);
          for (const it of map.items) if (!names.has(it.name)) it.taken = true;
          if (!next.riddle && map.stele) {  // énigme résolue : la stèle s'efface
            map.solid[map.at(map.stele.x, map.stele.y)] = 0;
            map.stele = null;
            map.lights = map.lights.filter((l) => l.color !== "160,240,255");
          }
        }
        if (next.narration) dialog = { text: next.narration, t: 7 + next.narration.length * 0.03, shown: 0 };
      },
      stop() { running = false; },
      setMap(on) { showMap = on; },
      // l'action n'a pas abouti (Hub injoignable) : on revient en jeu, un pas en arrière
      failed() {
        if (pending && pending.kind === "move") { const [bx, by] = pending.back; startMove(fuma, bx, by); }
        pending = null; state = "play";
      },
      // sorties visibles, en coordonnées d'écran (accessibilité et essais automatiques)
      portals() {
        if (!map) return [];
        const rect = canvas.getBoundingClientRect(), cam = camera(), out = {};
        for (const [i, dir] of Object.entries(map.exitAt)) {
          if (out[dir]) continue;
          out[dir] = { direction: dir, x: rect.left + ((i % COLS) * T + 8 - cam[0]) * rect.width / VW,
                       y: rect.top + (((i / COLS) | 0) * T + 8 - cam[1]) * rect.height / VH };
        }
        return Object.values(out);
      },
      themeName() { return map ? map.biome : ""; },
      mood() { return map ? map.mood : "day"; },
    };
  }

  // ---------- ambiance sonore générée (Web Audio, aucun fichier) ----------
  // Chaque type de lieu a sa musique (accords, timbre, motif) et ses bruits : vent et oiseaux au jardin,
  // ressac à la plage, gouttes et écho dans la grotte, horloge à la bibliothèque… Coupée par défaut.
  const hz = (midi) => 440 * 2 ** ((midi - 69) / 12);
  const MUSIC = {
    garden: { chords: [[60, 64, 67, 71], [57, 60, 64, 67], [53, 57, 60, 64], [55, 59, 62, 66]], voice: "harp", layers: ["breeze", "birds"] },
    forest: { chords: [[50, 57, 60, 64], [48, 55, 59, 62], [45, 52, 55, 60], [47, 54, 57, 62]], voice: "flute", layers: ["wind", "birdsRare", "leaves"] },
    orchard: { chords: [[62, 66, 69, 73], [59, 62, 66, 69], [55, 59, 62, 67], [57, 61, 64, 69]], voice: "harp", layers: ["breeze", "birds"] },
    lake: { chords: [[62, 66, 69, 73], [59, 62, 66, 69], [55, 59, 62, 66], [57, 61, 64, 68]], voice: "bell", layers: ["lapping", "birdsRare"] },
    beach: { chords: [[64, 68, 71, 75], [61, 64, 68, 71], [57, 61, 64, 68], [59, 63, 66, 71]], voice: "none", layers: ["waves"] },
    bridge: { chords: [[60, 64, 67, 72], [62, 65, 69, 72], [57, 60, 64, 69], [55, 59, 62, 67]], voice: "flute", layers: ["stream", "breeze"] },
    library: { chords: [[57, 60, 64, 67], [53, 57, 60, 64], [55, 58, 62, 65], [52, 55, 59, 62]], voice: "pluck", layers: ["room", "clock"] },
    sky: { chords: [[67, 71, 74, 78], [64, 67, 71, 74], [60, 64, 67, 71], [62, 66, 69, 74]], voice: "bell", layers: ["shimmer"] },
    cave: { chords: [[45, 52, 57, 60], [43, 50, 55, 58], [41, 48, 53, 57], [40, 47, 52, 55]], voice: "none", layers: ["drone", "drips"] },
    greenhouse: { chords: [[60, 64, 67, 74], [57, 64, 67, 72], [62, 65, 69, 72], [55, 62, 65, 71]], voice: "pluck", layers: ["drips", "birds"] },
    sanctuary: { chords: [[55, 62, 67, 71], [52, 59, 64, 67], [48, 55, 60, 64], [50, 57, 62, 66]], voice: "bell", layers: ["choir"] },
  };

  function createAudio() {
    let ctx = null, master = null, echo = null, noise = null, on = false, volume = 0.6;
    let theme = "garden", mood = "day", current = null;

    function setup() {
      ctx = ctx || new AudioContext();
      if (master) return;
      master = ctx.createGain(); master.gain.value = volume * volume;
      const limiter = ctx.createDynamicsCompressor();
      master.connect(limiter).connect(ctx.destination);
      // écho partagé (grotte, cloches, harpe)
      echo = ctx.createDelay(1.5); echo.delayTime.value = 0.32;
      const feedback = ctx.createGain(); feedback.gain.value = 0.38;
      const tone = ctx.createBiquadFilter(); tone.type = "lowpass"; tone.frequency.value = 2400;
      echo.connect(tone).connect(feedback).connect(echo);
      tone.connect(master);
      const length = ctx.sampleRate * 2;
      noise = ctx.createBuffer(1, length, ctx.sampleRate);
      const data = noise.getChannelData(0);
      for (let i = 0; i < length; i++) data[i] = Math.random() * 2 - 1;
    }

    function tone(bus, freq, type, start, attack, hold, release, level, send = 0) {
      const osc = ctx.createOscillator(), gain = ctx.createGain();
      osc.type = type; osc.frequency.value = freq;
      gain.gain.setValueAtTime(0, start);
      gain.gain.linearRampToValueAtTime(level, start + attack);
      gain.gain.setTargetAtTime(0, start + attack + hold, release / 3);
      osc.connect(gain).connect(bus);
      if (send) { const s = ctx.createGain(); s.gain.value = send; gain.connect(s).connect(echo); }
      osc.start(start); osc.stop(start + attack + hold + release + 0.1);
      return osc;
    }

    function noiseLayer(bus, filterType, freq, q, level, lfoHz = 0, depth = 0) {
      const src = ctx.createBufferSource(); src.buffer = noise; src.loop = true;
      const filter = ctx.createBiquadFilter(); filter.type = filterType; filter.frequency.value = freq; filter.Q.value = q;
      const gain = ctx.createGain(); gain.gain.value = level;
      src.connect(filter).connect(gain).connect(bus);
      const nodes = [src];
      if (lfoHz) {
        const lfo = ctx.createOscillator(), amount = ctx.createGain();
        lfo.frequency.value = lfoHz; amount.gain.value = depth;
        lfo.connect(amount).connect(gain.gain); lfo.start(); nodes.push(lfo);
      }
      src.start(ctx.currentTime + Math.random() * 0.1);
      return nodes;
    }

    function noiseBurst(bus, freq, duration, level) {
      const src = ctx.createBufferSource(); src.buffer = noise;
      const filter = ctx.createBiquadFilter(); filter.type = "bandpass"; filter.frequency.value = freq; filter.Q.value = 1.2;
      const gain = ctx.createGain(), now = ctx.currentTime;
      gain.gain.setValueAtTime(0, now); gain.gain.linearRampToValueAtTime(level, now + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);
      src.connect(filter).connect(gain).connect(bus);
      src.start(now, Math.random()); src.stop(now + duration + 0.05);
    }

    function build(name) {
      const spec = MUSIC[name] || MUSIC.garden;
      const bus = ctx.createGain(); bus.gain.value = 0; bus.connect(master);
      bus.gain.setTargetAtTime(1, ctx.currentTime, 1.2);
      const state = { bus, sources: [], timers: [], voices: [], step: 0, alive: true };
      const every = (fn, min, max) => {
        const loop = () => {
          if (!state.alive) return;
          fn();
          setTimeout(loop, (min + Math.random() * (max - min)) * 1000);
        };
        setTimeout(loop, Math.random() * min * 1000);
      };
      const night = mood !== "day";
      // nappe d'accords
      const chord = () => {
        const notes = spec.chords[state.step++ % spec.chords.length], now = ctx.currentTime;
        for (const v of state.voices) { v.gain.gain.setTargetAtTime(0, now, 1.2); v.osc.stop(now + 6); }
        const choir = spec.layers.includes("choir");
        state.voices = notes.flatMap((note, i) => [-5, 5].map((detune) => {
          const osc = ctx.createOscillator(), gain = ctx.createGain();
          osc.type = choir ? "sawtooth" : i === 0 ? "triangle" : "sine";
          osc.frequency.value = hz(note - (i === 0 ? 12 : 0)); osc.detune.value = detune;
          gain.gain.value = 0;
          gain.gain.setTargetAtTime((i === 0 ? 0.045 : 0.026) * (choir ? 0.45 : 1), now, choir ? 2.5 : 1.5);
          if (choir) {
            const f = ctx.createBiquadFilter(); f.type = "lowpass"; f.frequency.value = 900;
            osc.connect(f).connect(gain);
          } else osc.connect(gain);
          gain.connect(bus); osc.start(now);
          return { osc, gain };
        }));
        state.chord = notes;
      };
      chord();
      state.timers.push(setInterval(chord, 9000));
      // motif mélodique
      const scale = () => (state.chord || spec.chords[0]);
      if (spec.voice !== "none") {
        every(() => {
          if (Math.random() < 0.35) return;
          const notes = scale(), note = notes[(Math.random() * notes.length) | 0] + 12 * (spec.voice === "bell" ? 1 : Math.random() < 0.5 ? 0 : 1);
          const now = ctx.currentTime;
          if (spec.voice === "harp") tone(bus, hz(note), "triangle", now, 0.005, 0.05, 1.4, 0.05, 0.25);
          if (spec.voice === "pluck") tone(bus, hz(note), "square", now, 0.003, 0.02, 0.5, 0.012, 0.15);
          if (spec.voice === "bell") { tone(bus, hz(note), "sine", now, 0.005, 0.05, 2.5, 0.035, 0.4); tone(bus, hz(note) * 2.76, "sine", now, 0.005, 0.02, 1.2, 0.01, 0.3); }
          if (spec.voice === "flute") tone(bus, hz(note), "sine", now, 0.25, 0.6, 1.2, 0.03, 0.2);
        }, spec.voice === "bell" ? 1.4 : 0.55, spec.voice === "bell" ? 3.2 : 1.3);
      }
      // bruits d'ambiance
      for (const layer of spec.layers) {
        if (layer === "breeze") state.sources.push(...noiseLayer(bus, "lowpass", 700, 0.5, 0.035, 0.07, 0.02));
        if (layer === "wind") state.sources.push(...noiseLayer(bus, "bandpass", 420, 0.7, 0.06, 0.05, 0.04));
        if (layer === "lapping") state.sources.push(...noiseLayer(bus, "lowpass", 480, 0.6, 0.05, 0.28, 0.035));
        if (layer === "waves") state.sources.push(...noiseLayer(bus, "lowpass", 850, 0.4, 0.06, 0.09, 0.06));
        if (layer === "stream") state.sources.push(...noiseLayer(bus, "bandpass", 1600, 0.5, 0.05, 3.1, 0.012));
        if (layer === "room") state.sources.push(...noiseLayer(bus, "lowpass", 180, 0.5, 0.05));
        if (layer === "shimmer") state.sources.push(...noiseLayer(bus, "highpass", 7000, 0.3, 0.008, 0.2, 0.006));
        if (layer === "drone") {
          for (const f of [55, 82.4]) {
            const osc = ctx.createOscillator(), gain = ctx.createGain();
            osc.frequency.value = f; gain.gain.value = 0.035; osc.connect(gain).connect(bus); osc.start();
            state.sources.push(osc);
          }
        }
        if (layer === "birds" || layer === "birdsRare") {
          every(() => {
            const now = ctx.currentTime;
            if (night) {  // grillons la nuit
              for (let k = 0; k < 3; k++) tone(bus, 4300, "square", now + k * 0.07, 0.005, 0.03, 0.03, 0.004);
              return;
            }
            const n = 2 + ((Math.random() * 3) | 0), base = 2400 + Math.random() * 1600;
            for (let k = 0; k < n; k++) {
              const osc = ctx.createOscillator(), gain = ctx.createGain(), t0 = now + k * 0.12;
              osc.type = "sine"; osc.frequency.setValueAtTime(base, t0);
              osc.frequency.exponentialRampToValueAtTime(base * 1.45, t0 + 0.07);
              gain.gain.setValueAtTime(0, t0); gain.gain.linearRampToValueAtTime(0.018, t0 + 0.01);
              gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.09);
              osc.connect(gain).connect(bus); osc.start(t0); osc.stop(t0 + 0.12);
            }
          }, layer === "birds" ? 2.5 : 6, layer === "birds" ? 6 : 14);
        }
        if (layer === "leaves") every(() => noiseBurst(bus, 3200, 0.4, 0.02), 3, 8);
        if (layer === "clock") {
          let tock = false;
          state.timers.push(setInterval(() => { noiseBurst(bus, tock ? 2600 : 3400, 0.03, 0.04); tock = !tock; }, 1000));
        }
        if (layer === "drips") {
          every(() => {
            const now = ctx.currentTime, f = 1300 + Math.random() * 1300;
            const osc = ctx.createOscillator(), gain = ctx.createGain(), send = ctx.createGain();
            osc.frequency.setValueAtTime(f, now); osc.frequency.exponentialRampToValueAtTime(f * 1.6, now + 0.05);
            gain.gain.setValueAtTime(0.05, now); gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.15);
            send.gain.value = 0.7;
            osc.connect(gain).connect(bus); gain.connect(send).connect(echo);
            osc.start(now); osc.stop(now + 0.2);
          }, 0.8, 3);
        }
      }
      return state;
    }

    function retire(state) {
      if (!state) return;
      state.alive = false;
      const now = ctx.currentTime;
      state.bus.gain.cancelScheduledValues(now);
      state.bus.gain.setTargetAtTime(0, now, 0.8);
      for (const t of state.timers) { clearTimeout(t); clearInterval(t); }
      setTimeout(() => {
        for (const s of state.sources) { try { s.stop(); } catch (error) { /* déjà arrêté */ } }
        for (const v of state.voices) { try { v.osc.stop(); } catch (error) { /* déjà arrêté */ } }
        state.bus.disconnect();
      }, 4000);
    }

    function refresh() {
      if (!on) return;
      const key = `${theme}:${mood}`;
      if (current && current.key === key) return;
      retire(current);
      current = build(theme);
      current.key = key;
    }

    return {
      toggle() {
        on = !on;
        if (on) { setup(); ctx.resume(); refresh(); } else { retire(current); current = null; }
        return on;
      },
      setTheme(name, newMood = "day") { theme = MUSIC[name] ? name : "garden"; mood = newMood; refresh(); },
      setFloor(name) { this.setTheme(name, mood); },
      setVolume(value) {
        volume = Math.max(0, Math.min(1, value));
        if (master) master.gain.setTargetAtTime(volume * volume, ctx.currentTime, 0.05);
      },
      chime() {
        if (!on || !ctx) return;
        const now = ctx.currentTime;
        [84, 88, 91].forEach((note, i) => tone(master, hz(note), "sine", now + i * 0.12, 0.02, 0.05, 1.4, 0.05, 0.3));
      },
      get on() { return on; },
    };
  }

  window.EtherScene = { create: createScene, themeFor: biomeFor, biomeFor, moodFor, createAudio, catFrames,
                        objectSprite };
})();
