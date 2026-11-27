// Vérifications de l'assembleur (lancé par tests/circuit_lab/test_circuit_lab.py, ou à la main avec node).
"use strict";
const path = require("path");
const assert = require("assert");
require(path.join(__dirname, "..", "..", "core", "web", "c8_cpu.js"));
require(path.join(__dirname, "..", "..", "core", "web", "asm6502.js"));
const { assemble } = globalThis.AetherAsm;

const ok = assemble(`
; variables en RAM
.org $0000
compteur: .res 1
pointeur: .res 2
BOUTON = %1000_0000 & $ff
.org $C000
reset:
  sei
  ldx #$FF
  txs
  lda #<message
  sta pointeur
  lda #>message
  sta pointeur+1
  ldy #0
@boucle:
  lda (pointeur),y
  beq @fin
  sta $2007
  iny
  bne @boucle
@fin:
  inc compteur
  lda table,x
  lda compteur,x
  jmp (vecteur)
nmi: rti
message: .byte "Hi", 0
table: .word reset, $1234
vecteur: .word reset
.vectors nmi, reset, nmi
.segment chr
.tile "..1111..", ".1....1.", "1.2..2.1", "1......1", "1.3333.1", "1..33..1", ".1....1.", "..1111.."
`.replace("%1000_0000", "%10000000"));
assert.deepStrictEqual(ok.errors, []);
assert.strictEqual(ok.prg.length, 0x4000);
const at = (a) => ok.prg[a - 0xc000];
assert.deepStrictEqual([at(0xc000), at(0xc001), at(0xc002)], [0x78, 0xa2, 0xff]);
assert.strictEqual(at(0xc006), 0x85);                 // sta pointeur → page zéro
assert.strictEqual(at(0xc007), 0x01);
const sym = (n) => ok.symbols.get(n);
assert.strictEqual(sym("compteur"), 0);
assert.strictEqual(sym("bouton"), 0x80);
const fin = sym("reset@fin");
assert.strictEqual(at(fin), 0xe6);                    // inc compteur (page zéro)
assert.strictEqual(at(fin + 2), 0xbd);                // lda table,x (absolu indexé)
assert.strictEqual(at(fin + 5), 0xb5);                // lda compteur,x (page zéro indexé)
assert.strictEqual(at(fin + 7), 0x6c);                // jmp (indirect)
assert.strictEqual(at(0xfffc) | (at(0xfffd) << 8), 0xc000);
assert.deepStrictEqual([ok.chr[0], ok.chr[8]], [0b00111100, 0]);
assert.strictEqual(ok.chr[2], 0b10000001);            // ligne 3, bit faible (couleur 1 → 1)
assert.strictEqual(ok.chr[10], 0b00100100);           // ligne 3, bit fort (2 → 1)
assert.deepStrictEqual([...ok.rom.slice(0, 7)], [0x4e, 0x45, 0x53, 0x1a, 1, 1, 1]);

const bad = assemble(`
.org $8000
start:
  lda #300
  ldz #1
  bne loin
  sta inconnu
.res 200
loin: rts
`);
const lines = bad.errors.map((e) => `${e.line}:${e.message}`);
assert.ok(lines.some((l) => l.startsWith("4:") && /octet/.test(l)), lines);
assert.ok(lines.some((l) => l.startsWith("5:") && /instruction inconnue/.test(l)), lines);
assert.ok(lines.some((l) => l.startsWith("6:") && /trop loin/.test(l)), lines);
assert.ok(lines.some((l) => l.startsWith("7:") && /inconnu/.test(l)), lines);
assert.ok(!bad.ok);
console.log("assembleur : ok");
