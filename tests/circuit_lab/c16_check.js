// Vérifications de la console 16 bits : processeur 65C816 (16 bits, décimal, MVN, XBA), registres de calcul,
// assembleur (largeurs, erreurs, en-tête de cartouche), lecture des cartouches, jeu d'exemple (image, manette,
// son par le module SPC700) et pannes des pièces manquantes. Lancé par test_module.py.
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");
const ROOT = path.join(__dirname, "..", "..");
for (const f of ["nes_cpu.js", "asm6502.js", "c16_cpu.js", "c16_ppu.js", "c16_apu.js", "c16_machine.js", "asm65816.js"]) {
  require(path.join(ROOT, "core", "web", f));
}
const { assemble } = globalThis.AetherAsm16;
const { Machine, PARTS, parseRom } = globalThis.AetherC16;
const { LUT } = globalThis.AetherPPU16;
const ALL = PARTS.map((p) => p.id);
const without = (...ids) => ALL.filter((id) => !ids.includes(id));
const bgr = (r, g, b) => (b << 10) | (g << 5) | r;

// ---------- processeur et registres de calcul ----------
const cpuSrc = `
.org $0000
r_add: .res 2
r_dec: .res 1
r_xba: .res 2
r_mvn: .res 4
r_mul: .res 2
r_div: .res 2
r_rem: .res 2
r_long: .res 1
done: .res 1
.bank 0
reset:
  sei
  clc
  xce
  rep #$30
  ldx #$1FFF
  txs
  lda #$1234
  clc
  adc #$4321
  sta r_add
  sep #$20
  sed
  lda #$19
  clc
  adc #$28
  sta r_dec
  cld
  rep #$20
  lda #$ABCD
  xba
  sta r_xba
  lda #3
  ldx #src
  ldy #r_mvn
  mvn $00,$00
  sep #$20
  lda #12
  sta $4202
  lda #11
  sta $4203
  rep #$20
  lda $4216
  sta r_mul
  lda #1000
  sta $4204
  sep #$20
  lda #7
  sta $4206
  rep #$20
  lda $4214
  sta r_div
  lda $4216
  sta r_rem
  sep #$20
  lda.l far
  sta r_long
  lda #$5A
  sta done
@loop:
  bra @loop
src: .byte 1, 2, 3, 4
.bank 1
far: .byte $77
.vectors reset, reset, reset
`;
const built = assemble(cpuSrc);
assert.ok(built.ok, JSON.stringify(built.errors));
assert.strictEqual(built.rom.length, 0x10000, "deux banques LoROM = 64 Ko");
let m = new Machine(ALL, built.rom);
for (let i = 0; i < 5; i++) m.runFrame();
const w = (a) => m.wram[a] | (m.wram[a + 1] << 8);
const sym = (n) => built.symbols.get(n);
assert.strictEqual(m.wram[sym("done")], 0x5a, "le programme de test va jusqu'au bout");
assert.strictEqual(w(sym("r_add")), 0x5555, "addition 16 bits");
assert.strictEqual(m.wram[sym("r_dec")], 0x47, "addition décimale (BCD)");
assert.strictEqual(w(sym("r_xba")), 0xcdab, "XBA échange les deux octets");
assert.deepStrictEqual([...m.wram.slice(sym("r_mvn"), sym("r_mvn") + 4)], [1, 2, 3, 4], "MVN copie un bloc");
assert.strictEqual(w(sym("r_mul")), 132, "multiplication matérielle");
assert.strictEqual(w(sym("r_div")), 142, "division matérielle (quotient)");
assert.strictEqual(w(sym("r_rem")), 6, "division matérielle (reste)");
assert.strictEqual(m.wram[sym("r_long")], 0x77, "lecture longue dans la banque 1");

// ---------- assembleur ----------
const h = 0x7fc0, rom = built.rom;
const check = rom[h + 0x1e] | (rom[h + 0x1f] << 8), comp = rom[h + 0x1c] | (rom[h + 0x1d] << 8);
assert.strictEqual(check ^ comp, 0xffff, "somme de contrôle et complément");
let sum = 0;
for (const b of rom) sum = (sum + b) & 0xffff;
assert.strictEqual(sum, check, "la somme de contrôle est juste");
assert.strictEqual(rom[h + 0x15], 0x20, "carte LoROM annoncée");
const bad = assemble(".bank 0\nreset:\n  sep #$20\n  lda #$1234\n  lda.b $1234\n  foo\n.vectors reset, reset, reset\n");
assert.ok(!bad.ok);
assert.deepStrictEqual(bad.errors.map((e) => e.line), [4, 5, 6], JSON.stringify(bad.errors));
const wide = assemble(".bank 0\nreset:\n  rep #$20\n  lda #$1234\n  sep #$20\n  lda #$12\n.vectors reset, reset, reset\n");
assert.ok(wide.ok);
assert.deepStrictEqual([...wide.rom.slice(0, 9)], [0xc2, 0x20, 0xa9, 0x34, 0x12, 0xe2, 0x20, 0xa9, 0x12], "largeur suivie après REP/SEP");
assert.ok(!assemble(".bank 0\nnop\n").ok, "sans vecteurs : erreur");

