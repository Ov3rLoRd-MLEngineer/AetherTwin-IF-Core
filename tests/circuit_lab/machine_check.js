// Vérifications de la carte mère : une petite ROM assemblée allume l'écran, la vidéo produit des images et la NMI
// arrive à chaque image ; les pannes de composants manquants se voient. Lancé par test_circuit_lab.py.
"use strict";
const path = require("path");
const assert = require("assert");
for (const f of ["nes_cpu.js", "asm6502.js", "nes_ppu.js", "nes_machine.js"]) {
  require(path.join(__dirname, "..", "..", "core", "web", f));
}
const { assemble } = globalThis.AetherAsm;
const { Machine, PARTS } = globalThis.AetherNES;

const src = `
.org $0000
frames: .res 1
.org $C000
reset:
  sei
  ldx #$ff
  txs
@w1: bit $2002
  bpl @w1
@w2: bit $2002
  bpl @w2
  lda #$3f
  sta $2006
  lda #$00
  sta $2006
  lda #$21          ; couleur de fond : bleu clair
  sta $2007
  lda #$20          ; écran de fond 0, tuile 1 partout sur la 1re ligne
  sta $2006
  lda #$00
  sta $2006
  ldx #32
  lda #1
@t: sta $2007
  dex
  bne @t
  lda #0
  sta $2005
  sta $2005
  lda #%10000000
  sta $2000
  lda #%00001010
  sta $2001
loop: jmp loop
nmi:
  inc frames
  rti
.vectors nmi, reset, nmi
.segment chr
.org $0010
.tile "33333333","33333333","33333333","33333333","33333333","33333333","33333333","33333333"
`;
const built = assemble(src);
assert.deepStrictEqual(built.errors, []);
const all = PARTS.map((p) => p.id);
const m = new Machine(all, built.rom);
for (let i = 0; i < 10; i++) m.runFrame();
assert.ok(m.ram[0] >= 7 && m.ram[0] <= 9, `NMI par image : ${m.ram[0]}`);
assert.strictEqual(m.ppu.frameBuffer[100 * 256 + 100], 0x21);     // fond bleu
assert.strictEqual(m.ppu.frameBuffer[3 * 256 + 50], m.ppu.palette[3]); // tuile pleine sur la 1re ligne
assert.ok(m.activity.ram > 0 && m.activity.cart > 0 && m.activity.ppu > 0);

// sans RAM : la pile est perdue, l'interruption ne revient pas où il faut
const noRam = new Machine(all.filter((p) => p !== "ram"), built.rom);
for (let i = 0; i < 10; i++) noRam.runFrame();
assert.strictEqual(noRam.activity.ram, 0);
// sans verrou d'adresses : la ligne de tuiles est brouillée
const noLatch = new Machine(all.filter((p) => p !== "latch"), built.rom);
for (let i = 0; i < 10; i++) noLatch.runFrame();
const row = Array.from(noLatch.ppu.frameBuffer.slice(3 * 256, 4 * 256));
assert.notDeepStrictEqual(row, Array.from(m.ppu.frameBuffer.slice(3 * 256, 4 * 256)));
// sans horloge : rien ne tourne
const noClock = new Machine(all.filter((p) => p !== "clock"), built.rom);
assert.strictEqual(noClock.runFrame(), false);
assert.ok(!new Machine(all.filter((p) => p !== "video"), built.rom).signal);
// cartouche refusée si mappeur inconnu
const rom = Uint8Array.from(built.rom); rom[6] |= 0x10;
assert.throws(() => new Machine(all, rom), /mappeur 1/);
// le son produit des échantillons
assert.ok(m.apu.take().length > 600);
console.log("carte mère : ok");
