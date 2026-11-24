"use strict";
// Cartes à microcontrôleur de l'Atelier circuits Æther : ce qui est soudé autour du microcontrôleur.
//   - Carte RP2040 : LED sur GP0 à GP3 et GP25 (LED de la carte), boutons sur GP10 à GP13 (reliés au 3,3 V : appuyé = 1,
//     relâché = 0 grâce au tirage bas des broches) ; module sur GP16 à GP23.
//   - Carte AVR 8 bits : LED sur PB0 à PB3 et PB5 (LED « L » de la carte), boutons sur PC0 à PC3 (reliés à la masse :
//     appuyé = 0 ; il faut activer le tirage haut en écrivant 1 dans PORTC) ; module sur le port D.
// Module au choix : afficheur 7 segments (a à g et point, cathode commune : 1 = allumé) ou écran LCD 16 × 2 à
// contrôleur HD44780 en mode 4 bits (RS, E, D4 à D7 ; R/W relié à la masse).
// La luminosité des LED et des segments est la part du temps où la broche est restée à 1 pendant l'image : une
// modulation de largeur d'impulsion (MLI) ou un affichage multiplexé se voient donc comme sur une vraie carte.
(function (root) {
  const { AVR } = root.AetherAVR;
  const { RP2040 } = root.AetherRP2040;

  // ---------- écran LCD 16 × 2 (HD44780) ----------
  class LCD {
    constructor() { this.reset(); }
    reset() {
      this.ddram = new Uint8Array(0x68).fill(0x20);
      this.cgram = new Uint8Array(64);
      this.addr = 0; this.cg = false; this.mode8 = true; this.half = null; this.lastE = 0;
      this.on = false; this.cursor = false; this.blink = false; this.inc = true; this.shift = 0; this.lines = 1;
      this.commands = 0;
    }
    pins(rs, e, nibble) {
      if (this.lastE && !e) this.latch(rs, nibble & 15);
      this.lastE = e;
    }
    latch(rs, nib) {
      if (this.mode8) { this.exec(rs, nib << 4); return; }
      if (this.half === null) { this.half = nib; return; }
      const v = (this.half << 4) | nib;
      this.half = null;
      this.exec(rs, v);
    }
    step() {
      if (this.cg) { this.addr = (this.addr + (this.inc ? 1 : -1)) & 63; return; }
      let a = this.addr + (this.inc ? 1 : -1);
      if (a === 0x28) a = 0x40; else if (a === 0x68) a = 0; else if (a === 0x3f) a = 0x27; else if (a < 0) a = 0x67;
      this.addr = a;
    }
    exec(rs, v) {
      if (rs) {
        if (this.cg) this.cgram[this.addr & 63] = v & 0x1f; else this.ddram[this.addr] = v;
        this.step();
        return;
      }
      this.commands++;
      if (v & 0x80) { this.cg = false; let a = v & 0x7f; if (a >= 0x28 && a < 0x40) a = 0x40; if (a >= 0x68) a = 0; this.addr = a; }
      else if (v & 0x40) { this.cg = true; this.addr = v & 0x3f; }
      else if (v & 0x20) { this.mode8 = (v & 0x10) !== 0; this.lines = v & 8 ? 2 : 1; this.half = null; }
      else if (v & 0x10) { if (v & 8) this.shift = (this.shift + (v & 4 ? -1 : 1) + 40) % 40; else this.step(); }
      else if (v & 8) { this.on = (v & 4) !== 0; this.cursor = (v & 2) !== 0; this.blink = (v & 1) !== 0; }
      else if (v & 4) this.inc = (v & 2) !== 0;
      else if (v & 2) { this.addr = 0; this.shift = 0; this.cg = false; }
      else if (v & 1) { this.ddram.fill(0x20); this.addr = 0; this.shift = 0; this.inc = true; this.cg = false; }
    }
    char(code) {
      if (code < 8) return "▒";                 // caractère personnalisé (CGRAM)
      if (code === 0xdf) return "°";
      if (code === 0x7e) return "→";
      if (code === 0x7f) return "←";
      if (code === 0xff) return "█";
      if (code >= 0x20 && code < 0x7e) return code === 0x5c ? "¥" : String.fromCharCode(code);
      return " ";
    }
    rows() {
      if (!this.on) return ["", ""];
      const row = (base) => Array.from({ length: 16 }, (_, i) => this.char(this.ddram[base + ((i + this.shift) % 40)])).join("");
      return [row(0), this.lines === 2 ? row(0x40) : ""];
    }
  }

  // ---------- les deux cartes ----------
  const range = (a, n) => Array.from({ length: n }, (_, i) => a + i);
  const BOARDS = {
    rp2040: {
      title: "Carte RP2040", cpu: "RP2040 · Cortex-M0+ · 125 MHz", short: "RP2040", lang: "Thumb",
      leds: [{ pin: 0, color: "rouge", name: "GP0" }, { pin: 1, color: "ambre", name: "GP1" }, { pin: 2, color: "vert", name: "GP2" },
             { pin: 3, color: "bleu", name: "GP3" }, { pin: 25, color: "vert", name: "GP25 (LED)" }],
      buttons: range(10, 4).map((p, i) => ({ pin: p, name: `GP${p}`, key: String(i + 1) })),
      seg7: range(16, 8),
      lcd: { d: [16, 17, 18, 19], rs: 20, e: 21 },
      pinName: (p) => `GP${p}`,
    },
    avr: {
      title: "Carte AVR 8 bits", cpu: "ATmega328P · AVR · 16 MHz", short: "AVR", lang: "AVR",
      leds: [{ pin: "B0", color: "rouge", name: "PB0" }, { pin: "B1", color: "ambre", name: "PB1" }, { pin: "B2", color: "vert", name: "PB2" },
             { pin: "B3", color: "bleu", name: "PB3" }, { pin: "B5", color: "ambre", name: "PB5 (L)" }],
      buttons: range(0, 4).map((i) => ({ pin: `C${i}`, name: `PC${i}`, key: String(i + 1) })),
      seg7: range(0, 8).map((i) => `D${i}`),
      lcd: { d: ["D4", "D5", "D6", "D7"], rs: "D2", e: "D3" },
      pinName: (p) => `P${p}`,
    },
  };

  class Board {
    constructor(kind, moduleKind) {
      this.kind = kind;
      this.def = BOARDS[kind];
      this.module = moduleKind || "seg7";
      this.cpu = kind === "avr" ? new AVR() : new RP2040();
      this.lcd = new LCD();
      this.pressed = new Set();
      this.watch = [...this.def.leds.map((l) => l.pin), ...this.def.seg7];
      this.levels = new Map(); this.since = new Map(); this.onTime = new Map();
      this.frameStart = 0;
      this.cpu.onPort = () => this.sync();
      this.sync();
    }
    // Niveau d'une broche et « est-elle pilotée en sortie ? »
    level(pin) {
      if (this.kind === "avr") return (this.cpu.pinLevels(pin[0]) >> Number(pin[1])) & 1;
      return (this.cpu.pinLevels() >>> pin) & 1;
    }
    driven(pin) {
      if (this.kind === "avr") return (this.cpu.data[root.AetherAVR.PORTS[pin[0]] + 1] >> Number(pin[1])) & 1;
      return (this.cpu.driven() >>> pin) & 1;
    }
    lit(pin) { return this.level(pin) & this.driven(pin); }
    sync() {
      if (!this.levels) return;
      const now = this.cpu.cycles;
      for (const pin of this.watch) {
        const v = this.lit(pin), was = this.levels.get(pin) || 0;
        if (v !== was) {
          if (was) this.onTime.set(pin, (this.onTime.get(pin) || 0) + now - (this.since.get(pin) ?? now));
          this.levels.set(pin, v);
          this.since.set(pin, now);
        }
      }
      if (this.module === "lcd") {
        const l = this.def.lcd;
        const nib = l.d.reduce((acc, p, i) => acc | (this.level(p) << i), 0);
        this.lcd.pins(this.level(l.rs), this.level(l.e), nib);
      }
    }
    press(index, down) {
      const b = this.def.buttons[index];
      if (!b) return;
      if (down) this.pressed.add(index); else this.pressed.delete(index);
      if (this.kind === "avr") {
        const port = b.pin[0], bit = 1 << Number(b.pin[1]);
        this.cpu.extLow[port] = down ? this.cpu.extLow[port] | bit : this.cpu.extLow[port] & ~bit;
      } else {
        this.cpu.ext.high = down ? (this.cpu.ext.high | (1 << b.pin)) >>> 0 : (this.cpu.ext.high & ~(1 << b.pin)) >>> 0;
      }
      if (this.cpu.sleeping === "boucle") this.cpu.sleeping = false;
      this.sync();
    }
    setModule(kind) { this.module = kind; this.lcd.reset(); this.sync(); }
    load(built) {
      if (this.kind === "avr") this.cpu.load(built.image); else this.cpu.load(built.image, built.entry);
      this.lines = built.lines;
      this.lcd.reset();
      this.reset();
    }
    reset() {
      this.levels = null;
      this.cpu.reset();
      this.lcd.reset();
      this.levels = new Map(); this.since = new Map(); this.onTime = new Map();
      this.frameStart = this.cpu.cycles;
      for (const i of this.pressed) this.press(i, true);
      this.sync();
    }
    // Fait tourner le microcontrôleur pendant `ms` millisecondes de son temps à lui, puis mesure la luminosité.
    run(ms) {
      this.frameStart = this.cpu.cycles;
      this.onTime = new Map();
      for (const pin of this.watch) this.since.set(pin, this.frameStart);
      this.cpu.run(Math.round(this.cpu.hz * ms / 1000));
      return this.brightness();
    }
    brightness() {
      const now = this.cpu.cycles, span = Math.max(1, now - this.frameStart);
      const out = new Map();
      for (const pin of this.watch) {
        let on = this.onTime.get(pin) || 0;
        if (this.levels.get(pin)) on += now - Math.max(this.frameStart, this.since.get(pin) ?? this.frameStart);
        out.set(pin, Math.min(1, on / span));
      }
      return out;
    }
    pc() { return this.kind === "avr" ? this.cpu.pc : this.cpu.r[15]; }
    line() { return this.lines ? this.lines.get(this.pc()) : undefined; }
  }

  root.AetherMcuBoard = { Board, BOARDS, LCD };
})(typeof window !== "undefined" ? window : globalThis);
