"use strict";
// Atelier circuits Æther, onglet « Microcontrôleurs » : éditeur d'assembleur, carte dessinée (LED, boutons, afficheur
// 7 segments ou écran LCD), exécution en temps réel, pas à pas, registres et diagnostic.
// Cœurs : mcu_avr.js et mcu_rp2040.js ; carte : mcu_board.js ; assembleurs : mcu_asm.js ; exemples : mcu_examples.js.
(function () {
  const $ = (id) => document.getElementById(id);
  const SVG = "http://www.w3.org/2000/svg";
  const { Board, BOARDS } = window.AetherMcuBoard;
  const ASM = window.AetherMcuAsm;
  const EX = window.AetherMcuExamples;
  const SEGS = [
    "8,4 36,4 32,9 12,9", "37,6 41,9 39,32 34,30 35,10", "39,38 41,61 37,64 33,60 34,40", "8,66 36,66 32,61 12,61",
    "3,61 5,38 10,40 9,60 6,64", "3,9 7,6 10,10 9,30 4,32", "8,35 12,31 32,31 36,35 32,39 12,39", "42,62 45,62 45,65 42,65",
  ];
  const store = {
    get(k, d) { try { const v = localStorage.getItem(`circuit.mcu.${k}`); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(`circuit.mcu.${k}`, JSON.stringify(v)); } catch (e) { /* stockage indisponible */ } },
  };
  const ui = { kind: "rp2040", module: "seg7", board: null, built: null, running: false, paused: false, started: false,
               els: null, last: 0, emu: 0, wall: 0, saveTimer: 0 };
  const src = () => $("mcu-source");
  const say = (text, bad) => { const s = $("status"); if (s) { s.textContent = text || ""; s.classList.toggle("err", Boolean(bad)); } };
  const el = (name, attrs, parent, text) => {
    const n = document.createElementNS(SVG, name);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
    if (text !== undefined) n.textContent = text;
    if (parent) parent.appendChild(n);
    return n;
  };
  const hex = (v, n) => (v >>> 0).toString(16).toUpperCase().padStart(n, "0");

  // ---------- carte ----------
  function drawBoard() {
    const svg = $("mcu-svg");
    svg.replaceChildren();
    const def = BOARDS[ui.kind];
    const avr = ui.kind === "avr";
    el("rect", { x: 8, y: 8, width: 384, height: 284, rx: 14, class: `pcb${avr ? " avr" : ""}` }, svg);
    for (const [x, y] of [[20, 20], [380, 20], [20, 280], [380, 280]]) el("circle", { cx: x, cy: y, r: 5, class: "chip" }, svg);
    el("text", { x: 24, y: 30, class: "silk big" }, svg, `ÆTHER · ${def.title.toUpperCase()}`);
    // connecteur USB et quartz
    el("rect", { x: 8, y: 118, width: 26, height: 40, rx: 3, class: "chip" }, svg);
    el("text", { x: 40, y: 142, class: "silk" }, svg, "USB");
    el("rect", { x: 70, y: 194, width: 34, height: 14, rx: 7, class: "chip" }, svg);
    el("text", { x: 72, y: 220, class: "silk" }, svg, avr ? "16 MHz" : "12 MHz");
    // microcontrôleur
    const chip = avr ? { x: 70, y: 92, w: 130, h: 46 } : { x: 84, y: 76, w: 84, h: 84 };
    const traces = el("g", {}, svg);
    el("rect", { x: chip.x, y: chip.y, width: chip.w, height: chip.h, rx: 4, class: "chip" }, svg);
    const pins = avr ? 14 : 10;
    for (let i = 0; i < pins; i++) {
      const t = (i + 0.5) / pins;
      el("rect", { x: chip.x + t * chip.w - 2, y: chip.y - 5, width: 4, height: 5, class: "pad" }, svg);
      el("rect", { x: chip.x + t * chip.w - 2, y: chip.y + chip.h, width: 4, height: 5, class: "pad" }, svg);
      if (!avr) {
        el("rect", { x: chip.x - 5, y: chip.y + t * chip.h - 2, width: 5, height: 4, class: "pad" }, svg);
        el("rect", { x: chip.x + chip.w, y: chip.y + t * chip.h - 2, width: 5, height: 4, class: "pad" }, svg);
      }
    }
    el("text", { x: chip.x + chip.w / 2, y: chip.y + chip.h / 2 - 2, class: "chip-text" }, svg, avr ? "ATmega328P" : "RP2040");
    el("text", { x: chip.x + chip.w / 2, y: chip.y + chip.h / 2 + 12, class: "chip-text" }, svg, avr ? "AVR 8 bits" : "Cortex-M0+");
    const ox = chip.x + chip.w, oy = chip.y + chip.h / 2;

    // LED
    const leds = def.leds.map((l, i) => {
      const x = 236 + i * 30, y = 52;
      const trace = el("path", { d: `M${ox},${oy - 14 + i * 3} H${200 + i * 6} V${y + 22} H${x} V${y + 9}`, class: "trace" }, traces);
      const led = el("circle", { cx: x, cy: y, r: 8, class: `led c-${l.color}` }, svg);
      el("text", { x, y: y + 34, class: "silk mid" }, svg, l.name.replace(" (LED)", "").replace(" (L)", ""));
      if (/\((LED|L)\)/.test(l.name)) el("text", { x, y: y - 14, class: "silk mid" }, svg, avr ? "L" : "LED");
      return { led, trace, pin: l.pin };
    });
    // boutons
    const buttons = def.buttons.map((b, i) => {
      const x = 40 + i * 44, y = 252;
      el("path", { d: `M${chip.x + 12 + i * 10},${chip.y + chip.h} V${y - 30} H${x} V${y - 14}`, class: "trace" }, traces);
      const g = el("g", { "data-button": i }, svg);
      el("rect", { x: x - 14, y: y - 14, width: 28, height: 28, rx: 4, class: "chip" }, g);
      const cap = el("circle", { cx: x, cy: y, r: 9, class: "btn" }, g);
      el("text", { x, y: y + 3.5, class: "btn-key" }, g, b.key);
      el("text", { x, y: y + 26, class: "silk mid" }, svg, b.name);
      return cap;
    });
    // module
    let segs = null, lcd = null;
    const modTraces = [];
    if (ui.module === "seg7") {
      el("rect", { x: 262, y: 120, width: 100, height: 126, rx: 6, class: "module" }, svg);
      const g = el("g", { transform: "translate(278,132) scale(1.55)" }, svg);
      segs = SEGS.map((pts) => el("polygon", { points: pts, class: "seg" }, g));
      def.seg7.forEach((p, i) => modTraces.push([p, el("path", { d: `M${ox},${oy + 4 + i * 2} H${230 + i * 3} V${130 + i * 13} H262`, class: "trace" }, traces)]));
      el("text", { x: 312, y: 260, class: "silk mid" }, svg, `${def.pinName(def.seg7[0])} à ${def.pinName(def.seg7[7])}`);
    } else {
      el("rect", { x: 214, y: 122, width: 172, height: 104, rx: 6, class: "module" }, svg);
      el("rect", { x: 224, y: 146, width: 152, height: 56, rx: 3, class: "lcd" }, svg);
      lcd = [el("text", { x: 230, y: 168, class: "lcd-text", textLength: 140, lengthAdjust: "spacingAndGlyphs" }, svg, ""),
             el("text", { x: 230, y: 192, class: "lcd-text", textLength: 140, lengthAdjust: "spacingAndGlyphs" }, svg, "")];
      el("text", { x: 300, y: 138, class: "silk mid" }, svg, "LCD 16 × 2 · HD44780");
      const l = def.lcd;
      el("text", { x: 300, y: 240, class: "silk mid" }, svg, `RS ${def.pinName(l.rs)} · E ${def.pinName(l.e)} · D ${def.pinName(l.d[0])}–${def.pinName(l.d[3])}`);
      [...l.d, l.rs, l.e].forEach((p, i) => modTraces.push([p, el("path", { d: `M${ox},${oy + 4 + i * 2} H${206 + i * 1} V${200 + i * 3} H214`, class: "trace" }, traces)]));
    }
    ui.els = { leds, buttons, segs, lcd, modTraces };
  }
  function paint(bright) {
    const b = ui.board;
    if (!b || !ui.els) return;
    const lum = bright || b.brightness();
    for (const item of ui.els.leds) {
      const v = lum.get(item.pin) || 0;
      item.led.classList.toggle("on", v > 0.04);
      item.led.setAttribute("opacity", v > 0.04 ? (0.35 + 0.65 * v).toFixed(2) : "1");
      item.trace.classList.toggle("on", b.lit(item.pin) === 1);
    }
    ui.els.buttons.forEach((cap, i) => cap.classList.toggle("on", b.pressed.has(i)));
    if (ui.els.segs) {
      BOARDS[ui.kind].seg7.forEach((p, i) => {
        const v = lum.get(p) || 0;
        ui.els.segs[i].classList.toggle("on", v > 0.04);
        ui.els.segs[i].setAttribute("opacity", v > 0.04 ? (0.35 + 0.65 * v).toFixed(2) : "1");
      });
    }
    if (ui.els.lcd) {
      const rows = b.lcd.rows();
      ui.els.lcd.forEach((t, i) => { t.textContent = (rows[i] || "").padEnd(16, " ").replace(/ /g, " "); });
    }
    for (const [p, path] of ui.els.modTraces) path.classList.toggle("on", b.level(p) === 1);
  }

  // ---------- éditeur ----------
  function gutter(bad, here) {
    const lines = src().value.split("\n").length;
    const g = $("mcu-gutter");
    g.replaceChildren();
    const badSet = new Set(bad || []);
    for (let i = 1; i <= lines; i++) {
      const s = document.createElement("span");
      s.textContent = `${i}\n`;
      if (badSet.has(i)) s.className = "bad";
      if (here === i) s.className = "here";
      g.appendChild(s);
    }
    g.scrollTop = src().scrollTop;
  }
  function gotoLine(line) {
    const ta = src();
    const lines = ta.value.split("\n");
    let pos = 0;
    for (let i = 0; i < line - 1 && i < lines.length; i++) pos += lines[i].length + 1;
    ta.focus();
    ta.setSelectionRange(pos, pos + (lines[line - 1] || "").length);
    const lh = parseFloat(getComputedStyle(ta).lineHeight) || 19;
    ta.scrollTop = Math.max(0, (line - 4) * lh);
  }
  function build() {
    const built = ui.kind === "avr" ? ASM.avr(src().value) : ASM.thumb(src().value);
    const box = $("mcu-errors");
    box.replaceChildren();
    if (built.ok) {
      const s = document.createElement("span");
      s.className = "ok";
      s.textContent = `Assemblé sans erreur : ${built.image.length} octets.`;
      box.appendChild(s);
    } else {
      for (const e of built.errors.slice(0, 40)) {
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = `ligne ${e.line} : ${e.message}`;
        b.addEventListener("click", () => gotoLine(e.line));
        box.appendChild(b);
      }
    }
    gutter(built.errors.map((e) => e.line));
    ui.built = built;
    return built;
  }
  function remember() {
    clearTimeout(ui.saveTimer);
    ui.saveTimer = setTimeout(() => store.set(`${ui.kind}.source`, src().value), 400);
  }

  // ---------- exécution ----------
  function newBoard() {
    ui.board = new Board(ui.kind, ui.module);
    drawBoard();
    paint();
  }
  function run() {
    const built = build();
    if (!built.ok) { say("Le programme a des erreurs : corrige-les (clique une erreur pour aller à sa ligne).", true); return; }
    ui.board.load(built);
    ui.running = true; ui.paused = false;
    ui.emu = 0; ui.wall = 0;
    updateButtons();
    say(`Programme chargé dans la ${BOARDS[ui.kind].title.toLowerCase()} (${built.image.length} octets).`);
  }
  function updateButtons() {
    $("mcu-pause").textContent = ui.paused ? "▶ Reprendre" : "⏸ Pause";
    $("mcu-pause").disabled = !ui.running;
    $("mcu-step").disabled = !ui.running;
    $("mcu-reset").disabled = !ui.running;
    $("mcu-run").textContent = ui.running ? "↻ Relancer" : "▶ Lancer";
  }
  function frame(now) {
    const dt = Math.min(50, now - (ui.last || now));
    ui.last = now;
    if (ui.running && !ui.paused && visible() && !ui.board.cpu.halted) {
      // On simule autant de temps que la page en a vu passer, dans un budget de 12 ms de calcul.
      const t0 = performance.now();
      let done = 0;
      let bright = null;
      while (done < dt && performance.now() - t0 < 12) {
        const slice = Math.min(4, dt - done);
        bright = ui.board.run(slice);
        done += slice;
      }
      ui.emu += done; ui.wall += dt;
      if (ui.wall > 1000) { ui.emu *= 0.5; ui.wall *= 0.5; }
      $("mcu-speed").textContent = `vitesse : ${Math.round(100 * ui.emu / Math.max(1, ui.wall))} % du temps réel`;
      paint(bright);
      showState(false);
    }
    requestAnimationFrame(frame);
  }
  function showState(detail) {
    const b = ui.board, c = b.cpu;
    let text;
    if (ui.kind === "avr") {
      const r = c.regs();
      const row = (from) => r.r.slice(from, from + 8).map((v, i) => `r${String(from + i).padEnd(2)}=${hex(v, 2)}`).join(" ");
      text = `PC ${hex(r.pc * 2, 4)} (mot ${hex(r.pc, 4)})  SP ${hex(r.sp, 4)}  SREG ${r.sreg}\n${row(0)}\n${row(8)}\n${row(16)}\n${row(24)}\n`
           + `PORTB ${hex(c.data[0x25], 2)} DDRB ${hex(c.data[0x24], 2)}  PORTC ${hex(c.data[0x28], 2)} DDRC ${hex(c.data[0x27], 2)}  PORTD ${hex(c.data[0x2b], 2)} DDRD ${hex(c.data[0x2a], 2)}\n`
           + `TCNT0 ${hex(c.data[0x46], 2)}  ${(r.cycles / c.hz * 1000).toFixed(1)} ms`;
    } else {
      const r = c.regs();
      const name = (i) => (i === 13 ? "sp " : i === 14 ? "lr " : i === 15 ? "pc " : `r${String(i).padEnd(2)}`);
      const rows = [0, 4, 8, 12].map((s) => r.r.slice(s, s + 4).map((v, i) => `${name(s + i)}=${hex(v, 8)}`).join(" "));
      text = `${rows.join("\n")}\nNZCV ${r.flags}  OUT ${hex(c.out, 8)}  OE ${hex(c.oe, 8)}\nIN  ${hex(c.pinLevels(), 8)}  ${(r.us / 1000).toFixed(1)} ms`;
    }
    $("mcu-regs").textContent = text;
    const line = b.line();
    const lines = src().value.split("\n");
    $("mcu-line").textContent = line ? `ligne ${line} : ${(lines[line - 1] || "").trim()}` : "";
    if (detail || ui.paused) gutter(ui.built ? ui.built.errors.map((e) => e.line) : [], line);
    diagnose();
  }
  function diagnose() {
    const b = ui.board, c = b.cpu, box = $("mcu-diag");
    const notes = [];
    if (c.halted) notes.push(["warn", `Arrêt : ${c.halted}.`]);
    if (c.sleeping === "boucle") notes.push(["good", "Le programme tourne en boucle sur place : il attend sans rien faire."]);
    if (ui.kind === "avr") {
      for (const l of BOARDS.avr.leds) {
        const port = l.pin[0], bit = 1 << Number(l.pin[1]);
        const base = { B: 0x23, C: 0x26, D: 0x29 }[port];
        if (!(c.data[base + 1] & bit) && c.data[base + 2] & bit) notes.push(["warn", `${l.name} : PORT${port} = 1 mais DDR${port} = 0 ; la broche est une entrée (tirage haut), pas une sortie.`]);
      }
      const floating = c.floating("C") & 0x0f;
      if (ui.running && floating && b.pressed.size) notes.push(["warn", "Boutons PC0 à PC3 : sans tirage haut (PORTC = 1), une entrée « flotte » et se lit au hasard."]);
    } else {
      for (const n of c.notes || []) notes.push(["warn", n]);
      const sio = c.sioPins();
      for (const l of BOARDS.rp2040.leds) {
        const bit = 1 << l.pin;
        if ((c.out & bit) && !(sio & bit)) notes.push(["warn", `${l.name} : sortie à 1 dans le SIO, mais la broche n'a pas la fonction 5 (SIO) dans GPIO${l.pin}_CTRL.`]);
        else if ((c.out & bit) && !(c.oe & bit)) notes.push(["warn", `${l.name} : sortie à 1, mais la sortie n'est pas activée (GPIO_OE).`]);
      }
    }
    if (!notes.length) notes.push(["muted", ui.running ? "Rien à signaler." : "Écris ou choisis un programme, puis « Lancer »."]);
    const key = JSON.stringify(notes);
    if (box.dataset.key === key) return;
    box.dataset.key = key;
    box.replaceChildren();
    for (const [cls, text] of notes) { const p = document.createElement("p"); p.className = cls; p.textContent = text; box.appendChild(p); }
  }
  const visible = () => !$("mcu-view").hidden;

  // ---------- aide-mémoire ----------
  function cheat() {
    const box = $("mcu-cheat");
    box.replaceChildren();
    const p = (html) => { const n = document.createElement("p"); n.textContent = html; box.appendChild(n); };
    if (ui.kind === "avr") {
      p("Broches : LED sur PB0 à PB3 et PB5 (L). Boutons 1 à 4 sur PC0 à PC3, reliés à la masse (appuyé = 0) : active le tirage haut avec PORTC. Module sur le port D (7 segments : PD0 = a … PD7 = point ; LCD : RS = PD2, E = PD3, D4 à D7 = PD4 à PD7).");
      p("Ports : DDRx = sens (1 = sortie), PORTx = sortie ou tirage haut, PINx = lecture des broches (écrire 1 dans PINx inverse la sortie). Adresses d'entrée-sortie pour in/out : PINB 0x03, DDRB 0x04, PORTB 0x05, PINC 0x06, DDRC 0x07, PORTC 0x08, PIND 0x09, DDRD 0x0A, PORTD 0x0B.");
      p("Minuterie 0 : TCCR0B (pré-diviseur : CS00 = /1, CS01 = /8, CS01|CS00 = /64, CS02 = /256, CS02|CS00 = /1024), TCNT0, OCR0A, TCCR0A (WGM01 = mode CTC), TIMSK0 (TOIE0, OCIE0A ; avec sts), TIFR0. Vecteurs : OVF0addr (0x20), OC0Aaddr (0x1C) ; sei pour autoriser.");
      p("Instructions : ldi, mov, movw, add, adc, sub, sbc, subi, sbci, and, andi, or, ori, eor, com, neg, inc, dec, lsl, lsr, asr, rol, ror, swap, mul, cp, cpc, cpi, cpse, tst, clr, ser, adiw, sbiw, in, out, sbi, cbi, sbic, sbis, sbrc, sbrs, lds, sts, ld, st, ldd, std (X, Y, Z, +, -), lpm, push, pop, rjmp, rcall, jmp, call, ijmp, icall, ret, reti, breq, brne, brcs, brcc, brlo, brsh, brmi, brpl, brlt, brge…, sei, cli, sec, clc…, bst, bld, nop, sleep.");
      p("Directives : .org, .equ NOM = valeur, .def nom = r16, .db, .dw ; low(), high() ; une étiquette de code compte en mots : pour lpm, prends étiquette * 2.");
    } else {
      p("Broches : LED sur GP0 à GP3 et GP25 (LED de la carte). Boutons 1 à 4 sur GP10 à GP13, reliés au 3,3 V (appuyé = 1, relâché = 0 grâce au tirage bas). Module sur GP16 à GP23 (7 segments : GP16 = a … GP23 = point ; LCD : D4 à D7 = GP16 à GP19, RS = GP20, E = GP21).");
      p("Mise en route : libérer IO_BANK0, PADS_BANK0 et TIMER (RESETS_BASE + REG_ALIAS_CLR), attendre RESET_DONE, choisir la fonction 5 (SIO) dans IO_BANK0_BASE + 8 × n + 4, activer la sortie avec GPIO_OE_SET.");
      p("SIO (SIO_BASE = 0xD0000000) : GPIO_IN 0x04, GPIO_OUT 0x10, GPIO_OUT_SET 0x14, GPIO_OUT_CLR 0x18, GPIO_OUT_XOR 0x1C, GPIO_OE 0x20, GPIO_OE_SET 0x24, GPIO_OE_CLR 0x28. TIMER (TIMER_BASE) : TIMERAWL 0x28 compte les microsecondes.");
      p("Instructions Thumb : movs, mov, adds, subs, adcs, sbcs, rsbs/negs, muls, ands, orrs, eors, bics, mvns, lsls, lsrs, asrs, rors, cmp, cmn, tst, ldr, ldrb, ldrh, ldrsb, ldrsh, str, strb, strh, ldm, stm, push, pop, adr, b, b<cond> (beq, bne, bcs/bhs, bcc/blo, bmi, bpl, bhi, bls, bge, blt, bgt, ble), bl, bx, blx, sxtb, sxth, uxtb, uxth, rev, nop, wfi, bkpt.");
      p("Directives : .equ, NOM = valeur, .word, .hword, .byte, .ascii, .asciz, .align, .space, .ltorg ; « ldr r0, =valeur » range la constante dans une réserve placée après le code. Le programme démarre à l'étiquette main (ou _start), chargé en SRAM à 0x20000000.");
    }
  }

  // ---------- choix de carte, de module, d'exemple ----------
  function fillExamples() {
    const pick = $("mcu-example");
    pick.replaceChildren();
    const first = document.createElement("option"); first.value = ""; first.textContent = "Exemples…"; pick.appendChild(first);
    for (const [k, ex] of Object.entries(EX[ui.kind])) { const o = document.createElement("option"); o.value = k; o.textContent = ex.title; pick.appendChild(o); }
  }
  function useKind(kind, keepSource) {
    ui.kind = kind;
    store.set("board", kind);
    $("mcu-board").value = kind;
    if (!keepSource) {
      const saved = store.get(`${kind}.source`, "");
      src().value = saved || EX[kind].clignotant.source;
    }
    ui.running = false; ui.paused = false;
    newBoard();
    fillExamples();
    cheat();
    build();
    updateButtons();
    showState(true);
  }
  function useModule(m) {
    ui.module = m;
    store.set("module", m);
    $("mcu-module").value = m;
    if (ui.board) { ui.board.setModule(m); drawBoard(); paint(); }
  }

  function start() {
    if (ui.started) return;
    ui.started = true;
    ui.module = store.get("module", "seg7");
    $("mcu-module").value = ui.module;
    useKind(store.get("board", "rp2040"));
    $("mcu-board").addEventListener("change", (e) => { useKind(e.target.value); say(`${BOARDS[ui.kind].title} : ${BOARDS[ui.kind].cpu}.`); });
    $("mcu-module").addEventListener("change", (e) => useModule(e.target.value));
    $("mcu-example").addEventListener("change", (e) => {
      const ex = EX[ui.kind][e.target.value];
      e.target.value = "";
      if (!ex) return;
      if (src().value.trim() && src().value !== ex.source && !confirm("Remplacer le programme en cours par l'exemple ?")) return;
      src().value = ex.source;
      remember();
      useModule(ex.module);
      run();
      say(`Exemple lancé : ${ex.title}.`);
    });
    $("mcu-build").addEventListener("click", () => { const b = build(); say(b.ok ? "Assemblé sans erreur." : `${b.errors.length} erreur(s).`, !b.ok); });
    $("mcu-run").addEventListener("click", run);
    $("mcu-pause").addEventListener("click", () => { ui.paused = !ui.paused; updateButtons(); showState(true); });
    $("mcu-step").addEventListener("click", () => {
      if (!ui.running) return;
      ui.paused = true;
      if (ui.board.cpu.sleeping === "boucle") ui.board.cpu.sleeping = false;
      ui.board.cpu.step();
      ui.board.sync();
      updateButtons(); paint(); showState(true);
    });
    $("mcu-reset").addEventListener("click", () => { ui.board.reset(); paint(); showState(true); say("RESET."); });
    const ta = src();
    ta.addEventListener("input", () => { gutter([]); remember(); });
    ta.addEventListener("scroll", () => { $("mcu-gutter").scrollTop = ta.scrollTop; });
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Tab") { e.preventDefault(); ta.setRangeText("\t", ta.selectionStart, ta.selectionEnd, "end"); remember(); }
      else if (e.key === "Enter" && e.ctrlKey) { e.preventDefault(); run(); }
    });
    const svg = $("mcu-svg");
    const release = () => { for (const i of [...ui.board.pressed]) ui.board.press(i, false); paint(); };
    svg.addEventListener("pointerdown", (e) => {
      const g = e.target.closest && e.target.closest("[data-button]");
      if (!g) return;
      e.preventDefault();
      svg.setPointerCapture(e.pointerId);
      ui.board.press(Number(g.dataset.button), true);
      paint();
    });
    svg.addEventListener("pointerup", release);
    svg.addEventListener("pointercancel", release);
    const keys = (e, down) => {
      if (!visible() || (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName))) return;
      const k = ["Digit1", "Digit2", "Digit3", "Digit4", "Numpad1", "Numpad2", "Numpad3", "Numpad4"].indexOf(e.code);
      if (k < 0) return;
      const i = k % 4;
      e.preventDefault();
      if (down === ui.board.pressed.has(i)) return;
      ui.board.press(i, down);
      paint();
    };
    window.addEventListener("keydown", (e) => keys(e, true));
    window.addEventListener("keyup", (e) => keys(e, false));
    requestAnimationFrame(frame);
  }
  document.addEventListener("circuit-mode", (e) => { if (e.detail === "mcu") start(); });
  // La page a pu afficher cet onglet avant le chargement de ce script (dernier onglet mémorisé).
  if (!$("mcu-view").hidden) { start(); requestAnimationFrame(() => document.dispatchEvent(new CustomEvent("circuit-mode", { detail: "mcu" }))); }
  window.AetherMcuApp = { get board() { return ui.board; }, get built() { return ui.built; }, run, build, start, useKind, useModule,
                          frame: (ms) => { const b = ui.board.run(ms); paint(b); showState(false); return b; } };
})();
