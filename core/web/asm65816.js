"use strict";
// Assembleur 65816 de l'atelier circuits : du texte à une cartouche 16 bits « LoROM » (.sfc).
//
//   ; commentaire          étiquette:   @locale:      NOM = expression
//   .bank 0               (banque de ROM : le code suit en $00:8000, $01:8000…)      .org $808000
//   .byte 1, "texte"      .word étiquette    .long étiquette (3 octets)    .res 16, 0    .align 256
//   .a8 .a16 .i8 .i16     largeur de l'accumulateur / des index pour les valeurs immédiates
//                         (suivie aussi automatiquement après « rep #$20 », « sep #$30 »…)
//   .tile4 "..1122ff", … (8 lignes, couleurs 0-f ; . = transparent) → 32 octets de motif 4 bits par point
//   .title "MON JEU"      .vectors nmi, reset, irq   (vecteurs natifs et d'émulation)
//
// Modes : #imm  dp  dp,x  dp,y  (dp)  [dp]  (dp,x)  (dp),y  [dp],y  sr,s  (sr,s),y  abs  abs,x  abs,y
// long  long,x  (abs)  (abs,x)  [abs]  mvn $7e,$7e. Taille forcée par suffixe : lda.b (page directe), lda.w
// (absolu), lda.l (long). Expressions comme l'assembleur 6502, plus ^expr (octet de banque).
(function (root) {
  const { OPS } = root.AetherCPU16;
  const { evaluate, AsmError } = root.AetherAsm;
  const TABLE = {};
  OPS.forEach((info, code) => { if (info) (TABLE[info[0]] = TABLE[info[0]] || {})[info[1]] = code; });
  const ROM_MAX = 0x100000;  // 1 Mo (32 banques LoROM)

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
  // forme de l'opérande : [famille, expression]
  function operandShape(t) {
    t = t.trim();
    if (!t) return ["none", ""];
    if (/^a$/i.test(t)) return ["acc", ""];
    if (t[0] === "#") return ["imm", t.slice(1)];
    let m;
    if ((m = /^\((.*),\s*s\s*\)\s*,\s*y$/i.exec(t))) return ["sriy", m[1]];
    if ((m = /^\((.*),\s*x\s*\)$/i.exec(t))) return ["ix", m[1]];
    if ((m = /^\((.*)\)\s*,\s*y$/i.exec(t))) return ["iy", m[1]];
    if ((m = /^\[(.*)\]\s*,\s*y$/i.exec(t))) return ["ily", m[1]];
    if ((m = /^\((.*)\)$/.exec(t))) return ["i", m[1]];
    if ((m = /^\[(.*)\]$/.exec(t))) return ["il", m[1]];
    if ((m = /^(.*),\s*s$/i.exec(t))) return ["sr", m[1]];
    if ((m = /^(.*),\s*x$/i.exec(t))) return ["x", m[1]];
    if ((m = /^(.*),\s*y$/i.exec(t))) return ["y", m[1]];
    return ["direct", t];
  }
  // famille + taille (1 = page directe, 2 = absolu, 3 = long) → mode de la table du processeur
  const BY_SIZE = {
    direct: { 1: "dp", 2: "abs", 3: "abl" },
    x: { 1: "dpx", 2: "abx", 3: "ablx" },
    y: { 1: "dpy", 2: "aby" },
    i: { 1: "dpi", 2: "ind" },
    il: { 1: "dpil", 2: "indl" },
    ix: { 1: "dpix", 2: "indx" },
    iy: { 1: "dpiy" }, ily: { 1: "dpily" }, sr: { 1: "sr" }, sriy: { 1: "sriy" },
  };

  function assemble(source, options = {}) {
    const lines = source.replace(/\r\n?/g, "\n").split("\n");
    const symbols = new Map();
    const errors = [];
    const decisions = new Map();
    let rom, written, sourceMap, title, highest;

    function run(pass) {
      rom = new Uint8Array(ROM_MAX).fill(0xff);
      written = new Uint8Array(ROM_MAX);
      sourceMap = new Map();
      title = options.title || "AETHER 16";
      highest = 0;
      let pc = 0x008000, scope = "", a8 = true, i8 = true;
      const full = (name) => (name.startsWith("@") ? scope + name : name);
      const lookup = (name) => { const k = full(name.toLowerCase()); return symbols.has(k) ? symbols.get(k) : undefined; };
      const define = (name, v) => {
        const key = full(name.toLowerCase());
        if (pass === 1 && symbols.has(key) && symbols.get(key) !== v) throw new AsmError(`« ${name} » est déjà défini`);
        if (pass === 1 && TABLE[name.toUpperCase()]) throw new AsmError(`« ${name} » est le nom d'une instruction`);
        symbols.set(key, v);
      };
      const value = (expr, allowUnknown = pass === 1) => {
        let e = expr.trim(), bank = false;
        if (e.startsWith("^")) { bank = true; e = e.slice(1); }
        const r = evaluate(e, lookup, pc);
        if (r.unknown && pass === 2 && !allowUnknown) throw new AsmError(`symbole inconnu dans « ${expr.trim()} »`);
        return { value: bank ? (r.value >> 16) & 0xff : r.value, unknown: r.unknown };
      };
      const romOffset = (addr) => {
        const bank = (addr >> 16) & 0x7f, off = addr & 0xffff;
        if (off < 0x8000 || bank >= 0x7e) throw new AsmError(`adresse $${addr.toString(16)} hors de la ROM (banques $00-$7D, $8000-$FFFF)`);
        return (bank << 15) | (off & 0x7fff);
      };
      const emit = (byte, lineNo) => {
        const o = romOffset(pc);
        if (o >= ROM_MAX) throw new AsmError("programme trop grand (1 Mo au plus)");
        if (pass === 2) {
          if (written[o]) throw new AsmError(`l'adresse $${pc.toString(16).toUpperCase()} est écrite deux fois`);
          written[o] = 1; rom[o] = byte & 0xff; sourceMap.set(pc, lineNo);
        }
        highest = Math.max(highest, o + 1);
        pc = (pc & 0xff0000) | ((pc + 1) & 0xffff);
        if ((pc & 0xffff) === 0) pc = (pc + 0x18000) & 0xffffff;  // fin de banque LoROM : on passe à la suivante
      };
      const emitN = (v, n, lineNo) => { for (let k = 0; k < n; k++) emit(v >> (8 * k), lineNo); };

      lines.forEach((raw, index) => {
        const lineNo = index + 1;
        try {
          let line = stripComment(raw).trim();
          if (!line) return;
          let m;
          while ((m = /^([a-z_@][\w@]*)\s*:\s*/i.exec(line))) {
            if (!m[1].startsWith("@")) scope = m[1].toLowerCase();
            define(m[1], pc);
            line = line.slice(m[0].length);
          }
          if (!line) return;
          if ((m = /^([a-z_]\w*)\s*=\s*(.+)$/i.exec(line))) { define(m[1], value(m[2]).value); return; }
          const parts = /^(\.?[a-z0-9]+)(\.[bwl])?\s*(.*)$/i.exec(line);
          if (!parts) throw new AsmError(`ligne illisible : « ${line} »`);
          const word = parts[1].toLowerCase(), rest = parts[3];
          if (word.startsWith(".")) directive(word, rest, lineNo);
          else instruction(word.toUpperCase(), (parts[2] || "").toLowerCase(), rest, lineNo, index);
        } catch (error) {
          if (!(error instanceof AsmError)) throw error;
          if (pass === 2 || !/inconnu/.test(error.message)) errors.push({ line: lineNo, message: error.message, pass });
        }
      });

      function directive(word, rest, lineNo) {
        const args = splitArgs(rest);
        switch (word) {
          case ".org": pc = value(rest, false).value & 0xffffff; break;
          case ".bank": pc = ((value(rest, false).value & 0x7f) << 16) | 0x8000; break;
          case ".a8": a8 = true; break;
          case ".a16": a8 = false; break;
          case ".i8": i8 = true; break;
          case ".i16": i8 = false; break;
          case ".title": title = rest.replace(/"/g, "").trim(); break;
          case ".byte": case ".db":
            for (const a of args) {
              if (/^".*"$/.test(a)) { for (const ch of a.slice(1, -1)) emit(ch.charCodeAt(0), lineNo); continue; }
              const v = value(a).value;
              if (pass === 2 && (v < -128 || v > 255)) throw new AsmError(`${a} ne tient pas dans un octet`);
              emit(v, lineNo);
            }
            break;
          case ".word": case ".dw": for (const a of args) emitN(value(a).value, 2, lineNo); break;
          case ".long": case ".dl": for (const a of args) emitN(value(a).value, 3, lineNo); break;
          case ".res": case ".ds": {
            const count = value(args[0] || "0", false).value, fill = args[1] ? value(args[1], false).value : 0;
            if (count < 0 || count > 0x10000) throw new AsmError("taille réservée invalide");
            if ((pc & 0xffff) < 0x8000 || ((pc >> 16) & 0x7f) >= 0x7e) { pc += count; break; }  // réserve en RAM
            for (let i = 0; i < count; i++) emit(fill, lineNo);
            break;
          }
          case ".align": {
            const n = value(rest, false).value;
            if (n <= 0) throw new AsmError("alignement invalide");
            while (pc % n) emit(0xff, lineNo);
            break;
          }
          case ".vectors": {
            if (args.length !== 3) throw new AsmError(".vectors nmi, reset, irq attendu");
            const [nmi, reset, irq] = args.map((a) => value(a).value & 0xffff);
            const keep = pc;
            // natifs : COP FFE4, BRK FFE6, NMI FFEA, IRQ FFEE ; émulation : COP FFF4, NMI FFFA, RESET FFFC, IRQ/BRK FFFE
            const table = [[0xffe4, irq], [0xffe6, irq], [0xffea, nmi], [0xffee, irq],
                           [0xfff4, irq], [0xfffa, nmi], [0xfffc, reset], [0xfffe, irq]];
            for (const [addr, v] of table) { pc = addr; emitN(v, 2, lineNo); }
            pc = keep;
            break;
          }
          case ".tile4": {
            if (args.length !== 8) throw new AsmError(".tile4 attend 8 lignes de 8 points");
            const planes = [[], [], [], []];
            for (const a of args) {
              const row = a.replace(/"/g, "");
              if (!/^[.0-9a-f]{8}$/i.test(row)) throw new AsmError(`ligne de motif « ${row} » : 8 caractères parmi . 0-9 a-f`);
              const p = [0, 0, 0, 0];
              for (const ch of row) {
                const c = ch === "." ? 0 : parseInt(ch, 16);
                for (let b = 0; b < 4; b++) p[b] = (p[b] << 1) | ((c >> b) & 1);
              }
              for (let b = 0; b < 4; b++) planes[b].push(p[b]);
            }
            // format de la puce : plans 0/1 entrelacés ligne par ligne, puis plans 2/3
            for (let y = 0; y < 8; y++) { emit(planes[0][y], lineNo); emit(planes[1][y], lineNo); }
            for (let y = 0; y < 8; y++) { emit(planes[2][y], lineNo); emit(planes[3][y], lineNo); }
            break;
          }
          default: throw new AsmError(`directive inconnue : ${word}`);
        }
      }

      function instruction(name, suffix, rest, lineNo, index) {
        const modes = TABLE[name];
        if (!modes) throw new AsmError(`instruction inconnue : ${name}`);
        const [shape, expr] = operandShape(rest);
        const start = pc;
        if (modes.bm !== undefined) {  // MVN / MVP : banque source, banque destination
          const args = splitArgs(rest);
          if (args.length !== 2) throw new AsmError(`${name} attend deux banques : ${name.toLowerCase()} source, destination`);
          emit(modes.bm, lineNo);
          emit(value(args[1]).value, lineNo); emit(value(args[0]).value, lineNo);
          return;
        }
        if (shape === "none" || shape === "acc") {
          if (shape === "none" && modes.imp !== undefined) { emit(modes.imp, lineNo); return; }
          if (modes.acc !== undefined) { emit(modes.acc, lineNo); return; }
          if (modes.imm8 !== undefined && shape === "none") { emit(modes.imm8, lineNo); emit(0, lineNo); return; }  // BRK seul
          throw new AsmError(`${name} demande un opérande`);
        }
        if (modes.rel !== undefined || modes.rell !== undefined) {
          if (shape !== "direct") throw new AsmError(`${name} attend une étiquette (branchement relatif)`);
          const target = value(expr).value;
          const long = modes.rell !== undefined;
          emit(long ? modes.rell : modes.rel, lineNo);
          const offset = (target & 0xffff) - (((start & 0xffff) + (long ? 3 : 2)) & 0xffff);
          if (!long) {
            if (pass === 2 && (offset < -128 || offset > 127)) throw new AsmError(`branchement trop loin (${offset} octets) : utilise BRL ou JMP`);
            emit(offset, lineNo);
          } else emitN(offset, 2, lineNo);
          return;
        }
        if (shape === "imm") {
          const r = value(expr);
          let size;
          if (modes.imm8 !== undefined) { emit(modes.imm8, lineNo); size = 1; }
          else if (modes.imm !== undefined) { emit(modes.imm, lineNo); size = a8 ? 1 : 2; }
          else if (modes.immx !== undefined) { emit(modes.immx, lineNo); size = i8 ? 1 : 2; }
          else if (name === "PEA") { emit(modes.abs, lineNo); size = 2; }
          else throw new AsmError(`${name} n'accepte pas de valeur immédiate`);
          if (suffix === ".b") size = 1; else if (suffix === ".w") size = 2;
          if (pass === 2 && size === 1 && (r.value < -128 || r.value > 0xff)) {
            throw new AsmError(`#${expr} ne tient pas dans un octet (accumulateur ou index en 8 bits : .a16 / .i16 ou rep)`);
          }
          emitN(r.value, size, lineNo);
          // suivi automatique des largeurs
          if (!r.unknown && (name === "REP" || name === "SEP")) {
            if (r.value & 0x20) a8 = name === "SEP";
            if (r.value & 0x10) i8 = name === "SEP";
          }
          return;
        }
        const family = BY_SIZE[shape];
        if (!family) throw new AsmError(`${name} n'accepte pas ce mode d'adressage`);
        let mode;
        if (["PEI"].includes(name)) mode = "dpi";
        else if (name === "PEA") mode = "abs";
        else {
          let decided = decisions.get(index);
          if (pass === 1 || decided === undefined) {
            const forced = { ".b": 1, ".w": 2, ".l": 3 }[suffix];
            const r = value(expr);
            let size = forced;
            if (!size) {
              if (r.unknown) size = 2;
              else if (r.value >= 0 && r.value < 0x100 && !["JMP", "JSR", "JML", "JSL"].includes(name)) size = 1;
              else if (r.value > 0xffff) size = 3;
              else size = 2;
            }
            if (name === "JML" || name === "JSL") size = shape === "il" ? 2 : 3;
            if (name === "JMP" && size === 3) { name = "JML"; }
            // repli : si la taille voulue n'existe pas pour cette instruction, on prend la suivante
            const order = [size, size + 1, size + 2, size - 1].filter((s) => s >= 1 && s <= 3);
            decided = null;
            for (const s of order) { const md = family[s]; if (md && TABLE[name][md] !== undefined) { decided = md; break; } }
            if (!decided) throw new AsmError(`${name} n'accepte pas ce mode d'adressage`);
            decisions.set(index, decided);
          }
          mode = decided;
        }
        const op = (name === "JMP" && mode === "abl") ? TABLE.JML.abl : TABLE[name][mode];
        if (op === undefined) throw new AsmError(`${name} n'accepte pas ce mode d'adressage`);
        emit(op, lineNo);
        const v = value(expr).value;
        const size = { dp: 1, dpx: 1, dpy: 1, dpi: 1, dpil: 1, dpix: 1, dpiy: 1, dpily: 1, sr: 1, sriy: 1, abl: 3, ablx: 3 }[mode] || 2;
        if (pass === 2 && size === 1 && (v < 0 || v > 0xff)) throw new AsmError(`${expr} ne tient pas en page directe (0-$FF) : utilise ${name.toLowerCase()}.w`);
        emitN(v, size, lineNo);
      }
      return highest;
    }

    run(1);
    const firstErrors = errors.splice(0).filter((e) => !/inconnu/.test(e.message));
    run(2);
    errors.unshift(...firstErrors.filter((e) => !errors.some((x) => x.line === e.line)));
    errors.sort((a, b) => a.line - b.line);
    if (!errors.length && (rom[0x7ffc] | (rom[0x7ffd] << 8)) === 0xffff) {
      errors.push({ line: 0, message: "pas de vecteur de démarrage : ajoute « .vectors nmi, reset, irq »" });
    }
    // taille : puissance de 2, 32 Ko au minimum
    let size = 0x8000;
    while (size < highest) size <<= 1;
    const out = rom.slice(0, size);
    // en-tête interne ($7FC0) : titre, carte LoROM, ROM seule, taille, pas de sauvegarde, somme de contrôle
    const h = 0x7fc0;
    const t = title.toUpperCase().slice(0, 21).padEnd(21, " ");
    for (let i = 0; i < 21; i++) { const c = t.charCodeAt(i); out[h + i] = c >= 0x20 && c < 0x7f ? c : 0x20; }
    out[h + 0x15] = 0x20; out[h + 0x16] = 0x00; out[h + 0x17] = Math.round(Math.log2(size / 1024));
    out[h + 0x18] = 0; out[h + 0x19] = 0; out[h + 0x1a] = 0; out[h + 0x1b] = 0;
    out[h + 0x1c] = 0xff; out[h + 0x1d] = 0xff; out[h + 0x1e] = 0; out[h + 0x1f] = 0;
    let sum = 0;
    for (let i = 0; i < size; i++) sum = (sum + out[i]) & 0xffff;
    out[h + 0x1e] = sum & 0xff; out[h + 0x1f] = sum >> 8;
    out[h + 0x1c] = ~sum & 0xff; out[h + 0x1d] = (~sum >> 8) & 0xff;
    let used = 0;
    for (let i = 0; i < size; i++) used += written[i] ? 1 : 0;
    return { ok: errors.length === 0, errors, rom: out, symbols, sourceMap, used, title };
  }

  root.AetherAsm16 = { assemble };
})(typeof window !== "undefined" ? window : globalThis);