// ---------- lecture des cartouches ----------
const copier = new Uint8Array(512 + rom.length);
copier.set(rom, 512);
assert.ok(!parseRom(copier).hiRom && parseRom(copier).title === "AETHER 16", "en-tête de copieur retiré");
const hi = new Uint8Array(0x10000).fill(0xea);
const hh = 0xffc0;
"HAUTE".split("").forEach((c, i) => { hi[hh + i] = c.charCodeAt(0); });
hi[hh + 0x15] = 0x21; hi[hh + 0x16] = 0; hi[hh + 0x18] = 0; hi[hh + 0x3c] = 0x00; hi[hh + 0x3d] = 0x80;
hi[hh + 0x1c] = 0xff; hi[hh + 0x1d] = 0xff; hi[hh + 0x1e] = 0; hi[hh + 0x1f] = 0;
assert.ok(parseRom(hi).hiRom, "carte HiROM reconnue");
const copro = Uint8Array.from(rom);
copro[h + 0x16] = 0x03;
assert.throws(() => parseRom(copro), /coprocesseur/);

// ---------- jeu d'exemple ----------
const demoSrc = fs.readFileSync(path.join(ROOT, "modules", "circuit_lab", "examples", "lune16.asm"), "utf8");
const demo = assemble(demoSrc);
assert.ok(demo.ok, JSON.stringify(demo.errors));
m = new Machine(ALL, demo.rom);
const t0 = Date.now();
let quiet = 0;
for (let f = 0; f < 60; f++) { m.runFrame(); for (const s of m.takeAudio()) quiet = Math.max(quiet, Math.abs(s)); }
const ms = Date.now() - t0;
assert.strictEqual(m.apu.ipl.state, "run", "le programme du module son a été chargé et lancé");
assert.ok(quiet < 0.002, `silence avant la première note (${quiet})`);
const px = (x, y) => m.frame[y * 256 + x];
const region = (x0, y0, x1, y1, color) => {
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) if (px(x, y) === color) return true;
  return false;
};
assert.notStrictEqual(px(5, 12), px(5, 200), "dégradé du ciel par HDMA (haut et bas différents)");
assert.ok(region(192, 38, 208, 58, LUT[15][bgr(31, 30, 22)]), "la lune est affichée");
assert.ok(region(0, 192, 255, 200, LUT[15][bgr(6, 16, 8)]), "l'herbe est affichée");
const body = LUT[15][bgr(20, 20, 22)];
assert.ok(region(120, 172, 136, 192, body), "Fuma est à sa place de départ");
m.press(0, "Left", true);
for (let f = 0; f < 20; f++) m.runFrame();
m.press(0, "Left", false);
m.runFrame();
assert.ok(!region(120, 172, 136, 192, body) && region(70, 172, 100, 192, body), "la manette déplace Fuma vers la gauche");
m.press(0, "B", true);
let peak = 0;
for (let f = 0; f < 10; f++) { m.runFrame(); for (const s of m.takeAudio()) peak = Math.max(peak, Math.abs(s)); }
assert.ok(peak > 0.01, `B joue une note par le module son (${peak})`);

// ---------- pièces manquantes ----------
assert.strictEqual(new Machine(without("power"), demo.rom).runFrame(), false, "sans alimentation, rien ne tourne");
assert.strictEqual(new Machine(without("ppu2"), demo.rom).signal, false, "sans puce vidéo 2, pas de signal");
const mute = new Machine(without("sound"), demo.rom);
for (let f = 0; f < 30; f++) mute.runFrame();
const pc = mute.cpu.pc;
assert.ok(pc >= (demo.symbols.get("sound_boot") & 0xffff) && pc < (demo.symbols.get("play_note") & 0xffff),
  "sans module son, le programme attend sa réponse");
assert.ok(mute.frame.every((c) => (c & 0xffffff) === 0), "… et l'écran reste éteint");
for (const id of ["wram", "vram", "ppu1", "cart", "slot", "pads", "cpu"]) {
  const broken = new Machine(without(id), demo.rom);
  for (let f = 0; f < 10; f++) assert.ok(broken.runFrame(), id);
}
console.log(`console 16 bits : ok (60 images en ${ms} ms)`);
