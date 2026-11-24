// Vérifications du banc logique : portes, bascules, compteur, fronts simultanés, circuit instable, câblage incorrect
// et les montages d'exemple (additionneurs, verrou SR, diviseur, compteur 7 segments, petit processeur).
// Lancé par test_module.py.
"use strict";
const path = require("path");
const assert = require("assert");
require(path.join(__dirname, "..", "..", "core", "web", "logic_sim.js"));
const { Sim, EXAMPLES, TYPES, HEX7, pinPos, size } = globalThis.AetherLogic;

// ---------- portes : table de vérité ----------
const truth = { and: [0, 0, 0, 1], or: [0, 1, 1, 1], nand: [1, 1, 1, 0], nor: [1, 0, 0, 0], xor: [0, 1, 1, 0], xnor: [1, 0, 0, 1] };
for (const [type, want] of Object.entries(truth)) {
  const doc = { parts: [{ id: "a", type: "switch", x: 0, y: 0 }, { id: "b", type: "switch", x: 0, y: 0 },
                        { id: "g", type, x: 0, y: 0 }, { id: "l", type: "led", x: 0, y: 0 }],
                wires: [{ from: ["a", "Q"], to: ["g", "A"] }, { from: ["b", "Q"], to: ["g", "B"] }, { from: ["g", "Y"], to: ["l", "A"] }] };
  const s = new Sim(doc);
  [[0, 0], [0, 1], [1, 0], [1, 1]].forEach(([a, b], k) => {
    s.setInput("a", a); s.setInput("b", b);
    assert.strictEqual(s.inputs("l")[0], want[k], `${type}(${a}, ${b})`);
  });
}

// ---------- bascule D, entrée par défaut, remise à zéro ----------
{
  const s = new Sim({ parts: [{ id: "d", type: "switch", x: 0, y: 0 }, { id: "c", type: "button", x: 0, y: 0 },
                              { id: "r", type: "button", x: 0, y: 0 }, { id: "f", type: "dff", x: 0, y: 0 }],
                      wires: [{ from: ["d", "Q"], to: ["f", "D"] }, { from: ["c", "Q"], to: ["f", "CLK"] }, { from: ["r", "Q"], to: ["f", "R"] }] });
  s.setInput("d", 1);
  assert.strictEqual(s.outputs("f")[0], 0, "D sans front : Q ne bouge pas");
  s.setInput("c", 1);
  assert.deepStrictEqual(s.outputs("f"), [1, 0], "front montant : Q = D");
  s.setInput("d", 0); s.setInput("c", 0);
  assert.strictEqual(s.outputs("f")[0], 1, "front descendant : Q garde sa valeur");
  s.setInput("r", 1);
  assert.strictEqual(s.outputs("f")[0], 0, "R remet à zéro tout de suite");
}

// ---------- registre à décalage : fronts simultanés ----------
{
  const parts = [{ id: "h", type: "clock", x: 0, y: 0 }, { id: "in", type: "const1", x: 0, y: 0 }];
  const wires = [];
  let prev = ["in", "1"];
  for (let k = 0; k < 4; k++) {
    parts.push({ id: `f${k}`, type: "dff", x: 0, y: 0 });
    wires.push({ from: prev, to: [`f${k}`, "D"] }, { from: ["h", "CLK"], to: [`f${k}`, "CLK"] });
    prev = [`f${k}`, "Q"];
  }
  const s = new Sim({ parts, wires });
  s.step(); // premier front montant : seule la première bascule prend le 1
  assert.deepStrictEqual([0, 1, 2, 3].map((k) => s.outputs(`f${k}`)[0]), [1, 0, 0, 0], "décalage d'une case par front");
  s.step(); s.step();
  assert.deepStrictEqual([0, 1, 2, 3].map((k) => s.outputs(`f${k}`)[0]), [1, 1, 0, 0]);
}

// ---------- compteur 4 bits : retenue, chargement ----------
{
  const s = new Sim({ parts: [{ id: "h", type: "clock", x: 0, y: 0 }, { id: "c", type: "counter4", x: 0, y: 0 }],
                      wires: [{ from: ["h", "CLK"], to: ["c", "CLK"] }] });
  for (let i = 0; i < 30; i++) s.step();
  assert.strictEqual(s.stateOf("c").v, 15, "15 fronts montants en 30 demi-périodes");
  assert.strictEqual(s.outputs("c")[4], 1, "RET à 15");
  s.step(); s.step();
  assert.strictEqual(s.stateOf("c").v, 0, "le compteur repasse à 0");
}

