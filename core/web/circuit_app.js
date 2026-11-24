"use strict";
// Atelier circuits Æther : établi de la console 8 bits (carte mère à monter pièce par pièce), téléviseur cathodique,
// programmation en assembleur 6502 et débogueur. La console elle-même est dans nes_cpu.js, nes_ppu.js et
// nes_machine.js ; l'assembleur dans asm6502.js ; l'écran dans crt.js.
(function () {
  const { Machine, PARTS } = window.AetherNES;
  const { PALETTE } = window.AetherPPU;
  const { hex } = window.AetherCPU;
  const $ = (id) => document.getElementById(id);
  const SVG = "http://www.w3.org/2000/svg";
  const FRAME_MS = 1000 / 60.0988;
  const local = {
    get(key, fallback) { try { const v = localStorage.getItem(`circuit.${key}`); return v === null ? fallback : JSON.parse(v); } catch (e) { return fallback; } },
    set(key, value) { try { localStorage.setItem(`circuit.${key}`, JSON.stringify(value)); } catch (e) { /* stockage indisponible */ } },
  };
  const byId = Object.fromEntries(PARTS.map((p) => [p.id, p]));

  const S = {
    installed: new Set(local.get("installed", [])),
    on: false, paused: false, machine: null,
    rom: null, cartLabel: "", cartPick: "example",
    selected: null, glow: Object.fromEntries(PARTS.map((p) => [p.id, 0])),
    built: null, tv: null, frames: 0, jamShown: false,
  };

  // ---------- Hub ----------
  let activated = false;
  async function post(path, body) {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(data.detail || `erreur ${r.status}`); e.status = r.status; throw e; }
    return data;
  }
  async function call(command, payload) {
    try {
      if (!activated) { await post("/modules/circuit_lab/activate"); activated = true; }
      let reply;
      try { reply = await post(`/modules/circuit_lab/command/${command}`, payload); }
      catch (e) {
        if (e.status !== 409) throw e;
        await post("/modules/circuit_lab/activate");
        reply = await post(`/modules/circuit_lab/command/${command}`, payload);
      }
      if (!reply.ok) throw new Error((reply.error || "erreur du module").replace(/^\w+Error: /, ""));
      return reply.result;
    } catch (e) {
      if (e instanceof TypeError) throw new Error("Hub injoignable : lance AetherTwin, puis rouvre l'atelier");
      throw e;
    }
  }
  function status(text, bad) { const el = $("status"); el.textContent = text || ""; el.classList.toggle("err", Boolean(bad)); }

  // ---------- carte mère ----------
  // [x, y, largeur, hauteur, forme]
  const SOCKETS = {
    power: [30, 30, 100, 62, "power"], clock: [160, 42, 64, 32, "xtal"], cpu: [260, 38, 200, 58, "dip"],
    pads: [510, 30, 120, 70, "conn"], ram: [260, 132, 120, 46, "dip"], decoder: [404, 134, 76, 42, "dip"],
    slot: [30, 128, 26, 236, "slot"], cart: [66, 150, 150, 192, "cart"], ppu: [260, 222, 200, 58, "dip"],
    vram: [490, 222, 124, 46, "dip"], latch: [490, 300, 100, 40, "dip"], video: [510, 362, 120, 48, "conn"],
  };
  const WIRES = [
    ["power", "cpu"], ["power", "ppu"], ["clock", "cpu"], ["clock", "ppu"], ["cpu", "ram"], ["cpu", "decoder"],
    ["decoder", "ram"], ["decoder", "ppu"], ["cpu", "ppu"], ["cpu", "slot"], ["slot", "cart"], ["ppu", "latch"],
    ["latch", "vram"], ["ppu", "slot"], ["cpu", "pads"], ["ppu", "video"],
  ];
  const center = (id) => { const [x, y, w, h] = SOCKETS[id]; return [x + w / 2, y + h / 2]; };
  function el(name, attrs, parent, text) {
    const node = document.createElementNS(SVG, name);
    for (const k in attrs) node.setAttribute(k, attrs[k]);
    if (text !== undefined) node.textContent = text;
    if (parent) parent.appendChild(node);
    return node;
  }
  const svgRefs = { wires: [], glow: {}, groups: {}, led: null };

  function drawBoard() {
    const svg = $("board");
    svg.textContent = "";
    el("rect", { x: 8, y: 8, width: 644, height: 414, rx: 14, class: "pcb" }, svg);
    for (let i = 0; i < 4; i++) el("circle", { cx: [24, 636, 24, 636][i], cy: [24, 24, 406, 406][i], r: 6, fill: "#0a1f16", stroke: "#b9a77a" }, svg);
    el("text", { x: 316, y: 412, class: "silk" }, svg, "ÆTHER-8  rév. A  ·  carte mère");
    svgRefs.wires = WIRES.map(([a, b], i) => {
      const [ax, ay] = center(a), [bx, by] = center(b);
      const off = (i % 3 - 1) * 5;
      const d = Math.abs(bx - ax) > Math.abs(by - ay) ? `M${ax},${ay + off} H${(ax + bx) / 2 + off} V${by + off} H${bx}`
                                                    : `M${ax + off},${ay} V${(ay + by) / 2 + off} H${bx + off} V${by}`;
      return { a, b, node: el("path", { d, class: "trace" }, svg) };
    });
    for (const part of PARTS) {
      const [x, y, w, h, shape] = SOCKETS[part.id];
      const g = el("g", { "data-part": part.id }, svg);
      svgRefs.groups[part.id] = g;
      el("rect", { x: x - 3, y: y - 3, width: w + 6, height: h + 6, rx: 4, class: "socket", "data-socket": part.id }, g);
      el("text", { x: x, y: y - 6, class: "silk" }, g, part.socket.toUpperCase());
      if (!S.installed.has(part.id)) continue;
      g.classList.add("mounted");
      if (S.selected === part.id) g.classList.add("selected");
      drawPart(g, part, x, y, w, h, shape);
      svgRefs.glow[part.id] = el("rect", { x, y, width: w, height: h, rx: 4, class: "glow" }, g);
    }
    svgRefs.led = el("circle", { cx: 142, cy: 104, r: 5, class: "led" }, svg);
    el("text", { x: 150, y: 108, class: "silk" }, svg, "POWER");
    for (const g of Object.values(svgRefs.groups)) {
      g.addEventListener("click", () => select(g.dataset.part));
      g.addEventListener("dblclick", () => { if (S.installed.has(g.dataset.part)) toggle(g.dataset.part, false); });
      g.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("text/x-part")) { e.preventDefault(); g.firstChild.classList.add("drop"); } });
      g.addEventListener("dragleave", () => g.firstChild.classList.remove("drop"));
      g.addEventListener("drop", (e) => {
        e.preventDefault(); g.firstChild.classList.remove("drop");
        const id = e.dataTransfer.getData("text/x-part");
        if (id !== g.dataset.part) { status(`« ${byId[id].label} » ne va pas sur ce support : sa place est ${byId[id].socket.toUpperCase()}.`, true); return; }
        toggle(id, true);
      });
    }
    paintActivity();
  }

  function drawPart(g, part, x, y, w, h, shape) {
    if (shape === "dip") {
      const pins = Math.floor((w - 10) / 9);
      for (let i = 0; i < pins; i++) {
        el("rect", { x: x + 6 + i * 9, y: y - 4, width: 4, height: 5, class: "pins" }, g);
        el("rect", { x: x + 6 + i * 9, y: y + h - 1, width: 4, height: 5, class: "pins" }, g);
      }
      el("rect", { x, y, width: w, height: h, rx: 3, class: "body" }, g);
      el("circle", { cx: x + 8, cy: y + h / 2, r: 4, fill: "#0e0f12" }, g);
    } else if (shape === "cart") {
      el("rect", { x, y, width: w, height: h, rx: 6, class: "body cart" }, g);
      el("rect", { x: x + 14, y: y + 18, width: w - 28, height: h - 70, rx: 4, fill: "#d8d2c4" }, g);
      el("text", { x: x + w / 2, y: y + 62, "text-anchor": "middle", class: "cart-title" }, g, S.cartLabel || "cartouche");
      for (let i = 0; i < 6; i++) el("rect", { x: x + 20 + i * 20, y: y + h - 38, width: 12, height: 22, rx: 2, fill: "#4d5058" }, g);
    } else if (shape === "slot") {
      el("rect", { x, y, width: w, height: h, rx: 3, class: "body" }, g);
      for (let i = 0; i < 18; i++) el("rect", { x: x + 6, y: y + 8 + i * 12.5, width: w - 12, height: 4, class: "pins" }, g);
    } else if (shape === "xtal") {
      el("rect", { x, y, width: w, height: h, rx: h / 2, fill: "#c9ccd3", stroke: "#8d929c" }, g);
    } else if (shape === "power") {
      el("rect", { x, y, width: w, height: h, rx: 4, class: "body power" }, g);
      for (let i = 0; i < 7; i++) el("rect", { x: x + 8 + i * 12, y: y + 6, width: 6, height: 22, fill: "#5a5e66" }, g);
    } else {
      el("rect", { x, y, width: w, height: h, rx: 5, class: "body" }, g);
      for (let i = 0; i < 7; i++) el("circle", { cx: x + 18 + i * 14, cy: y + 16, r: 3, class: "pins" }, g);
    }
    if (shape === "slot" || shape === "cart") return;
    const shortLabel = part.label.replace(/ \(.*\)/, "");
    const label = shape === "xtal" ? "21,48 MHz" : shortLabel.length * 6.4 > w - 8 ? shortLabel.split(" ")[0] : shortLabel;
    const ty = shape === "cart" ? y + h - 52 : y + h / 2 + 4;
    if (shape === "xtal") { el("text", { x: x + w / 2, y: ty, "text-anchor": "middle", class: "label dark" }, g, label); return; }
    el("text", { x: x + w / 2, y: ty - 5, "text-anchor": "middle", class: "label" }, g, label);
    el("text", { x: x + w / 2, y: ty + 10, "text-anchor": "middle", class: "ref" }, g, part.ref);
  }

  function paintActivity() {
    const running = S.on && S.machine;
    for (const id in svgRefs.glow) svgRefs.glow[id].style.opacity = running ? Math.min(0.28, S.glow[id] * 0.28).toFixed(2) : 0;
    for (const w of svgRefs.wires) {
      const live = running && S.installed.has(w.a) && S.installed.has(w.b) && S.glow[w.a] > 0.05 && S.glow[w.b] > 0.05;
      w.node.classList.toggle("live", Boolean(live));
    }
    if (svgRefs.led) svgRefs.led.classList.toggle("on", S.on && S.installed.has("power"));
    $("tv-led").classList.toggle("on", S.on && S.installed.has("power"));
  }

  function drawTray() {
    const tray = $("tray");
    tray.textContent = "";
    const left = PARTS.filter((p) => !S.installed.has(p.id));
    if (!left.length) { const d = document.createElement("div"); d.className = "tray-empty"; d.textContent = "Tout est monté sur la carte."; tray.appendChild(d); }
    for (const part of left) {
      const item = document.createElement("div");
      item.className = "part"; item.draggable = true; item.title = part.role;
      item.innerHTML = `<span class="chip"></span><div><b></b><span></span></div>`;
      item.querySelector("b").textContent = part.label;
      item.querySelector("div span").textContent = part.ref;
      item.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/x-part", part.id); e.dataTransfer.effectAllowed = "move"; });
      item.addEventListener("click", () => { select(part.id); toggle(part.id, true); });
      tray.appendChild(item);
    }
  }

  function select(id) {
    S.selected = id;
    for (const [pid, g] of Object.entries(svgRefs.groups)) g.classList.toggle("selected", pid === id);
    const part = byId[id], box = $("part-info");
    box.textContent = "";
    if (!part) return;
    const h = document.createElement("h3"); h.textContent = `${part.label} — ${part.ref}`; box.appendChild(h);
    const p1 = document.createElement("p"); p1.textContent = part.role; box.appendChild(p1);
    const p2 = document.createElement("p"); p2.className = "missing"; p2.textContent = `S'il manque : ${part.missing}`; box.appendChild(p2);
    const b = document.createElement("button"); b.type = "button";
    const mounted = S.installed.has(id);
    b.textContent = mounted ? "Retirer de la carte" : "Monter sur la carte";
    b.addEventListener("click", () => toggle(id, !mounted));
    box.appendChild(b);
  }

  function toggle(id, mount) {
    if (mount) S.installed.add(id); else S.installed.delete(id);
    local.set("installed", [...S.installed]);
    drawBoard(); drawTray(); select(id);
    if (S.on) { boot(); status(mount ? `${byId[id].label} monté : la console redémarre.` : `${byId[id].label} retiré : la console redémarre.`); }
    diagnose();
  }

  // ---------- cartouche ----------
  async function loadExample() {
    const result = await call("example", { name: "etoiles" });
    return result.source;
  }
  async function cartridge() {
    if (S.cartPick === "example") {
      if (!S.exampleRom) {
        const built = window.AetherAsm.assemble(await loadExample());
        if (!built.ok) throw new Error("l'exemple ne s'assemble pas");
        S.exampleRom = built.rom;
      }
      return [S.exampleRom, "Fuma et les étoiles"];
    }
    if (S.cartPick === "mine") {
      const built = build();
      if (!built.ok) throw new Error("ton programme a des erreurs (onglet Programmation)");
      return [built.rom, `${$("prog-name").value || "mon_jeu"}.nes`];
    }
    if (S.fileRom) return [S.fileRom, S.fileName];
    throw new Error("choisis un fichier .nes");
  }

  // ---------- console ----------
  function boot() {
    try {
      S.machine = new Machine([...S.installed], S.rom);
    } catch (e) {
      S.machine = null; S.on = false; status(e.message, true);
    }
    if (S.machine) S.machine.apu.sampleRate = audio.ctx ? audio.ctx.sampleRate : 44100;
    S.jamShown = false; S.frames = 0;
    audio.flush();
    updatePowerButton(); diagnose(); showRegs();
  }
  async function powerOn() {
    try {
      const [rom, label] = await cartridge();
      S.rom = rom; S.cartLabel = label;
    } catch (e) { status(e.message, true); return; }
    $("cart-name").textContent = `Cartouche : ${S.cartLabel}`;
    await audio.start();
    S.on = true; S.paused = false;
    boot(); drawBoard();
    status(S.installed.has("power") ? "Console allumée." : "Le bouton est enfoncé… mais il n'y a pas d'alimentation sur la carte.");
  }
  function powerOff() {
    S.on = false; S.machine = null; audio.flush();
    updatePowerButton(); paintActivity(); diagnose(); status("Console éteinte.");
  }
  function updatePowerButton() {
    $("power").setAttribute("aria-pressed", String(S.on));
    $("power").textContent = S.on ? "⏻ Éteindre" : "⏻ Allumer";
    $("pause").textContent = S.paused ? "▶ Reprendre" : "⏸ Pause";
    $("step-frame").disabled = $("step-op").disabled = !(S.on && S.paused && S.machine);
  }
  function screenMode() {
    if (!S.on || !S.machine || !S.machine.powered) return 0;
    return S.machine.signal ? 2 : 1;
  }

  function runFrame() {
    const m = S.machine;
    pollGamepad();
    if (!m.runFrame()) return;
    S.frames += 1;
    for (const k in m.activity) {
      const target = m.activity[k] > 0 ? Math.min(1, 0.35 + Math.log10(1 + m.activity[k]) / 4) : 0;
      S.glow[k] += (target - S.glow[k]) * 0.35;
    }
    audio.push(m.apu.take());
    if (m.cpu.jammed && !S.jamShown) { S.jamShown = true; diagnose(); }
  }

  // ---------- son ----------
  const audio = {
    ctx: null, node: null, gain: null,
    async start() {
      if (this.ctx) { if (this.ctx.state === "suspended") await this.ctx.resume(); return; }
      try {
        this.ctx = new AudioContext();
        await this.ctx.audioWorklet.addModule("/static/circuit_audio.js");
        this.node = new AudioWorkletNode(this.ctx, "aether-console-sound", { outputChannelCount: [1] });
        this.gain = this.ctx.createGain();
        this.gain.gain.value = Number($("volume").value);
        this.node.connect(this.gain).connect(this.ctx.destination);
      } catch (e) { this.ctx = null; status("Son indisponible dans ce navigateur.", true); }
    },
    push(samples) { if (this.node && samples.length) this.node.port.postMessage(Float32Array.from(samples)); },
    flush() { if (this.node) this.node.port.postMessage("flush"); },
    volume(v) { if (this.gain) this.gain.gain.setTargetAtTime(v, this.ctx.currentTime, 0.02); },
  };

  // ---------- manettes ----------
  const KEYS = { ArrowUp: "Up", ArrowDown: "Down", ArrowLeft: "Left", ArrowRight: "Right", KeyX: "A", KeyZ: "B",
                 Enter: "Start", ShiftRight: "Select", NumpadEnter: "Start" };
  function key(code, down) {
    const button = KEYS[code];
    if (!button || !S.machine) return false;
    S.machine.press(0, button, down);
    return true;
  }
  function onKey(e, down) {
    if (e.target && (e.target.tagName === "TEXTAREA" || e.target.tagName === "INPUT" || e.target.tagName === "SELECT")) return;
    if (!S.on) return;
    if (key(e.code, down)) e.preventDefault();
  }
  const padState = {};
  function pollGamepad() {
    const pads = navigator.getGamepads ? navigator.getGamepads() : [];
    let player = 0;
    for (const gp of pads) {
      if (!gp || player > 1) continue;
      const b = (i) => Boolean(gp.buttons[i] && gp.buttons[i].pressed);
      const ax = gp.axes[0] || 0, ay = gp.axes[1] || 0;
      const state = { A: b(0), B: b(1) || b(2), Select: b(8), Start: b(9),
                      Up: b(12) || ay < -0.5, Down: b(13) || ay > 0.5, Left: b(14) || ax < -0.5, Right: b(15) || ax > 0.5 };
      const prev = padState[player] || {};
      for (const k in state) if (state[k] !== prev[k]) S.machine.press(player, k, state[k]);
      padState[player] = state;
      player += 1;
    }
  }

  // ---------- débogueur ----------
  function peek(addr) {
    const m = S.machine;
    if (addr < 0x2000) return m.ram[addr & 0x7ff];
    if (addr >= 0x8000 && m.cart) return m.cart.prg[(addr - 0x8000) % m.cart.prg.length];
    return 0;
  }
  function showRegs() {
    const m = S.machine;
    if (!m || !m.has("cpu") || !m.clocked) { $("regs").textContent = "Processeur : —"; $("disasm").textContent = ""; return; }
    const c = m.cpu, f = "NV-BDIZC".split("").map((ch, i) => (c.p & (0x80 >> i) ? ch : "·")).join("");
    $("regs").textContent = `PC ${hex(c.pc, 4)}  A ${hex(c.a)}  X ${hex(c.x)}  Y ${hex(c.y)}  SP ${hex(c.sp)}\n`
      + `Drapeaux ${f}   cycles ${c.cycles}   images ${S.frames}`;
    const lines = [];
    let pc = c.pc;
    const where = S.built && S.cartPick === "mine" ? S.built.sourceMap : null;
    for (let i = 0; i < 6; i++) {
      const d = c.disassemble(pc, peek);
      const line = where && where.get(pc) ? `  ← ligne ${where.get(pc)}` : "";
      lines.push(`${i === 0 ? "▶" : " "} ${hex(pc, 4)}  ${d.text.padEnd(16)}${line}`);
      pc = (pc + d.size) & 0xffff;
    }
    $("disasm").textContent = lines.join("\n");
  }

  // ---------- diagnostic ----------
  function diagnose() {
    const box = $("diag");
    box.textContent = "";
    const add = (text, cls) => { const p = document.createElement("p"); p.textContent = text; if (cls) p.className = cls; box.appendChild(p); };
    const missing = PARTS.filter((p) => !S.installed.has(p.id));
    if (!S.on) add("Console éteinte.", "muted");
    else if (!missing.length) add(`Allumée : la carte est complète. ${S.cartLabel ? `Cartouche « ${S.cartLabel} ».` : ""}`, "good");
    if (missing.length === PARTS.length) { add("La carte est vide : commence par l'alimentation, puis l'horloge et le processeur."); return; }
    for (const part of missing) add(`${part.label} manquant : ${part.missing[0].toLowerCase()}${part.missing.slice(1)}`, "warn");
    if (S.on && S.machine && S.machine.cpu.jammed) add("Le processeur est bloqué : il a lu une instruction qui fige la puce (souvent du bruit sur le bus).", "warn");
  }

  // ---------- téléviseur ----------
  let crt = null;
  function render() {
    const mode = screenMode();
    crt.setMode(mode);
    const frame = S.machine ? S.machine.ppu.frameBuffer : null;
    crt.draw(frame);
    const tv = S.tv;
    if (tv && !tv.closed && tv.AetherTV) {
      try { tv.AetherTV.show(frame, mode, crt.settings, S.on && S.installed.has("power")); } catch (e) { S.tv = null; }
    }
    paintActivity();
    if (S.on && !S.paused && S.frames % 8 === 0) showRegs();
  }
  function openTv() {
    if (S.tv && !S.tv.closed) { S.tv.focus(); return; }
    S.tv = window.open("/static/crt.html", "aether-tv", "popup,width=900,height=760");
    if (!S.tv) status("La fenêtre du téléviseur a été bloquée par le navigateur.", true);
  }
  // utilisé par la fenêtre du téléviseur (même origine). `pump` : quand le téléviseur passe en plein écran, il
  // recouvre l'atelier, que le navigateur met alors en veille (plus d'animation) ; le téléviseur fait donc avancer
  // la console lui-même, sinon il ne reçoit plus d'images et s'éteint.
  window.AetherCircuit = {
    key: (code, down) => (S.on ? key(code, down) : false),
    power: () => ($("power").click()),
    pump: () => { const now = performance.now(); if (now - last > 40) step(now); },
  };

  let acc = 0, last = performance.now();
  function loop(now) {
    step(now);
    requestAnimationFrame(loop);
  }
  function step(now) {
    if (now <= last) return;
    const dt = Math.min(100, now - last); last = now;
    if (S.on && S.machine && !S.paused) {
      acc += dt;
      let n = 0;
      while (acc >= FRAME_MS && n < 3) { runFrame(); acc -= FRAME_MS; n += 1; }
      if (n === 3) acc = 0;
    } else acc = 0;
    render();
  }

  // ---------- programmation ----------
  const src = $("source"), gutter = $("gutter");
  function paintGutter(bad) {
    const count = src.value.split("\n").length;
    const marks = new Set(bad || []);
    let html = "";
    for (let i = 1; i <= count; i++) html += marks.has(i) ? `<span class="bad">${i}</span>\n` : `${i}\n`;
    gutter.innerHTML = html;
    gutter.scrollTop = src.scrollTop;
  }
  function gotoLine(line) {
    const lines = src.value.split("\n");
    let start = 0;
    for (let i = 0; i < line - 1 && i < lines.length; i++) start += lines[i].length + 1;
    src.focus();
    src.setSelectionRange(start, start + (lines[line - 1] || "").length);
    src.scrollTop = Math.max(0, (line - 5) * 19.5);
  }
  function build() {
    const built = window.AetherAsm.assemble(src.value);
    S.built = built;
    const box = $("errors");
    box.textContent = "";
    if (built.ok) {
      const d = document.createElement("div"); d.className = "ok";
      d.textContent = `Assemblé sans erreur : ${built.used} octets de code, cartouche de ${built.prg.length / 1024} Ko de programme + 8 Ko de motifs.`;
      box.appendChild(d);
      $("prog-size").textContent = `${built.used} / ${built.prg.length} octets`;
    } else {
      for (const err of built.errors.slice(0, 50)) {
        const b = document.createElement("button"); b.type = "button";
        b.textContent = `ligne ${err.line} : ${err.message}`;
        b.addEventListener("click", () => gotoLine(err.line));
        box.appendChild(b);
      }
      $("prog-size").textContent = `${built.errors.length} erreur(s)`;
    }
    paintGutter(built.errors.map((e) => e.line));
    return built;
  }
  async function runMine() {
    const built = build();
    if (!built.ok) { status("Le programme a des erreurs : corrige-les avant de le lancer.", true); return; }
    S.cartPick = "mine"; $("cart-pick").value = "mine";
    if (S.on) powerOff();
    await powerOn();
  }
  function exportRom() {
    const built = build();
    if (!built.ok) { status("Le programme a des erreurs : rien à exporter.", true); return; }
    const name = ($("prog-name").value || "mon_jeu").replace(/[^\w.-]+/g, "_");
    const url = URL.createObjectURL(new Blob([built.rom], { type: "application/octet-stream" }));
    const a = document.createElement("a"); a.href = url; a.download = `${name}.nes`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    status(`${name}.nes exporté (${built.rom.length} octets).`);
  }
  let saveTimer = 0;
  function remember() { clearTimeout(saveTimer); saveTimer = setTimeout(() => { local.set("source", src.value); local.set("name", $("prog-name").value); }, 400); }
  async function saveProject() {
    try {
      const result = await call("project_save", { name: $("prog-name").value, source: src.value });
      $("prog-name").value = result.name;
      status(`« ${result.name} » enregistré.`);
    } catch (e) { status(e.message, true); }
  }
  async function openDialog() {
    const list = $("open-list");
    list.textContent = "";
    try {
      const items = await call("projects", {});
      if (!items.length) list.textContent = "Aucun programme enregistré pour l'instant.";
      for (const item of items) {
        const row = document.createElement("div"); row.className = "item";
        const open = document.createElement("button"); open.type = "button"; open.textContent = item.name;
        open.addEventListener("click", async () => {
          try {
            const p = await call("project_load", { name: item.name });
            src.value = p.source; $("prog-name").value = p.name; remember(); build(); $("open-dialog").close();
            status(`« ${p.name} » ouvert.`);
          } catch (e) { status(e.message, true); }
        });
        const del = document.createElement("button"); del.type = "button"; del.className = "ghost"; del.textContent = "Supprimer";
        del.addEventListener("click", async () => {
          if (!confirm(`Supprimer « ${item.name} » ?`)) return;
          try { await call("project_delete", { name: item.name }); row.remove(); } catch (e) { status(e.message, true); }
        });
        row.append(open, del); list.appendChild(row);
      }
    } catch (e) { list.textContent = e.message; }
    $("open-dialog").showModal();
  }

  // ---------- mise en route ----------
  function setMode(mode) {
    for (const b of document.querySelectorAll("#modes button")) b.setAttribute("aria-selected", String(b.dataset.mode === mode));
    for (const v of document.querySelectorAll(".view")) v.hidden = v.dataset.view !== mode;
    local.set("mode", mode);
    if (mode === "code") paintGutter(S.built ? S.built.errors.map((e) => e.line) : []);
  }
  function wire() {
    for (const b of document.querySelectorAll("#modes button")) b.addEventListener("click", () => setMode(b.dataset.mode));
    $("btn-theme").addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
      document.documentElement.dataset.theme = next; local.set("theme", next);
    });
    $("all-in").addEventListener("click", () => { PARTS.forEach((p) => S.installed.add(p.id)); toggle("cart", true); });
    $("all-out").addEventListener("click", () => { S.installed.clear(); local.set("installed", []); drawBoard(); drawTray(); select(null); if (S.on) boot(); diagnose(); });
    $("power").addEventListener("click", () => (S.on ? powerOff() : powerOn()));
    $("reset").addEventListener("click", () => { if (S.machine && S.machine.clocked && S.machine.has("cpu")) { S.machine.cpu.reset(); S.jamShown = false; status("RESET."); } });
    $("cart-pick").addEventListener("change", (e) => {
      S.cartPick = e.target.value;
      if (S.cartPick === "file") $("nes-file").click();
      else if (S.on) { powerOff(); powerOn(); }
    });
    $("nes-file").addEventListener("change", async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const bytes = new Uint8Array(await file.arrayBuffer());
      try { window.AetherNES.parseRom(bytes); } catch (err) { status(`${file.name} : ${err.message}`, true); return; }
      S.fileRom = bytes; S.fileName = file.name;
      if (S.on) powerOff();
      await powerOn();
    });
    $("volume").addEventListener("input", (e) => { audio.volume(Number(e.target.value)); local.set("volume", Number(e.target.value)); });
    $("crt-fx").addEventListener("change", (e) => {
      Object.assign(crt.settings, e.target.checked ? { curve: 0.12, scan: 0.7, glow: 0.8 } : { curve: 0, scan: 0, glow: 0 });
      local.set("crt", e.target.checked);
    });
    $("tv-open").addEventListener("click", openTv);
    $("pause").addEventListener("click", () => { if (!S.on) return; S.paused = !S.paused; updatePowerButton(); showRegs(); });
    $("step-frame").addEventListener("click", () => { if (S.machine) { runFrame(); showRegs(); } });
    $("step-op").addEventListener("click", () => {
      const m = S.machine;
      if (!m || !m.has("cpu") || !m.clocked) return;
      const cycles = m.cpu.step();
      m.apu.run(cycles);
      if (m.has("ppu")) for (let i = 0; i < cycles * 3; i++) if (m.ppu.tick()) m.cpu.nmi = true;
      showRegs();
    });
    window.addEventListener("keydown", (e) => onKey(e, true));
    window.addEventListener("keyup", (e) => onKey(e, false));
    window.addEventListener("beforeunload", () => { if (S.tv && !S.tv.closed) S.tv.close(); });

    src.addEventListener("input", () => { paintGutter([]); remember(); });
    src.addEventListener("scroll", () => { gutter.scrollTop = src.scrollTop; });
    src.addEventListener("keydown", (e) => {
      if (e.key === "Tab") {
        e.preventDefault();
        const s = src.selectionStart;
        src.setRangeText("\t", s, src.selectionEnd, "end");
        remember();
      } else if (e.key === "Enter" && e.ctrlKey) { e.preventDefault(); runMine(); }
    });
    $("prog-name").addEventListener("input", remember);
    $("prog-build").addEventListener("click", build);
    $("prog-run").addEventListener("click", runMine);
    $("prog-export").addEventListener("click", exportRom);
    $("prog-save").addEventListener("click", saveProject);
    $("prog-open").addEventListener("click", openDialog);
    $("open-close").addEventListener("click", () => $("open-dialog").close());
    $("prog-example").addEventListener("click", async () => {
      if (src.value.trim() && !confirm("Remplacer le programme en cours par l'exemple ?")) return;
      try { src.value = await loadExample(); $("prog-name").value = "etoiles"; remember(); build(); status("Exemple chargé : « Fuma et les étoiles »."); }
      catch (e) { status(e.message, true); }
    });
  }

  async function init() {
    document.documentElement.dataset.theme = local.get("theme", "dark");
    crt = new window.AetherCRT($("screen"), PALETTE);
    if (!local.get("crt", true)) { $("crt-fx").checked = false; Object.assign(crt.settings, { curve: 0, scan: 0, glow: 0 }); }
    $("volume").value = local.get("volume", 0.2);
    wire();
    drawBoard(); drawTray(); diagnose(); updatePowerButton(); showRegs();
    setMode(local.get("mode", "bench"));
    $("prog-name").value = local.get("name", "mon_jeu");
    const saved = local.get("source", "");
    if (saved) { src.value = saved; build(); }
    else {
      try { src.value = await loadExample(); $("prog-name").value = "etoiles"; build(); }
      catch (e) { status(e.message, true); }
    }
    paintGutter(S.built ? S.built.errors.map((e) => e.line) : []);
    if (!S.installed.size) select("power");
    requestAnimationFrame(loop);
  }
  init();
})();
