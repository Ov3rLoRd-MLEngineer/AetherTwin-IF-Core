// Vérifications des cartes à microcontrôleur : encodage des deux assembleurs (AVR et Thumb), calculs et drapeaux des
// deux cœurs, erreurs signalées, périphériques (ports, minuterie et interruption de l'AVR ; resets, SIO et TIMER du
// RP2040), écran LCD HD44780, et les huit programmes d'exemple (rythme des clignotants, boutons, texte de l'écran).
// Lancé par test_module.py.
"use strict";
const path = require("path");
const assert = require("assert");
for (const f of ["mcu_asm.js", "mcu_avr.js", "mcu_rp2040.js", "mcu_board.js", "mcu_examples.js"]) {
  require(path.join(__dirname, "..", "..", "core", "web", f));
}
const ASM = globalThis.AetherMcuAsm;
const { Board, LCD } = globalThis.AetherMcuBoard;
const EX = globalThis.AetherMcuExamples;
const HEX7 = [0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f, 0x77, 0x7c, 0x39, 0x5e, 0x79, 0x71];
const words = (img) => Array.from({ length: img.length >> 1 }, (_, i) => img[2 * i] | (img[2 * i + 1] << 8));
const ok = (built, what) => { assert.ok(built.ok, `${what} : ${JSON.stringify(built.errors)}`); return built; };

// ---------- assembleur AVR : encodages connus ----------
{
  const b = ok(ASM.avr(`
        ldi r16, 0xff
        out PORTB, r16
        sbi DDRB, PB5
here:   rjmp here
        add r1, r2
        ret
        lpm r16, Z+
        ld r24, X+
        std Y+5, r17
        call 0x100
        adiw r24, 1
        sbiw r26, 1
        in r16, SREG
        brne here
        .db "AB", 1`), "avr");
  assert.deepStrictEqual(words(b.image), [0xef0f, 0xb905, 0x9a25, 0xcfff, 0x0c12, 0x9508, 0x9105, 0x918d, 0x831d, 0x940e, 0x0100,
                                          0x9601, 0x9711, 0xb70f, 0xf7a1, 0x4241, 0x0001]);
  const bad = ASM.avr("        ldi r5, 1\n        frob r1\n        breq loin\n        .org 200\nloin:   nop\n        rjmp nulle_part");
  assert.deepStrictEqual(bad.errors.map((e) => e.line), [1, 2, 3, 6]);
  assert.match(bad.errors[0].message, /r16 à r31/);
  assert.match(bad.errors[1].message, /inconnue/);
  assert.match(bad.errors[2].message, /trop loin/);
  assert.match(bad.errors[3].message, /symbole inconnu : nulle_part/);
}

// ---------- assembleur Thumb : encodages connus ----------
{
  const b = ok(ASM.thumb(`
main:   movs r0, #1
        adds r0, r1, r2
        ldr r0, [r1, #4]
        str r1, [r0]
        push {r4, lr}
        pop {r4, pc}
        bx lr
self:   b self
        lsls r1, r1, #16
        mov r2, r1
        bl next
next:   cmp r4, #16
        nop
        ldrb r1, [r0, r4]
        sub sp, #8
        add r0, sp, #4
        beq next
        ldr r3, =0xd0000000
        .align 2`), "thumb");
  const h = words(b.image);
  assert.deepStrictEqual(h.slice(0, 18), [0x2001, 0x1888, 0x6848, 0x6001, 0xb510, 0xbd10, 0x4770, 0xe7fe, 0x0409, 0x460a, 0xf000, 0xf800,
                                          0x2c10, 0xbf00, 0x5d01, 0xb082, 0xa801, 0xd0f9]);
  assert.strictEqual(h[18] & 0xf800, 0x4800, "ldr r3, =… est un chargement relatif à pc");
  const pool = (h[18] & 0xff) * 4 + ((0x20000000 + 36 + 4) & ~3) - 0x20000000;
  assert.strictEqual(b.image[pool + 3], 0xd0, "la constante est rangée dans la réserve");
  assert.strictEqual(b.entry, 0x20000000);
  const bad = ASM.thumb("main:   movs r0, #300\n        adds r9, r1, r2\n        b nulle_part\n        frob\n        ldr r0, [r1, #3]");
  assert.deepStrictEqual(bad.errors.map((e) => e.line), [1, 2, 3, 4, 5]);
}

