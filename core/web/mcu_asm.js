"use strict";
// Assembleurs des cartes à microcontrôleur de l'Atelier circuits Æther, sans dépendance :
//   - AVR 8 bits (ATmega328P) : syntaxe proche d'avra/avrasm (.org, .equ, .def, .db, .dw, low(), high()) ;
//   - ARM Thumb (Cortex-M0+ du RP2040) : syntaxe unifiée de GNU as (movs, ldr r0, =valeur, push {r4, lr}, .word…).
// Deux passes : la première mesure chaque ligne et place les étiquettes, la seconde encode. Chaque erreur donne la
// ligne et un message en français. Le résultat garde aussi la correspondance adresse → ligne pour le débogueur.
(function (root) {
  class AsmError extends Error {}

  // ---------- expressions ----------
  const FUNCS = {
    low: (v) => v & 0xff, lo8: (v) => v & 0xff, byte1: (v) => v & 0xff,
    high: (v) => (v >> 8) & 0xff, hi8: (v) => (v >> 8) & 0xff, byte2: (v) => (v >> 8) & 0xff,
    byte3: (v) => (v >> 16) & 0xff, bv: (v) => 1 << v, exp2: (v) => 2 ** v,
  };
  function tokenize(text) {
    const out = [];
    const re = /\s*(0x[0-9a-f]+|0b[01]+|\$[0-9a-f]+|\d+|'(?:\\.|[^'])'|[a-z_.][\w.]*|<<|>>|[-+*/%&|^~!()])/giy;
    let m, last = 0;
    while (last < text.length && (m = re.exec(text)) !== null) { out.push(m[1]); last = re.lastIndex; }
    if (text.slice(last).trim()) throw new AsmError(`expression illisible près de « ${text.slice(last).trim()} »`);
    return out;
  }
  function evaluate(text, lookup) {
    const tokens = tokenize(text);
    if (!tokens.length) throw new AsmError("valeur manquante");
    let i = 0, unknown = null;
    const peek = () => tokens[i], next = () => tokens[i++];
    function atom() {
      const t = next();
      if (t === undefined) throw new AsmError("expression incomplète");
      if (t === "(") { const v = binary(0); if (next() !== ")") throw new AsmError("parenthèse « ) » manquante"); return v; }
      if (t === "-") return -atom();
      if (t === "+") return atom();
      if (t === "~") return ~atom();
      if (t === "!") return atom() ? 0 : 1;
      if (/^0x/i.test(t)) return parseInt(t.slice(2), 16);
      if (/^0b/i.test(t)) return parseInt(t.slice(2), 2);
      if (t[0] === "$") return parseInt(t.slice(1), 16);
      if (/^\d/.test(t)) return parseInt(t, 10);
      if (t[0] === "'") return t[1] === "\\" ? ({ n: 10, r: 13, t: 9, 0: 0 }[t[2]] ?? t.charCodeAt(2)) : t.charCodeAt(1);
      const fn = FUNCS[t.toLowerCase()];
      if (fn && peek() === "(") { next(); const v = binary(0); if (next() !== ")") throw new AsmError("parenthèse « ) » manquante"); return fn(v); }
      const v = lookup(t);
      if (v === undefined) { unknown = unknown || t; return 0; }
      return v;
    }
    const PRIO = { "|": 1, "^": 2, "&": 3, "<<": 4, ">>": 4, "+": 5, "-": 5, "*": 6, "/": 6, "%": 6 };
    function binary(min) {
      let left = atom();
      while (peek() in PRIO && PRIO[peek()] >= min) {
        const o = next(), right = binary(PRIO[o] + 1);
        switch (o) {
          case "+": left += right; break; case "-": left -= right; break; case "*": left *= right; break;
          case "/": left = right ? Math.trunc(left / right) : 0; break; case "%": left = right ? left % right : 0; break;
          case "&": left &= right; break; case "|": left |= right; break; case "^": left ^= right; break;
          case "<<": left <<= right; break; case ">>": left >>= right; break; default: break;
        }
      }
      return left;
    }
    const value = binary(0);
    if (i < tokens.length) throw new AsmError(`« ${tokens[i]} » inattendu dans l'expression`);
    return { value, unknown };
  }

  // ---------- découpe des lignes ----------
  function stripComment(line, marks) {
    let quote = null;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (quote) { if (ch === "\\") i++; else if (ch === quote) quote = null; continue; }
      if (ch === '"' || (ch === "'" && line[i + 2] === "'")) { quote = ch; continue; }
      for (const m of marks) if (line.startsWith(m, i)) return line.slice(0, i);
    }
    return line;
  }
  function splitArgs(text) {
    const out = [];
    let cur = "", depth = 0, quote = null;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (quote) { cur += ch; if (ch === "\\") { cur += text[++i] || ""; } else if (ch === quote) quote = null; continue; }
      if (ch === '"') { quote = ch; cur += ch; continue; }
      if (ch === "'" && text[i + 2] === "'") { cur += text.slice(i, i + 3); i += 2; continue; }
      if (ch === "[" || ch === "{" || ch === "(") depth++;
      if (ch === "]" || ch === "}" || ch === ")") depth--;
      if (ch === "," && depth === 0) { out.push(cur.trim()); cur = ""; continue; }
      cur += ch;
    }
    if (cur.trim() || out.length) out.push(cur.trim());
    return out;
  }
  function parse(source, marks) {
    const rows = [];
    source.split(/\r?\n/).forEach((raw, k) => {
      let text = stripComment(raw, marks).trim();
      const row = { line: k + 1, labels: [], op: "", args: [], raw: text };
      let m;
      while ((m = /^([a-z_.][\w.]*)\s*:/i.exec(text))) { row.labels.push(m[1]); text = text.slice(m[0].length).trim(); }
      if ((m = /^([a-z_][\w.]*)\s*=\s*(.+)$/i.exec(text))) { row.op = ".equ"; row.args = [m[1], m[2]]; }
      else if (text) {
        m = /^(\S+)\s*(.*)$/.exec(text);
        row.op = m[1].toLowerCase();
        row.rest = m[2];
        row.args = splitArgs(m[2]);
      }
      if (row.labels.length || row.op) rows.push(row);
    });
    return rows;
  }
  function strBytes(arg) {
    const m = /^"((?:\\.|[^"])*)"$/.exec(arg);
    if (!m) return null;
    const out = [];
    for (let i = 0; i < m[1].length; i++) {
      let c = m[1][i];
      if (c === "\\") { c = m[1][++i]; out.push({ n: 10, r: 13, t: 9, 0: 0, '"': 34, "\\": 92 }[c] ?? c.charCodeAt(0)); }
      else out.push(m[1].charCodeAt(i) & 0xff);
    }
    return out;
  }

  // Moteur commun : unit = taille de l'adresse (2 octets par mot pour l'AVR, 1 octet pour l'ARM).
  function assembleWith(source, cpu) {
    const rows = parse(source, cpu.comments);
    const symbols = new Map(Object.entries(cpu.predefined).map(([k, v]) => [k.toLowerCase(), v]));
    const defs = new Map();
    const errors = [];
    let pass = 1;
    const lookup = (name) => symbols.get(name.toLowerCase());
    const ctx = { cpu, symbols, defs, lookup, pass, pools: [] };
    const value = (text, here) => {
      const r = evaluate(text.replace(/^#/, ""), (n) => (n === "." ? here : lookup(n)));
      if (r.unknown && ctx.pass === 2) throw new AsmError(`symbole inconnu : ${r.unknown}`);
      return r.value;
    };
    ctx.value = value;
    let bytes = null, lines = null;
    for (pass = 1; pass <= 2; pass++) {
      ctx.pass = pass;
      ctx.poolIndex = 0;
      cpu.begin(ctx);
      let pc = cpu.base;
      const out = new Map();
      lines = new Map();
      for (const row of rows) {
        try {
          for (const label of row.labels) {
            const key = label.toLowerCase();
            if (pass === 1 && symbols.has(key) && !(key in cpu.predefinedLower)) throw new AsmError(`étiquette « ${label} » déjà définie`);
            symbols.set(key, pc);
          }
          if (!row.op) continue;
          if (row.op === ".equ" || row.op === ".set") {
            const [name, expr] = row.args.length === 2 ? row.args : (row.rest || "").split("=").map((s) => s.trim());
            if (!name || expr === undefined) throw new AsmError(".equ attend un nom et une valeur");
            symbols.set(name.toLowerCase(), value(expr, pc));
            continue;
          }
          const emitted = cpu.line(row, pc, ctx);
          if (emitted.org !== undefined) { pc = emitted.org; continue; }
          if (emitted.bytes && emitted.bytes.length) {
            if (cpu.isCode(row.op)) lines.set(pc, row.line);
            const at = (pc - cpu.base) * cpu.unit;
            emitted.bytes.forEach((b, k) => out.set(at + k, b & 0xff));
          }
          pc += emitted.size;
        } catch (e) {
          if (!(e instanceof AsmError)) throw e;
          if (pass === 2 || !/symbole inconnu/.test(e.message)) errors.push({ line: row.line, message: e.message });
          if (pass === 1) continue;
        }
      }
      const tail = cpu.end ? cpu.end(pc, ctx, out) : null;
      if (tail) pc = tail;
      bytes = out;
      ctx.end = pc;
    }
    const seen = new Set();
    const unique = errors.filter((e) => { const k = `${e.line}:${e.message}`; if (seen.has(k)) return false; seen.add(k); return true; });
    let size = 0;
    for (const k of (bytes || new Map()).keys()) size = Math.max(size, k + 1);
    const image = new Uint8Array(size);
    for (const [k, v] of bytes || new Map()) image[k] = v;
    const sym = {};
    for (const [k, v] of symbols) if (!(k in cpu.predefinedLower)) sym[k] = v;
    return { ok: unique.length === 0, errors: unique.sort((a, b) => a.line - b.line), image, lines, symbols: sym,
             entry: cpu.entry ? cpu.entry(symbols) : cpu.base, base: cpu.base };
  }
  function prep(cpu) {
    cpu.predefinedLower = {};
    for (const k of Object.keys(cpu.predefined)) cpu.predefinedLower[k.toLowerCase()] = true;
    return cpu;
  }

  // =====================================================================================================
  // AVR
  // =====================================================================================================
  const AVR_IO = {
    PINB: 0x03, DDRB: 0x04, PORTB: 0x05, PINC: 0x06, DDRC: 0x07, PORTC: 0x08, PIND: 0x09, DDRD: 0x0a, PORTD: 0x0b,
    TIFR0: 0x15, GPIOR0: 0x1e, TCCR0A: 0x24, TCCR0B: 0x25, TCNT0: 0x26, OCR0A: 0x27, OCR0B: 0x28,
    SPL: 0x3d, SPH: 0x3e, SREG: 0x3f, TIMSK0: 0x6e, RAMSTART: 0x100, RAMEND: 0x8ff, FLASHEND: 0x3fff,
    TOV0: 0, OCF0A: 1, TOIE0: 0, OCIE0A: 1, CS00: 0, CS01: 1, CS02: 2, WGM00: 0, WGM01: 1,
    OC0Aaddr: 0x1c, OVF0addr: 0x20, INT_VECTORS_SIZE: 0x34,
    XL: 26, XH: 27, YL: 28, YH: 29, ZL: 30, ZH: 31,
  };
  for (let i = 0; i < 8; i++) { AVR_IO[`PB${i}`] = i; AVR_IO[`PC${i}`] = i; AVR_IO[`PD${i}`] = i; }
  for (let i = 0; i < 8; i++) { AVR_IO[`PINB${i}`] = i; AVR_IO[`PORTB${i}`] = i; AVR_IO[`DDB${i}`] = i; AVR_IO[`PORTD${i}`] = i; AVR_IO[`DDD${i}`] = i; AVR_IO[`PORTC${i}`] = i; AVR_IO[`DDC${i}`] = i; }
  const TWO = { cpc: 0x0400, sbc: 0x0800, add: 0x0c00, cpse: 0x1000, cp: 0x1400, sub: 0x1800, adc: 0x1c00,
                and: 0x2000, eor: 0x2400, or: 0x2800, mov: 0x2c00, mul: 0x9c00 };
  const IMM = { cpi: 0x3000, sbci: 0x4000, subi: 0x5000, ori: 0x6000, sbr: 0x6000, andi: 0x7000, ldi: 0xe000 };
  const ONE = { com: 0, neg: 1, swap: 2, inc: 3, asr: 5, lsr: 6, ror: 7, dec: 10 };
  const BR = { brcs: [0, 1], brlo: [0, 1], brcc: [0, 0], brsh: [0, 0], breq: [1, 1], brne: [1, 0], brmi: [2, 1],
               brpl: [2, 0], brvs: [3, 1], brvc: [3, 0], brlt: [4, 1], brge: [4, 0], brhs: [5, 1], brhc: [5, 0],
               brts: [6, 1], brtc: [6, 0], brie: [7, 1], brid: [7, 0] };
  const FLAGS = "czn vsh ti".replace(/ /g, "");
  const PLAIN = { nop: 0x0000, ret: 0x9508, reti: 0x9518, sleep: 0x9588, break: 0x9598, wdr: 0x95a8, ijmp: 0x9409,
                  icall: 0x9509, lpm: 0x95c8 };
  const LD_PTR = { x: 0x900c, "x+": 0x900d, "-x": 0x900e, y: 0x8008, "y+": 0x9009, "-y": 0x900a, z: 0x8000, "z+": 0x9001, "-z": 0x9002 };
  const AVR = prep({
    base: 0, unit: 2, comments: [";", "//"], predefined: AVR_IO,
    begin(ctx) { ctx.defs.clear(); },
    isCode: (op) => op[0] !== ".",
    reg(text, ctx) {
      const t = text.trim().toLowerCase();
      const alias = ctx.defs.get(t) || { xl: "r26", xh: "r27", yl: "r28", yh: "r29", zl: "r30", zh: "r31" }[t];
      const m = /^r(\d+)$/.exec(alias || t);
      if (!m || Number(m[1]) > 31) throw new AsmError(`registre attendu (r0 à r31) au lieu de « ${text} »`);
      return Number(m[1]);
    },
    line(row, pc, ctx) {
      const op = row.op, a = row.args, v = (t) => ctx.value(t, pc);
      const reg = (t) => this.reg(t, ctx);
      const need = (n) => { if (a.length !== n) throw new AsmError(`${op} attend ${n} opérande${n > 1 ? "s" : ""}`); };
      const range = (x, lo, hi, what) => { if (ctx.pass === 2 && (x < lo || x > hi)) throw new AsmError(`${what} hors limites (${lo} à ${hi}) : ${x}`); return x; };
      const words = (...w) => ({ size: w.length, bytes: w.flatMap((x) => [x & 0xff, (x >> 8) & 0xff]) });
      const hiReg = (t) => { const r = reg(t); if (r < 16) throw new AsmError(`${op} n'accepte que r16 à r31`); return r - 16; };
      if (op === ".org") { need(1); return { org: v(a[0]) }; }
      if (op === ".def") {
        const [name, r] = (row.rest || "").split("=").map((s) => s.trim());
        if (!name || !r) throw new AsmError(".def attend « nom = registre »");
        ctx.defs.set(name.toLowerCase(), `r${reg(r)}`);
        return { size: 0 };
      }
      if ([".device", ".include", ".cseg", ".list", ".nolist", ".text", ".global", ".globl"].includes(op)) return { size: 0 };
      if (op === ".db" || op === ".byte") {
        const out = [];
        for (const arg of a) { const s = strBytes(arg); if (s) out.push(...s); else out.push(range(v(arg), -128, 255, "octet") & 0xff); }
        if (out.length & 1) out.push(0);
        return { size: out.length / 2, bytes: out };
      }
      if (op === ".dw" || op === ".word") return words(...a.map((x) => range(v(x), -32768, 65535, "mot")));
      if (op in TWO) { need(2); const d = reg(a[0]), r = reg(a[1]); return words(TWO[op] | ((r & 0x10) << 5) | (d << 4) | (r & 0xf)); }
      if (["clr", "tst", "lsl", "rol"].includes(op)) {
        need(1); const d = reg(a[0]); const base = { clr: 0x2400, tst: 0x2000, lsl: 0x0c00, rol: 0x1c00 }[op];
        return words(base | ((d & 0x10) << 5) | (d << 4) | (d & 0xf));
      }
      if (op === "movw") { need(2); const d = reg(a[0]), r = reg(a[1]); if ((d | r) & 1) throw new AsmError("movw veut des registres pairs"); return words(0x0100 | ((d >> 1) << 4) | (r >> 1)); }
      if (op in IMM || op === "ser" || op === "cbr") {
        if (op === "ser") { need(1); return words(0xef0f | (hiReg(a[0]) << 4)); }
        need(2);
        const d = hiReg(a[0]);
        let k = range(v(a[1]), -128, 255, "valeur immédiate") & 0xff;
        const base = op === "cbr" ? 0x7000 : IMM[op];
        if (op === "cbr") k = ~k & 0xff;
        return words(base | ((k & 0xf0) << 4) | (d << 4) | (k & 0xf));
      }
      if (op in ONE) { need(1); return words(0x9400 | (reg(a[0]) << 4) | ONE[op]); }
      if (op in PLAIN && a.length === 0) return words(PLAIN[op]);
      if (op === "lpm") {
        need(2); const d = reg(a[0]), p = a[1].replace(/\s/g, "").toLowerCase();
        if (p === "z") return words(0x9004 | (d << 4));
        if (p === "z+") return words(0x9005 | (d << 4));
        throw new AsmError("lpm lit par Z ou Z+");
      }
      if (op === "bset" || op === "bclr") { need(1); return words((op === "bset" ? 0x9408 : 0x9488) | (range(v(a[0]), 0, 7, "bit") << 4)); }
      if (/^(se|cl)[cznvshti]$/.test(op)) { const s = FLAGS.indexOf(op[2]); return words((op[0] === "s" ? 0x9408 : 0x9488) | (s << 4)); }
      if (op in BR || op === "brbs" || op === "brbc") {
        let s, set, target;
        if (op in BR) { need(1); [s, set] = BR[op]; target = a[0]; } else { need(2); s = v(a[0]) & 7; set = op === "brbs" ? 1 : 0; target = a[1]; }
        const k = range(v(target) - (pc + 1), -64, 63, "saut conditionnel trop loin (utilise rjmp) :");
        return words((set ? 0xf000 : 0xf400) | ((k & 0x7f) << 3) | s);
      }
      if (op === "rjmp" || op === "rcall") {
        need(1); const k = range(v(a[0]) - (pc + 1), -2048, 2047, "saut relatif trop loin (utilise jmp)");
        return words((op === "rjmp" ? 0xc000 : 0xd000) | (k & 0xfff));
      }
      if (op === "jmp" || op === "call") {
        need(1); const k = range(v(a[0]), 0, 0x3fffff, "adresse");
        return words((op === "jmp" ? 0x940c : 0x940e) | (((k >> 17) & 0x1f) << 4) | ((k >> 16) & 1), k & 0xffff);
      }
      if (op === "in") { need(2); const d = reg(a[0]), p = range(v(a[1]), 0, 63, "adresse d'entrée-sortie (utilise lds au-delà de 63)"); return words(0xb000 | ((p & 0x30) << 5) | (d << 4) | (p & 0xf)); }
      if (op === "out") { need(2); const p = range(v(a[0]), 0, 63, "adresse d'entrée-sortie (utilise sts au-delà de 63)"), r = reg(a[1]); return words(0xb800 | ((p & 0x30) << 5) | (r << 4) | (p & 0xf)); }
      if (["sbi", "cbi", "sbis", "sbic"].includes(op)) {
        need(2); const p = range(v(a[0]), 0, 31, "adresse d'entrée-sortie (0 à 31 pour les instructions de bit)"), b = range(v(a[1]), 0, 7, "bit");
        return words({ cbi: 0x9800, sbic: 0x9900, sbi: 0x9a00, sbis: 0x9b00 }[op] | (p << 3) | b);
      }
      if (["sbrc", "sbrs", "bld", "bst"].includes(op)) {
        need(2); const r = reg(a[0]), b = range(v(a[1]), 0, 7, "bit");
        return words({ bld: 0xf800, bst: 0xfa00, sbrc: 0xfc00, sbrs: 0xfe00 }[op] | (r << 4) | b);
      }
      if (op === "adiw" || op === "sbiw") {
        need(2); const d = reg(a[0]); if (![24, 26, 28, 30].includes(d)) throw new AsmError(`${op} n'accepte que r24, r26, r28 ou r30`);
        const k = range(v(a[1]), 0, 63, "valeur immédiate");
        return words((op === "adiw" ? 0x9600 : 0x9700) | ((k & 0x30) << 2) | (((d - 24) >> 1) << 4) | (k & 0xf));
      }
      if (op === "lds") { need(2); return words(0x9000 | (reg(a[0]) << 4), range(v(a[1]), 0, 0xffff, "adresse")); }
      if (op === "sts") { need(2); return words(0x9200 | (reg(a[1]) << 4), range(v(a[0]), 0, 0xffff, "adresse")); }
      if (op === "push" || op === "pop") { need(1); return words((op === "push" ? 0x920f : 0x900f) | (reg(a[0]) << 4)); }
      if (op === "ld" || op === "ldd" || op === "st" || op === "std") {
        need(2);
        const store = op[0] === "s";
        const r = reg(store ? a[1] : a[0]);
        const ptr = (store ? a[0] : a[1]).replace(/\s/g, "").toLowerCase();
        const disp = /^([yz])\+(.+)$/.exec(ptr);
        if (disp && disp[2] !== "") {
          const q = range(v(disp[2]), 0, 63, "décalage");
          return words((disp[1] === "y" ? 0x8008 : 0x8000) | (store ? 0x0200 : 0) | ((q & 0x20) << 8) | ((q & 0x18) << 7) | (q & 7) | (r << 4));
        }
        if (!(ptr in LD_PTR)) throw new AsmError(`pointeur attendu (X, X+, -X, Y, Y+q, Z, Z+q…) au lieu de « ${ptr} »`);
        return words((LD_PTR[ptr] | (store ? 0x0200 : 0)) | (r << 4));
      }
      throw new AsmError(`instruction AVR inconnue : ${op}`);
    },
    entry: () => 0,
  });

  // =====================================================================================================
  // ARM Thumb (ARMv6-M)
  // =====================================================================================================
  const RP = {
    SIO_BASE: 0xd0000000, GPIO_IN: 0x004, GPIO_OUT: 0x010, GPIO_OUT_SET: 0x014, GPIO_OUT_CLR: 0x018, GPIO_OUT_XOR: 0x01c,
    GPIO_OE: 0x020, GPIO_OE_SET: 0x024, GPIO_OE_CLR: 0x028, GPIO_OE_XOR: 0x02c,
    IO_BANK0_BASE: 0x40014000, PADS_BANK0_BASE: 0x4001c000, RESETS_BASE: 0x4000c000, TIMER_BASE: 0x40054000,
    RESET: 0x0, RESET_DONE: 0x8, TIMERAWH: 0x24, TIMERAWL: 0x28, TIMEHR: 0x08, TIMELR: 0x0c,
    REG_ALIAS_XOR: 0x1000, REG_ALIAS_SET: 0x2000, REG_ALIAS_CLR: 0x3000,
    RESET_IO_BANK0: 1 << 5, RESET_PADS_BANK0: 1 << 8, RESET_TIMER: 1 << 21, FUNCSEL_SIO: 5,
    SYST_CSR: 0xe000e010, SYST_RVR: 0xe000e014, SYST_CVR: 0xe000e018,
  };
  const REGS = { sp: 13, lr: 14, pc: 15, ip: 12, fp: 11, sb: 9, sl: 10 };
  const COND = { eq: 0, ne: 1, cs: 2, hs: 2, cc: 3, lo: 3, mi: 4, pl: 5, vs: 6, vc: 7, hi: 8, ls: 9, ge: 10, lt: 11, gt: 12, le: 13, al: 14 };
  const DP = { ands: 0, eors: 1, adcs: 5, sbcs: 6, rors: 7, tst: 8, cmn: 11, orrs: 12, muls: 13, bics: 14, mvns: 15 };
  const THUMB = prep({
    base: 0x20000000, unit: 1, comments: ["@", "//", ";"], predefined: RP,
    isCode: (op) => op[0] !== ".",
    entry: (symbols) => symbols.get("_start") ?? symbols.get("main") ?? 0x20000000,
    reg(text) {
      const t = text.trim().toLowerCase();
      if (t in REGS) return REGS[t];
      const m = /^r(\d+)$/.exec(t);
      if (!m || Number(m[1]) > 15) throw new AsmError(`registre attendu (r0 à r15, sp, lr, pc) au lieu de « ${text} »`);
      return Number(m[1]);
    },
    // Réserve de constantes : les « ldr rX, =valeur » d'un bloc sont rangés après lui (à .ltorg ou à la fin).
    flushPool(pc, ctx, out) {
      const pending = ctx.lits.filter((l) => l.pool === undefined);
      if (!pending.length) return pc;
      let at = (pc + 3) & ~3;
      const placed = new Map();
      for (const lit of pending) {
        const key = lit.text;
        if (!placed.has(key)) {
          placed.set(key, at);
          if (out) {
            const val = ctx.value(lit.text, at) >>> 0;
            for (let k = 0; k < 4; k++) out.set(at - this.base + k, (val >>> (8 * k)) & 0xff);
          }
          at += 4;
        }
        lit.pool = placed.get(key);
        lit.poolPass = ctx.pass;
      }
      if (out) for (let p = pc; p < ((pc + 3) & ~3); p++) out.set(p - this.base, 0);
      return at;
    },
    end(pc, ctx, out) {
      const tail = this.flushPool(pc, ctx, ctx.pass === 2 ? out : null);
      if (ctx.pass === 1) ctx.pools = ctx.lits.map((l) => l.pool);
      return tail;
    },
    line(row, pc, ctx) {
      const a = row.args, v = (t) => ctx.value(t, pc);
      let op = row.op;
      const reg = (t) => this.reg(t);
      const low = (t) => { const r = reg(t); if (r > 7) throw new AsmError(`${op} n'accepte ici que r0 à r7 (« ${t} »)`); return r; };
      const isReg = (t) => { try { reg(t); return true; } catch (e) { return false; } };
      const imm = (t) => { if (!/^#/.test(t.trim())) throw new AsmError(`valeur immédiate attendue (#…) au lieu de « ${t} »`); return v(t.trim().slice(1)); };
      const isImm = (t) => t !== undefined && /^#/.test(t.trim());
      const range = (x, lo, hi, what) => { if (ctx.pass === 2 && (x < lo || x > hi)) throw new AsmError(`${what} hors limites (${lo} à ${hi}) : ${x}`); return x; };
      const h = (...w) => ({ size: 2 * w.length, bytes: w.flatMap((x) => [x & 0xff, (x >> 8) & 0xff]) });
      const need = (...n) => { if (!n.includes(a.length)) throw new AsmError(`${op} attend ${n.join(" ou ")} opérandes`); };
      const list = (t) => {
        const m = /^\{(.*)\}$/.exec(t.trim());
        if (!m) throw new AsmError("liste de registres attendue, par exemple {r4, r5, lr}");
        let mask = 0;
        for (const part of m[1].split(",")) {
          const [x, y] = part.split("-").map((s) => s.trim());
          if (!x) continue;
          const from = reg(x), to = y ? reg(y) : from;
          for (let r = from; r <= to; r++) mask |= 1 << r;
        }
        return mask;
      };

      // directives
      if (op === ".word" || op === ".long" || op === ".4byte") return { size: 4 * a.length, bytes: a.flatMap((x) => { const n = v(x) >>> 0; return [n & 0xff, (n >>> 8) & 0xff, (n >>> 16) & 0xff, n >>> 24]; }) };
      if (op === ".hword" || op === ".short" || op === ".2byte") return { size: 2 * a.length, bytes: a.flatMap((x) => { const n = v(x); return [n & 0xff, (n >> 8) & 0xff]; }) };
      if (op === ".byte") return { size: a.length, bytes: a.map((x) => v(x) & 0xff) };
      if (op === ".ascii" || op === ".asciz" || op === ".string") {
        const out = [];
        for (const arg of a) { const s = strBytes(arg); if (!s) throw new AsmError(`chaîne entre guillemets attendue`); out.push(...s); if (op !== ".ascii") out.push(0); }
        return { size: out.length, bytes: out };
      }
      if (op === ".align" || op === ".balign" || op === ".p2align") {
        const n = a.length ? v(a[0]) : 2;
        const to = op === ".balign" ? n : 1 << n;
        const pad = (to - ((pc - this.base) % to)) % to;
        return { size: pad, bytes: new Array(pad).fill(0) };
      }
      if (op === ".space" || op === ".skip" || op === ".zero") { const n = v(a[0]); return { size: n, bytes: new Array(n).fill(a[1] ? v(a[1]) & 0xff : 0) }; }
      if (op === ".ltorg" || op === ".pool") {
        const end = this.flushPool(pc, ctx, ctx.pass === 2 ? ctx.out : null);
        return { size: end - pc, bytes: [] };
      }
      if (op === ".org") return { org: v(a[0]) };
      if (op[0] === ".") return { size: 0 }; // .thumb, .syntax, .text, .global, .thumb_func, .section, .type…

      const shortcuts = { mov: "movs", lsl: "lsls", lsr: "lsrs", asr: "asrs", and: "ands", eor: "eors", orr: "orrs",
                          bic: "bics", mvn: "mvns", adc: "adcs", sbc: "sbcs", ror: "rors", mul: "muls", neg: "negs", rsb: "rsbs",
                          ldmia: "ldm", stmia: "stm", ldmfd: "ldm", stmea: "stm", "b.n": "b", "bl.n": "bl" };
      // « mov rX, rY » garde son sens UAL (copie sans toucher aux drapeaux) ; « mov rX, #n » devient movs.
      if (op === "mov" && a.length === 2 && isImm(a[1])) op = "movs";
      else if (op !== "mov" && op !== "add" && op !== "sub" && op in shortcuts) op = shortcuts[op];
      if (op === "add" && a.length === 3 && isImm(a[2]) && !["sp", "pc", "r13", "r15"].includes(a[1].trim().toLowerCase()) && reg(a[0]) !== 13) op = "adds";
      if (op === "sub" && a.length === 3 && isImm(a[2]) && reg(a[0]) !== 13) op = "subs";
      if ((op === "add" || op === "sub") && a.length === 2 && isImm(a[1]) && reg(a[0]) !== 13) op += "s";
      if (op === "sub" && a.length === 3 && !isImm(a[2])) op = "subs";
      if (op === "add" && a.length === 3 && !isImm(a[2]) && reg(a[0]) < 8 && reg(a[1]) < 8 && reg(a[2]) < 8) op = "adds";

      switch (op) {
        case "movs":
          need(2);
          if (isImm(a[1])) return h(0x2000 | (low(a[0]) << 8) | (range(imm(a[1]), 0, 255, "valeur (movs)") & 0xff));
          return h(0x0000 | (low(a[1]) << 3) | low(a[0]));
        case "mov": need(2); { const d = reg(a[0]), m = reg(a[1]); return h(0x4600 | ((d & 8) << 4) | (m << 3) | (d & 7)); }
        case "adds": case "subs": {
          const sub = op === "subs";
          if (a.length === 2 && isImm(a[1])) return h((sub ? 0x3800 : 0x3000) | (low(a[0]) << 8) | (range(imm(a[1]), 0, 255, "valeur") & 0xff));
          need(3);
          const d = low(a[0]), n = low(a[1]);
          if (isImm(a[2])) {
            const k = imm(a[2]);
            if (d === n && (k > 7 || k < 0)) return h((sub ? 0x3800 : 0x3000) | (d << 8) | (range(k, 0, 255, "valeur") & 0xff));
            return h((sub ? 0x1e00 : 0x1c00) | (range(k, 0, 7, "valeur (3 bits ; mets le même registre deux fois pour aller jusqu'à 255)") << 6) | (n << 3) | d);
          }
          return h((sub ? 0x1a00 : 0x1800) | (low(a[2]) << 6) | (n << 3) | d);
        }
        case "add": case "sub": {
          const sub = op === "sub";
          const d = reg(a[0]);
          if (d === 13) { // add sp, #n ; add sp, sp, #n
            const k = imm(a[a.length - 1]);
            if (k & 3) throw new AsmError("le pas de sp est un multiple de 4");
            return h((sub ? 0xb080 : 0xb000) | (range(k >> 2, 0, 127, "décalage de sp (×4)") & 0x7f));
          }
          if (a.length === 3 && isImm(a[2])) {
            const n = reg(a[1]), k = imm(a[2]);
            if (sub) throw new AsmError("sub rX, sp/pc, #n n'existe pas en Thumb");
            if (k & 3) throw new AsmError("le décalage est un multiple de 4");
            if (n === 13) return h(0xa800 | (low(a[0]) << 8) | range(k >> 2, 0, 255, "décalage (×4)"));
            if (n === 15) return h(0xa000 | (low(a[0]) << 8) | range(k >> 2, 0, 255, "décalage (×4)"));
          }
          if (sub) throw new AsmError("sub entre registres hauts n'existe pas en Thumb");
          const m = reg(a[a.length - 1]);
          if (a.length === 3 && reg(a[1]) !== d) throw new AsmError("add avec un registre haut : le premier et le deuxième registre doivent être les mêmes");
          return h(0x4400 | ((d & 8) << 4) | (m << 3) | (d & 7));
        }
        case "cmp": need(2);
          if (isImm(a[1])) return h(0x2800 | (low(a[0]) << 8) | (range(imm(a[1]), 0, 255, "valeur") & 0xff));
          { const n = reg(a[0]), m = reg(a[1]); if (n < 8 && m < 8) return h(0x4280 | (m << 3) | n); return h(0x4500 | ((n & 8) << 4) | (m << 3) | (n & 7)); }
        case "lsls": case "lsrs": case "asrs": {
          const kind = { lsls: 0, lsrs: 1, asrs: 2 }[op];
          if (a.length === 2 && isImm(a[1])) a.splice(1, 0, a[0]);
          if (a.length === 3 && isImm(a[2])) {
            let k = imm(a[2]);
            if (kind && k === 32) k = 0;
            return h((kind << 11) | (range(k, 0, kind ? 32 : 31, "décalage") << 6) | (low(a[1]) << 3) | low(a[0]));
          }
          const d = low(a[0]), s = low(a[a.length - 1]);
          if (a.length === 3 && low(a[1]) !== d) throw new AsmError(`${op} rX, rX, rY : le premier et le deuxième registre doivent être les mêmes`);
          return h(0x4000 | ([2, 3, 4][kind] << 6) | (s << 3) | d);
        }
        case "negs": case "rsbs": { need(2, 3); return h(0x4000 | (9 << 6) | (low(a[1]) << 3) | low(a[0])); }
        case "muls": { need(2, 3); const d = low(a[0]), n = low(a[1]); if (a.length === 3 && low(a[2]) !== d) throw new AsmError("muls rd, rn, rd : le dernier registre doit être rd"); return h(0x4000 | (13 << 6) | (n << 3) | d); }
        case "ands": case "eors": case "adcs": case "sbcs": case "rors": case "tst": case "cmn": case "orrs": case "bics": case "mvns": {
          need(2, 3);
          const d = low(a[0]), m = low(a[a.length - 1]);
          if (a.length === 3 && low(a[1]) !== d) throw new AsmError(`${op} : le premier et le deuxième registre doivent être les mêmes`);
          return h(0x4000 | (DP[op] << 6) | (m << 3) | d);
        }
        case "bx": case "blx": need(1); return h((op === "bx" ? 0x4700 : 0x4780) | (reg(a[0]) << 3));
        case "sxth": case "sxtb": case "uxth": case "uxtb": need(2); return h(0xb200 | ({ sxth: 0, sxtb: 1, uxth: 2, uxtb: 3 }[op] << 6) | (low(a[1]) << 3) | low(a[0]));
        case "rev": case "rev16": case "revsh": need(2); return h(0xba00 | ({ rev: 0, rev16: 1, revsh: 3 }[op] << 6) | (low(a[1]) << 3) | low(a[0]));
        case "push": case "pop": {
          need(1); const mask = list(a[0]);
          const extra = op === "push" ? 1 << 14 : 1 << 15;
          if (mask & ~0xff & ~extra) throw new AsmError(`${op} n'accepte que r0 à r7 et ${op === "push" ? "lr" : "pc"}`);
          return h((op === "push" ? 0xb400 : 0xbc00) | (mask & extra ? 0x100 : 0) | (mask & 0xff));
        }
        case "ldm": case "stm": {
          need(2); const n = low(a[0].replace("!", "")), mask = list(a[1]);
          if (mask & ~0xff) throw new AsmError(`${op} n'accepte que r0 à r7`);
          return h((op === "stm" ? 0xc000 : 0xc800) | (n << 8) | mask);
        }
        case "nop": return h(0xbf00);
        case "yield": return h(0xbf10);
        case "wfe": return h(0xbf20);
        case "wfi": return h(0xbf30);
        case "sev": return h(0xbf40);
        case "bkpt": return h(0xbe00 | (a.length ? imm(a[0]) & 0xff : 0));
        case "svc": return h(0xdf00 | (imm(a[0]) & 0xff));
        case "udf": return h(0xde00 | (a.length ? imm(a[0]) & 0xff : 0));
        case "cpsie": case "cpsid": return h(op === "cpsie" ? 0xb662 : 0xb672);
        case "dmb": return h(0xf3bf, 0x8f5f);
        case "dsb": return h(0xf3bf, 0x8f4f);
        case "isb": return h(0xf3bf, 0x8f6f);
        case "b": {
          need(1); const off = v(a[0]) - (pc + 4);
          if (ctx.pass === 2 && (off & 1)) throw new AsmError("cible de saut impaire");
          return h(0xe000 | ((range(off, -2048, 2046, "saut trop loin") >> 1) & 0x7ff));
        }
        case "bl": {
          need(1); const off = range(v(a[0]) - (pc + 4), -(1 << 24), (1 << 24) - 2, "appel trop loin");
          const s = (off >> 24) & 1, i1 = (off >> 23) & 1, i2 = (off >> 22) & 1;
          const j1 = (i1 ^ 1) ^ s, j2 = (i2 ^ 1) ^ s;
          return h(0xf000 | (s << 10) | ((off >> 12) & 0x3ff), 0xd000 | (j1 << 13) | (j2 << 11) | ((off >> 1) & 0x7ff));
        }
        case "adr": {
          need(2); const target = v(a[1]), base = (pc + 4) & ~3, off = target - base;
          if (ctx.pass === 2 && (off & 3)) throw new AsmError("adr vise une adresse alignée sur 4 (ajoute .align 2 avant l'étiquette)");
          return h(0xa000 | (low(a[0]) << 8) | range(off >> 2, 0, 255, "adr : cible trop loin ou en arrière"));
        }
        default: break;
      }
      const cond = /^b(eq|ne|cs|hs|cc|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le)$/.exec(op);
      if (cond) {
        need(1); const off = v(a[0]) - (pc + 4);
        return h(0xd000 | (COND[cond[1]] << 8) | ((range(off, -256, 254, "saut conditionnel trop loin (utilise b)") >> 1) & 0xff));
      }
      const mem = /^(ldr|str)(b|h|sb|sh)?$/.exec(op);
      if (mem) {
        need(2);
        const load = mem[1] === "ldr", size = mem[2] || "";
        const t = low(a[0]);
        const addr = a[1].trim();
        if (load && size === "" && addr[0] === "=") { // réserve de constantes
          if (ctx.pass === 1) ctx.lits.push({ text: addr.slice(1), at: pc });
          else {
            const entry = ctx.pools[ctx.poolIndex];
            ctx.lits.push({ text: addr.slice(1), at: pc });
            ctx.poolIndex++;
            if (entry === undefined) throw new AsmError("réserve de constantes introuvable");
            const off = entry - ((pc + 4) & ~3);
            return h(0x4800 | (t << 8) | (range(off >> 2, 0, 255, "constante trop loin : ajoute .ltorg plus près") & 0xff));
          }
          return h(0x4800 | (t << 8));
        }
        if (load && size === "" && addr[0] !== "[") { // ldr rX, étiquette
          const off = v(addr) - ((pc + 4) & ~3);
          if (ctx.pass === 2 && (off & 3)) throw new AsmError("ldr vise une adresse alignée sur 4");
          return h(0x4800 | (t << 8) | range(off >> 2, 0, 255, "ldr : étiquette trop loin ou en arrière"));
        }
        const m = /^\[\s*([^,\]]+)\s*(?:,\s*([^\]]+))?\]$/.exec(addr);
        if (!m) throw new AsmError(`adresse attendue entre crochets, par exemple [r1, #4] (« ${addr} »)`);
        const n = reg(m[1]), second = m[2] ? m[2].trim() : "#0";
        if (!isImm(second)) {
          const rm = low(second);
          const code = { "str": 0, "strh": 1, "strb": 2, "ldrsb": 3, "ldr": 4, "ldrh": 5, "ldrb": 6, "ldrsh": 7 }[op];
          if (n > 7) throw new AsmError("adresse [rN, rM] : rN doit être r0 à r7");
          return h(0x5000 | (code << 9) | (rm << 6) | (n << 3) | t);
        }
        const k = imm(second);
        if (size === "sb" || size === "sh") throw new AsmError(`${op} n'existe qu'avec un registre de décalage : [rN, rM]`);
        if (n === 13 || n === 15) {
          if (size) throw new AsmError(`${op} avec sp ou pc n'existe pas`);
          if (k & 3) throw new AsmError("décalage multiple de 4 attendu");
          if (n === 15 && !load) throw new AsmError("str [pc, …] n'existe pas");
          return h((n === 13 ? (load ? 0x9800 : 0x9000) : 0x4800) | (t << 8) | range(k >> 2, 0, 255, "décalage (×4)"));
        }
        const rn = low(m[1]);
        if (size === "") { if (k & 3) throw new AsmError("décalage multiple de 4 attendu"); return h((load ? 0x6800 : 0x6000) | (range(k >> 2, 0, 31, "décalage (0 à 124)") << 6) | (rn << 3) | t); }
        if (size === "b") return h((load ? 0x7800 : 0x7000) | (range(k, 0, 31, "décalage (0 à 31)") << 6) | (rn << 3) | t);
        if (k & 1) throw new AsmError("décalage pair attendu");
        return h((load ? 0x8800 : 0x8000) | (range(k >> 1, 0, 31, "décalage (0 à 62)") << 6) | (rn << 3) | t);
      }
      throw new AsmError(`instruction Thumb inconnue : ${op}`);
    },
  });

  // Les réserves de constantes de la passe 2 doivent écrire dans l'image : on passe la table de sortie au contexte.
  function assembleThumb(source) {
    const cpu = Object.create(THUMB);
    cpu.begin = function (ctx) { ctx.lits = []; ctx.poolIndex = 0; ctx.out = null; };
    return assembleWith(source, wrapOut(cpu));
  }
  // Donne à .ltorg l'accès à l'image en cours de remplissage (passe 2).
  function wrapOut(cpu) {
    const line = cpu.line;
    cpu.line = function (row, pc, ctx) {
      if ((row.op === ".ltorg" || row.op === ".pool") && ctx.pass === 2) {
        const before = new Map();
        ctx.out = before;
        const r = line.call(this, row, pc, ctx);
        r.bytes = [];
        for (let p = pc; p < pc + r.size; p++) r.bytes.push(before.get(p - this.base) || 0);
        return r;
      }
      return line.call(this, row, pc, ctx);
    };
    return cpu;
  }

  root.AetherMcuAsm = {
    AsmError, evaluate,
    avr: (source) => assembleWith(source, AVR),
    thumb: assembleThumb,
    AVR_IO, RP,
  };
})(typeof window !== "undefined" ? window : globalThis);
