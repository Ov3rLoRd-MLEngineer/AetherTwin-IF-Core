"use strict";
// Assembleur 6502 de l'atelier circuits : du texte à une cartouche iNES (mappeur 0, « NROM »).
//
//   ; commentaire                     étiquette:          @locale:  (rattachée à la dernière étiquette)
//   NOM = expression                  lda #<adresse       sta $2000,x   lda (ptr),y   jmp (vecteur)
//   .segment prg | chr                .org $8000          .byte 1, $ff, "texte"   .word etiquette
//   .res 16, 0     (16 octets à 0)    .align 256          .vectors nmi, reset, irq   (écrit en $FFFA)
//   .tile "..1122..", … (8 lignes : 0/. = fond, 1, 2, 3 = couleurs) → 16 octets de motif 2 bits par pixel
//   .ines mirror=horizontal|vertical  (miroir des écrans de fond ; vertical par défaut)
//
// Expressions : $1F, %1010, 42, 'A', symboles, * (adresse courante), < (octet faible), > (octet fort),
// + - * / % & | ^ << >> ~ et parenthèses.
(function (root) {
  const { OPS } = root.AetherCPU;
  // mnémonique → mode → opcode (instructions officielles seulement : l'assembleur enseigne le 6502 « propre »)
  const TABLE = {};
  OPS.forEach((info, code) => {
    if (!info || info.name.startsWith("*")) return;
    (TABLE[info.name] = TABLE[info.name] || {})[info.mode] = code;
  });
  const MODE_SIZE = { imp: 1, acc: 1, imm: 2, zp: 2, zpx: 2, zpy: 2, rel: 2, izx: 2, izy: 2, abs: 3, abx: 3, aby: 3, ind: 3 };

  class AsmError extends Error {}

  // ---------- expressions ----------
  function tokenize(text) {
    const tokens = [];
    const re = /\s*(\$[0-9a-f]+|%[01]+|\d+|'(?:\\.|[^'])'|[a-z_@.][\w.@]*|<<|>>|[-+*/%&|^~<>()])/giy;
    let m, last = 0;
    while ((m = re.exec(text)) !== null) {
      tokens.push(m[1]);
      last = re.lastIndex;
      if (last >= text.length) break;
    }
    if (text.slice(last).trim()) throw new AsmError(`expression illisible près de « ${text.slice(last).trim()} »`);
    return tokens;
  }
  function evaluate(text, lookup, here) {
    const tokens = tokenize(text);
    let i = 0;
    const peek = () => tokens[i];
    const next = () => tokens[i++];
    let unknown = false;
    function atom() {
      const t = next();
      if (t === undefined) throw new AsmError("expression incomplète");
      if (t === "(") { const v = binary(0); if (next() !== ")") throw new AsmError("parenthèse « ) » manquante"); return v; }
      if (t === "-") return -atom();
      if (t === "~") return ~atom();
      if (t === "<") return atom() & 0xff;
      if (t === ">") return (atom() >> 8) & 0xff;
      if (t === "*") return here;
      if (t[0] === "$") return parseInt(t.slice(1), 16);
      if (t[0] === "%") return parseInt(t.slice(1), 2);
      if (/^\d/.test(t)) return parseInt(t, 10);
      if (t[0] === "'") return t.length === 4 ? t.charCodeAt(2) : t.charCodeAt(1);
      const v = lookup(t);
      if (v === undefined) { unknown = true; return 0; }
      return v;
    }
    const PRIO = { "|": 1, "^": 2, "&": 3, "<<": 4, ">>": 4, "+": 5, "-": 5, "*": 6, "/": 6, "%": 6 };
    function binary(min) {
      let left = atom();
      while (peek() in PRIO && PRIO[peek()] >= min) {
        const o = next();
        const right = binary(PRIO[o] + 1);
        switch (o) {
          case "+": left += right; break; case "-": left -= right; break; case "*": left *= right; break;
          case "/": if (!right && !unknown) throw new AsmError("division par zéro"); left = right ? Math.trunc(left / right) : 0; break;
          case "%": left = right ? left % right : 0; break; case "&": left &= right; break; case "|": left |= right; break;
          case "^": left ^= right; break; case "<<": left <<= right; break; case ">>": left >>= right; break;
          default: break;
        }
      }
      return left;
    }
    const value = binary(0);
    if (i < tokens.length) throw new AsmError(`« ${tokens[i]} » inattendu dans l'expression`);
    return { value, unknown };
  }

  // Sépare une liste d'arguments sur les virgules hors chaînes.
  function splitArgs(text) {
    const out = [];
    let cur = "", quote = null;
    for (const ch of text) {
      if (quote) { cur += ch; if (ch === quote) quote = null; continue; }
      if (ch === '"' || ch === "'") { quote = ch; cur += ch; continue; }
      if (ch === ",") { out.push(cur.trim()); cur = ""; continue; }
      cur += ch;
    }
    if (cur.trim() || out.length) out.push(cur.trim());
    return out;
  }
  function stripComment(line) {
    let quote = null;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (quote) { if (ch === quote) quote = null; continue; }
      if (ch === '"' || ch === "'") { quote = ch; continue; }
      if (ch === ";") return line.slice(0, i);
    }
    return line;
  }

  // Mode d'adressage d'un opérande (avant évaluation) : [mode générique, texte de l'expression].
  function operandShape(name, text) {
    const t = text.trim();
    if (!t) return ["imp", ""];
    if (/^a$/i.test(t)) return ["acc", ""];
    if (t[0] === "#") return ["imm", t.slice(1)];
    let m = /^\((.*),\s*x\s*\)$/i.exec(t);
    if (m) return ["izx", m[1]];
    m = /^\((.*)\)\s*,\s*y$/i.exec(t);
    if (m) return ["izy", m[1]];
    if (name === "JMP" && /^\(.*\)$/.test(t)) return ["ind", t.slice(1, -1)];
    m = /^(.*),\s*x$/i.exec(t);
    if (m) return ["x", m[1]];
    m = /^(.*),\s*y$/i.exec(t);
    if (m) return ["y", m[1]];
    return ["direct", t];
  }

  function assemble(source) {
    const lines = source.replace(/\r\n?/g, "\n").split("\n");
    const symbols = new Map();
    const errors = [];
    const decisions = new Map();  // ligne → mode choisi au premier passage (taille stable)
    let prg, chr, sourceMap, mirror, written;

    function run(pass) {
      prg = new Uint8Array(0x8000).fill(0xff);
      chr = new Uint8Array(0x2000);
      sourceMap = new Map();
      mirror = "vertical";
      let segment = "prg";
      let pc = 0x8000;
      written = { prg: new Uint8Array(0x8000), chr: new Uint8Array(0x2000) };
      let lowest = 0x10000;
      let scope = "";
      const full = (name) => (name.startsWith("@") ? scope + name : name);
      const lookup = (name) => {
        const key = full(name.toLowerCase());
        return symbols.has(key) ? symbols.get(key) : undefined;
      };
      const define = (name, value, lineNo) => {
        const key = full(name.toLowerCase());
        if (pass === 1 && symbols.has(key) && symbols.get(key) !== value) {
          throw new AsmError(`« ${name} » est déjà défini`);
        }
        if (pass === 1 && TABLE[name.toUpperCase()]) throw new AsmError(`« ${name} » est le nom d'une instruction`);
        symbols.set(key, value);
        return lineNo;
      };
      const value = (expr, lineNo, { allowUnknown = false } = {}) => {
        const r = evaluate(expr, lookup, pc);
        if (r.unknown && pass === 2 && !allowUnknown) {
          const missing = tokenize(expr).find((t) => /^[a-z_@.]/i.test(t) && lookup(t) === undefined);
          throw new AsmError(`symbole inconnu : « ${missing} »`);
        }
        return r;
      };
      const emit = (byte, lineNo) => {
        if (segment === "prg") {
          if (pc < 0x8000 || pc > 0xffff) throw new AsmError(`adresse $${pc.toString(16)} hors de la ROM ($8000-$FFFF)`);
          if (pass === 2) {
            if (written.prg[pc - 0x8000]) throw new AsmError(`l'adresse $${pc.toString(16).toUpperCase()} est écrite deux fois`);
            written.prg[pc - 0x8000] = 1;
            prg[pc - 0x8000] = byte & 0xff;
            sourceMap.set(pc, lineNo);
          }
          lowest = Math.min(lowest, pc);
        } else {
          if (pc < 0 || pc > 0x1fff) throw new AsmError(`adresse $${pc.toString(16)} hors de la mémoire de motifs ($0000-$1FFF)`);
          if (pass === 2) chr[pc] = byte & 0xff;
        }
        pc += 1;
      };

      lines.forEach((raw, index) => {
        const lineNo = index + 1;
        try {
          let line = stripComment(raw).trim();
          if (!line) return;
          // étiquettes en tête de ligne
          let m;
          while ((m = /^([a-z_@][\w@]*)\s*:\s*/i.exec(line))) {
            const name = m[1];
            if (!name.startsWith("@")) scope = name.toLowerCase();
            define(name, pc, lineNo);
            line = line.slice(m[0].length);
          }
          if (!line) return;
          m = /^([a-z_][\w]*)\s*=\s*(.+)$/i.exec(line);
          if (m) { define(m[1], value(m[2], lineNo, { allowUnknown: pass === 1 }).value, lineNo); return; }
          const parts = /^(\.?[a-z]+)\s*(.*)$/i.exec(line);
          if (!parts) throw new AsmError(`ligne illisible : « ${line} »`);
          const word = parts[1].toLowerCase(), rest = parts[2];
          if (word.startsWith(".")) { directive(word, rest, lineNo); return; }
          instruction(word.toUpperCase(), rest, lineNo, index);
        } catch (error) {
          if (!(error instanceof AsmError)) throw error;
          if (pass === 2 || !/inconnu/.test(error.message)) errors.push({ line: lineNo, message: error.message, pass });
        }
      });

      function directive(word, rest, lineNo) {
        const args = splitArgs(rest);
        switch (word) {
          case ".org": pc = value(rest, lineNo).value; break;
          case ".segment": {
            const name = rest.replace(/"/g, "").trim().toLowerCase();
            if (name !== "prg" && name !== "chr") throw new AsmError("segment « prg » (programme) ou « chr » (motifs) attendu");
            if (name !== segment) { segment = name; pc = name === "prg" ? 0x8000 : 0; }
            break;
          }
          case ".byte": case ".db":
            for (const a of args) {
              if (/^".*"$/.test(a)) { for (const ch of a.slice(1, -1)) emit(ch.charCodeAt(0), lineNo); continue; }
              const v = value(a, lineNo, { allowUnknown: pass === 1 }).value;
              if (pass === 2 && (v < -128 || v > 255)) throw new AsmError(`${a} ne tient pas dans un octet`);
              emit(v, lineNo);
            }
            break;
          case ".word": case ".dw":
            for (const a of args) { const v = value(a, lineNo, { allowUnknown: pass === 1 }).value; emit(v, lineNo); emit(v >> 8, lineNo); }
            break;
          case ".res": case ".ds": {
            const count = value(args[0] || "0", lineNo).value;
            const fill = args[1] ? value(args[1], lineNo).value : 0;
            if (count < 0 || count > 0x8000) throw new AsmError("taille réservée invalide");
            if (segment === "prg" && pc < 0x8000) { pc += count; break; }  // réserve en RAM : rien à écrire
            for (let i = 0; i < count; i++) emit(fill, lineNo);
            break;
          }
          case ".align": {
            const n = value(rest, lineNo).value;
            if (n <= 0) throw new AsmError("alignement invalide");
            while (pc % n) emit(0xff, lineNo);
            break;
          }
          case ".vectors": {
            if (args.length !== 3) throw new AsmError(".vectors nmi, reset, irq attendu");
            const keep = pc, seg = segment;
            segment = "prg"; pc = 0xfffa;
            for (const a of args) { const v = value(a, lineNo, { allowUnknown: pass === 1 }).value; emit(v, lineNo); emit(v >> 8, lineNo); }
            pc = keep; segment = seg;
            break;
          }
          case ".tile": {
            if (args.length !== 8) throw new AsmError(".tile attend 8 lignes de 8 pixels");
            const rows = args.map((a) => a.replace(/"/g, ""));
            const lo = [], hi = [];
            for (const row of rows) {
              if (row.length !== 8 || /[^.0-3]/.test(row)) throw new AsmError(`ligne de motif « ${row} » : 8 caractères parmi . 0 1 2 3`);
              let l = 0, h = 0;
              for (const ch of row) { const c = ch === "." ? 0 : Number(ch); l = (l << 1) | (c & 1); h = (h << 1) | (c >> 1); }
              lo.push(l); hi.push(h);
            }
            for (const b of lo.concat(hi)) emit(b, lineNo);
            break;
          }
          case ".ines": {
            const mm = /mirror\s*=\s*(horizontal|vertical)/i.exec(rest);
            if (!mm) throw new AsmError(".ines mirror=horizontal ou mirror=vertical attendu");
            mirror = mm[1].toLowerCase();
            break;
          }
          default: throw new AsmError(`directive inconnue : ${word}`);
        }
      }

      function instruction(name, rest, lineNo, index) {
        const modes = TABLE[name];
        if (!modes) throw new AsmError(`instruction inconnue : ${name}`);
        if (segment !== "prg") throw new AsmError("une instruction doit être dans le segment prg");
        let [shape, expr] = operandShape(name, rest);
        let mode;
        if (shape === "imp" || shape === "acc") {
          mode = modes.imp !== undefined ? "imp" : modes.acc !== undefined ? "acc" : null;
          if (!mode) throw new AsmError(`${name} demande un opérande`);
        } else if (modes.rel !== undefined) {
          mode = "rel";
          if (shape !== "direct") throw new AsmError(`${name} attend une étiquette (branchement relatif)`);
        } else if (["imm", "izx", "izy", "ind"].includes(shape)) {
          mode = shape;
        } else {
          const r = evaluate(expr, lookup, pc);
          let decided = decisions.get(index);
          if (pass === 1 || decided === undefined) {
            const small = !r.unknown && r.value >= 0 && r.value < 0x100;
            const zpMode = shape === "direct" ? "zp" : shape === "x" ? "zpx" : "zpy";
            const absMode = shape === "direct" ? "abs" : shape === "x" ? "abx" : "aby";
            decided = (small && modes[zpMode] !== undefined) || modes[absMode] === undefined ? zpMode : absMode;
            decisions.set(index, decided);
          }
          mode = decided;
        }
        if (modes[mode] === undefined) throw new AsmError(`${name} n'accepte pas ce mode d'adressage`);
        emit(modes[mode], lineNo);
        if (mode === "imp" || mode === "acc") return;
        const start = pc - 1;
        const r = value(expr, lineNo, { allowUnknown: pass === 1 });
        let v = r.value;
        if (mode === "rel") {
          const offset = v - (start + 2);
          if (pass === 2 && (offset < -128 || offset > 127)) {
            throw new AsmError(`branchement trop loin (${offset} octets, de -128 à 127) : utilise JMP`);
          }
          emit(offset & 0xff, lineNo);
        } else if (MODE_SIZE[mode] === 2) {
          if (pass === 2 && (v < -128 || v > 0xff)) {
            throw new AsmError(mode === "imm" ? `#${expr} ne tient pas dans un octet (utilise < ou >)` : `${expr} est hors de la page zéro`);
          }
          emit(v, lineNo);
        } else {
          emit(v, lineNo); emit(v >> 8, lineNo);
        }
      }
      return lowest;
    }

    run(1);
    const firstErrors = errors.splice(0).filter((e) => !/inconnu/.test(e.message));
    const lowest = run(2);
    errors.unshift(...firstErrors.filter((e) => !errors.some((x) => x.line === e.line)));
    errors.sort((a, b) => a.line - b.line);
    if (!errors.length && (prg[0x7ffc] | (prg[0x7ffd] << 8)) === 0xffff) {
      errors.push({ line: 0, message: "pas de vecteur de démarrage : ajoute « .vectors nmi, reset, irq »" });
    }
    const size16 = lowest >= 0xc000;  // tout le programme tient dans les 16 derniers Ko
    const prgOut = size16 ? prg.slice(0x4000) : prg;
    const header = new Uint8Array([0x4e, 0x45, 0x53, 0x1a, size16 ? 1 : 2, 1, mirror === "vertical" ? 1 : 0, 0,
      0, 0, 0, 0, 0, 0, 0, 0]);
    const rom = new Uint8Array(16 + prgOut.length + chr.length);
    rom.set(header); rom.set(prgOut, 16); rom.set(chr, 16 + prgOut.length);
    let used = 0;  // octets de programme réellement écrits
    for (let i = 0; i < 0x8000; i++) used += written.prg[i] ? 1 : 0;
    return { ok: errors.length === 0, errors, rom, prg: prgOut, chr, mirror, symbols, sourceMap, used };
  }

  root.AetherAsm = { assemble, evaluate, AsmError };
})(typeof window !== "undefined" ? window : globalThis);