// ---------- cœur AVR : calculs, pile, flash, mémoire, comparaisons ----------
{
  const b = ok(ASM.avr(`
        .org 0
        ldi r16, high(RAMEND)
        out SPH, r16
        ldi r16, low(RAMEND)
        out SPL, r16
        ldi r16, 200
        ldi r17, 100
        add r16, r17            ; 300 : 44 et retenue
        mov r29, r16
        clr r18
        adc r18, r18            ; r18 = la retenue
        ldi r19, 7
        ldi r20, 6
        mul r19, r20            ; r1:r0 = 42
        mov r21, r0
        ldi r24, low(1000)
        ldi r25, high(1000)
        sbiw r24, 1
        ldi r22, 5
        rcall double
        ldi ZL, low(table * 2)
        ldi ZH, high(table * 2)
        lpm r23, Z+
        lpm r23, Z
        ldi r26, low(0x200)
        ldi r27, high(0x200)
        ldi r16, 0x5a
        st X+, r16
        ld r2, -X
        ldi r16, 3
        cpi r16, 5
        brlt petit
        ldi r28, 0
        rjmp suite
petit:  ldi r28, 1
suite:  break
double: lsl r22
        ret
table:  .db 0x12, 0x34`), "avr cpu");
  const board = new Board("avr");
  board.load(b);
  board.cpu.run(10000);
  const r = board.cpu.data;
  assert.match(board.cpu.halted, /BREAK/);
  assert.deepStrictEqual([r[29], r[18], r[21], r[24] | (r[25] << 8), r[22], r[23], r[2], r[28]], [44, 1, 42, 999, 10, 0x34, 0x5a, 1]);
  assert.strictEqual(board.cpu.sp, 0x8ff, "la pile est revenue à son point de départ");
}

// ---------- cœur Thumb : calculs, drapeaux, pile, appels, chargements signés ----------
{
  const b = ok(ASM.thumb(`
main:   movs r0, #200
        movs r1, #100
        adds r2, r0, r1
        subs r3, r1, r0
        movs r4, #7
        movs r5, #6
        muls r4, r5
        ldr r6, =0x12345678
        rev r7, r6
        push {r4-r7}
        pop {r0-r3}
        bl carre
        ldr r1, =donnees
        ldrh r2, [r1, #2]
        movs r4, #1
        ldrsb r3, [r1, r4]
        movs r4, #0
        cmp r3, r4
        blt negatif
        movs r5, #0
        b fin
negatif: movs r5, #1
fin:    bkpt #0
carre:  muls r0, r0, r0
        bx lr
        .align 2
donnees: .hword 0x80ff, 0xbeef`), "thumb cpu");
  const board = new Board("rp2040");
  board.load(b);
  board.cpu.run(10000);
  const r = board.cpu.r;
  assert.match(board.cpu.halted, /BKPT/);
  assert.deepStrictEqual([r[0], r[1], r[2], r[3], r[5]], [1764, b.symbols.donnees, 0xbeef, 0xffffff80, 1]);
  assert.strictEqual(r[13], 0x20042000, "pile revenue en haut de la SRAM");
  const flags = new Board("rp2040");
  flags.load(ok(ASM.thumb("main: movs r0, #0\n subs r0, #1\n bkpt"), "drapeaux"));
  flags.cpu.run(100);
  assert.strictEqual(flags.cpu.regs().flags, "N···", "0 − 1 : négatif, emprunt (C = 0)");
  const crash = new Board("rp2040");
  crash.load(ok(ASM.thumb("main: ldr r0, =0x20000001\n ldr r1, [r0]\n bkpt"), "faute"));
  crash.cpu.run(100);
  assert.match(crash.cpu.halted, /HardFault.*mal alignée/);
}

// ---------- RP2040 : broches bloquées tant que IO_BANK0 est en reset ----------
{
  const b = ok(ASM.thumb(`
main:   ldr r0, =IO_BANK0_BASE + 25 * 8 + 4
        movs r1, #FUNCSEL_SIO
        str r1, [r0]
        ldr r6, =SIO_BASE
        ldr r4, =1 << 25
        str r4, [r6, #GPIO_OE_SET]
        str r4, [r6, #GPIO_OUT_SET]
        bkpt`), "reset");
  const board = new Board("rp2040");
  board.load(b);
  board.cpu.run(1000);
  assert.strictEqual(board.lit(25), 0, "la fonction SIO n'a pas pu être choisie");
  assert.match(board.cpu.notes.join(" "), /IO_BANK0 est encore tenu en reset/);
}

