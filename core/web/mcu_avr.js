"use strict";
// Microcontrôleur AVR 8 bits simulé instruction par instruction (famille de l'ATmega328P, 16 MHz), sans dépendance.
// Mémoire de données : r0–r31 en 0x00–0x1F, entrées-sorties en 0x20–0xFF, SRAM de 2 Ko en 0x100–0x8FF.
// Programme : 16 K mots de 16 bits (32 Ko de flash). Périphériques simulés : ports B, C et D (DDRx, PORTx, PINx ;
// écrire 1 dans PINx inverse la sortie), minuterie 0 (pré-diviseur, débordement, mode CTC avec OCR0A) et ses
// interruptions. Tout le reste de l'espace d'entrées-sorties se lit et s'écrit comme une mémoire ordinaire.
(function (root) {
  const DATA = 0x900, FLASH_WORDS = 0x4000;
  const SREG = 0x5f, SPL = 0x5d, SPH = 0x5e;
  const PORTS = { B: 0x23, C: 0x26, D: 0x29 }; // adresse de PINx ; DDRx = +1 ; PORTx = +2
  const TIFR0 = 0x35, TCCR0A = 0x44, TCCR0B = 0x45, TCNT0 = 0x46, OCR0A = 0x47, TIMSK0 = 0x6e;
  const PRESCALE = [0, 1, 8, 64, 256, 1024, 0, 0];
  const C = 1, Z = 2, N = 4, V = 8, S = 16, H = 32, T = 64, I = 128;

  class AVR {
    constructor() {
      this.flash = new Uint16Array(FLASH_WORDS);
      this.data = new Uint8Array(DATA);
      this.lines = new Map();
      this.extLow = { B: 0, C: 0, D: 0 };   // broches tirées à la masse de l'extérieur (boutons)
      this.extHigh = { B: 0, C: 0, D: 0 };  // broches tirées au +5 V de l'extérieur
      this.onPort = null;                  // rappel quand une sortie change (carte : LED, écran…)
      this.hz = 16e6;
      this.reset();
    }
    load(image) {
      this.flash.fill(0xffff);
      for (let i = 0; i + 1 < image.length || i < image.length; i += 2) this.flash[i >> 1] = image[i] | ((image[i + 1] || 0) << 8);
      this.reset();
    }
    reset() {
      this.data.fill(0);
      this.pc = 0;
      this.cycles = 0;
      this.sp = DATA - 1;
      this.halted = null;
      this.sleeping = false;
      this.timerAcc = 0;
      this.pendingSkip = 0;
      if (this.onPort) this.onPort();
    }
    get sp() { return this.data[SPL] | (this.data[SPH] << 8); }
    set sp(v) { this.data[SPL] = v & 0xff; this.data[SPH] = (v >> 8) & 0xff; }
    get sreg() { return this.data[SREG]; }

    // ---------- broches ----------
    pinLevels(port) {
      const base = PORTS[port];
      const ddr = this.data[base + 1], out = this.data[base + 2];
      const ext = this.extLow[port], hi = this.extHigh[port];
      // Sortie : niveau imposé par PORTx. Entrée : bouton à la masse > bouton au +5 V > tirage interne (PORTx = 1).
      return ((ddr & out) | (~ddr & ~ext & (hi | out))) & 0xff;
    }
    // Broche en entrée sans tirage et sans rien de branché : elle « flotte » (lue à 0 ici).
    floating(port) {
      const base = PORTS[port];
      return ~this.data[base + 1] & ~this.data[base + 2] & 0xff;
    }

    // ---------- espace de données ----------
    read(a) {
      if (a === 0x23 || a === 0x26 || a === 0x29) return this.pinLevels(a === 0x23 ? "B" : a === 0x26 ? "C" : "D");
      if (a >= DATA) { this.fault(`lecture hors de la mémoire : 0x${a.toString(16)}`); return 0; }
      return this.data[a];
    }
    write(a, v) {
      v &= 0xff;
      if (a >= DATA) { this.fault(`écriture hors de la mémoire : 0x${a.toString(16)}`); return; }
      if (a === 0x23 || a === 0x26 || a === 0x29) { this.data[a + 2] ^= v; if (this.onPort) this.onPort(); return; } // PINx : bascule
      if (a === TIFR0) { this.data[a] &= ~v; return; } // un 1 efface le drapeau
      this.data[a] = v;
      if (a >= 0x24 && a <= 0x2b && this.onPort) this.onPort();
    }
    fault(msg) { if (!this.halted) this.halted = msg; }

    push(v) { const sp = this.sp; if (sp < 0x100) this.fault("pile trop basse : elle déborde sur les registres (trop d'appels imbriqués ?)"); this.write(sp, v); this.sp = sp - 1; }
    pop() { const sp = this.sp + 1; this.sp = sp; if (sp >= DATA) { this.fault("pile vide : ret ou pop sans appel correspondant"); return 0; } return this.data[sp]; }
    pushPc(pc) { this.push(pc & 0xff); this.push((pc >> 8) & 0xff); }
    popPc() { const hi = this.pop(); return ((hi << 8) | this.pop()) & 0x3fff; }

    // ---------- minuterie 0 ----------
    tick(n) {
      this.cycles += n;
      const div = PRESCALE[this.data[TCCR0B] & 7];
      if (!div) return;
      this.timerAcc += n;
      while (this.timerAcc >= div) {
        this.timerAcc -= div;
        const ctc = (this.data[TCCR0A] & 3) === 2;
        let t = this.data[TCNT0];
        if (ctc && t === this.data[OCR0A]) { t = 0; this.data[TIFR0] |= 2; }
        else if (t === 0xff) { t = 0; this.data[TIFR0] |= 1; }
        else { t += 1; if (t === this.data[OCR0A]) this.data[TIFR0] |= 2; }
        this.data[TCNT0] = t;
      }
    }
    interrupts() {
      if (!(this.data[SREG] & I)) return false;
      const pend = this.data[TIFR0] & this.data[TIMSK0];
      if (!pend) return false;
      const vector = pend & 2 ? 0x1c : 0x20;
      this.data[TIFR0] &= pend & 2 ? ~2 : ~1;
      this.sleeping = false;
      this.pushPc(this.pc);
      this.data[SREG] &= ~I;
      this.pc = vector;
      this.tick(4);
      return true;
    }

    // ---------- drapeaux ----------
    flags(mask, set) { this.data[SREG] = (this.data[SREG] & ~mask) | set; }
    addFlags(d, r, res, carryIn) {
      void carryIn;
      const d7 = d >> 7 & 1, r7 = r >> 7 & 1, R7 = res >> 7 & 1, d3 = d >> 3 & 1, r3 = r >> 3 & 1, R3 = res >> 3 & 1;
      const h = (d3 & r3) | (r3 & ~R3) | (~R3 & d3);
      const v = (d7 & r7 & ~R7) | (~d7 & ~r7 & R7);
      const c = (d7 & r7) | (r7 & ~R7) | (~R7 & d7);
      const n = R7;
      this.flags(C | Z | N | V | S | H, (c & 1 ? C : 0) | ((res & 0xff) === 0 ? Z : 0) | (n ? N : 0) | (v & 1 ? V : 0) | ((n ^ (v & 1)) ? S : 0) | (h & 1 ? H : 0));
    }
    subFlags(d, r, res, keepZ) {
      const d7 = d >> 7 & 1, r7 = r >> 7 & 1, R7 = res >> 7 & 1, d3 = d >> 3 & 1, r3 = r >> 3 & 1, R3 = res >> 3 & 1;
      const h = (~d3 & r3) | (r3 & R3) | (R3 & ~d3);
      const v = (d7 & ~r7 & ~R7) | (~d7 & r7 & R7);
      const c = (~d7 & r7) | (r7 & R7) | (R7 & ~d7);
      const n = R7;
      let z = (res & 0xff) === 0;
      if (keepZ) z = z && (this.data[SREG] & Z) !== 0;
      this.flags(C | Z | N | V | S | H, (c & 1 ? C : 0) | (z ? Z : 0) | (n ? N : 0) | (v & 1 ? V : 0) | ((n ^ (v & 1)) ? S : 0) | (h & 1 ? H : 0));
    }
    logicFlags(res) {
      const n = res >> 7 & 1;
      this.flags(Z | N | V | S, ((res & 0xff) === 0 ? Z : 0) | (n ? N | S : 0));
    }
    // Taille (en mots) de l'instruction à l'adresse donnée : utile pour les sauts conditionnels (CPSE, SBRC…).
    size(pc) {
      const op = this.flash[pc & 0x3fff];
      return ((op & 0xfe0e) === 0x940c || (op & 0xfe0e) === 0x940e || (op & 0xfe0f) === 0x9000 || (op & 0xfe0f) === 0x9200) ? 2 : 1;
    }
    skip() { this.pc = (this.pc + this.size(this.pc)) & 0x3fff; this.tick(1); }

    // ---------- une instruction ----------
    step() {
      if (this.halted) return 0;
      if (this.interrupts()) return 4;
      if (this.sleeping) { this.tick(1); return 1; }
      const before = this.cycles;
      const pc = this.pc;
      const op = this.flash[pc];
      this.pc = (pc + 1) & 0x3fff;
      const r = this.data;
      const d5 = (op >> 4) & 0x1f, r5 = (op & 0xf) | ((op >> 5) & 0x10);
      const d4 = 16 + ((op >> 4) & 0xf), k8 = (op & 0xf) | ((op >> 4) & 0xf0);
      let cyc = 1;
      switch (op >> 12) {
        case 0x0: {
          if (op === 0) break; // NOP
          const sub = (op >> 10) & 3;
          if ((op & 0xff00) === 0x0100) { const d = ((op >> 4) & 0xf) * 2, s = (op & 0xf) * 2; r[d] = r[s]; r[d + 1] = r[s + 1]; break; } // MOVW
          if ((op & 0xff00) === 0x0200) { // MULS
            const a = (r[d4] << 24) >> 24, b = (r[16 + (op & 0xf)] << 24) >> 24, p = (a * b) & 0xffff;
            r[0] = p & 0xff; r[1] = p >> 8; this.flags(C | Z, (p & 0x8000 ? C : 0) | (p === 0 ? Z : 0)); cyc = 2; break;
          }
          if (sub === 0) { this.fault(`instruction non prise en charge : 0x${op.toString(16).padStart(4, "0")}`); break; }
          const a = r[d5], b = r[r5], c = r[SREG] & C;
          if (sub === 1) { const res = (a - b - c) & 0xff; this.subFlags(a, b, res, true); break; } // CPC
          if (sub === 2) { const res = (a - b - c) & 0xff; this.subFlags(a, b, res, true); r[d5] = res; break; } // SBC
          { const res = (a + b) & 0xff; this.addFlags(a, b, res); r[d5] = res; break; } // ADD
        }
        case 0x1: {
          const sub = (op >> 10) & 3, a = r[d5], b = r[r5];
          if (sub === 0) { if (a === b) { this.skip(); cyc = 1; } break; } // CPSE
          if (sub === 1) { this.subFlags(a, b, (a - b) & 0xff); break; } // CP
          if (sub === 2) { const res = (a - b) & 0xff; this.subFlags(a, b, res); r[d5] = res; break; } // SUB
          { const res = (a + b + (r[SREG] & C)) & 0xff; this.addFlags(a, b, res); r[d5] = res; break; } // ADC
        }
        case 0x2: {
          const sub = (op >> 10) & 3;
          if (sub === 3) { r[d5] = r[r5]; break; } // MOV
          const res = sub === 0 ? r[d5] & r[r5] : sub === 1 ? r[d5] ^ r[r5] : r[d5] | r[r5];
          r[d5] = res; this.logicFlags(res); break;
        }
        case 0x3: { const a = r[d4]; this.subFlags(a, k8, (a - k8) & 0xff); break; } // CPI
        case 0x4: { const a = r[d4], res = (a - k8 - (r[SREG] & C)) & 0xff; this.subFlags(a, k8, res, true); r[d4] = res; break; } // SBCI
        case 0x5: { const a = r[d4], res = (a - k8) & 0xff; this.subFlags(a, k8, res); r[d4] = res; break; } // SUBI
        case 0x6: { const res = r[d4] | k8; r[d4] = res; this.logicFlags(res); break; } // ORI
        case 0x7: { const res = r[d4] & k8; r[d4] = res; this.logicFlags(res); break; } // ANDI
        case 0x8: case 0xa: { // LDD / STD avec Y+q ou Z+q
          const q = (op & 7) | ((op >> 7) & 0x18) | ((op >> 8) & 0x20);
          const base = op & 8 ? r[28] | (r[29] << 8) : r[30] | (r[31] << 8);
          if (op & 0x200) this.write(base + q, r[d5]); else r[d5] = this.read(base + q);
          cyc = 2; break;
        }
        case 0x9: cyc = this.exec9(op, d5, r5); break;
        case 0xb: { // IN / OUT
          const a = 0x20 + ((op & 0xf) | ((op >> 5) & 0x30));
          if (op & 0x800) this.write(a, r[d5]); else r[d5] = this.read(a);
          break;
        }
        case 0xc: case 0xd: { // RJMP / RCALL
          const k = ((op & 0xfff) << 20) >> 20;
          if (op & 0x1000) { this.pushPc(this.pc); cyc = 3; } else cyc = 2;
          if (k === -1 && !(op & 0x1000)) { if (!(r[SREG] & I)) this.sleeping = "boucle"; }
          this.pc = (this.pc + k) & 0x3fff;
          break;
        }
        case 0xe: r[d4] = k8; break; // LDI
        case 0xf: {
          const sub = (op >> 9) & 7;
          if (sub < 4) { // BRBS / BRBC
            const bit = op & 7, set = (r[SREG] >> bit) & 1;
            if (set === (op & 0x400 ? 0 : 1)) { this.pc = (this.pc + (((op >> 3) & 0x7f) << 25 >> 25)) & 0x3fff; cyc = 2; }
            break;
          }
          const bit = op & 7;
          if (sub === 4) { r[d5] = (r[d5] & ~(1 << bit)) | ((r[SREG] & T ? 1 : 0) << bit); break; } // BLD
          if (sub === 5) { this.flags(T, (r[d5] >> bit) & 1 ? T : 0); break; } // BST
          const v = (r[d5] >> bit) & 1;
          if ((sub === 6 && !v) || (sub === 7 && v)) this.skip(); // SBRC / SBRS
          break;
        }
        default: this.fault(`instruction non prise en charge : 0x${op.toString(16).padStart(4, "0")}`);
      }
      if (this.halted && this.halted !== true) this.pc = pc;
      this.tick(cyc);
      return this.cycles - before;
    }

    exec9(op, d5, r5) {
      const r = this.data;
      const X = () => r[26] | (r[27] << 8), Y = () => r[28] | (r[29] << 8), Zp = () => r[30] | (r[31] << 8);
      const setW = (lo, v) => { r[lo] = v & 0xff; r[lo + 1] = (v >> 8) & 0xff; };
      const hi = (op >> 8) & 0xf;
      if (hi <= 3) { // chargements et rangements
        const store = (op & 0x200) !== 0, mode = op & 0xf;
        if (mode === 0) { const k = this.flash[this.pc]; this.pc = (this.pc + 1) & 0x3fff; if (store) this.write(k, r[d5]); else r[d5] = this.read(k); return 2; } // LDS / STS
        if (mode === 0xf) { if (store) this.push(r[d5]); else r[d5] = this.pop(); return 2; } // PUSH / POP
        if (!store && (mode === 4 || mode === 5)) { // LPM Rd, Z(+)
          const z = Zp(), w = this.flash[(z >> 1) & 0x3fff];
          r[d5] = z & 1 ? w >> 8 : w & 0xff;
          if (mode === 5) setW(30, z + 1);
          return 3;
        }
        const ptr = { 1: [30, 1], 2: [30, -1], 9: [28, 1], 10: [28, -1], 12: [26, 0], 13: [26, 1], 14: [26, -1] }[mode];
        if (!ptr) { this.fault(`instruction non prise en charge : 0x${op.toString(16).padStart(4, "0")}`); return 1; }
        let a = r[ptr[0]] | (r[ptr[0] + 1] << 8);
        if (ptr[1] < 0) { a = (a - 1) & 0xffff; setW(ptr[0], a); }
        if (store) this.write(a, r[d5]); else r[d5] = this.read(a);
        if (ptr[1] > 0) setW(ptr[0], a + 1);
        void X; void Y;
        return 2;
      }
      if (hi === 4 || hi === 5) {
        const low = op & 0xf;
        if (low <= 7 && low !== 4) { // instructions à un registre
          const a = r[d5];
          let res;
          switch (low) {
            case 0: res = ~a & 0xff; this.logicFlags(res); this.flags(C, C); break; // COM
            case 1: res = (-a) & 0xff; this.subFlags(0, a, res); break; // NEG
            case 2: res = ((a << 4) | (a >> 4)) & 0xff; break; // SWAP
            case 3: res = (a + 1) & 0xff; { const n = res >> 7; const v = a === 0x7f; this.flags(Z | N | V | S, (res ? 0 : Z) | (n ? N : 0) | (v ? V : 0) | ((n ^ v) ? S : 0)); } break; // INC
            case 5: case 6: case 7: { // ASR / LSR / ROR
              const c = a & 1;
              res = low === 5 ? (a >> 1) | (a & 0x80) : low === 6 ? a >> 1 : (a >> 1) | ((r[0x5f] & C) << 7);
              const n = res >> 7 & 1, v = n ^ c;
              this.flags(C | Z | N | V | S, (c ? C : 0) | (res ? 0 : Z) | (n ? N : 0) | (v ? V : 0) | ((n ^ v) ? S : 0));
              break;
            }
            default: break;
          }
          r[d5] = res;
          return 1;
        }
        if (low === 0xa) { const a = r[d5], res = (a - 1) & 0xff, n = res >> 7, v = a === 0x80; this.flags(Z | N | V | S, (res ? 0 : Z) | (n ? N : 0) | (v ? V : 0) | ((n ^ v) ? S : 0)); r[d5] = res; return 1; } // DEC
        if ((op & 0xfe0e) === 0x940c || (op & 0xfe0e) === 0x940e) { // JMP / CALL
          const k = ((((op >> 4) & 0x1f) << 1 | (op & 1)) << 16) | this.flash[this.pc];
          this.pc = (this.pc + 1) & 0x3fff;
          if (op & 2) { this.pushPc(this.pc); this.pc = k & 0x3fff; return 4; }
          if ((k & 0x3fff) === ((this.pc - 2) & 0x3fff) && !(r[0x5f] & I)) this.sleeping = "boucle";
          this.pc = k & 0x3fff; return 3;
        }
        switch (op) {
          case 0x9409: this.pc = Zp() & 0x3fff; return 2; // IJMP
          case 0x9509: this.pushPc(this.pc); this.pc = Zp() & 0x3fff; return 3; // ICALL
          case 0x9508: this.pc = this.popPc(); return 4; // RET
          case 0x9518: this.pc = this.popPc(); r[0x5f] |= I; return 4; // RETI
          case 0x9588: this.sleeping = "sleep"; return 1; // SLEEP
          case 0x9598: this.halted = "BREAK : arrêt demandé par le programme"; return 1;
          case 0x95a8: return 1; // WDR
          case 0x95c8: { const z = Zp(), w = this.flash[(z >> 1) & 0x3fff]; r[0] = z & 1 ? w >> 8 : w & 0xff; return 3; } // LPM
          default: break;
        }
        if ((op & 0xff0f) === 0x9408) { const s = (op >> 4) & 7; r[0x5f] |= 1 << s; return 1; } // BSET
        if ((op & 0xff0f) === 0x9488) { const s = (op >> 4) & 7; r[0x5f] &= ~(1 << s); return 1; } // BCLR
        this.fault(`instruction non prise en charge : 0x${op.toString(16).padStart(4, "0")}`);
        return 1;
      }
      if (hi === 6 || hi === 7) { // ADIW / SBIW
        const d = 24 + ((op >> 4) & 3) * 2, k = (op & 0xf) | ((op >> 2) & 0x30);
        const a = r[d] | (r[d + 1] << 8);
        const res = (hi === 6 ? a + k : a - k) & 0xffff;
        const r15 = res >> 15, a15 = a >> 15;
        const v = hi === 6 ? (~a15 & r15) & 1 : (a15 & ~r15) & 1;
        const c = hi === 6 ? (~r15 & a15) & 1 : (r15 & ~a15) & 1;
        this.flags(C | Z | N | V | S, (c ? C : 0) | (res ? 0 : Z) | (r15 ? N : 0) | (v ? V : 0) | ((r15 ^ v) ? S : 0));
        setW(d, res);
        return 2;
      }
      if (hi >= 8 && hi <= 0xb) { // CBI / SBIC / SBI / SBIS
        const a = 0x20 + ((op >> 3) & 0x1f), bit = op & 7;
        if (hi === 8) { this.write(a, this.data[a] & ~(1 << bit)); return 2; }
        if (hi === 0xa) {
          if (a === 0x23 || a === 0x26 || a === 0x29) this.write(a, 1 << bit); else this.write(a, this.data[a] | (1 << bit));
          return 2;
        }
        const v = (this.read(a) >> bit) & 1;
        if ((hi === 9 && !v) || (hi === 0xb && v)) this.skip();
        return 1;
      }
      // MUL
      const p = (r[d5] * r[r5]) & 0xffff;
      r[0] = p & 0xff; r[1] = p >> 8;
      this.flags(C | Z, (p & 0x8000 ? C : 0) | (p ? 0 : Z));
      return 2;
    }

    // Avance de n cycles environ (une image d'affichage, par exemple). S'arrête sur une erreur.
    run(cycles) {
      const end = this.cycles + cycles;
      while (this.cycles < end && !this.halted) {
        if (this.sleeping) { // en sommeil ou bloqué sur « rjmp . » : on saute directement au prochain événement
          const div = PRESCALE[this.data[TCCR0B] & 7];
          if (!div || !(this.data[SREG] & I) || !(this.data[TIMSK0] & 3)) { this.tick(end - this.cycles); break; }
          this.tick(1);
          if (this.data[TIFR0] & this.data[TIMSK0]) this.sleeping = false;
          continue;
        }
        this.step();
      }
    }
    regs() {
      const r = this.data, s = r[SREG];
      const flags = "ITHSVNZC".split("").map((f, i) => (s & (128 >> i) ? f : "·")).join("");
      return { pc: this.pc, sp: this.sp, sreg: flags, r: Array.from(r.slice(0, 32)), cycles: this.cycles };
    }
  }

  root.AetherAVR = { AVR, PORTS };
})(typeof window !== "undefined" ? window : globalThis);
