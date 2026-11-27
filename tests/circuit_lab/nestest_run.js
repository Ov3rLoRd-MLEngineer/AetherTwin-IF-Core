// Compare le 6502 de l'atelier à la trace de référence nestest (registres, drapeaux, pile, cycles).
// Usage : node nestest_run.js <nestest.nes> <nestest.log>. La ROM et la trace ne sont pas dans le dépôt.
"use strict";
const fs = require("fs");
const path = require("path");
require(path.join(__dirname, "..", "..", "core", "web", "c8_cpu.js"));
const { CPU6502, hex } = globalThis.AetherCPU;

const rom = fs.readFileSync(process.argv[2]);
const log = fs.readFileSync(process.argv[3], "utf8").split(/\r?\n/).filter(Boolean);
const prg = rom.subarray(16, 16 + 16384);
const ram = new Uint8Array(0x800);
const bus = {
  read(a) {
    if (a < 0x2000) return ram[a & 0x7ff];
    if (a >= 0x8000) return prg[a & 0x3fff];
    return 0xff;  // registres PPU/APU : non utilisés par la partie « automatique » de nestest
  },
  write(a, v) { if (a < 0x2000) ram[a & 0x7ff] = v; },
};
const cpu = new CPU6502(bus);
cpu.pc = 0xc000; cpu.sp = 0xfd; cpu.p = 0x24; cpu.cycles = 7;
let ok = 0;
for (const line of log) {
  const want = {
    pc: parseInt(line.slice(0, 4), 16),
    a: parseInt(/A:(\w\w)/.exec(line)[1], 16), x: parseInt(/X:(\w\w)/.exec(line)[1], 16),
    y: parseInt(/Y:(\w\w)/.exec(line)[1], 16), p: parseInt(/P:(\w\w)/.exec(line)[1], 16),
    sp: parseInt(/SP:(\w\w)/.exec(line)[1], 16), cyc: parseInt(/CYC:(\d+)/.exec(line)[1], 10),
  };
  const got = { pc: cpu.pc, a: cpu.a, x: cpu.x, y: cpu.y, p: cpu.p, sp: cpu.sp, cyc: cpu.cycles };
  const diff = Object.keys(want).filter((k) => want[k] !== got[k]);
  if (diff.length) {
    console.log(`ÉCART ligne ${ok + 1} : ${line}`);
    console.log("obtenu :", diff.map((k) => `${k}=${k === "cyc" ? got[k] : hex(got[k], k === "pc" ? 4 : 2)}`).join(" "));
    process.exit(1);
  }
  ok += 1;
  cpu.step();
}
console.log(`nestest : ${ok} instructions identiques à la trace ; résultats $02=${hex(ram[2])} $03=${hex(ram[3])}`);