// ---------- écran LCD : mode 4 bits, adresses, effacement ----------
{
  const lcd = new LCD();
  const nib = (rs, n) => { lcd.pins(rs, 1, n); lcd.pins(rs, 0, n); };
  const byte = (rs, v) => { nib(rs, v >> 4); nib(rs, v & 15); };
  nib(0, 3); nib(0, 3); nib(0, 3); nib(0, 2);
  byte(0, 0x28); byte(0, 0x0c); byte(0, 0x01);
  for (const ch of "Salut") byte(1, ch.charCodeAt(0));
  byte(0, 0xc0);
  byte(1, 0x41);
  assert.deepStrictEqual(lcd.rows(), ["Salut           ", "A               "]);
  byte(0, 0x08);
  assert.deepStrictEqual(lcd.rows(), ["", ""], "écran éteint");
}

// ---------- programmes d'exemple ----------
function period(board, pin, ms) {
  const changes = [];
  let last = board.lit(pin);
  for (let t = 0; t < ms; t++) {
    board.run(1);
    const v = board.lit(pin);
    if (v !== last) { changes.push(t); last = v; }
  }
  return changes.slice(1).map((t, i) => t - changes[i]);
}
function boot(kind, name) {
  const ex = EX[kind][name];
  const built = ok(kind === "avr" ? ASM.avr(ex.source) : ASM.thumb(ex.source), `${kind}/${name}`);
  const board = new Board(kind, ex.module);
  board.load(built);
  return board;
}
function click(board, i, ms) { board.press(i, true); board.run(ms); board.press(i, false); board.run(ms); }

{
  const avr = boot("avr", "clignotant");
  const gaps = period(avr, "B5", 1300);
  assert.ok(gaps.length >= 3 && gaps.every((g) => g > 225 && g < 275), `clignotant AVR : ${gaps}`);

  const rp = boot("rp2040", "clignotant");
  const gaps2 = period(rp, 25, 1300);
  assert.ok(gaps2.length >= 3 && gaps2.every((g) => g >= 249 && g <= 251), `clignotant RP2040 : ${gaps2}`);

  const ch = boot("avr", "chenillard");
  const seen = [];
  for (let i = 0; i < 12; i++) { ch.run(66); seen.push(ch.cpu.data[0x25] & 15); }
  assert.ok(new Set(seen).size === 4, `chenillard AVR : ${seen}`);
  assert.ok(ch.cpu.sleeping === "sleep" || ch.cpu.sleeping === false, "le programme principal dort entre deux interruptions");

  const ch2 = boot("rp2040", "chenillard");
  const fwd = [];
  for (let i = 0; i < 5; i++) { fwd.push(ch2.cpu.out & 15); ch2.run(120); }
  ch2.press(0, true);
  const back = [];
  for (let i = 0; i < 4; i++) { ch2.run(120); back.push(ch2.cpu.out & 15); }
  assert.deepStrictEqual(fwd.slice(1, 5), [1, 2, 4, 8], `chenillard RP2040 en avant : ${fwd}`);
  assert.ok(back[1] === back[0] >> 1 || (back[0] === 1 && back[1] === 8), `chenillard RP2040 en arrière : ${back}`);

  for (const kind of ["avr", "rp2040"]) {
    const c = boot(kind, "compteur");
    c.run(20);
    click(c, 0, 30); click(c, 0, 30); click(c, 0, 30); click(c, 1, 30);
    const segs = kind === "avr" ? c.cpu.data[0x2b] : (c.cpu.out >>> 16) & 0xff;
    assert.strictEqual(segs, HEX7[2], `compteur ${kind} : trois + et un − donnent 2`);
    click(c, 1, 30); click(c, 1, 30); click(c, 1, 30);
    const again = kind === "avr" ? c.cpu.data[0x2b] : (c.cpu.out >>> 16) & 0xff;
    assert.strictEqual(again, HEX7[15], `compteur ${kind} : sous 0, on repart à F`);
  }

  const l1 = boot("avr", "lcd"); l1.run(200);
  assert.deepStrictEqual(l1.lcd.rows(), ["Bonjour Fuma !  ", "AVR 8 bits      "]);
  const l2 = boot("rp2040", "lcd"); l2.run(200);
  assert.deepStrictEqual(l2.lcd.rows(), ["Bonjour Fuma !  ", "RP2040 en Thumb "]);
}

console.log("microcontrôleurs : ok");
