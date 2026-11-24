"use strict";
// Banc logique Æther (façon FPGA) : simulateur de circuits numériques à câbler, sans dépendance.
// Un circuit = des pièces (portes, bascules, compteurs, blocs, entrées et sorties) et des fils qui relient une sortie
// à une entrée. Chaque signal vaut 0 ou 1. La simulation avance par demi-périodes d'horloge (« pas ») :
//   1. les horloges basculent ;
//   2. la logique combinatoire se stabilise (relaxation pièce par pièce jusqu'à un point fixe ; au-delà de
//      MAX_PASSES passes, le circuit est déclaré instable : il oscille, par exemple un inverseur bouclé sur lui-même) ;
//   3. les pièces séquentielles dont l'entrée d'horloge vient de monter (front montant) prennent toutes en même temps
//      leur nouvel état, calculé sur les entrées d'avant le front ; puis on stabilise de nouveau (compteurs en cascade).
// Le chronogramme garde les derniers échantillons des entrées, horloges, LED et sondes.
(function (root) {
  const MAX_PASSES = 64;
  const MAX_HISTORY = 240;
  const bits = (v, n) => Array.from({ length: n }, (_, i) => (v >> i) & 1);
  const word = (a, from, n) => { let v = 0; for (let i = 0; i < n; i++) v |= (a[from + i] ? 1 : 0) << i; return v; };
  const names = (prefix, n) => Array.from({ length: n }, (_, i) => `${prefix}${i}`);
  // Segments a à g allumés pour chaque chiffre hexadécimal (bit 0 = a … bit 6 = g).
  const HEX7 = [0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f, 0x77, 0x7c, 0x39, 0x5e, 0x79, 0x71];

  const gate = (label, symbol, fn) => ({ cat: "Portes", label, symbol, ins: ["A", "B"], outs: ["Y"], w: 56,
                                          eval: (i) => [fn(i[0], i[1]) ? 1 : 0] });
  // Une entrée « NOM=1 » vaut 1 quand rien n'y est branché (sinon 0).
  const TYPES = {
    switch: { cat: "Entrées", label: "Interrupteur", ins: [], outs: ["Q"], w: 56, input: true, trace: "out",
              init: (p) => ({ v: p.on ? 1 : 0 }), eval: (i, s) => [s.v] },
    button: { cat: "Entrées", label: "Bouton poussoir", ins: [], outs: ["Q"], w: 56, input: true, trace: "out",
              init: () => ({ v: 0 }), eval: (i, s) => [s.v] },
    clock: { cat: "Entrées", label: "Horloge", ins: [], outs: ["CLK"], w: 56, trace: "out", props: { half: 1 },
             init: () => ({ v: 0, n: 0 }), eval: (i, s) => [s.v] },
    const1: { cat: "Entrées", label: "Constante 1", ins: [], outs: ["1"], w: 40, eval: () => [1] },
    const0: { cat: "Entrées", label: "Constante 0", ins: [], outs: ["0"], w: 40, eval: () => [0] },

    led: { cat: "Sorties", label: "LED", ins: ["A"], outs: [], w: 40, trace: "in", props: { color: "rouge" },
           eval: () => [] },
    probe: { cat: "Sorties", label: "Sonde", ins: ["A"], outs: [], w: 40, trace: "in", eval: () => [] },
    hex7: { cat: "Sorties", label: "Afficheur 7 segments (hexa)", ins: names("D", 4), outs: [], w: 80,
            eval: () => [] },
    seg7: { cat: "Sorties", label: "Afficheur 7 segments (brut)", ins: ["a", "b", "c", "d", "e", "f", "g", "dp"], outs: [],
            w: 80, eval: () => [] },

    not: { cat: "Portes", label: "NON", symbol: "1", ins: ["A"], outs: ["Y"], w: 56, eval: (i) => [i[0] ? 0 : 1] },
    and: gate("ET", "&", (a, b) => a & b),
    or: gate("OU", "≥1", (a, b) => a | b),
    nand: gate("NON-ET", "&", (a, b) => !(a & b)),
    nor: gate("NON-OU", "≥1", (a, b) => !(a | b)),
    xor: gate("OU exclusif", "=1", (a, b) => a ^ b),
    xnor: gate("NON-OU exclusif", "=", (a, b) => !(a ^ b)),

    srlatch: { cat: "Bascules", label: "Verrou SR", ins: ["S", "R"], outs: ["Q", "/Q"], w: 64, init: () => ({ q: 0 }),
               eval: (i, s) => { if (i[0] && !i[1]) s.q = 1; else if (i[1] && !i[0]) s.q = 0; return [s.q, s.q ^ 1]; } },
    dff: { cat: "Bascules", label: "Bascule D", ins: ["D", "CLK", "R"], outs: ["Q", "/Q"], w: 64, clk: 1,
           init: () => ({ q: 0 }),
           eval: (i, s) => { if (i[2]) s.q = 0; return [s.q, s.q ^ 1]; },
           next: (i, s) => (i[2] ? 0 : i[0]), apply: (s, q) => { s.q = q; } },
    tff: { cat: "Bascules", label: "Bascule T", ins: ["T=1", "CLK", "R"], outs: ["Q", "/Q"], w: 64, clk: 1,
           init: () => ({ q: 0 }),
           eval: (i, s) => { if (i[2]) s.q = 0; return [s.q, s.q ^ 1]; },
           next: (i, s) => (i[2] ? 0 : s.q ^ i[0]), apply: (s, q) => { s.q = q; } },
    jkff: { cat: "Bascules", label: "Bascule JK", ins: ["J", "CLK", "K", "R"], outs: ["Q", "/Q"], w: 64, clk: 1,
            init: () => ({ q: 0 }),
            eval: (i, s) => { if (i[3]) s.q = 0; return [s.q, s.q ^ 1]; },
            next: (i, s) => (i[3] ? 0 : i[0] && i[2] ? s.q ^ 1 : i[0] ? 1 : i[2] ? 0 : s.q),
            apply: (s, q) => { s.q = q; } },

    counter4: { cat: "Blocs", label: "Compteur 4 bits", ins: ["CLK", "EN=1", "RAZ", "CH", ...names("D", 4)],
                outs: [...names("Q", 4), "RET"], w: 72, clk: 0, init: () => ({ v: 0 }),
                eval: (i, s) => { if (i[2]) s.v = 0; return [...bits(s.v, 4), i[1] && s.v === 15 ? 1 : 0]; },
                next: (i, s) => (i[2] ? 0 : i[3] ? word(i, 4, 4) : i[1] ? (s.v + 1) & 15 : s.v),
                apply: (s, v) => { s.v = v; } },
    reg4: { cat: "Blocs", label: "Registre 4 bits", ins: [...names("D", 4), "CH=1", "CLK"], outs: names("Q", 4), w: 72,
            clk: 5, init: () => ({ v: 0 }), eval: (i, s) => bits(s.v, 4),
            next: (i, s) => (i[4] ? word(i, 0, 4) : s.v), apply: (s, v) => { s.v = v; } },
    fa: { cat: "Blocs", label: "Additionneur complet", ins: ["A", "B", "Ri"], outs: ["S", "Ro"], w: 64,
          eval: (i) => { const t = i[0] + i[1] + i[2]; return [t & 1, t >> 1]; } },
    add4: { cat: "Blocs", label: "Additionneur 4 bits", ins: [...names("A", 4), ...names("B", 4), "Ri"],
            outs: [...names("S", 4), "Ro"], w: 72,
            eval: (i) => { const t = word(i, 0, 4) + word(i, 4, 4) + i[8]; return [...bits(t, 4), t >> 4]; } },
    mux2: { cat: "Blocs", label: "Multiplexeur 2 vers 1", ins: ["A", "B", "SEL"], outs: ["Y"], w: 64,
            eval: (i) => [i[2] ? i[1] : i[0]] },
    mux4b: { cat: "Blocs", label: "Multiplexeur 4 bits", ins: [...names("A", 4), ...names("B", 4), "SEL"],
             outs: names("Y", 4), w: 72, eval: (i) => (i[8] ? i.slice(4, 8) : i.slice(0, 4)) },
    dec2: { cat: "Blocs", label: "Décodeur 2 vers 4", ins: ["A0", "A1", "EN=1"], outs: names("Y", 4), w: 64,
            eval: (i) => { const n = i[0] | (i[1] << 1); return [0, 1, 2, 3].map((k) => (i[2] && k === n ? 1 : 0)); } },
    rom: { cat: "Blocs", label: "Mémoire ROM 16 × 8", ins: names("A", 4), outs: names("D", 8), w: 72,
           props: { data: new Array(16).fill(0) },
           eval: (i, s, p) => bits(((p.data || [])[word(i, 0, 4)] | 0) & 0xff, 8) },
  };
  // Titres courts écrits dans les blocs.
  const SHORT = { srlatch: "Verrou SR", dff: "Bascule D", tff: "Bascule T", jkff: "Bascule JK", counter4: "Compteur",
                  reg4: "Registre", fa: "Add. complet", add4: "Add. 4 bits", mux2: "Mux 2 → 1", mux4b: "Mux 4 bits",
                  dec2: "Décodeur", rom: "ROM 16 × 8" };
  for (const [type, def] of Object.entries(TYPES)) {
    def.type = type;
    def.inNames = def.ins.map((n) => n.split("=")[0]);
    def.inDefault = def.ins.map((n) => (n.endsWith("=1") ? 1 : 0));
    def.short = SHORT[type] || def.label;
    def.head = def.cat === "Blocs" || def.cat === "Bascules" ? 14 : 0; // place du titre des blocs
  }

  // ---------- géométrie (partagée par l'éditeur et les vérifications) ----------
  const PITCH = 16;
  function size(def) {
    const n = Math.max(def.ins.length, def.outs.length, 1);
    return { w: def.w, h: Math.max(32, n * PITCH + 8 + def.head) };
  }
  function pinPos(part, side, index) {
    const def = TYPES[part.type];
    const { w, h } = size(def);
    const n = side === "in" ? def.ins.length : def.outs.length;
    const top = part.y + def.head + (h - def.head - (n - 1) * PITCH) / 2;
    return { x: side === "in" ? part.x : part.x + w, y: top + index * PITCH };
  }

  // ---------- simulateur ----------
  class Sim {
    constructor(doc) { this.load(doc || { parts: [], wires: [] }); }

    load(doc) {
      this.doc = doc;
      this.t = 0;
      this.unstable = false;
      this.history = [];
      this.problems = [];
      const index = new Map();
      this.parts = doc.parts.map((p, k) => {
        const def = TYPES[p.type];
        if (!def) throw new Error(`pièce inconnue : ${p.type}`);
        index.set(p.id, k);
        const props = Object.assign({}, JSON.parse(JSON.stringify(def.props || {})), p.props || {});
        p.props = props;
        return { src: p, def, props, st: def.init ? def.init(props) : {}, ins: new Array(def.ins.length).fill(null),
                 inV: def.inDefault.slice(), out: new Array(def.outs.length).fill(0), lastClk: 0 };
      });
      for (const w of doc.wires) {
        const a = this.parts[index.get(w.from[0])], b = this.parts[index.get(w.to[0])];
        if (!a || !b) { this.problems.push("fil relié à une pièce absente"); continue; }
        const o = a.def.outs.indexOf(w.from[1]), i = b.def.inNames.indexOf(w.to[1]);
        if (o < 0 || i < 0) { this.problems.push(`broche inconnue : ${w.from[1]} → ${w.to[1]}`); continue; }
        if (b.ins[i]) { this.problems.push(`${label(b)} : l'entrée ${w.to[1]} reçoit déjà un fil`); continue; }
        b.ins[i] = { p: a, o };
      }
      this.index = index;
      this.settle();
      for (const p of this.parts) if (p.def.clk !== undefined) p.lastClk = this.readInputs(p)[p.def.clk];
      this.record();
    }

    part(id) { return this.parts[this.index.get(id)]; }

    readInputs(p) {
      for (let k = 0; k < p.ins.length; k++) {
        const s = p.ins[k];
        p.inV[k] = s ? s.p.out[s.o] : p.def.inDefault[k];
      }
      return p.inV;
    }

    // Stabilise la logique combinatoire. Renvoie false si le circuit oscille.
    settle() {
      for (let pass = 0; pass < MAX_PASSES; pass++) {
        let changed = false;
        for (const p of this.parts) {
          const v = p.def.eval(this.readInputs(p), p.st, p.props);
          for (let k = 0; k < v.length; k++) {
            if (p.out[k] !== v[k]) { p.out[k] = v[k]; changed = true; }
          }
        }
        if (!changed) { this.unstable = false; return true; }
      }
      this.unstable = true;
      return false;
    }

    // Fronts montants : toutes les bascules touchées prennent leur nouvel état en même temps.
    edges() {
      for (let round = 0; round < 32; round++) {
        const hits = [];
        for (const p of this.parts) {
          if (p.def.clk === undefined) continue;
          const clk = this.readInputs(p)[p.def.clk];
          if (clk && !p.lastClk) hits.push([p, p.def.next(p.inV, p.st, p.props)]);
          p.lastClk = clk;
        }
        if (!hits.length) return;
        for (const [p, v] of hits) p.def.apply(p.st, v);
        this.settle();
      }
    }

    // Un pas = une demi-période de l'horloge la plus rapide.
    step() {
      this.t += 1;
      for (const p of this.parts) {
        if (p.def.type !== "clock") continue;
        const half = Math.max(1, p.props.half | 0);
        if (++p.st.n >= half) { p.st.n = 0; p.st.v ^= 1; }
      }
      this.settle();
      this.edges();
      this.record();
    }

    // Interrupteur ou bouton : change la valeur puis propage (sans avancer le temps).
    setInput(id, v) {
      const p = this.part(id);
      if (!p || !p.def.input) return;
      p.st.v = v ? 1 : 0;
      p.props.on = Boolean(v);
      this.settle();
      this.edges();
      if (this.history.length) this.history[this.history.length - 1].v = this.sample();
    }

    traced() { return this.parts.filter((p) => p.def.trace); }
    sample() {
      return this.traced().map((p) => (p.def.trace === "out" ? p.out[0] : this.readInputs(p)[0]));
    }
    record() {
      this.history.push({ t: this.t, v: this.sample() });
      if (this.history.length > MAX_HISTORY) this.history.shift();
    }

    // Valeur vue par une entrée (pour l'affichage des LED et afficheurs).
    inputs(id) { const p = this.part(id); return p ? this.readInputs(p).slice() : []; }
    outputs(id) { const p = this.part(id); return p ? p.out.slice() : []; }
    segments(id) {
      const p = this.part(id);
      if (!p) return 0;
      const i = this.readInputs(p);
      return p.def.type === "hex7" ? HEX7[word(i, 0, 4)] : word(i, 0, 8);
    }
    stateOf(id) { const p = this.part(id); return p ? Object.assign({}, p.st) : {}; }
  }
  function label(p) { return p.src.label || p.def.label; }

  // ---------- montages d'exemple ----------
  function build(fn) {
    const parts = [], wires = [];
    const api = {
      add(type, x, y, labelText, props) {
        const id = `p${parts.length + 1}`;
        parts.push({ id, type, x, y, label: labelText || "", props: props || {} });
        return id;
      },
      wire(a, ao, b, bi) { wires.push({ from: [a, ao], to: [b, bi] }); },
    };
    fn(api);
    return { version: 1, parts, wires };
  }
  const EXAMPLES = {
    demi: { title: "Demi-additionneur", text: "A + B : la somme S par un OU exclusif, la retenue R par un ET.",
            build: () => build(({ add, wire }) => {
              const a = add("switch", 40, 60, "A"), b = add("switch", 40, 140, "B");
              const x = add("xor", 200, 60), n = add("and", 200, 140);
              const s = add("led", 340, 64, "S"), r = add("led", 340, 144, "R", { color: "ambre" });
              wire(a, "Q", x, "A"); wire(b, "Q", x, "B"); wire(a, "Q", n, "A"); wire(b, "Q", n, "B");
              wire(x, "Y", s, "A"); wire(n, "Y", r, "A");
            }) },
    complet: { title: "Additionneur complet en portes",
               text: "Deux demi-additionneurs et un OU : A + B + retenue d'entrée Ri donnent la somme S et la retenue Ro.",
               build: () => build(({ add, wire }) => {
                 const a = add("switch", 40, 40, "A"), b = add("switch", 40, 120, "B"), ci = add("switch", 40, 220, "Ri");
                 const x1 = add("xor", 180, 40), a1 = add("and", 180, 120), x2 = add("xor", 320, 120);
                 const a2 = add("and", 320, 220), o = add("or", 460, 160);
                 const s = add("led", 600, 124, "S"), co = add("led", 600, 164, "Ro", { color: "ambre" });
                 wire(a, "Q", x1, "A"); wire(b, "Q", x1, "B"); wire(a, "Q", a1, "A"); wire(b, "Q", a1, "B");
                 wire(x1, "Y", x2, "A"); wire(ci, "Q", x2, "B"); wire(x1, "Y", a2, "A"); wire(ci, "Q", a2, "B");
                 wire(a1, "Y", o, "A"); wire(a2, "Y", o, "B"); wire(x2, "Y", s, "A"); wire(o, "Y", co, "A");
               }) },
    verrou: { title: "Verrou SR en portes NON-OU",
              text: "Deux NON-OU rebouclés gardent un bit en mémoire : S le met à 1, R le remet à 0.",
              build: () => build(({ add, wire }) => {
                const s = add("button", 40, 60, "S"), r = add("button", 40, 180, "R");
                const n1 = add("nor", 220, 60), n2 = add("nor", 220, 180);
                const q = add("led", 380, 64, "Q"), nq = add("led", 380, 184, "/Q", { color: "ambre" });
                wire(r, "Q", n1, "A"); wire(n2, "Y", n1, "B"); wire(s, "Q", n2, "B"); wire(n1, "Y", n2, "A");
                wire(n1, "Y", q, "A"); wire(n2, "Y", nq, "A");
              }) },
    diviseur: { title: "Diviseur d'horloge (bascules D)",
                text: "Chaque bascule D dont /Q revient sur D change d'état à chaque front : elle divise sa fréquence par 2.",
                build: () => build(({ add, wire }) => {
                  const clk = add("clock", 40, 120, "H");
                  let prev = [clk, "CLK"];
                  const leds = [];
                  for (let k = 0; k < 3; k++) {
                    const f = add("dff", 170 + k * 150, 100);
                    wire(f, "/Q", f, "D"); wire(prev[0], prev[1], f, "CLK");
                    leds.push([f, add("led", 200 + k * 150, 220, `H/${2 << k}`, { color: k ? "vert" : "rouge" })]);
                    prev = [f, "/Q"];
                  }
                  for (const [f, l] of leds) wire(f, "Q", l, "A");
                }) },
    compteur: { title: "Compteur 4 bits sur 7 segments",
                text: "Un compteur synchrone avance à chaque front montant ; l'afficheur décode les 4 bits en chiffre hexadécimal.",
                build: () => build(({ add, wire }) => {
                  const clk = add("clock", 40, 80, "H"), raz = add("switch", 40, 180, "RAZ");
                  const c = add("counter4", 200, 60), d = add("hex7", 380, 60, "", {});
                  const ro = add("led", 380, 210, "RET", { color: "ambre" });
                  wire(clk, "CLK", c, "CLK"); wire(raz, "Q", c, "RAZ"); wire(c, "RET", ro, "A");
                  for (let k = 0; k < 4; k++) {
                    wire(c, `Q${k}`, d, `D${k}`);
                    wire(c, `Q${k}`, add("led", 520, 64 + k * 40, `Q${k}`, { color: "vert" }), "A");
                  }
                }) },
    processeur: { title: "Petit processeur 4 bits",
                  text: "Compteur de programme, ROM, additionneur, multiplexeur et accumulateur. Chaque mot de la ROM : "
                      + "bits 0 à 3 = valeur, bit 4 = AJOUTE (sinon CHARGE), bit 5 = SAUTE. Programme : CHARGE 0, AJOUTE 3, SAUTE 1.",
                  build: () => build(({ add, wire }) => {
                    const clk = add("clock", 24, 48, "H", { half: 1 });
                    const pc = add("counter4", 112, 48, "PC");
                    const rom = add("rom", 256, 48, "ROM", { data: [0x00, 0x13, 0x21, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] });
                    const sum = add("add4", 416, 232, "UAL");
                    const mux = add("mux4b", 560, 64, "");
                    const acc = add("reg4", 704, 64, "ACC");
                    const inv = add("not", 576, 304, "");
                    const out = add("hex7", 840, 64, "ACC");
                    const show = add("hex7", 112, 272, "PC");
                    const jump = add("led", 432, 64, "SAUTE", { color: "ambre" });
                    wire(clk, "CLK", pc, "CLK"); wire(clk, "CLK", acc, "CLK");
                    wire(rom, "D5", pc, "CH"); wire(rom, "D5", inv, "A"); wire(inv, "Y", acc, "CH");
                    wire(rom, "D4", mux, "SEL"); wire(rom, "D5", jump, "A");
                    for (let k = 0; k < 4; k++) {
                      wire(pc, `Q${k}`, rom, `A${k}`); wire(pc, `Q${k}`, show, `D${k}`);
                      wire(rom, `D${k}`, pc, `D${k}`); wire(rom, `D${k}`, mux, `A${k}`); wire(rom, `D${k}`, sum, `B${k}`);
                      wire(acc, `Q${k}`, sum, `A${k}`); wire(sum, `S${k}`, mux, `B${k}`);
                      wire(mux, `Y${k}`, acc, `D${k}`); wire(acc, `Q${k}`, out, `D${k}`);
                    }
                  }) },
  };

  root.AetherLogic = { TYPES, HEX7, Sim, EXAMPLES, size, pinPos, PITCH, MAX_PASSES };
})(typeof window !== "undefined" ? window : globalThis);
