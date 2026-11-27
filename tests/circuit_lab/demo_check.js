// Le jeu d'exemple s'assemble sans erreur, démarre, réagit à la manette et marque des points.
// Usage : node demo_check.js [image.ppm] (écrit la dernière image si un chemin est donné).
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");
for (const f of ["c8_cpu.js", "asm6502.js", "c8_ppu.js", "c8_machine.js"]) {
  require(path.join(__dirname, "..", "..", "core", "web", f));
}
const { assemble } = globalThis.AetherAsm;
const { Machine, PARTS } = globalThis.AetherNES;
const { PALETTE } = globalThis.AetherPPU;

const source = fs.readFileSync(path.join(__dirname, "..", "..", "modules", "circuit_lab", "examples", "etoiles.asm"), "utf8");
const built = assemble(source);
assert.deepStrictEqual(built.errors, [], JSON.stringify(built.errors));
const m = new Machine(PARTS.map((p) => p.id), built.rom);
for (let i = 0; i < 30; i++) m.runFrame();
const start = m.ram[3];                         // cat_x
m.press(0, "Right", true);
for (let i = 0; i < 20; i++) m.runFrame();
m.press(0, "Right", false);
assert.ok(m.ram[3] > start + 20, `le chat avance : ${start} → ${m.ram[3]}`);
let caught = 0;
for (let i = 0; i < 1800 && !caught; i++) {    // 30 s : on suit la première étoile qui tombe
  const sx = m.ram[8], cx = m.ram[3];
  m.press(0, "Left", sx + 4 < cx + 8); m.press(0, "Right", sx + 4 > cx + 8);
  m.runFrame();
  caught = m.ram[4] * 100 + m.ram[5] * 10 + m.ram[6];
}
assert.ok(caught > 0, "au moins une étoile attrapée");
const fb = m.ppu.frameBuffer;
assert.strictEqual(fb[26 * 8 * 256 + 3 * 256 + 9], 0x1a);   // herbe verte sur la ligne 26
if (process.argv[2]) {
  const out = Buffer.alloc(256 * 240 * 3);
  for (let i = 0; i < fb.length; i++) {
    const c = PALETTE[fb[i]];
    out[i * 3] = c & 255; out[i * 3 + 1] = (c >> 8) & 255; out[i * 3 + 2] = (c >> 16) & 255;
  }
  fs.writeFileSync(process.argv[2], Buffer.concat([Buffer.from("P6\n256 240\n255\n"), out]));
}
console.log(`jeu d'exemple : ok (${built.prg.length} octets de programme, score ${caught})`);
