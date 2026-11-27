"use strict";
// Processeur 6502 (variante 2A03 : pas de mode décimal) de l'atelier circuits. Précis à l'instruction près :
// cycles officiels, pénalités de page et de branchement, interruptions NMI et IRQ, instructions non officielles
// courantes. Vérifié contre la trace de référence nestest (voir tests/circuit_lab).
// Le bus est un objet { read(adresse), write(adresse, valeur) } fourni par la carte mère (c8_machine.js).
(function (root) {
  const FLAG = { C: 0x01, Z: 0x02, I: 0x04, D: 0x08, B: 0x10, U: 0x20, V: 0x40, N: 0x80 };

  // Table des opcodes : mnémonique, mode d'adressage, cycles de base, +1 si la page change (lectures).
  // Modes : imp acc imm zp zpx zpy abs abx aby ind izx izy rel.
  const OPS = new Array(256);
  function op(codes, name, mode, cycles, page = 0) {
    for (const code of [].concat(codes)) OPS[code] = { name, mode, cycles, page };
  }
  // ---------- officiels ----------
  op(0x69, "ADC", "imm", 2); op(0x65, "ADC", "zp", 3); op(0x75, "ADC", "zpx", 4); op(0x6d, "ADC", "abs", 4);
  op(0x7d, "ADC", "abx", 4, 1); op(0x79, "ADC", "aby", 4, 1); op(0x61, "ADC", "izx", 6); op(0x71, "ADC", "izy", 5, 1);
  op(0x29, "AND", "imm", 2); op(0x25, "AND", "zp", 3); op(0x35, "AND", "zpx", 4); op(0x2d, "AND", "abs", 4);
  op(0x3d, "AND", "abx", 4, 1); op(0x39, "AND", "aby", 4, 1); op(0x21, "AND", "izx", 6); op(0x31, "AND", "izy", 5, 1);
  op(0x0a, "ASL", "acc", 2); op(0x06, "ASL", "zp", 5); op(0x16, "ASL", "zpx", 6); op(0x0e, "ASL", "abs", 6); op(0x1e, "ASL", "abx", 7);
  op(0x90, "BCC", "rel", 2); op(0xb0, "BCS", "rel", 2); op(0xf0, "BEQ", "rel", 2); op(0x30, "BMI", "rel", 2);
  op(0xd0, "BNE", "rel", 2); op(0x10, "BPL", "rel", 2); op(0x50, "BVC", "rel", 2); op(0x70, "BVS", "rel", 2);
  op(0x24, "BIT", "zp", 3); op(0x2c, "BIT", "abs", 4);
  op(0x00, "BRK", "imp", 7);
  op(0x18, "CLC", "imp", 2); op(0xd8, "CLD", "imp", 2); op(0x58, "CLI", "imp", 2); op(0xb8, "CLV", "imp", 2);
  op(0xc9, "CMP", "imm", 2); op(0xc5, "CMP", "zp", 3); op(0xd5, "CMP", "zpx", 4); op(0xcd, "CMP", "abs", 4);
  op(0xdd, "CMP", "abx", 4, 1); op(0xd9, "CMP", "aby", 4, 1); op(0xc1, "CMP", "izx", 6); op(0xd1, "CMP", "izy", 5, 1);
  op(0xe0, "CPX", "imm", 2); op(0xe4, "CPX", "zp", 3); op(0xec, "CPX", "abs", 4);
  op(0xc0, "CPY", "imm", 2); op(0xc4, "CPY", "zp", 3); op(0xcc, "CPY", "abs", 4);
  op(0xc6, "DEC", "zp", 5); op(0xd6, "DEC", "zpx", 6); op(0xce, "DEC", "abs", 6); op(0xde, "DEC", "abx", 7);
  op(0xca, "DEX", "imp", 2); op(0x88, "DEY", "imp", 2);
  op(0x49, "EOR", "imm", 2); op(0x45, "EOR", "zp", 3); op(0x55, "EOR", "zpx", 4); op(0x4d, "EOR", "abs", 4);
  op(0x5d, "EOR", "abx", 4, 1); op(0x59, "EOR", "aby", 4, 1); op(0x41, "EOR", "izx", 6); op(0x51, "EOR", "izy", 5, 1);
  op(0xe6, "INC", "zp", 5); op(0xf6, "INC", "zpx", 6); op(0xee, "INC", "abs", 6); op(0xfe, "INC", "abx", 7);
  op(0xe8, "INX", "imp", 2); op(0xc8, "INY", "imp", 2);
  op(0x4c, "JMP", "abs", 3); op(0x6c, "JMP", "ind", 5); op(0x20, "JSR", "abs", 6);
  op(0xa9, "LDA", "imm", 2); op(0xa5, "LDA", "zp", 3); op(0xb5, "LDA", "zpx", 4); op(0xad, "LDA", "abs", 4);
  op(0xbd, "LDA", "abx", 4, 1); op(0xb9, "LDA", "aby", 4, 1); op(0xa1, "LDA", "izx", 6); op(0xb1, "LDA", "izy", 5, 1);
  op(0xa2, "LDX", "imm", 2); op(0xa6, "LDX", "zp", 3); op(0xb6, "LDX", "zpy", 4); op(0xae, "LDX", "abs", 4); op(0xbe, "LDX", "aby", 4, 1);
  op(0xa0, "LDY", "imm", 2); op(0xa4, "LDY", "zp", 3); op(0xb4, "LDY", "zpx", 4); op(0xac, "LDY", "abs", 4); op(0xbc, "LDY", "abx", 4, 1);
  op(0x4a, "LSR", "acc", 2); op(0x46, "LSR", "zp", 5); op(0x56, "LSR", "zpx", 6); op(0x4e, "LSR", "abs", 6); op(0x5e, "LSR", "abx", 7);
  op(0xea, "NOP", "imp", 2);
  op(0x09, "ORA", "imm", 2); op(0x05, "ORA", "zp", 3); op(0x15, "ORA", "zpx", 4); op(0x0d, "ORA", "abs", 4);
  op(0x1d, "ORA", "abx", 4, 1); op(0x19, "ORA", "aby", 4, 1); op(0x01, "ORA", "izx", 6); op(0x11, "ORA", "izy", 5, 1);
  op(0x48, "PHA", "imp", 3); op(0x08, "PHP", "imp", 3); op(0x68, "PLA", "imp", 4); op(0x28, "PLP", "imp", 4);
  op(0x2a, "ROL", "acc", 2); op(0x26, "ROL", "zp", 5); op(0x36, "ROL", "zpx", 6); op(0x2e, "ROL", "abs", 6); op(0x3e, "ROL", "abx", 7);
  op(0x6a, "ROR", "acc", 2); op(0x66, "ROR", "zp", 5); op(0x76, "ROR", "zpx", 6); op(0x6e, "ROR", "abs", 6); op(0x7e, "ROR", "abx", 7);
  op(0x40, "RTI", "imp", 6); op(0x60, "RTS", "imp", 6);
  op(0xe9, "SBC", "imm", 2); op(0xe5, "SBC", "zp", 3); op(0xf5, "SBC", "zpx", 4); op(0xed, "SBC", "abs", 4);
  op(0xfd, "SBC", "abx", 4, 1); op(0xf9, "SBC", "aby", 4, 1); op(0xe1, "SBC", "izx", 6); op(0xf1, "SBC", "izy", 5, 1);
  op(0x38, "SEC", "imp", 2); op(0xf8, "SED", "imp", 2); op(0x78, "SEI", "imp", 2);
  op(0x85, "STA", "zp", 3); op(0x95, "STA", "zpx", 4); op(0x8d, "STA", "abs", 4); op(0x9d, "STA", "abx", 5);
  op(0x99, "STA", "aby", 5); op(0x81, "STA", "izx", 6); op(0x91, "STA", "izy", 6);
  op(0x86, "STX", "zp", 3); op(0x96, "STX", "zpy", 4); op(0x8e, "STX", "abs", 4);
  op(0x84, "STY", "zp", 3); op(0x94, "STY", "zpx", 4); op(0x8c, "STY", "abs", 4);
  op(0xaa, "TAX", "imp", 2); op(0xa8, "TAY", "imp", 2); op(0xba, "TSX", "imp", 2);
  op(0x8a, "TXA", "imp", 2); op(0x9a, "TXS", "imp", 2); op(0x98, "TYA", "imp", 2);
  // ---------- non officiels (stables, utilisés par certains jeux et par nestest) ----------
  op([0x1a, 0x3a, 0x5a, 0x7a, 0xda, 0xfa], "*NOP", "imp", 2);
  op([0x80, 0x82, 0x89, 0xc2, 0xe2], "*NOP", "imm", 2);
  op([0x04, 0x44, 0x64], "*NOP", "zp", 3);
  op([0x14, 0x34, 0x54, 0x74, 0xd4, 0xf4], "*NOP", "zpx", 4);
  op(0x0c, "*NOP", "abs", 4);
  op([0x1c, 0x3c, 0x5c, 0x7c, 0xdc, 0xfc], "*NOP", "abx", 4, 1);
  op(0xa7, "*LAX", "zp", 3); op(0xb7, "*LAX", "zpy", 4); op(0xaf, "*LAX", "abs", 4); op(0xbf, "*LAX", "aby", 4, 1);
  op(0xa3, "*LAX", "izx", 6); op(0xb3, "*LAX", "izy", 5, 1);
  op(0x87, "*SAX", "zp", 3); op(0x97, "*SAX", "zpy", 4); op(0x8f, "*SAX", "abs", 4); op(0x83, "*SAX", "izx", 6);
  op(0xeb, "*SBC", "imm", 2);
  for (const [name, base] of [["*SLO", 0x00], ["*RLA", 0x20], ["*SRE", 0x40], ["*RRA", 0x60], ["*DCP", 0xc0], ["*ISB", 0xe0]]) {
    op(base + 0x07, name, "zp", 5); op(base + 0x17, name, "zpx", 6); op(base + 0x0f, name, "abs", 6);
    op(base + 0x1f, name, "abx", 7); op(base + 0x1b, name, "aby", 7); op(base + 0x03, name, "izx", 8); op(base + 0x13, name, "izy", 8);
  }
  const SIZE = { imp: 1, acc: 1, imm: 2, zp: 2, zpx: 2, zpy: 2, rel: 2, izx: 2, izy: 2, abs: 3, abx: 3, aby: 3, ind: 3 };

  class CPU6502 {
    constructor(bus) {
      this.bus = bus;
      this.a = 0; this.x = 0; this.y = 0; this.sp = 0xfd; this.p = 0x24; this.pc = 0;
      this.cycles = 0;        // cycles écoulés depuis la mise sous tension
      this.stall = 0;         // cycles volés (copie OAM par DMA)
      this.nmi = false;       // front de NMI en attente
      this.irq = false;       // ligne IRQ (niveau)
      this.jammed = false;    // opcode inconnu : le processeur se bloque (comme un vrai 6502 sur KIL)
    }
    read(addr) { return this.bus.read(addr & 0xffff); }
    write(addr, value) { this.bus.write(addr & 0xffff, value & 0xff); }
    read16(addr) { return this.read(addr) | (this.read(addr + 1) << 8); }
    push(v) { this.write(0x100 | this.sp, v); this.sp = (this.sp - 1) & 0xff; }
    pull() { this.sp = (this.sp + 1) & 0xff; return this.read(0x100 | this.sp); }
    flag(f, on) { if (on) this.p |= f; else this.p &= ~f; }
    nz(v) { this.flag(FLAG.Z, (v & 0xff) === 0); this.flag(FLAG.N, v & 0x80); return v & 0xff; }

    reset() {
      this.pc = this.read16(0xfffc);
      this.sp = (this.sp - 3) & 0xff;
      this.p |= FLAG.I;
      this.cycles += 7;
      this.jammed = false;
    }
    powerOn() {
      this.a = 0; this.x = 0; this.y = 0; this.sp = 0x00; this.p = 0x24; this.cycles = 0;
      this.reset();  // sp : 0x00 - 3 = 0xfd
    }
    interrupt(vector, brk) {
      this.push(this.pc >> 8); this.push(this.pc & 0xff);
      this.push((this.p | FLAG.U | (brk ? FLAG.B : 0)) & ~(brk ? 0 : FLAG.B));
      this.p |= FLAG.I;
      this.pc = this.read16(vector);
      return 7;
    }

    // Adresse effective et changement de page pour l'opcode courant ; avance pc.
    address(mode) {
      let addr = 0, crossed = false;
      switch (mode) {
        case "imm": addr = this.pc; this.pc = (this.pc + 1) & 0xffff; break;
        case "zp": addr = this.read(this.pc); this.pc = (this.pc + 1) & 0xffff; break;
        case "zpx": addr = (this.read(this.pc) + this.x) & 0xff; this.pc = (this.pc + 1) & 0xffff; break;
        case "zpy": addr = (this.read(this.pc) + this.y) & 0xff; this.pc = (this.pc + 1) & 0xffff; break;
        case "abs": addr = this.read16(this.pc); this.pc = (this.pc + 2) & 0xffff; break;
        case "abx": { const base = this.read16(this.pc); this.pc = (this.pc + 2) & 0xffff;
          addr = (base + this.x) & 0xffff; crossed = (base & 0xff00) !== (addr & 0xff00); break; }
        case "aby": { const base = this.read16(this.pc); this.pc = (this.pc + 2) & 0xffff;
          addr = (base + this.y) & 0xffff; crossed = (base & 0xff00) !== (addr & 0xff00); break; }
        case "ind": { const ptr = this.read16(this.pc); this.pc = (this.pc + 2) & 0xffff;
          // défaut du 6502 : l'octet fort est lu dans la même page
          addr = this.read(ptr) | (this.read((ptr & 0xff00) | ((ptr + 1) & 0xff)) << 8); break; }
        case "izx": { const zp = (this.read(this.pc) + this.x) & 0xff; this.pc = (this.pc + 1) & 0xffff;
          addr = this.read(zp) | (this.read((zp + 1) & 0xff) << 8); break; }
        case "izy": { const zp = this.read(this.pc); this.pc = (this.pc + 1) & 0xffff;
          const base = this.read(zp) | (this.read((zp + 1) & 0xff) << 8);
          addr = (base + this.y) & 0xffff; crossed = (base & 0xff00) !== (addr & 0xff00); break; }
        case "rel": { const off = this.read(this.pc); this.pc = (this.pc + 1) & 0xffff;
          addr = (this.pc + (off < 0x80 ? off : off - 0x100)) & 0xffff; break; }
        default: break;
      }
      return [addr, crossed];
    }

    adc(v) {
      const sum = this.a + v + (this.p & FLAG.C);
      this.flag(FLAG.C, sum > 0xff);
      this.flag(FLAG.V, (~(this.a ^ v) & (this.a ^ sum)) & 0x80);
      this.a = this.nz(sum);
    }
    compare(reg, v) { this.flag(FLAG.C, reg >= v); this.nz(reg - v); }
    asl(v) { this.flag(FLAG.C, v & 0x80); return this.nz(v << 1); }
    lsr(v) { this.flag(FLAG.C, v & 1); return this.nz(v >> 1); }
    rol(v) { const c = this.p & FLAG.C; this.flag(FLAG.C, v & 0x80); return this.nz((v << 1) | c); }
    ror(v) { const c = this.p & FLAG.C; this.flag(FLAG.C, v & 1); return this.nz((v >> 1) | (c << 7)); }

    // Exécute une instruction (ou une interruption) ; rend le nombre de cycles.
    step() {
      if (this.stall > 0) { const s = this.stall; this.stall = 0; this.cycles += s; return s; }
      if (this.jammed) { this.cycles += 2; return 2; }
      if (this.nmi) { this.nmi = false; const c = this.interrupt(0xfffa, false); this.cycles += c; return c; }
      if (this.irq && !(this.p & FLAG.I)) { const c = this.interrupt(0xfffe, false); this.cycles += c; return c; }
      const code = this.read(this.pc);
      const info = OPS[code];
      if (!info) { this.jammed = true; this.cycles += 2; return 2; }
      this.pc = (this.pc + 1) & 0xffff;
      let cycles = info.cycles;
      const mode = info.mode;
      let addr = 0, crossed = false;
      if (mode !== "imp" && mode !== "acc") [addr, crossed] = this.address(mode);
      if (crossed && info.page) cycles += 1;
      const branch = (cond) => {
        if (!cond) return;
        cycles += ((this.pc & 0xff00) !== (addr & 0xff00)) ? 2 : 1;
        this.pc = addr;
      };
      const modify = (fn) => { const v = fn(this.read(addr)); this.write(addr, v); return v; };
      switch (info.name) {
        case "ADC": this.adc(this.read(addr)); break;
        case "SBC": case "*SBC": this.adc(this.read(addr) ^ 0xff); break;
        case "AND": this.a = this.nz(this.a & this.read(addr)); break;
        case "ORA": this.a = this.nz(this.a | this.read(addr)); break;
        case "EOR": this.a = this.nz(this.a ^ this.read(addr)); break;
        case "ASL": if (mode === "acc") this.a = this.asl(this.a); else modify((v) => this.asl(v)); break;
        case "LSR": if (mode === "acc") this.a = this.lsr(this.a); else modify((v) => this.lsr(v)); break;
        case "ROL": if (mode === "acc") this.a = this.rol(this.a); else modify((v) => this.rol(v)); break;
        case "ROR": if (mode === "acc") this.a = this.ror(this.a); else modify((v) => this.ror(v)); break;
        case "BCC": branch(!(this.p & FLAG.C)); break;
        case "BCS": branch(this.p & FLAG.C); break;
        case "BEQ": branch(this.p & FLAG.Z); break;
        case "BNE": branch(!(this.p & FLAG.Z)); break;
        case "BMI": branch(this.p & FLAG.N); break;
        case "BPL": branch(!(this.p & FLAG.N)); break;
        case "BVC": branch(!(this.p & FLAG.V)); break;
        case "BVS": branch(this.p & FLAG.V); break;
        case "BIT": { const v = this.read(addr);
          this.flag(FLAG.Z, (this.a & v) === 0); this.flag(FLAG.V, v & 0x40); this.flag(FLAG.N, v & 0x80); break; }
        case "BRK": this.pc = (this.pc + 1) & 0xffff; this.interrupt(0xfffe, true); break;
        case "CLC": this.p &= ~FLAG.C; break;
        case "CLD": this.p &= ~FLAG.D; break;
        case "CLI": this.p &= ~FLAG.I; break;
        case "CLV": this.p &= ~FLAG.V; break;
        case "SEC": this.p |= FLAG.C; break;
        case "SED": this.p |= FLAG.D; break;
        case "SEI": this.p |= FLAG.I; break;
        case "CMP": this.compare(this.a, this.read(addr)); break;
        case "CPX": this.compare(this.x, this.read(addr)); break;
        case "CPY": this.compare(this.y, this.read(addr)); break;
        case "DEC": modify((v) => this.nz(v - 1)); break;
        case "INC": modify((v) => this.nz(v + 1)); break;
        case "DEX": this.x = this.nz(this.x - 1); break;
        case "DEY": this.y = this.nz(this.y - 1); break;
        case "INX": this.x = this.nz(this.x + 1); break;
        case "INY": this.y = this.nz(this.y + 1); break;
        case "JMP": this.pc = addr; break;
        case "JSR": { const ret = (this.pc - 1) & 0xffff; this.push(ret >> 8); this.push(ret & 0xff); this.pc = addr; break; }
        case "RTS": this.pc = ((this.pull() | (this.pull() << 8)) + 1) & 0xffff; break;
        case "RTI": this.p = (this.pull() & ~FLAG.B) | FLAG.U; this.pc = this.pull() | (this.pull() << 8); break;
        case "LDA": this.a = this.nz(this.read(addr)); break;
        case "LDX": this.x = this.nz(this.read(addr)); break;
        case "LDY": this.y = this.nz(this.read(addr)); break;
        case "STA": this.write(addr, this.a); break;
        case "STX": this.write(addr, this.x); break;
        case "STY": this.write(addr, this.y); break;
        case "PHA": this.push(this.a); break;
        case "PHP": this.push(this.p | FLAG.B | FLAG.U); break;
        case "PLA": this.a = this.nz(this.pull()); break;
        case "PLP": this.p = (this.pull() & ~FLAG.B) | FLAG.U; break;
        case "TAX": this.x = this.nz(this.a); break;
        case "TAY": this.y = this.nz(this.a); break;
        case "TSX": this.x = this.nz(this.sp); break;
        case "TXA": this.a = this.nz(this.x); break;
        case "TXS": this.sp = this.x; break;
        case "TYA": this.a = this.nz(this.y); break;
        case "NOP": case "*NOP": if (mode !== "imp") this.read(addr); break;
        case "*LAX": this.a = this.x = this.nz(this.read(addr)); break;
        case "*SAX": this.write(addr, this.a & this.x); break;
        case "*SLO": this.a = this.nz(this.a | modify((v) => this.asl(v))); break;
        case "*RLA": this.a = this.nz(this.a & modify((v) => this.rol(v))); break;
        case "*SRE": this.a = this.nz(this.a ^ modify((v) => this.lsr(v))); break;
        case "*RRA": this.adc(modify((v) => this.ror(v))); break;
        case "*DCP": this.compare(this.a, modify((v) => (v - 1) & 0xff)); break;
        case "*ISB": this.adc(modify((v) => (v + 1) & 0xff) ^ 0xff); break;
        default: break;
      }
      this.cycles += cycles;
      return cycles;
    }

    // Désassemble l'instruction à `addr` (débogueur de l'atelier) : { text, size }.
    disassemble(addr, peek = (a) => this.read(a)) {
      const code = peek(addr);
      const info = OPS[code];
      if (!info) return { text: `.byte $${hex(code)}`, size: 1 };
      const size = SIZE[info.mode];
      const lo = peek((addr + 1) & 0xffff), hi = peek((addr + 2) & 0xffff), w = lo | (hi << 8);
      const name = info.name.replace("*", "");
      const arg = {
        imp: "", acc: " A", imm: ` #$${hex(lo)}`, zp: ` $${hex(lo)}`, zpx: ` $${hex(lo)},X`, zpy: ` $${hex(lo)},Y`,
        abs: ` $${hex(w, 4)}`, abx: ` $${hex(w, 4)},X`, aby: ` $${hex(w, 4)},Y`, ind: ` ($${hex(w, 4)})`,
        izx: ` ($${hex(lo)},X)`, izy: ` ($${hex(lo)}),Y`,
        rel: ` $${hex((addr + 2 + (lo < 0x80 ? lo : lo - 0x100)) & 0xffff, 4)}`,
      }[info.mode];
      return { text: name + arg, size };
    }
  }
  function hex(v, n = 2) { return v.toString(16).toUpperCase().padStart(n, "0"); }

  root.AetherCPU = { CPU6502, OPS, SIZE, FLAG, hex };
})(typeof window !== "undefined" ? window : globalThis);
