"use strict";
// Processeur de la console 16 bits de l'atelier (« Japon grise 16 bits 1990 ») : un 65C816, le descendant 16 bits
// du 6502. Il démarre en mode « émulation » (un 6502 : registres 8 bits, pile en page 1) et passe en mode natif
// (XCE) : accumulateur et index de 8 ou 16 bits (drapeaux M et X), 16 Mo d'adresses (banques de 64 Ko), page
// directe déplaçable (D), pile n'importe où en banque 0.
//
// Le bus (`read`, `write`, `io`) compte lui-même le temps de chaque accès : 6, 8 ou 12 cycles de l'horloge maître
// selon la zone, comme sur la vraie carte. `io()` est un cycle interne sans accès mémoire.
(function (root) {
  const N = 0x80, V = 0x40, M = 0x20, X = 0x10, D = 0x08, I = 0x04, Z = 0x02, C = 0x01;

  // ---------- table des instructions : [mnémonique, mode d'adressage] ----------
  // Modes : imp acc imm (largeur M) immx (largeur X) imm8 dp dpx dpy dpi dpil dpix dpiy dpily sr sriy abs abx aby
  //         abl ablx rel rell bm ind indx indl
  const OPS = new Array(256);
  const ALU = ["ORA", "AND", "EOR", "ADC", "STA", "LDA", "CMP", "SBC"];
  const ALU_MODES = { 0x01: "dpix", 0x03: "sr", 0x05: "dp", 0x07: "dpil", 0x09: "imm", 0x0d: "abs", 0x0f: "abl",
                      0x11: "dpiy", 0x12: "dpi", 0x13: "sriy", 0x15: "dpx", 0x17: "dpily", 0x19: "aby", 0x1d: "abx",
                      0x1f: "ablx" };
  ALU.forEach((name, i) => { for (const off in ALU_MODES) OPS[i * 0x20 + Number(off)] = [name, ALU_MODES[off]]; });
  OPS[0x89] = ["BIT", "imm"];
  ["ASL", "ROL", "LSR", "ROR"].forEach((name, i) => {
    const b = i * 0x20;
    OPS[b + 0x06] = [name, "dp"]; OPS[b + 0x0a] = [name, "acc"]; OPS[b + 0x0e] = [name, "abs"];
    OPS[b + 0x16] = [name, "dpx"]; OPS[b + 0x1e] = [name, "abx"];
  });
  const more = {
    0x00: ["BRK", "imm8"], 0x02: ["COP", "imm8"], 0x04: ["TSB", "dp"], 0x08: ["PHP", "imp"], 0x0b: ["PHD", "imp"],
    0x0c: ["TSB", "abs"], 0x10: ["BPL", "rel"], 0x14: ["TRB", "dp"], 0x18: ["CLC", "imp"], 0x1a: ["INC", "acc"],
    0x1b: ["TCS", "imp"], 0x1c: ["TRB", "abs"], 0x20: ["JSR", "abs"], 0x22: ["JSL", "abl"], 0x24: ["BIT", "dp"],
    0x28: ["PLP", "imp"], 0x2b: ["PLD", "imp"], 0x2c: ["BIT", "abs"], 0x30: ["BMI", "rel"], 0x34: ["BIT", "dpx"],
    0x38: ["SEC", "imp"], 0x3a: ["DEC", "acc"], 0x3b: ["TSC", "imp"], 0x3c: ["BIT", "abx"], 0x40: ["RTI", "imp"],
    0x42: ["WDM", "imm8"], 0x44: ["MVP", "bm"], 0x48: ["PHA", "imp"], 0x4b: ["PHK", "imp"], 0x4c: ["JMP", "abs"],
    0x50: ["BVC", "rel"], 0x54: ["MVN", "bm"], 0x58: ["CLI", "imp"], 0x5a: ["PHY", "imp"], 0x5b: ["TCD", "imp"],
    0x5c: ["JML", "abl"], 0x60: ["RTS", "imp"], 0x62: ["PER", "rell"], 0x64: ["STZ", "dp"], 0x68: ["PLA", "imp"],
    0x6b: ["RTL", "imp"], 0x6c: ["JMP", "ind"], 0x70: ["BVS", "rel"], 0x74: ["STZ", "dpx"], 0x78: ["SEI", "imp"],
    0x7a: ["PLY", "imp"], 0x7b: ["TDC", "imp"], 0x7c: ["JMP", "indx"], 0x80: ["BRA", "rel"], 0x82: ["BRL", "rell"],
    0x84: ["STY", "dp"], 0x86: ["STX", "dp"], 0x88: ["DEY", "imp"], 0x8a: ["TXA", "imp"], 0x8b: ["PHB", "imp"],
    0x8c: ["STY", "abs"], 0x8e: ["STX", "abs"], 0x90: ["BCC", "rel"], 0x94: ["STY", "dpx"], 0x96: ["STX", "dpy"],
    0x98: ["TYA", "imp"], 0x9a: ["TXS", "imp"], 0x9b: ["TXY", "imp"], 0x9c: ["STZ", "abs"], 0x9e: ["STZ", "abx"],
    0xa0: ["LDY", "immx"], 0xa2: ["LDX", "immx"], 0xa4: ["LDY", "dp"], 0xa6: ["LDX", "dp"], 0xa8: ["TAY", "imp"],
    0xaa: ["TAX", "imp"], 0xab: ["PLB", "imp"], 0xac: ["LDY", "abs"], 0xae: ["LDX", "abs"], 0xb0: ["BCS", "rel"],
    0xb4: ["LDY", "dpx"], 0xb6: ["LDX", "dpy"], 0xb8: ["CLV", "imp"], 0xba: ["TSX", "imp"], 0xbb: ["TYX", "imp"],
    0xbc: ["LDY", "abx"], 0xbe: ["LDX", "aby"], 0xc0: ["CPY", "immx"], 0xc2: ["REP", "imm8"], 0xc4: ["CPY", "dp"],
    0xc6: ["DEC", "dp"], 0xc8: ["INY", "imp"], 0xca: ["DEX", "imp"], 0xcb: ["WAI", "imp"], 0xcc: ["CPY", "abs"],
    0xce: ["DEC", "abs"], 0xd0: ["BNE", "rel"], 0xd4: ["PEI", "dpi"], 0xd6: ["DEC", "dpx"], 0xd8: ["CLD", "imp"],
    0xda: ["PHX", "imp"], 0xdb: ["STP", "imp"], 0xdc: ["JML", "indl"], 0xde: ["DEC", "abx"], 0xe0: ["CPX", "immx"],
    0xe2: ["SEP", "imm8"], 0xe4: ["CPX", "dp"], 0xe6: ["INC", "dp"], 0xe8: ["INX", "imp"], 0xea: ["NOP", "imp"],
    0xeb: ["XBA", "imp"], 0xec: ["CPX", "abs"], 0xee: ["INC", "abs"], 0xf0: ["BEQ", "rel"], 0xf4: ["PEA", "abs"],
    0xf6: ["INC", "dpx"], 0xf8: ["SED", "imp"], 0xfa: ["PLX", "imp"], 0xfb: ["XCE", "imp"], 0xfc: ["JSR", "indx"],
    0xfe: ["INC", "abx"],
  };
  for (const code in more) OPS[Number(code)] = more[code];
  // octets d'opérande (hors immédiats dont la taille dépend de M ou X)
  const SIZE = { imp: 0, acc: 0, imm8: 1, dp: 1, dpx: 1, dpy: 1, dpi: 1, dpil: 1, dpix: 1, dpiy: 1, dpily: 1, sr: 1,
                 sriy: 1, rel: 1, abs: 2, abx: 2, aby: 2, ind: 2, indx: 2, indl: 2, rell: 2, bm: 2, abl: 3, ablx: 3 };

  const hex = (v, n = 2) => "$" + (v >>> 0).toString(16).toUpperCase().padStart(n, "0");

  class CPU65816 {
    constructor(bus) {
      this.bus = bus;
      this.a = 0; this.x = 0; this.y = 0; this.s = 0x1ff; this.d = 0; this.dbr = 0; this.pbr = 0; this.pc = 0;
      this.p = M | X | I; this.e = 1;
      this.nmiPending = false; this.irqLine = false; this.waiting = false; this.stopped = false;
      this.wrap = false;  // dernier mode : page directe ou pile (le 2e octet reste en banque 0)
      this.instructions = 0;
    }
    get jammed() { return this.stopped; }
    reset() {
      this.e = 1; this.p = (this.p | M | X | I) & ~D; this.d = 0; this.dbr = 0; this.pbr = 0;
      this.s = 0x100 | (this.s & 0xff); this.x &= 0xff; this.y &= 0xff;
      this.waiting = false; this.stopped = false; this.nmiPending = false;
      this.pc = this.read8(0xfffc) | (this.read8(0xfffd) << 8);
    }

    // ---------- bus ----------
    read8(a) { return this.bus.read(a & 0xffffff); }
    write8(a, v) { this.bus.write(a & 0xffffff, v & 0xff); }
    io() { this.bus.io(); }
    fetch8() { const v = this.read8((this.pbr << 16) | this.pc); this.pc = (this.pc + 1) & 0xffff; return v; }
    fetch16() { const lo = this.fetch8(); return lo | (this.fetch8() << 8); }
    fetch24() { const lo = this.fetch16(); return lo | (this.fetch8() << 16); }
    next(a) { return this.wrap ? (a & 0xff0000) | ((a + 1) & 0xffff) : (a + 1) & 0xffffff; }
    readW(a, wide) { const lo = this.read8(a); return wide ? lo | (this.read8(this.next(a)) << 8) : lo; }
    writeW(a, v, wide) { this.write8(a, v); if (wide) this.write8(this.next(a), v >> 8); }
    push8(v) { this.write8(this.s, v); this.s = this.e ? 0x100 | ((this.s - 1) & 0xff) : (this.s - 1) & 0xffff; }
    pull8() { this.s = this.e ? 0x100 | ((this.s + 1) & 0xff) : (this.s + 1) & 0xffff; return this.read8(this.s); }
    push16(v) { this.push8(v >> 8); this.push8(v); }
    pull16() { const lo = this.pull8(); return lo | (this.pull8() << 8); }

    // ---------- drapeaux ----------
    get m8() { return (this.p & M) !== 0; }
    get x8() { return (this.p & X) !== 0; }
    nz(v, wide) {
      const r = wide ? v & 0xffff : v & 0xff;
      this.p = (this.p & ~(N | Z)) | (r ? 0 : Z) | ((wide ? r >> 8 : r) & N);
    }
    flag(bit, on) { this.p = on ? this.p | bit : this.p & ~bit; }
    fixWidth() {
      if (this.e) this.p |= M | X;
      if (this.p & X) { this.x &= 0xff; this.y &= 0xff; }
    }

    // ---------- adresses effectives ----------
    dpBase(o, index) {
      if (this.d & 0xff) this.io();
      if (index === undefined) return (this.d + o) & 0xffff;
      this.io();
      if (this.e && !(this.d & 0xff)) return this.d | ((o + index) & 0xff);
      return (this.d + o + index) & 0xffff;
    }
    dpPointer(p, long) {
      // pointeur lu en banque 0 (en mode émulation avec DL = 0, il reste dans la page)
      const step = (k) => (this.e && !(this.d & 0xff) ? (p & 0xff00) | ((p + k) & 0xff) : (p + k) & 0xffff);
      const lo = this.read8(p), mid = this.read8(step(1));
      return long ? lo | (mid << 8) | (this.read8(step(2)) << 16) : lo | (mid << 8);
    }
    ea(mode) {
      this.wrap = false;
      switch (mode) {
        case "dp": this.wrap = true; return this.dpBase(this.fetch8());
        case "dpx": this.wrap = true; return this.dpBase(this.fetch8(), this.x);
        case "dpy": this.wrap = true; return this.dpBase(this.fetch8(), this.y);
        case "dpi": return (this.dbr << 16) | this.dpPointer(this.dpBase(this.fetch8()), false);
        case "dpil": return this.dpPointer(this.dpBase(this.fetch8()), true);
        case "dpix": return (this.dbr << 16) | this.dpPointer(this.dpBase(this.fetch8(), this.x), false);
        case "dpiy": { const base = (this.dbr << 16) | this.dpPointer(this.dpBase(this.fetch8()), false); this.io();
          return (base + this.y) & 0xffffff; }
        case "dpily": return (this.dpPointer(this.dpBase(this.fetch8()), true) + this.y) & 0xffffff;
        case "sr": { const o = this.fetch8(); this.io(); this.wrap = true; return (this.s + o) & 0xffff; }
        case "sriy": { const o = this.fetch8(); this.io(); const p = (this.s + o) & 0xffff;
          const ptr = this.read8(p) | (this.read8((p + 1) & 0xffff) << 8); this.io();
          return (((this.dbr << 16) | ptr) + this.y) & 0xffffff; }
        case "abs": return (this.dbr << 16) | this.fetch16();
        case "abx": { const a = (this.dbr << 16) | this.fetch16(); this.io(); return (a + this.x) & 0xffffff; }
        case "aby": { const a = (this.dbr << 16) | this.fetch16(); this.io(); return (a + this.y) & 0xffffff; }
        case "abl": return this.fetch24();
        case "ablx": return (this.fetch24() + this.x) & 0xffffff;
        default: throw new Error(`mode ${mode}`);
      }
    }
    load(mode, wide) {
      if (mode === "imm" || mode === "immx") return wide ? this.fetch16() : this.fetch8();
      return this.readW(this.ea(mode), wide);
    }

    // ---------- arithmétique ----------
    adc(v) {
      const wide = !this.m8, mask = wide ? 0xffff : 0xff, sign = wide ? 0x8000 : 0x80;
      const a = this.a & mask, c = this.p & C;
      let r;
      if (!(this.p & D)) {
        r = a + v + c;
        this.flag(V, (~(a ^ v) & (a ^ r) & sign) !== 0);
        this.flag(C, r > mask);
      } else {
        let carry = c; r = 0;
        for (let shift = 0; shift < (wide ? 16 : 8); shift += 4) {
          let digit = ((a >> shift) & 15) + ((v >> shift) & 15) + carry;
          if (digit > 9) digit += 6;
          carry = digit > 15 ? 1 : 0;
          r |= (digit & 15) << shift;
        }
        const bin = a + v + c;
        this.flag(V, (~(a ^ v) & (a ^ bin) & sign) !== 0);
        this.flag(C, carry === 1);
      }
      this.setA(r & mask);
    }
    sbc(v) {
      const wide = !this.m8, mask = wide ? 0xffff : 0xff;
      if (!(this.p & D)) { this.adc(~v & mask); return; }
      const a = this.a & mask, sign = wide ? 0x8000 : 0x80;
      let borrow = (this.p & C) ? 0 : 1, r = 0;
      for (let shift = 0; shift < (wide ? 16 : 8); shift += 4) {
        let digit = ((a >> shift) & 15) - ((v >> shift) & 15) - borrow;
        borrow = digit < 0 ? 1 : 0;
        if (digit < 0) digit += 10;
        r |= (digit & 15) << shift;
      }
      const bin = a - v - ((this.p & C) ? 0 : 1);
      this.flag(V, ((a ^ v) & (a ^ bin) & sign) !== 0);
      this.flag(C, borrow === 0);
      this.setA(r & mask);
    }
    setA(v) {
      if (this.m8) { this.a = (this.a & 0xff00) | (v & 0xff); this.nz(v, false); }
      else { this.a = v & 0xffff; this.nz(v, true); }
    }
    compare(reg, v, wide) {
      const mask = wide ? 0xffff : 0xff, r = (reg & mask) - v;
      this.flag(C, r >= 0);
      this.nz(r, wide);
    }
    rmw(mode, fn) {
      const wide = !this.m8;
      if (mode === "acc") {
        this.io();
        const v = wide ? this.a : this.a & 0xff;
        const r = fn(v, wide);
        this.a = wide ? r & 0xffff : (this.a & 0xff00) | (r & 0xff);
        return;
      }
      const a = this.ea(mode);
      if (mode === "abx") this.io();
      const v = this.readW(a, wide);
      this.io();
      this.writeW(a, fn(v, wide), wide);
    }
    branch(cond) {
      const o = this.fetch8();
      if (!cond) return;
      this.io();
      this.pc = (this.pc + ((o << 24) >> 24)) & 0xffff;
    }

    // ---------- interruptions ----------
    interrupt(nativeVector, emuVector, software) {
      if (!software) { this.read8((this.pbr << 16) | this.pc); this.io(); }
      if (!this.e) this.push8(this.pbr);
      this.push16(this.pc);
      this.push8(this.e ? (software ? this.p | 0x30 : (this.p | 0x20) & ~0x10) : this.p);
      this.p = (this.p | I) & ~D;
      this.pbr = 0;
      const v = this.e ? emuVector : nativeVector;
      this.pc = this.read8(v) | (this.read8(v + 1) << 8);
    }

    // ---------- une instruction ----------
    step() {
      if (this.stopped) { this.io(); return; }
      if (this.nmiPending) { this.nmiPending = false; this.waiting = false; this.interrupt(0xffea, 0xfffa, false); return; }
      if (this.irqLine && !(this.p & I)) { this.waiting = false; this.interrupt(0xffee, 0xfffe, false); return; }
      if (this.waiting) { if (this.irqLine) this.waiting = false; else { this.io(); return; } }
      this.instructions += 1;
      const op = this.fetch8();
      const [name, mode] = OPS[op];
      const m16 = !this.m8, x16 = !this.x8;
      switch (name) {
        case "LDA": this.setA(this.load(mode, m16)); break;
        case "LDX": this.x = this.load(mode, x16); this.nz(this.x, x16); break;
        case "LDY": this.y = this.load(mode, x16); this.nz(this.y, x16); break;
        case "STA": this.writeW(this.ea(mode), this.a, m16); break;
        case "STX": this.writeW(this.ea(mode), this.x, x16); break;
        case "STY": this.writeW(this.ea(mode), this.y, x16); break;
        case "STZ": this.writeW(this.ea(mode), 0, m16); break;
        case "ADC": this.adc(this.load(mode, m16)); break;
        case "SBC": this.sbc(this.load(mode, m16)); break;
        case "AND": this.setA(this.a & this.load(mode, m16)); break;
        case "ORA": this.setA(this.a | this.load(mode, m16)); break;
        case "EOR": this.setA(this.a ^ this.load(mode, m16)); break;
        case "CMP": this.compare(this.a, this.load(mode, m16), m16); break;
        case "CPX": this.compare(this.x, this.load(mode, x16), x16); break;
        case "CPY": this.compare(this.y, this.load(mode, x16), x16); break;
        case "BIT": {
          const v = this.load(mode, m16), top = m16 ? 0x8000 : 0x80;
          this.flag(Z, (v & this.a & (m16 ? 0xffff : 0xff)) === 0);
          if (mode !== "imm") { this.flag(N, (v & top) !== 0); this.flag(V, (v & (top >> 1)) !== 0); }
          break;
        }
        case "INC": this.rmw(mode, (v, w) => { const r = (v + 1) & (w ? 0xffff : 0xff); this.nz(r, w); return r; }); break;
        case "DEC": this.rmw(mode, (v, w) => { const r = (v - 1) & (w ? 0xffff : 0xff); this.nz(r, w); return r; }); break;
        case "ASL": this.rmw(mode, (v, w) => { const t = w ? 0x8000 : 0x80; this.flag(C, (v & t) !== 0);
          const r = (v << 1) & (w ? 0xffff : 0xff); this.nz(r, w); return r; }); break;
        case "LSR": this.rmw(mode, (v, w) => { this.flag(C, (v & 1) !== 0); const r = v >> 1; this.nz(r, w); return r; }); break;
        case "ROL": this.rmw(mode, (v, w) => { const t = w ? 0x8000 : 0x80, c = this.p & C; this.flag(C, (v & t) !== 0);
          const r = ((v << 1) | c) & (w ? 0xffff : 0xff); this.nz(r, w); return r; }); break;
        case "ROR": this.rmw(mode, (v, w) => { const c = this.p & C; this.flag(C, (v & 1) !== 0);
          const r = (v >> 1) | (c ? (w ? 0x8000 : 0x80) : 0); this.nz(r, w); return r; }); break;
        case "TSB": this.rmw(mode, (v, w) => { this.flag(Z, (v & this.a & (w ? 0xffff : 0xff)) === 0); return v | this.a; }); break;
        case "TRB": this.rmw(mode, (v, w) => { this.flag(Z, (v & this.a & (w ? 0xffff : 0xff)) === 0); return v & ~this.a; }); break;
        case "INX": this.io(); this.x = (this.x + 1) & (x16 ? 0xffff : 0xff); this.nz(this.x, x16); break;
        case "INY": this.io(); this.y = (this.y + 1) & (x16 ? 0xffff : 0xff); this.nz(this.y, x16); break;
        case "DEX": this.io(); this.x = (this.x - 1) & (x16 ? 0xffff : 0xff); this.nz(this.x, x16); break;
        case "DEY": this.io(); this.y = (this.y - 1) & (x16 ? 0xffff : 0xff); this.nz(this.y, x16); break;
        case "TAX": this.io(); this.x = x16 ? this.a : this.a & 0xff; this.nz(this.x, x16); break;
        case "TAY": this.io(); this.y = x16 ? this.a : this.a & 0xff; this.nz(this.y, x16); break;
        case "TXA": this.io(); this.setA(this.x); break;
        case "TYA": this.io(); this.setA(this.y); break;
        case "TXY": this.io(); this.y = this.x; this.nz(this.y, x16); break;
        case "TYX": this.io(); this.x = this.y; this.nz(this.x, x16); break;
        case "TSX": this.io(); this.x = x16 ? this.s : this.s & 0xff; this.nz(this.x, x16); break;
        case "TXS": this.io(); this.s = this.e ? 0x100 | (this.x & 0xff) : this.x; break;
        case "TCS": this.io(); this.s = this.e ? 0x100 | (this.a & 0xff) : this.a; break;
        case "TSC": this.io(); this.a = this.s; this.nz(this.a, true); break;
        case "TCD": this.io(); this.d = this.a; this.nz(this.d, true); break;
        case "TDC": this.io(); this.a = this.d; this.nz(this.a, true); break;
        case "XBA": this.io(); this.io(); this.a = ((this.a >> 8) | (this.a << 8)) & 0xffff; this.nz(this.a & 0xff, false); break;
        case "XCE": { this.io(); const c = this.p & C; this.flag(C, this.e === 1); this.e = c;
          if (this.e) { this.s = 0x100 | (this.s & 0xff); } this.fixWidth(); break; }
        case "REP": { const v = this.fetch8(); this.io(); this.p &= ~v; this.fixWidth(); break; }
        case "SEP": { const v = this.fetch8(); this.io(); this.p |= v; this.fixWidth(); break; }
        case "PHP": this.io(); this.push8(this.e ? this.p | 0x30 : this.p); break;
        case "PLP": this.io(); this.io(); this.p = this.pull8(); this.fixWidth(); break;
        case "PHA": this.io(); if (m16) this.push16(this.a); else this.push8(this.a); break;
        case "PLA": { this.io(); this.io(); this.setA(m16 ? this.pull16() : this.pull8()); break; }
        case "PHX": this.io(); if (x16) this.push16(this.x); else this.push8(this.x); break;
        case "PHY": this.io(); if (x16) this.push16(this.y); else this.push8(this.y); break;
        case "PLX": this.io(); this.io(); this.x = x16 ? this.pull16() : this.pull8(); this.nz(this.x, x16); break;
        case "PLY": this.io(); this.io(); this.y = x16 ? this.pull16() : this.pull8(); this.nz(this.y, x16); break;
        case "PHB": this.io(); this.push8(this.dbr); break;
        case "PLB": this.io(); this.io(); this.dbr = this.pull8(); this.nz(this.dbr, false); break;
        case "PHD": this.io(); this.push16(this.d); break;
        case "PLD": this.io(); this.io(); this.d = this.pull16(); this.nz(this.d, true); break;
        case "PHK": this.io(); this.push8(this.pbr); break;
        case "PEA": this.push16(this.fetch16()); break;
        case "PEI": { const p = this.dpBase(this.fetch8()); this.wrap = true;
          this.push16(this.read8(p) | (this.read8((p + 1) & 0xffff) << 8)); break; }
        case "PER": { const o = this.fetch16(); this.io(); this.push16((this.pc + o) & 0xffff); break; }
        case "BPL": this.branch(!(this.p & N)); break;
        case "BMI": this.branch((this.p & N) !== 0); break;
        case "BVC": this.branch(!(this.p & V)); break;
        case "BVS": this.branch((this.p & V) !== 0); break;
        case "BCC": this.branch(!(this.p & C)); break;
        case "BCS": this.branch((this.p & C) !== 0); break;
        case "BNE": this.branch(!(this.p & Z)); break;
        case "BEQ": this.branch((this.p & Z) !== 0); break;
        case "BRA": this.branch(true); break;
        case "BRL": { const o = this.fetch16(); this.io(); this.pc = (this.pc + o) & 0xffff; break; }
        case "JMP":
          if (mode === "abs") this.pc = this.fetch16();
          else if (mode === "ind") { const p = this.fetch16(); this.pc = this.read8(p) | (this.read8((p + 1) & 0xffff) << 8); }
          else { const p = (this.fetch16() + this.x) & 0xffff; this.io();
            this.pc = this.read8((this.pbr << 16) | p) | (this.read8((this.pbr << 16) | ((p + 1) & 0xffff)) << 8); }
          break;
        case "JML":
          if (mode === "abl") { const t = this.fetch24(); this.pbr = t >> 16; this.pc = t & 0xffff; }
          else { const p = this.fetch16(); const lo = this.read8(p) | (this.read8((p + 1) & 0xffff) << 8);
            this.pbr = this.read8((p + 2) & 0xffff); this.pc = lo; }
          break;
        case "JSR":
          if (mode === "abs") { const t = this.fetch16(); this.io(); this.push16((this.pc - 1) & 0xffff); this.pc = t; }
          else { const p = this.fetch16(); this.push16((this.pc - 1) & 0xffff); const q = (p + this.x) & 0xffff; this.io();
            this.pc = this.read8((this.pbr << 16) | q) | (this.read8((this.pbr << 16) | ((q + 1) & 0xffff)) << 8); }
          break;
        case "JSL": { const t = this.fetch24(); this.push8(this.pbr); this.io(); this.push16((this.pc - 1) & 0xffff);
          this.pbr = t >> 16; this.pc = t & 0xffff; break; }
        case "RTS": this.io(); this.io(); this.pc = (this.pull16() + 1) & 0xffff; this.io(); break;
        case "RTL": this.io(); this.io(); this.pc = (this.pull16() + 1) & 0xffff; this.pbr = this.pull8(); break;
        case "RTI": this.io(); this.io(); this.p = this.pull8(); this.fixWidth(); this.pc = this.pull16();
          if (!this.e) this.pbr = this.pull8(); break;
        case "BRK": this.fetch8(); this.interrupt(0xffe6, 0xfffe, true); break;
        case "COP": this.fetch8(); this.interrupt(0xffe4, 0xfff4, true); break;
        case "CLC": this.io(); this.p &= ~C; break;
        case "SEC": this.io(); this.p |= C; break;
        case "CLI": this.io(); this.p &= ~I; break;
        case "SEI": this.io(); this.p |= I; break;
        case "CLD": this.io(); this.p &= ~D; break;
        case "SED": this.io(); this.p |= D; break;
        case "CLV": this.io(); this.p &= ~V; break;
        case "NOP": this.io(); break;
        case "WDM": this.fetch8(); break;
        case "WAI": this.io(); this.io(); this.waiting = true; break;
        case "STP": this.io(); this.io(); this.stopped = true; break;
        case "MVN": case "MVP": {
          const dst = this.fetch8(), src = this.fetch8();
          this.dbr = dst;
          const v = this.read8((src << 16) | this.x);
          this.write8((dst << 16) | this.y, v);
          this.io(); this.io();
          const step = name === "MVN" ? 1 : -1, mask = x16 ? 0xffff : 0xff;
          this.x = (this.x + step) & mask; this.y = (this.y + step) & mask;
          this.a = (this.a - 1) & 0xffff;
          if (this.a !== 0xffff) this.pc = (this.pc - 3) & 0xffff;
          break;
        }
        default: throw new Error(`instruction ${name}`);
      }
    }

    // ---------- débogueur ----------
    // peek(adresse 24 bits) ; m8 / x8 : largeur des immédiats (par défaut l'état actuel du processeur)
    disassemble(addr, peek, m8 = this.m8, x8 = this.x8) {
      const op = peek(addr);
      const [name, mode] = OPS[op];
      const bank = addr & 0xff0000;
      const at = (k) => peek(bank | ((addr + k) & 0xffff));
      let size = 1 + SIZE[mode] || 1;
      if (mode === "imm") size = m8 ? 2 : 3;
      if (mode === "immx") size = x8 ? 2 : 3;
      if (mode === "imp") size = 1;
      if (mode === "acc") size = 1;
      const b1 = at(1), w = b1 | (at(2) << 8), l = w | (at(3) << 16);
      let arg = "";
      switch (mode) {
        case "imp": break;
        case "acc": arg = "A"; break;
        case "imm": case "immx": arg = "#" + (size === 2 ? hex(b1) : hex(w, 4)); break;
        case "imm8": arg = "#" + hex(b1); break;
        case "dp": arg = hex(b1); break;
        case "dpx": arg = hex(b1) + ",X"; break;
        case "dpy": arg = hex(b1) + ",Y"; break;
        case "dpi": arg = `(${hex(b1)})`; break;
        case "dpil": arg = `[${hex(b1)}]`; break;
        case "dpix": arg = `(${hex(b1)},X)`; break;
        case "dpiy": arg = `(${hex(b1)}),Y`; break;
        case "dpily": arg = `[${hex(b1)}],Y`; break;
        case "sr": arg = hex(b1) + ",S"; break;
        case "sriy": arg = `(${hex(b1)},S),Y`; break;
        case "abs": arg = (name === "PEA" ? "#" : "") + hex(w, 4); break;
        case "abx": arg = hex(w, 4) + ",X"; break;
        case "aby": arg = hex(w, 4) + ",Y"; break;
        case "abl": arg = hex(l, 6); break;
        case "ablx": arg = hex(l, 6) + ",X"; break;
        case "ind": arg = `(${hex(w, 4)})`; break;
        case "indx": arg = `(${hex(w, 4)},X)`; break;
        case "indl": arg = `[${hex(w, 4)}]`; break;
        case "rel": arg = hex((addr + 2 + ((b1 << 24) >> 24)) & 0xffff, 4); break;
        case "rell": arg = hex((addr + 3 + ((w << 16) >> 16)) & 0xffff, 4); break;
        case "bm": arg = `${hex(at(2))},${hex(b1)}`; break;
        default: break;
      }
      return { text: arg ? `${name} ${arg}` : name, size };
    }
  }

  root.AetherCPU16 = { CPU65816, OPS, SIZE, hex, FLAGS: { N, V, M, X, D, I, Z, C } };
})(typeof window !== "undefined" ? window : globalThis);
