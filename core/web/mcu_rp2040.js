"use strict";
// Microcontrôleur RP2040 simulé instruction par instruction (un cœur ARM Cortex-M0+, jeu Thumb ARMv6-M, 125 MHz),
// sans dépendance. Le programme est chargé directement en SRAM (0x2000_0000), comme le fait un débogueur SWD : pas
// de ROM de démarrage ni de mémoire flash externe à simuler. Périphériques simulés :
//   - RESETS (0x4000_C000) : IO_BANK0, PADS_BANK0 et TIMER démarrent tenus en reset ; il faut les libérer ;
//   - IO_BANK0 (0x4001_4000) : GPIOn_CTRL, fonction 5 (SIO) pour piloter la broche par logiciel ;
//   - PADS_BANK0 (0x4001_C000) : tirages internes (haut, bas : bas par défaut) ;
//   - SIO (0xD000_0000) : GPIO_IN, GPIO_OUT (+ SET, CLR, XOR), GPIO_OE (+ SET, CLR, XOR) ;
//   - TIMER (0x4005_4000) : compteur en microsecondes (TIMERAWH, TIMERAWL, TIMEHR, TIMELR) ;
//   - SysTick (0xE000_E010) : décompteur 24 bits (sans interruption).
// Les registres des périphériques en 0x4xxx_xxxx ont leurs alias atomiques : +0x1000 XOR, +0x2000 SET, +0x3000 CLR.
(function (root) {
  const SRAM = 0x20000000, SRAM_SIZE = 264 * 1024;
  const RESETS = 0x4000c000, IO_BANK0 = 0x40014000, PADS = 0x4001c000, TIMER = 0x40054000, SIO = 0xd0000000;
  const R_IO = 1 << 5, R_PADS = 1 << 8, R_TIMER = 1 << 21;
  const hex = (v) => `0x${(v >>> 0).toString(16).padStart(8, "0")}`;

  class RP2040 {
    constructor() {
      this.ram = new Uint8Array(SRAM_SIZE);
      this.view = new DataView(this.ram.buffer);
      this.r = new Uint32Array(16);
      this.ext = { high: 0, low: 0 };      // broches tirées de l'extérieur (boutons)
      this.onPort = null;
      this.hz = 125e6;
      this.image = new Uint8Array(0);
      this.entry = SRAM;
      this.reset();
    }
    load(image, entry) { this.image = image; this.entry = entry === undefined ? SRAM : entry; this.reset(); }
    reset() {
      this.ram.fill(0);
      this.ram.set(this.image.subarray(0, SRAM_SIZE));
      this.r.fill(0);
      this.r[13] = SRAM + SRAM_SIZE;            // pile en haut de la SRAM
      this.r[14] = 0xffffffff;
      this.r[15] = this.entry & ~1;
      this.N = this.Z = this.C = this.V = false;
      this.cycles = 0;
      this.halted = null;
      this.sleeping = false;
      this.resets = 0x01ffffff;
      this.ctrl = new Uint32Array(30).fill(0x1f);
      this.pads = new Uint32Array(30).fill(0x56); // IE + tirage bas, comme au démarrage
      this.out = 0; this.oe = 0;
      this.timeLatch = 0;
      this.systick = { csr: 0, rvr: 0, cvr: 0, acc: 0 };
      this.warned = new Set();
      if (this.onPort) this.onPort();
    }

    // ---------- broches ----------
    sioPins() { let m = 0; for (let i = 0; i < 30; i++) if ((this.ctrl[i] & 0x1f) === 5) m |= 1 << i; return m >>> 0; }
    // Niveau de chaque broche : sortie SIO si la fonction 5 est choisie et la sortie activée ; sinon le bouton, sinon
    // le tirage interne (PUE = haut, PDE = bas).
    pinLevels() {
      const drive = (this.oe & this.sioPins()) >>> 0;
      let pulls = 0;
      for (let i = 0; i < 30; i++) if (this.pads[i] & 8) pulls |= 1 << i;
      const ext = (this.ext.high & ~this.ext.low) | (pulls & ~this.ext.low & ~this.ext.high);
      return ((drive & this.out) | (~drive & ext)) >>> 0 & 0x3fffffff;
    }
    driven() { return (this.oe & this.sioPins()) >>> 0; }
    warn(key, msg) { if (!this.warned.has(key)) { this.warned.add(key); (this.notes = this.notes || []).push(msg); } }

    // ---------- mémoire ----------
    fault(msg) { if (!this.halted) this.halted = `erreur matérielle (HardFault) : ${msg}`; }
    micros() { return Math.floor(this.cycles / (this.hz / 1e6)); }
    readPeriph(a) {
      const base = a & ~0x3fff, off = a & 0xfff;
      if (base === RESETS) {
        if (off === 0) return this.resets;
        if (off === 8) return ~this.resets & 0x01ffffff;
        return 0;
      }
      if (base === IO_BANK0) {
        if (this.resets & R_IO) { this.warn("io", "IO_BANK0 est encore tenu en reset : libère-le (RESETS, bit 5) avant de choisir la fonction des broches."); return 0; }
        const n = off >> 3;
        if (n < 30) return off & 4 ? this.ctrl[n] : ((this.pinLevels() >> n) & 1) << 17;
        return 0;
      }
      if (base === PADS) {
        if (this.resets & R_PADS) { this.warn("pads", "PADS_BANK0 est encore tenu en reset (RESETS, bit 8)."); return 0; }
        const n = (off - 4) >> 2;
        return n >= 0 && n < 30 ? this.pads[n] : 0;
      }
      if (base === TIMER) {
        if (this.resets & R_TIMER) { this.warn("timer", "TIMER est encore tenu en reset (RESETS, bit 21) : il ne compte pas."); return 0; }
        const us = this.micros();
        switch (off) {
          case 0x0c: this.timeLatch = Math.floor(us / 4294967296); return us >>> 0; // TIMELR (fige TIMEHR)
          case 0x08: return this.timeLatch >>> 0;
          case 0x28: return us >>> 0; // TIMERAWL
          case 0x24: return Math.floor(us / 4294967296) >>> 0; // TIMERAWH
          default: return 0;
        }
      }
      return 0;
    }
    writePeriph(a, v) {
      const alias = (a >> 12) & 3, reg = a & ~0x3000;
      const old = this.readPeriphRaw(reg);
      const val = alias === 0 ? v : alias === 1 ? old ^ v : alias === 2 ? old | v : old & ~v;
      const base = reg & ~0x3fff, off = reg & 0xfff;
      if (base === RESETS && off === 0) { this.resets = val & 0x01ffffff; return; }
      if (base === IO_BANK0) {
        if (this.resets & R_IO) { this.warn("io", "IO_BANK0 est encore tenu en reset : libère-le (RESETS, bit 5) avant de choisir la fonction des broches."); return; }
        const n = off >> 3;
        if (n < 30 && off & 4) { this.ctrl[n] = val; if (this.onPort) this.onPort(); }
        return;
      }
      if (base === PADS) {
        if (this.resets & R_PADS) { this.warn("pads", "PADS_BANK0 est encore tenu en reset (RESETS, bit 8)."); return; }
        const n = (off - 4) >> 2;
        if (n >= 0 && n < 30) { this.pads[n] = val; if (this.onPort) this.onPort(); }
      }
    }
    readPeriphRaw(a) {
      const base = a & ~0x3fff, off = a & 0xfff;
      if (base === RESETS && off === 0) return this.resets;
      if (base === IO_BANK0 && (off & 4)) return this.ctrl[off >> 3] || 0;
      if (base === PADS) return this.pads[(off - 4) >> 2] || 0;
      return 0;
    }
    readSio(off) {
      switch (off) {
        case 0x000: return 0; // CPUID : cœur 0
        case 0x004: return this.pinLevels();
        case 0x008: return 0; // GPIO_HI_IN (broches de la flash)
        case 0x010: case 0x014: case 0x018: case 0x01c: return this.out;
        case 0x020: case 0x024: case 0x028: case 0x02c: return this.oe;
        default: return 0;
      }
    }
    writeSio(off, v) {
      const m = v & 0x3fffffff;
      switch (off) {
        case 0x010: this.out = m; break; case 0x014: this.out |= m; break; case 0x018: this.out &= ~m; break; case 0x01c: this.out ^= m; break;
        case 0x020: this.oe = m; break; case 0x024: this.oe |= m; break; case 0x028: this.oe &= ~m; break; case 0x02c: this.oe ^= m; break;
        default: return;
      }
      this.out >>>= 0; this.oe >>>= 0;
      if (this.onPort) this.onPort();
    }
    systickRead(off) {
      const s = this.systick;
      if (off === 0x10) { const v = s.csr; s.csr &= ~0x10000; return v; }
      if (off === 0x14) return s.rvr;
      if (off === 0x18) return s.cvr;
      return 0;
    }
    read32(a) {
      a >>>= 0;
      if (a & 3) { this.fault(`lecture de 32 bits mal alignée à ${hex(a)}`); return 0; }
      if (a >= SRAM && a < SRAM + SRAM_SIZE) return this.view.getUint32(a - SRAM, true);
      if (a >= 0x40000000 && a < 0x50000000) return this.readPeriph(a) >>> 0;
      if (a >= SIO && a < SIO + 0x200) return this.readSio(a - SIO) >>> 0;
      if (a >= 0xe000e010 && a < 0xe000e020) return this.systickRead(a - 0xe000e000) >>> 0;
      if (a < 0x4000 || (a >= 0x10000000 && a < 0x11000000)) return 0;
      this.fault(`lecture à une adresse sans mémoire : ${hex(a)}`);
      return 0;
    }
    write32(a, v) {
      a >>>= 0;
      if (a & 3) { this.fault(`écriture de 32 bits mal alignée à ${hex(a)}`); return; }
      if (a >= SRAM && a < SRAM + SRAM_SIZE) { this.view.setUint32(a - SRAM, v >>> 0, true); return; }
      if (a >= 0x40000000 && a < 0x50000000) { this.writePeriph(a, v >>> 0); return; }
      if (a >= SIO && a < SIO + 0x200) { this.writeSio(a - SIO, v >>> 0); return; }
      if (a >= 0xe000e010 && a < 0xe000e020) {
        const s = this.systick, off = a - 0xe000e000;
        if (off === 0x10) s.csr = (s.csr & 0x10000) | (v & 7);
        else if (off === 0x14) s.rvr = v & 0xffffff;
        else if (off === 0x18) { s.cvr = 0; s.csr &= ~0x10000; }
        return;
      }
      this.fault(`écriture à une adresse interdite : ${hex(a)}`);
    }
    read16(a) {
      a >>>= 0;
      if (a & 1) { this.fault(`lecture de 16 bits mal alignée à ${hex(a)}`); return 0; }
      if (a >= SRAM && a < SRAM + SRAM_SIZE) return this.view.getUint16(a - SRAM, true);
      return (this.read32(a & ~3) >>> ((a & 2) * 8)) & 0xffff;
    }
    write16(a, v) {
      a >>>= 0;
      if (a & 1) { this.fault(`écriture de 16 bits mal alignée à ${hex(a)}`); return; }
      if (a >= SRAM && a < SRAM + SRAM_SIZE) { this.view.setUint16(a - SRAM, v & 0xffff, true); return; }
      this.write32(a & ~3, (v & 0xffff) * 0x10001); // les périphériques recopient la demi-mot sur les deux moitiés
    }
    read8(a) {
      a >>>= 0;
      if (a >= SRAM && a < SRAM + SRAM_SIZE) return this.ram[a - SRAM];
      return (this.read32(a & ~3) >>> ((a & 3) * 8)) & 0xff;
    }
    write8(a, v) {
      a >>>= 0;
      if (a >= SRAM && a < SRAM + SRAM_SIZE) { this.ram[a - SRAM] = v; return; }
      this.write32(a & ~3, (v & 0xff) * 0x01010101);
    }
    fetch(a) {
      if (a >= SRAM && a < SRAM + SRAM_SIZE - 1) return this.view.getUint16(a - SRAM, true);
      this.fault(`le processeur exécute hors de la SRAM, à ${hex(a)} (retour de fonction perdu ?)`);
      return 0xbf00;
    }

    // ---------- calcul ----------
    nz(v) { this.N = (v >>> 31) === 1; this.Z = (v >>> 0) === 0; }
    addc(a, b, c) {
      const res = (a >>> 0) + (b >>> 0) + c;
      const r32 = res >>> 0;
      this.N = (r32 >>> 31) === 1; this.Z = r32 === 0; this.C = res > 0xffffffff;
      this.V = (((a ^ r32) & (b ^ r32)) >>> 31) === 1;
      return r32;
    }
    sub(a, b) { return this.addc(a, ~b >>> 0, 1); }
    cond(c) {
      switch (c) {
        case 0: return this.Z; case 1: return !this.Z; case 2: return this.C; case 3: return !this.C;
        case 4: return this.N; case 5: return !this.N; case 6: return this.V; case 7: return !this.V;
        case 8: return this.C && !this.Z; case 9: return !this.C || this.Z;
        case 10: return this.N === this.V; case 11: return this.N !== this.V;
        case 12: return !this.Z && this.N === this.V; case 13: return this.Z || this.N !== this.V;
        default: return true;
      }
    }
    reg(n) { return n === 15 ? (this.r[15] + 2) >>> 0 : this.r[n]; } // pc lu = instruction + 4 (déjà avancé de 2)
    branch(target) { this.r[15] = target & ~1; }

    // ---------- une instruction ----------
    step() {
      if (this.halted) return 0;
      const pc = this.r[15];
      const op = this.fetch(pc);
      this.r[15] = pc + 2;
      const r = this.r;
      let cyc = 1;
      const top = op >>> 11;
      if (top <= 2) { // LSLS / LSRS / ASRS imm
        const imm = (op >> 6) & 31, m = r[(op >> 3) & 7], d = op & 7;
        let res;
        if (top === 0) { if (imm) this.C = ((m >>> (32 - imm)) & 1) === 1; res = (m << imm) >>> 0; }
        else if (top === 1) { const s = imm || 32; this.C = ((m >>> (s - 1)) & 1) === 1; res = s === 32 ? 0 : m >>> s; }
        else { const s = imm || 32; this.C = ((m >>> (s - 1)) & 1) === 1; res = s === 32 ? ((m | 0) >> 31) >>> 0 : ((m | 0) >> s) >>> 0; }
        r[d] = res; this.nz(res);
      } else if (top === 3) { // ADDS / SUBS registre ou imm3
        const n = r[(op >> 3) & 7], d = op & 7, x = (op >> 6) & 7, b = op & 0x400 ? x : r[x];
        r[d] = op & 0x200 ? this.sub(n, b) : this.addc(n, b, 0);
      } else if (top <= 7) { // MOVS / CMP / ADDS / SUBS imm8
        const d = (op >> 8) & 7, k = op & 0xff;
        if (top === 4) { r[d] = k; this.nz(k); } else if (top === 5) this.sub(r[d], k);
        else if (top === 6) r[d] = this.addc(r[d], k, 0); else r[d] = this.sub(r[d], k);
      } else if ((op & 0xfc00) === 0x4000) { cyc = this.dataOp(op); }
      else if ((op & 0xfc00) === 0x4400) { // registres hauts, BX, BLX
        const kind = (op >> 8) & 3, d = (op & 7) | ((op >> 4) & 8), m = (op >> 3) & 15;
        if (kind === 0) { const res = (this.reg(d) + this.reg(m)) >>> 0; if (d === 15) { this.branch(res); cyc = 2; } else r[d] = res; }
        else if (kind === 1) this.sub(this.reg(d), this.reg(m));
        else if (kind === 2) { const v = this.reg(m); if (d === 15) { this.branch(v); cyc = 2; } else r[d] = v; }
        else {
          const target = this.reg(m);
          if (!(target & 1)) this.fault(`bx/blx vers ${hex(target)} : en Thumb, le bit 0 de l'adresse doit valoir 1`);
          if (op & 0x80) r[14] = (pc + 2) | 1;
          this.branch(target); cyc = 2;
          if (target === 0xffffffff) this.halted = "fin du programme (retour de la fonction principale)";
        }
      } else if ((op & 0xf800) === 0x4800) { // LDR littéral
        const a = ((pc + 4) & ~3) + (op & 0xff) * 4;
        r[(op >> 8) & 7] = this.read32(a); cyc = 2;
      } else if ((op & 0xf000) === 0x5000) { // chargement / rangement, décalage par registre
        const a = (r[(op >> 3) & 7] + r[(op >> 6) & 7]) >>> 0, t = op & 7;
        switch ((op >> 9) & 7) {
          case 0: this.write32(a, r[t]); break; case 1: this.write16(a, r[t]); break; case 2: this.write8(a, r[t]); break;
          case 3: r[t] = ((this.read8(a) << 24) >> 24) >>> 0; break; case 4: r[t] = this.read32(a); break;
          case 5: r[t] = this.read16(a); break; case 6: r[t] = this.read8(a); break;
          default: r[t] = ((this.read16(a) << 16) >> 16) >>> 0; break;
        }
        cyc = 2;
      } else if ((op & 0xe000) === 0x6000) { // LDR/STR(B) imm5
        const byte = op & 0x1000, load = op & 0x800, k = (op >> 6) & 31, n = r[(op >> 3) & 7], t = op & 7;
        const a = (n + (byte ? k : k * 4)) >>> 0;
        if (load) r[t] = byte ? this.read8(a) : this.read32(a); else if (byte) this.write8(a, r[t]); else this.write32(a, r[t]);
        cyc = 2;
      } else if ((op & 0xf000) === 0x8000) { // LDRH/STRH imm5
        const a = (r[(op >> 3) & 7] + ((op >> 6) & 31) * 2) >>> 0, t = op & 7;
        if (op & 0x800) r[t] = this.read16(a); else this.write16(a, r[t]);
        cyc = 2;
      } else if ((op & 0xf000) === 0x9000) { // LDR/STR sp + imm8
        const a = (r[13] + (op & 0xff) * 4) >>> 0, t = (op >> 8) & 7;
        if (op & 0x800) r[t] = this.read32(a); else this.write32(a, r[t]);
        cyc = 2;
      } else if ((op & 0xf000) === 0xa000) { // ADR / ADD rd, sp, #imm
        const d = (op >> 8) & 7, k = (op & 0xff) * 4;
        r[d] = op & 0x800 ? (r[13] + k) >>> 0 : (((pc + 4) & ~3) + k) >>> 0;
      } else if ((op & 0xf000) === 0xb000) { cyc = this.misc(op, pc); }
      else if ((op & 0xf000) === 0xc000) { // STM / LDM
        const n = (op >> 8) & 7, list = op & 0xff;
        let a = r[n];
        for (let i = 0; i < 8; i++) {
          if (!(list & (1 << i))) continue;
          if (op & 0x800) r[i] = this.read32(a); else this.write32(a, r[i]);
          a = (a + 4) >>> 0; cyc++;
        }
        if (!(op & 0x800) || !(list & (1 << n))) r[n] = a;
      } else if ((op & 0xf000) === 0xd000) { // B cond, SVC, UDF
        const c = (op >> 8) & 15;
        if (c === 15) this.halted = `SVC #${op & 0xff} : appel système (non simulé)`;
        else if (c === 14) this.fault("instruction UDF (indéfinie)");
        else if (this.cond(c)) { this.branch((pc + 4 + (((op & 0xff) << 24) >> 23)) >>> 0); cyc = 2; if ((op & 0xff) === 0xfe) this.idle(); }
      } else if ((op & 0xf800) === 0xe000) { // B
        const off = ((op & 0x7ff) << 21) >> 20;
        this.branch((pc + 4 + off) >>> 0); cyc = 2;
        if (off === -4) this.idle();
      } else if ((op & 0xf800) === 0xf000) { // 32 bits : BL, MSR, MRS, barrières
        const op2 = this.fetch(pc + 2);
        this.r[15] = pc + 4;
        if ((op2 & 0xd000) === 0xd000) {
          const s = (op >> 10) & 1, j1 = (op2 >> 13) & 1, j2 = (op2 >> 11) & 1;
          const i1 = 1 ^ j1 ^ s, i2 = 1 ^ j2 ^ s;
          let off = (s << 24) | (i1 << 23) | (i2 << 22) | ((op & 0x3ff) << 12) | ((op2 & 0x7ff) << 1);
          off = (off << 7) >> 7;
          r[14] = (pc + 4) | 1;
          this.branch((pc + 4 + off) >>> 0); cyc = 3;
        } else if (op === 0xf3bf && (op2 & 0xff00) === 0x8f00) cyc = 3; // DMB, DSB, ISB
        else if ((op & 0xfff0) === 0xf3e0 && (op2 & 0xf000) === 0x8000) { r[(op2 >> 8) & 15] = (op2 & 0xff) === 8 || (op2 & 0xff) === 9 ? r[13] : 0; cyc = 3; } // MRS
        else if ((op & 0xfff0) === 0xf380 && (op2 & 0xff00) === 0x8800) { if ((op2 & 0xff) === 8 || (op2 & 0xff) === 9) r[13] = r[op & 15] & ~3; cyc = 3; } // MSR
        else this.fault(`instruction 32 bits inconnue : ${op.toString(16)} ${op2.toString(16)}`);
      } else this.fault(`instruction inconnue : 0x${op.toString(16).padStart(4, "0")}`);
      if (this.halted) this.r[15] = pc;
      this.tick(cyc);
      return cyc;
    }
    // Boucle vide « b . » : le cœur n'a plus rien à faire ; on le laisse attendre sans brûler de calcul.
    idle() { this.sleeping = "boucle"; }

    dataOp(op) {
      const r = this.r, d = op & 7, m = r[(op >> 3) & 7], a = r[d];
      let res;
      switch ((op >> 6) & 15) {
        case 0: res = a & m; r[d] = res; this.nz(res); break; // ANDS
        case 1: res = (a ^ m) >>> 0; r[d] = res; this.nz(res); break; // EORS
        case 2: { const s = m & 0xff; res = s >= 32 ? 0 : (a << s) >>> 0; if (s) this.C = s <= 32 && ((a >>> (32 - s)) & 1) === 1; r[d] = res; this.nz(res); break; } // LSLS
        case 3: { const s = m & 0xff; res = s >= 32 ? 0 : a >>> s; if (s) this.C = s <= 32 && ((a >>> (s - 1)) & 1) === 1; r[d] = res; this.nz(res); break; } // LSRS
        case 4: { const s = m & 0xff; res = (((a | 0) >> Math.min(s, 31)) >>> 0); if (s) this.C = (((a | 0) >> Math.min(s - 1, 31)) & 1) === 1; r[d] = res; this.nz(res); break; } // ASRS
        case 5: r[d] = this.addc(a, m, this.C ? 1 : 0); break; // ADCS
        case 6: r[d] = this.addc(a, ~m >>> 0, this.C ? 1 : 0); break; // SBCS
        case 7: { const s = m & 31; res = s ? ((a >>> s) | (a << (32 - s))) >>> 0 : a; if (m & 0xff) this.C = (res >>> 31) === 1; r[d] = res; this.nz(res); break; } // RORS
        case 8: this.nz((a & m) >>> 0); break; // TST
        case 9: r[d] = this.sub(0, m); break; // RSBS (NEGS)
        case 10: this.sub(a, m); break; // CMP
        case 11: this.addc(a, m, 0); break; // CMN
        case 12: res = (a | m) >>> 0; r[d] = res; this.nz(res); break; // ORRS
        case 13: res = Math.imul(a, m) >>> 0; r[d] = res; this.nz(res); break; // MULS
        case 14: res = (a & ~m) >>> 0; r[d] = res; this.nz(res); break; // BICS
        default: res = (~m) >>> 0; r[d] = res; this.nz(res); break; // MVNS
      }
      return 1;
    }

    misc(op, pc) {
      const r = this.r;
      if ((op & 0xff00) === 0xb000) { const k = (op & 0x7f) * 4; r[13] = (op & 0x80 ? r[13] - k : r[13] + k) >>> 0; return 1; } // ADD/SUB sp
      if ((op & 0xff00) === 0xb200) { // SXTH SXTB UXTH UXTB
        const m = r[(op >> 3) & 7], d = op & 7;
        r[d] = [((m << 16) >> 16) >>> 0, ((m << 24) >> 24) >>> 0, m & 0xffff, m & 0xff][(op >> 6) & 3];
        return 1;
      }
      if ((op & 0xfe00) === 0xb400) { // PUSH
        let sp = r[13];
        const list = (op & 0xff) | (op & 0x100 ? 0x4000 : 0);
        let n = 0;
        for (let i = 0; i < 16; i++) if (list & (1 << i)) n++;
        sp = (sp - 4 * n) >>> 0;
        r[13] = sp;
        for (let i = 0; i < 16; i++) if (list & (1 << i)) { this.write32(sp, r[i]); sp += 4; }
        if (r[13] < SRAM + 0x100 && r[13] >= SRAM) this.warn("stack", "la pile arrive au bas de la SRAM : récursion trop profonde ?");
        return 1 + n;
      }
      if ((op & 0xfe00) === 0xbc00) { // POP
        let sp = r[13], n = 0;
        for (let i = 0; i < 8; i++) if (op & (1 << i)) { r[i] = this.read32(sp); sp += 4; n++; }
        if (op & 0x100) {
          const target = this.read32(sp); sp += 4; n++;
          r[13] = sp >>> 0;
          if (target === 0xffffffff) { this.halted = "fin du programme (retour de la fonction principale)"; return 1; }
          if (!(target & 1)) this.fault(`pop {pc} vers ${hex(target)} : en Thumb, le bit 0 de l'adresse doit valoir 1`);
          this.branch(target);
          return 3 + n;
        }
        r[13] = sp >>> 0;
        return 1 + n;
      }
      if ((op & 0xffef) === 0xb662) return 1; // CPSIE / CPSID i
      if ((op & 0xff00) === 0xba00) { // REV, REV16, REVSH
        const m = r[(op >> 3) & 7], d = op & 7, kind = (op >> 6) & 3;
        if (kind === 0) r[d] = (((m & 0xff) << 24) | ((m & 0xff00) << 8) | ((m >>> 8) & 0xff00) | (m >>> 24)) >>> 0;
        else if (kind === 1) r[d] = (((m & 0x00ff00ff) << 8) | ((m >>> 8) & 0x00ff00ff)) >>> 0;
        else if (kind === 3) r[d] = ((((m & 0xff) << 24) >> 16) | ((m >>> 8) & 0xff)) >>> 0;
        else this.fault("instruction inconnue");
        return 1;
      }
      if ((op & 0xff00) === 0xbe00) { this.halted = `BKPT #${op & 0xff} : point d'arrêt`; return 1; }
      if ((op & 0xff00) === 0xbf00) { // NOP, YIELD, WFE, WFI, SEV
        const hint = (op >> 4) & 15;
        if (hint === 2 || hint === 3) this.sleeping = "wfi";
        return 1;
      }
      this.fault(`instruction inconnue : 0x${op.toString(16)} à ${hex(pc)}`);
      return 1;
    }

    tick(n) {
      this.cycles += n;
      const s = this.systick;
      if (s.csr & 1) {
        s.acc += n;
        while (s.acc > 0) {
          if (s.cvr === 0) { s.cvr = s.rvr; s.acc -= 1; continue; }
          const take = Math.min(s.acc, s.cvr);
          s.cvr -= take; s.acc -= take;
          if (s.cvr === 0) s.csr |= 0x10000;
        }
      }
    }
    run(cycles) {
      const end = this.cycles + cycles;
      while (this.cycles < end && !this.halted) {
        if (this.sleeping) { this.tick(end - this.cycles); if (this.sleeping === "wfi") this.sleeping = false; break; }
        this.step();
      }
    }
    regs() {
      return { r: Array.from(this.r), flags: `${this.N ? "N" : "·"}${this.Z ? "Z" : "·"}${this.C ? "C" : "·"}${this.V ? "V" : "·"}`,
               cycles: this.cycles, us: this.micros() };
    }
  }

  root.AetherRP2040 = { RP2040, SRAM, SRAM_SIZE, hex };
})(typeof window !== "undefined" ? window : globalThis);