// ---------- blocs combinatoires ----------
{
  const add = TYPES.add4.eval([1, 1, 1, 1, 1, 0, 0, 0, 0]);
  assert.deepStrictEqual(add, [0, 0, 0, 0, 1], "15 + 1 = 16 : somme 0, retenue 1");
  assert.deepStrictEqual(TYPES.mux4b.eval([1, 0, 1, 0, 0, 1, 0, 1, 1]), [0, 1, 0, 1], "SEL = 1 choisit B");
  assert.deepStrictEqual(TYPES.dec2.eval([1, 1, 1]), [0, 0, 0, 1]);
  assert.deepStrictEqual(TYPES.dec2.eval([1, 1, 0]), [0, 0, 0, 0], "décodeur désactivé");
  assert.strictEqual(HEX7[8], 0x7f);
}

// ---------- circuit instable et câblage incorrect ----------
{
  const osc = new Sim({ parts: [{ id: "n", type: "not", x: 0, y: 0 }], wires: [{ from: ["n", "Y"], to: ["n", "A"] }] });
  assert.ok(osc.unstable, "un inverseur rebouclé oscille");
  const bad = new Sim({ parts: [{ id: "a", type: "switch", x: 0, y: 0 }, { id: "b", type: "switch", x: 0, y: 0 }, { id: "l", type: "led", x: 0, y: 0 }],
                        wires: [{ from: ["a", "Q"], to: ["l", "A"] }, { from: ["b", "Q"], to: ["l", "A"] }, { from: ["a", "Z"], to: ["l", "A"] }] });
  assert.strictEqual(bad.problems.length, 2, "deux sorties sur une entrée et une broche inconnue sont signalées");
  assert.throws(() => new Sim({ parts: [{ id: "x", type: "inconnue", x: 0, y: 0 }], wires: [] }));
}

// ---------- montages d'exemple ----------
{
  const demi = new Sim(EXAMPLES.demi.build());
  demi.setInput("p1", 1); demi.setInput("p2", 1);
  assert.deepStrictEqual([demi.inputs("p5")[0], demi.inputs("p6")[0]], [0, 1], "1 + 1 = 10");

  const complet = new Sim(EXAMPLES.complet.build());
  for (let n = 0; n < 8; n++) {
    complet.setInput("p1", n & 1); complet.setInput("p2", (n >> 1) & 1); complet.setInput("p3", (n >> 2) & 1);
    const total = (n & 1) + ((n >> 1) & 1) + ((n >> 2) & 1);
    assert.deepStrictEqual([complet.inputs("p9")[0], complet.inputs("p10")[0]], [total & 1, total >> 1], `additionneur complet ${n}`);
  }

  const verrou = new Sim(EXAMPLES.verrou.build());
  assert.ok(!verrou.unstable);
  verrou.setInput("p1", 1); verrou.setInput("p1", 0);
  assert.strictEqual(verrou.inputs("p5")[0], 1, "S met Q à 1 et il y reste");
  verrou.setInput("p2", 1); verrou.setInput("p2", 0);
  assert.strictEqual(verrou.inputs("p5")[0], 0, "R remet Q à 0");

  const div = new Sim(EXAMPLES.diviseur.build());
  const rows = [];
  for (let i = 0; i < 16; i++) { div.step(); rows.push(div.sample().join("")); }
  assert.deepStrictEqual(rows.slice(0, 4), ["1100", "0100", "1010", "0010"], "H/2 puis H/4 : division par 2 à chaque étage");

  const cpt = new Sim(EXAMPLES.compteur.build());
  for (let i = 0; i < 10; i++) cpt.step();
  assert.strictEqual(cpt.segments("p4"), HEX7[5], "5 fronts : l'afficheur montre 5");
  cpt.setInput("p2", 1);
  assert.strictEqual(cpt.segments("p4"), HEX7[0], "RAZ remet à 0");

  const cpu = new Sim(EXAMPLES.processeur.build());
  const acc = [];
  for (let i = 0; i < 16; i++) { cpu.step(); if (i % 2 === 0) acc.push(cpu.stateOf("p6").v); }
  assert.deepStrictEqual(acc, [0, 3, 3, 6, 6, 9, 9, 12], "CHARGE 0, AJOUTE 3, SAUTE 1 : 0, 3, 6, 9, 12…");
  assert.ok(!cpu.unstable && !cpu.problems.length);
}

// ---------- géométrie : broches sur la grille et dans la pièce ----------
for (const [type, def] of Object.entries(TYPES)) {
  const part = { type, x: 0, y: 0 };
  const { h } = size(def);
  def.ins.forEach((n, k) => { const p = pinPos(part, "in", k); assert.ok(p.y > 0 && p.y < h, `${type}.${n}`); });
}

console.log("banc logique : ok");
