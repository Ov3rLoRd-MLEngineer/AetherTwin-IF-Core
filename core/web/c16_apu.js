"use strict";
// Module son de la console 16 bits de l'atelier : un processeur 8 bits SPC700 (1,024 MHz) avec 64 Ko de mémoire
// à lui, trois minuteries, et un DSP à 8 voix (échantillons compressés « BRR », enveloppes, bruit, écho) qui sort
// 32 000 échantillons stéréo par seconde. Le processeur principal ne lui parle que par 4 « ports » d'un octet.
//
// La petite ROM de démarrage du module (64 octets) n'est pas fournie : c'est un microcode du fabricant. Son
// protocole public de chargement (attente de $CC, blocs d'octets numérotés, saut au programme) est reproduit
// ici en JavaScript (« IPL simulé »), ce qui suffit aux programmes et aux cartouches.
(function (root) {
  const SPC_HZ = 1024000;
  // cycles de chaque instruction du SPC700 (branchements pris : +2)
  const CYCLES = [
    2, 8, 4, 5, 3, 4, 3, 6, 2, 6, 5, 4, 5, 4, 6, 8, 2, 8, 4, 5, 4, 5, 5, 6, 5, 5, 6, 5, 2, 2, 4, 6,
    2, 8, 4, 5, 3, 4, 3, 6, 2, 6, 5, 4, 5, 4, 5, 4, 2, 8, 4, 5, 4, 5, 5, 6, 5, 5, 6, 5, 2, 2, 3, 8,
    2, 8, 4, 5, 3, 4, 3, 6, 2, 6, 4, 4, 5, 4, 6, 6, 2, 8, 4, 5, 4, 5, 5, 6, 5, 5, 4, 5, 2, 2, 4, 3,
    2, 8, 4, 5, 3, 4, 3, 6, 2, 6, 4, 4, 5, 4, 5, 5, 2, 8, 4, 5, 4, 5, 5, 6, 5, 5, 5, 5, 2, 2, 3, 6,
    2, 8, 4, 5, 3, 4, 3, 6, 2, 6, 5, 4, 5, 2, 4, 5, 2, 8, 4, 5, 4, 5, 5, 6, 5, 5, 5, 5, 2, 2, 12, 5,
    3, 8, 4, 5, 3, 4, 3, 6, 2, 6, 4, 4, 5, 2, 4, 4, 2, 8, 4, 5, 4, 5, 5, 6, 5, 5, 5, 5, 2, 2, 3, 4,
    3, 8, 4, 5, 4, 5, 4, 7, 2, 5, 6, 4, 5, 2, 4, 9, 2, 8, 4, 5, 5, 6, 6, 7, 4, 5, 5, 5, 2, 2, 6, 3,
    2, 8, 4, 5, 3, 4, 3, 6, 2, 4, 5, 3, 4, 3, 4, 3, 2, 8, 4, 5, 4, 5, 5, 6, 3, 4, 5, 4, 2, 2, 4, 3,
  ];
  // nombre d'échantillons (32 kHz) entre deux pas d'enveloppe ou de bruit, selon le « taux » 0-31
  const RATE = [0, 2048, 1536, 1280, 1024, 768, 640, 512, 384, 320, 256, 192, 160, 128, 96, 80, 64, 48, 40, 32,
                24, 20, 16, 12, 10, 8, 6, 5, 4, 3, 2, 1];
  const clamp16 = (v) => (v > 32767 ? 32767 : v < -32768 ? -32768 : v);
  const s8 = (v) => (v << 24) >> 24;

  // ---------- DSP ----------
  class Voice {
    constructor() {
      this.buf = new Int16Array(19);   // 3 échantillons du bloc précédent + 16 du bloc courant
      this.pos = 0; this.addr = 0; this.loop = 0; this.header = 0; this.active = false;
      this.env = 0; this.state = 3; this.out = 0; this.p1 = 0; this.p2 = 0; this.keyOn = false; this.delay = 0;
    }
  }
  class DSP {
    constructor(ram) {
      this.ram = ram;
      this.regs = new Uint8Array(128);
      this.voices = Array.from({ length: 8 }, () => new Voice());
      this.counter = 0; this.noise = 0x4000; this.echoPos = 0; this.echoHist = [new Int16Array(8), new Int16Array(8)];
      this.echoIdx = 0;
      this.regs[0x6c] = 0xe0;
    }
    read(a) { return this.regs[a & 0x7f]; }
    write(a, v) {
      if (a >= 0x80) return;
      this.regs[a] = v;
      if (a === 0x7c) this.regs[0x7c] = 0;           // ENDX : toute écriture l'efface
      else if (a === 0x4c) { for (let i = 0; i < 8; i++) if (v & (1 << i)) this.voices[i].keyOn = true; }
    }
    brrBlock(vo) {
      const ram = this.ram;
      const h = ram[vo.addr & 0xffff];
      vo.header = h;
      const shift = h >> 4, filter = (h >> 2) & 3;
      vo.buf.copyWithin(0, 16, 19);
      let p1 = vo.p1, p2 = vo.p2;
      for (let i = 0; i < 16; i++) {
        const byte = ram[(vo.addr + 1 + (i >> 1)) & 0xffff];
        let n = (i & 1) ? byte & 15 : byte >> 4;
        if (n >= 8) n -= 16;
        let s = shift <= 12 ? (n << shift) >> 1 : (n < 0 ? -2048 : 0);
        if (filter === 1) s += p1 + ((-p1) >> 4);
        else if (filter === 2) s += (p1 << 1) + ((-p1 * 3) >> 5) - p2 + (p2 >> 4);
        else if (filter === 3) s += (p1 << 1) + ((-p1 * 13) >> 6) - p2 + ((p2 * 3) >> 4);
        s = clamp16(s);
        s = (s << 17) >> 16;  // 15 bits utiles, comme la puce
        vo.buf[3 + i] = s;
        p2 = p1; p1 = s;
      }
      vo.p1 = p1; vo.p2 = p2;
    }
    keyOn(i) {
      const vo = this.voices[i], r = this.regs;
      const dir = r[0x5d] << 8, src = r[i * 16 + 4];
      vo.addr = this.ram[(dir + src * 4) & 0xffff] | (this.ram[(dir + src * 4 + 1) & 0xffff] << 8);
      vo.loop = this.ram[(dir + src * 4 + 2) & 0xffff] | (this.ram[(dir + src * 4 + 3) & 0xffff] << 8);
      vo.p1 = 0; vo.p2 = 0; vo.buf.fill(0); vo.pos = 0; vo.env = 0; vo.state = 0; vo.active = true;
      this.regs[0x7c] &= ~(1 << i);
      this.brrBlock(vo);
    }
    tick(rate) { return rate !== 0 && (this.counter % RATE[rate]) === 0; }
    envelope(vo, i) {
      const r = this.regs, adsr1 = r[i * 16 + 5], adsr2 = r[i * 16 + 6], gain = r[i * 16 + 7];
      if (vo.state === 3) { vo.env -= 8; if (vo.env < 0) vo.env = 0; return; }  // relâchement
      if (adsr1 & 0x80) {
        if (vo.state === 0) {
          const rate = (adsr1 & 15) * 2 + 1;
          if (this.tick(rate)) vo.env += rate === 31 ? 1024 : 32;
          if (vo.env >= 0x7e0) { vo.env = Math.min(vo.env, 0x7ff); vo.state = 1; }
        } else if (vo.state === 1) {
          if (this.tick(((adsr1 >> 4) & 7) * 2 + 16)) vo.env -= ((vo.env - 1) >> 8) + 1;
          if ((vo.env >> 8) === (adsr2 >> 5)) vo.state = 2;
        } else if (this.tick(adsr2 & 31)) vo.env -= ((vo.env - 1) >> 8) + 1;
      } else if (!(gain & 0x80)) vo.env = (gain & 0x7f) << 4;
      else if (this.tick(gain & 31)) {
        switch ((gain >> 5) & 3) {
          case 0: vo.env -= 32; break;
          case 1: vo.env -= ((vo.env - 1) >> 8) + 1; break;
          case 2: vo.env += 32; break;
          default: vo.env += vo.env < 0x600 ? 32 : 8; break;
        }
      }
      vo.env = Math.max(0, Math.min(0x7ff, vo.env));
    }
    // Un échantillon stéréo (32 kHz).
    sample() {
      const r = this.regs, ram = this.ram;
      this.counter = (this.counter + 1) % 30720;
      const flg = r[0x6c];
      if (flg & 0x80) for (const vo of this.voices) { vo.state = 3; vo.env = 0; vo.active = false; }
      if (this.tick(flg & 31)) {
        const fb = ((this.noise << 13) ^ (this.noise << 14)) & 0x4000;
        this.noise = fb ^ (this.noise >> 1);
      }
      const kon = r[0x4c], koff = r[0x5c], non = r[0x3d], pmon = r[0x2d], eon = r[0x4d];
      let mainL = 0, mainR = 0, echoL = 0, echoR = 0, prevOut = 0;
      for (let i = 0; i < 8; i++) {
        const vo = this.voices[i], base = i * 16;
        if (vo.keyOn) { vo.keyOn = false; this.keyOn(i); }
        if (koff & (1 << i)) vo.state = 3;
        if (!vo.active) { r[base + 8] = 0; r[base + 9] = 0; prevOut = 0; continue; }
        let pitch = (r[base + 2] | (r[base + 3] << 8)) & 0x3fff;
        if ((pmon & (1 << i)) && i > 0) pitch += ((prevOut >> 5) * pitch) >> 10;
        pitch = Math.max(0, Math.min(0x7fff, pitch));
        const idx = vo.pos >> 12, frac = (vo.pos >> 4) & 0xff;
        let s;
        if (non & (1 << i)) s = ((this.noise << 17) >> 16);
        else {
          // interpolation cubique entre 4 échantillons voisins
          const b = vo.buf, k = idx;
          const s0 = b[k], s1 = b[k + 1], s2 = b[k + 2], s3 = b[k + 3], t = frac / 256;
          s = s1 + 0.5 * t * (s2 - s0 + t * (2 * s0 - 5 * s1 + 4 * s2 - s3 + t * (3 * (s1 - s2) + s3 - s0)));
          s = clamp16(Math.round(s)) >> 1;
        }
        this.envelope(vo, i);
        const out = (s * vo.env) >> 11;
        prevOut = out;
        r[base + 8] = vo.env >> 4;
        r[base + 9] = (out >> 7) & 0xff;
        const l = (out * s8(r[base])) >> 7, rr = (out * s8(r[base + 1])) >> 7;
        mainL += l; mainR += rr;
        if (eon & (1 << i)) { echoL += l; echoR += rr; }
        vo.pos += pitch;
        while ((vo.pos >> 12) >= 16) {
          vo.pos -= 16 << 12;
          if (vo.header & 1) {
            this.regs[0x7c] |= 1 << i;
            if (vo.header & 2) vo.addr = vo.loop; else { vo.state = 3; vo.env = 0; vo.active = false; break; }
          } else vo.addr = (vo.addr + 9) & 0xffff;
          this.brrBlock(vo);
        }
        if (vo.state === 3 && vo.env === 0 && !(kon & (1 << i))) vo.active = false;
      }
      r[0x4c] = 0;  // KON est consommé
      mainL = clamp16(mainL); mainR = clamp16(mainR);
      let outL = (mainL * s8(r[0x0c])) >> 7, outR = (mainR * s8(r[0x1c])) >> 7;
      // écho : tampon circulaire en mémoire du module, filtre à 8 coefficients
      const esa = r[0x6d] << 8, edl = r[0x7d] & 15, len = edl ? edl * 2048 : 4;
      const addr = (esa + this.echoPos) & 0xffff;
      const rd = (a) => (ram[a & 0xffff] | (ram[(a + 1) & 0xffff] << 8)) << 16 >> 16;
      const inL = rd(addr) >> 1, inR = rd(addr + 2) >> 1;
      const hl = this.echoHist[0], hr = this.echoHist[1];
      this.echoIdx = (this.echoIdx + 1) & 7;
      hl[this.echoIdx] = inL; hr[this.echoIdx] = inR;
      let firL = 0, firR = 0;
      for (let k = 0; k < 8; k++) {
        const c = s8(r[k * 16 + 0x0f]), h = (this.echoIdx + 1 + k) & 7;
        firL += (hl[h] * c) >> 6; firR += (hr[h] * c) >> 6;
      }
      firL = clamp16(firL); firR = clamp16(firR);
      outL = clamp16(outL + ((firL * s8(r[0x2c])) >> 7));
      outR = clamp16(outR + ((firR * s8(r[0x3c])) >> 7));
      if (!(flg & 0x20)) {
        const efb = s8(r[0x0d]);
        const wl = clamp16(clamp16(echoL) + ((firL * efb) >> 7)) & ~1, wr = clamp16(clamp16(echoR) + ((firR * efb) >> 7)) & ~1;
        ram[addr & 0xffff] = wl & 0xff; ram[(addr + 1) & 0xffff] = (wl >> 8) & 0xff;
        ram[(addr + 2) & 0xffff] = wr & 0xff; ram[(addr + 3) & 0xffff] = (wr >> 8) & 0xff;
      }
      this.echoPos += 4;
      if (this.echoPos >= len) this.echoPos = 0;
      if (flg & 0x40) return [0, 0];
      return [outL, outR];
    }
  }

  // ---------- SPC700 ----------
  class APU16 {
    constructor(sampleRate = 44100) {
      this.ram = new Uint8Array(65536);
      this.dsp = new DSP(this.ram);
      this.portIn = new Uint8Array(4);   // écrits par le processeur principal
      this.portOut = new Uint8Array(4);  // écrits par le module son
      this.a = 0; this.x = 0; this.y = 0; this.sp = 0xef; this.pc = 0xffc0; this.psw = 0;
      this.control = 0x80; this.dspAddr = 0;
      this.timerTarget = [0, 0, 0]; this.timerStage = [0, 0, 0]; this.timerOut = [0, 0, 0]; this.timerOn = [false, false, false];
      this.timerTick = [0, 0, 0];
      this.cycles = 0; this.sampleClock = 0; this.halted = false;
      this.ipl = { state: "boot", y: 0 };
      this.sampleRate = sampleRate; this.resample = 0; this.samples = []; this.hp = 0; this.prev = 0;
      this.enabled = true;
      this.iplBoot();
    }
    // ---------- IPL simulé ----------
    iplBoot() {
      for (let i = 1; i <= 0xef; i++) this.ram[i] = 0;
      this.portOut[0] = 0xaa; this.portOut[1] = 0xbb;
      this.ipl = { state: "wait_cc", y: 0 };
    }
    iplMain() {
      const addr = this.portIn[2] | (this.portIn[3] << 8);
      this.ram[0] = addr & 0xff; this.ram[1] = addr >> 8;
      this.portOut[0] = this.portIn[0];
      if (this.portIn[1]) { this.ipl.state = "wait_00"; return; }
      // saut au programme chargé
      this.ipl.state = "run";
      this.a = 0; this.x = 0; this.y = 0; this.sp = 0xef; this.psw = 0x02; this.pc = addr;
    }
    iplStep() {
      const ipl = this.ipl;
      for (let guard = 0; guard < 4; guard++) {
        if (ipl.state === "wait_cc") { if (this.portIn[0] === 0xcc) this.iplMain(); else return; }
        else if (ipl.state === "wait_00") { if (this.portIn[0] === 0) { ipl.y = 0; ipl.state = "transfer"; } else return; }
        else if (ipl.state === "transfer") {
          if (this.portIn[0] === ipl.y) {
            const base = this.ram[0] | (this.ram[1] << 8);
            this.ram[(base + ipl.y) & 0xffff] = this.portIn[1];
            this.portOut[0] = ipl.y;
            ipl.y = (ipl.y + 1) & 0xff;
            if (ipl.y === 0) this.ram[1] = (this.ram[1] + 1) & 0xff;
            return;
          }
          if (((ipl.y - this.portIn[0]) & 0x80) !== 0) this.iplMain(); else return;
        } else return;
      }
    }
    get running() { return this.ipl.state === "run"; }

    // ---------- ports vus du processeur principal ----------
    cpuRead(port) { return this.portOut[port & 3]; }
    cpuWrite(port, v) { this.portIn[port & 3] = v; if (!this.running) this.iplStep(); }

    // ---------- mémoire du module ----------
    read(a) {
      a &= 0xffff;
      if (a >= 0xf0 && a <= 0xff) {
        switch (a) {
          case 0xf2: return this.dspAddr;
          case 0xf3: return this.dsp.read(this.dspAddr & 0x7f);
          case 0xf4: case 0xf5: case 0xf6: case 0xf7: return this.portIn[a - 0xf4];
          case 0xfd: case 0xfe: case 0xff: { const v = this.timerOut[a - 0xfd]; this.timerOut[a - 0xfd] = 0; return v; }
          default: return this.ram[a];
        }
      }
      return this.ram[a];
    }
    write(a, v) {
      a &= 0xffff;
      if (a >= 0xf0 && a <= 0xff) {
        switch (a) {
          case 0xf1:
            for (let t = 0; t < 3; t++) {
              const on = (v & (1 << t)) !== 0;
              if (on && !this.timerOn[t]) { this.timerStage[t] = 0; this.timerOut[t] = 0; }
              this.timerOn[t] = on;
            }
            if (v & 0x10) { this.portIn[0] = 0; this.portIn[1] = 0; }
            if (v & 0x20) { this.portIn[2] = 0; this.portIn[3] = 0; }
            this.control = v;
            return;
          case 0xf2: this.dspAddr = v; return;
          case 0xf3: this.dsp.write(this.dspAddr, v); return;
          case 0xf4: case 0xf5: case 0xf6: case 0xf7: this.portOut[a - 0xf4] = v; return;
          case 0xfa: case 0xfb: case 0xfc: this.timerTarget[a - 0xfa] = v; return;
          default: this.ram[a] = v; return;
        }
      }
      this.ram[a] = v;
    }
    dp(a) { return ((this.psw & 0x20) ? 0x100 : 0) | (a & 0xff); }
    rd(a) { return this.read(this.dp(a)); }
    wd(a, v) { this.write(this.dp(a), v); }
    fetch() { const v = this.read(this.pc); this.pc = (this.pc + 1) & 0xffff; return v; }
    fetch16() { const lo = this.fetch(); return lo | (this.fetch() << 8); }
    push(v) { this.ram[0x100 | this.sp] = v; this.sp = (this.sp - 1) & 0xff; }
    pop() { this.sp = (this.sp + 1) & 0xff; return this.ram[0x100 | this.sp]; }
    rdw(a) { return this.rd(a) | (this.rd(a + 1) << 8); }
    wdw(a, v) { this.wd(a, v & 0xff); this.wd(a + 1, v >> 8); }
    nz(v) { this.psw = (this.psw & 0x7d) | (v & 0x80) | ((v & 0xff) ? 0 : 2); return v & 0xff; }
    nz16(v) { this.psw = (this.psw & 0x7d) | ((v >> 8) & 0x80) | ((v & 0xffff) ? 0 : 2); }
    setC(on) { this.psw = on ? this.psw | 1 : this.psw & ~1; }
    adc(a, b) {
      const c = this.psw & 1, r = a + b + c;
      this.psw &= ~0x49;
      if (r > 0xff) this.psw |= 1;
      if (((a & 15) + (b & 15) + c) > 15) this.psw |= 8;
      if (~(a ^ b) & (a ^ r) & 0x80) this.psw |= 0x40;
      return this.nz(r);
    }
    alu(k, a, b) {
      switch (k) {
        case 0: return this.nz(a | b);
        case 1: return this.nz(a & b);
        case 2: return this.nz(a ^ b);
        case 3: { const r = a - b; this.setC(r >= 0); this.nz(r); return a; }
        case 4: return this.adc(a, b);
        default: return this.adc(a, b ^ 0xff);
      }
    }
    branch(cond, extra) { const o = s8(this.fetch()); if (cond) { this.pc = (this.pc + o) & 0xffff; return 2 + (extra || 0); } return 0; }
    bit(w) { return { addr: w & 0x1fff, bit: w >> 13 }; }

    // une instruction ; rend le nombre de cycles
    step() {
      if (!this.running) { this.iplStep(); return 2; }
      if (this.halted) return 2;
      if (this.pc >= 0xffc0 && (this.control & 0x80)) { this.iplBoot(); return 2; }
      const op = this.fetch();
      let cyc = CYCLES[op];
      const hi = op >> 4, lo = op & 15;
      // groupe arithmétique (lignes 0-B, colonnes 4-9)
      if (hi <= 0xb && lo >= 4 && lo <= 9) {
        const k = hi >> 1, odd = hi & 1;
        let addr = -1, b;
        switch (lo) {
          case 4: addr = this.dp(this.fetch() + (odd ? this.x : 0)); b = this.read(addr); break;
          case 5: addr = (this.fetch16() + (odd ? this.x : 0)) & 0xffff; b = this.read(addr); break;
          case 6: addr = odd ? (this.fetch16() + this.y) & 0xffff : this.dp(this.x); b = this.read(addr); break;
          case 7: { const d = this.fetch();
            addr = odd ? (this.rdw(d) + this.y) & 0xffff : this.rdw(d + this.x);
            b = this.read(addr); break; }
          case 8:
            if (!odd) { b = this.fetch(); this.a = this.alu(k, this.a, b); return cyc; }
            { b = this.fetch(); const d = this.dp(this.fetch()); const r = this.alu(k, this.read(d), b); if (k !== 3) this.write(d, r); return cyc; }
          default:
            if (!odd) { const s = this.rd(this.fetch()); const d = this.dp(this.fetch()); const r = this.alu(k, this.read(d), s); if (k !== 3) this.write(d, r); }
            else { const d = this.dp(this.x); const r = this.alu(k, this.read(d), this.rd(this.y)); if (k !== 3) this.write(d, r); }
            return cyc;
        }
        this.a = this.alu(k, this.a, b);
        return cyc;
      }
      if (lo === 1) { this.push(this.pc >> 8); this.push(this.pc & 0xff); const v = 0xffde - hi * 2; this.pc = this.read(v) | (this.read(v + 1) << 8); return cyc; }
      if (lo === 2) { const d = this.dp(this.fetch()), m = 1 << (hi >> 1); const v = this.read(d); this.write(d, hi & 1 ? v & ~m : v | m); return cyc; }
      if (lo === 3) { const v = this.rd(this.fetch()), m = 1 << (hi >> 1); return cyc + this.branch(hi & 1 ? !(v & m) : (v & m) !== 0); }
      const shiftOp = (kind, v) => {
        let r;
        if (kind === 0) { this.setC(v & 0x80); r = v << 1; }
        else if (kind === 1) { const c = this.psw & 1; this.setC(v & 0x80); r = (v << 1) | c; }
        else if (kind === 2) { this.setC(v & 1); r = v >> 1; }
        else { const c = this.psw & 1; this.setC(v & 1); r = (v >> 1) | (c << 7); }
        return this.nz(r);
      };
      switch (op) {
        case 0x00: return cyc;
        case 0x10: return cyc + this.branch(!(this.psw & 0x80));
        case 0x30: return cyc + this.branch((this.psw & 0x80) !== 0);
        case 0x50: return cyc + this.branch(!(this.psw & 0x40));
        case 0x70: return cyc + this.branch((this.psw & 0x40) !== 0);
        case 0x90: return cyc + this.branch(!(this.psw & 1));
        case 0xb0: return cyc + this.branch((this.psw & 1) !== 0);
        case 0xd0: return cyc + this.branch(!(this.psw & 2));
        case 0xf0: return cyc + this.branch((this.psw & 2) !== 0);
        case 0x2f: return cyc + this.branch(true) - 2;
        case 0x20: this.psw &= ~0x20; return cyc;
        case 0x40: this.psw |= 0x20; return cyc;
        case 0x60: this.psw &= ~1; return cyc;
        case 0x80: this.psw |= 1; return cyc;
        case 0xa0: this.psw |= 4; return cyc;
        case 0xc0: this.psw &= ~4; return cyc;
        case 0xe0: this.psw &= ~0x48; return cyc;
        case 0xed: this.psw ^= 1; return cyc;
        // décalages et incréments
        case 0x0b: case 0x2b: case 0x4b: case 0x6b: { const d = this.dp(this.fetch()); this.write(d, shiftOp(hi >> 1, this.read(d))); return cyc; }
        case 0x1b: case 0x3b: case 0x5b: case 0x7b: { const d = this.dp(this.fetch() + this.x); this.write(d, shiftOp(hi >> 1, this.read(d))); return cyc; }
        case 0x0c: case 0x2c: case 0x4c: case 0x6c: { const a = this.fetch16(); this.write(a, shiftOp(hi >> 1, this.read(a))); return cyc; }
        case 0x1c: case 0x3c: case 0x5c: case 0x7c: this.a = shiftOp(hi >> 1, this.a); return cyc;
        case 0x8b: { const d = this.dp(this.fetch()); this.write(d, this.nz(this.read(d) - 1)); return cyc; }
        case 0x9b: { const d = this.dp(this.fetch() + this.x); this.write(d, this.nz(this.read(d) - 1)); return cyc; }
        case 0xab: { const d = this.dp(this.fetch()); this.write(d, this.nz(this.read(d) + 1)); return cyc; }
        case 0xbb: { const d = this.dp(this.fetch() + this.x); this.write(d, this.nz(this.read(d) + 1)); return cyc; }
        case 0x8c: { const a = this.fetch16(); this.write(a, this.nz(this.read(a) - 1)); return cyc; }
        case 0xac: { const a = this.fetch16(); this.write(a, this.nz(this.read(a) + 1)); return cyc; }
        case 0x9c: this.a = this.nz(this.a - 1); return cyc;
        case 0xbc: this.a = this.nz(this.a + 1); return cyc;
        case 0x1d: this.x = this.nz(this.x - 1); return cyc;
        case 0x3d: this.x = this.nz(this.x + 1); return cyc;
        case 0xdc: this.y = this.nz(this.y - 1); return cyc;
        case 0xfc: this.y = this.nz(this.y + 1); return cyc;
        // transferts
        case 0xc4: this.wd(this.fetch(), this.a); return cyc;
        case 0xd4: this.wd(this.fetch() + this.x, this.a); return cyc;
        case 0xc5: this.write(this.fetch16(), this.a); return cyc;
        case 0xd5: this.write((this.fetch16() + this.x) & 0xffff, this.a); return cyc;
        case 0xc6: this.wd(this.x, this.a); return cyc;
        case 0xd6: this.write((this.fetch16() + this.y) & 0xffff, this.a); return cyc;
        case 0xc7: { const d = this.fetch(); this.write(this.rdw(d + this.x), this.a); return cyc; }
        case 0xd7: { const d = this.fetch(); this.write((this.rdw(d) + this.y) & 0xffff, this.a); return cyc; }
        case 0xe4: this.a = this.nz(this.rd(this.fetch())); return cyc;
        case 0xf4: this.a = this.nz(this.rd(this.fetch() + this.x)); return cyc;
        case 0xe5: this.a = this.nz(this.read(this.fetch16())); return cyc;
        case 0xf5: this.a = this.nz(this.read((this.fetch16() + this.x) & 0xffff)); return cyc;
        case 0xe6: this.a = this.nz(this.rd(this.x)); return cyc;
        case 0xf6: this.a = this.nz(this.read((this.fetch16() + this.y) & 0xffff)); return cyc;
        case 0xe7: { const d = this.fetch(); this.a = this.nz(this.read(this.rdw(d + this.x))); return cyc; }
        case 0xf7: { const d = this.fetch(); this.a = this.nz(this.read((this.rdw(d) + this.y) & 0xffff)); return cyc; }
        case 0xe8: this.a = this.nz(this.fetch()); return cyc;
        case 0xcd: this.x = this.nz(this.fetch()); return cyc;
        case 0x8d: this.y = this.nz(this.fetch()); return cyc;
        case 0xc8: { const b = this.fetch(); const r = this.x - b; this.setC(r >= 0); this.nz(r); return cyc; }
        case 0xad: { const b = this.fetch(); const r = this.y - b; this.setC(r >= 0); this.nz(r); return cyc; }
        case 0x1e: case 0x3e: case 0x5e: case 0x7e: {
          const b = op === 0x1e || op === 0x5e ? this.read(this.fetch16()) : this.rd(this.fetch());
          const reg = op === 0x1e || op === 0x3e ? this.x : this.y;
          const r = reg - b; this.setC(r >= 0); this.nz(r); return cyc;
        }
        case 0xd8: this.wd(this.fetch(), this.x); return cyc;
        case 0xf8: this.x = this.nz(this.rd(this.fetch())); return cyc;
        case 0xc9: this.write(this.fetch16(), this.x); return cyc;
        case 0xd9: this.wd(this.fetch() + this.y, this.x); return cyc;
        case 0xe9: this.x = this.nz(this.read(this.fetch16())); return cyc;
        case 0xf9: this.x = this.nz(this.rd(this.fetch() + this.y)); return cyc;
        case 0xcb: this.wd(this.fetch(), this.y); return cyc;
        case 0xdb: this.wd(this.fetch() + this.x, this.y); return cyc;
        case 0xcc: this.write(this.fetch16(), this.y); return cyc;
        case 0xeb: this.y = this.nz(this.rd(this.fetch())); return cyc;
        case 0xfb: this.y = this.nz(this.rd(this.fetch() + this.x)); return cyc;
        case 0xec: this.y = this.nz(this.read(this.fetch16())); return cyc;
        case 0x5d: this.x = this.nz(this.a); return cyc;
        case 0x7d: this.a = this.nz(this.x); return cyc;
        case 0xdd: this.a = this.nz(this.y); return cyc;
        case 0xfd: this.y = this.nz(this.a); return cyc;
        case 0x9d: this.x = this.nz(this.sp); return cyc;
        case 0xbd: this.sp = this.x; return cyc;
        case 0xfa: { const s = this.rd(this.fetch()); this.wd(this.fetch(), s); return cyc; }
        case 0x8f: { const v = this.fetch(); this.wd(this.fetch(), v); return cyc; }
        case 0xaf: this.wd(this.x, this.a); this.x = (this.x + 1) & 0xff; return cyc;
        case 0xbf: this.a = this.nz(this.rd(this.x)); this.x = (this.x + 1) & 0xff; return cyc;
        // pile
        case 0x0d: this.push(this.psw); return cyc;
        case 0x2d: this.push(this.a); return cyc;
        case 0x4d: this.push(this.x); return cyc;
        case 0x6d: this.push(this.y); return cyc;
        case 0x8e: this.psw = this.pop(); return cyc;
        case 0xae: this.a = this.pop(); return cyc;
        case 0xce: this.x = this.pop(); return cyc;
        case 0xee: this.y = this.pop(); return cyc;
        // 16 bits
        case 0x1a: case 0x3a: { const d = this.fetch(); const v = (this.rdw(d) + (op === 0x3a ? 1 : -1)) & 0xffff; this.wdw(d, v); this.nz16(v); return cyc; }
        case 0x5a: { const w = this.rdw(this.fetch()), ya = (this.y << 8) | this.a, r = ya - w; this.setC(r >= 0); this.nz16(r & 0xffff); return cyc; }
        case 0x7a: case 0x9a: {
          const w = this.rdw(this.fetch()), ya = (this.y << 8) | this.a;
          const b = op === 0x7a ? w : (~w & 0xffff), c = op === 0x7a ? 0 : 1;
          const r = ya + b + c;
          this.psw &= ~0x49;
          if (r > 0xffff) this.psw |= 1;
          if (((ya & 0xfff) + (b & 0xfff) + c) > 0xfff) this.psw |= 8;
          if (~(ya ^ b) & (ya ^ r) & 0x8000) this.psw |= 0x40;
          this.a = r & 0xff; this.y = (r >> 8) & 0xff; this.nz16(r & 0xffff); return cyc;
        }
        case 0xba: { const w = this.rdw(this.fetch()); this.a = w & 0xff; this.y = w >> 8; this.nz16(w); return cyc; }
        case 0xda: { const d = this.fetch(); this.wdw(d, (this.y << 8) | this.a); return cyc; }
        case 0xcf: { const r = this.y * this.a; this.a = r & 0xff; this.y = r >> 8; this.nz(this.y); return cyc; }
        case 0x9e: {
          const ya = (this.y << 8) | this.a, x = this.x;
          this.psw &= ~0x48;
          if (this.y >= x) this.psw |= 0x40;
          if ((this.y & 15) >= (x & 15)) this.psw |= 8;
          if (this.y < (x << 1)) { this.a = Math.floor(ya / x) & 0xff; this.y = (ya % x) & 0xff; }
          else { this.a = (255 - Math.floor((ya - (x << 9)) / (256 - x))) & 0xff; this.y = (x + ((ya - (x << 9)) % (256 - x))) & 0xff; }
          this.nz(this.a); return cyc;
        }
        case 0xdf: if ((this.psw & 1) || this.a > 0x99) { this.a = (this.a + 0x60) & 0xff; this.psw |= 1; }
          if ((this.psw & 8) || (this.a & 15) > 9) this.a = (this.a + 6) & 0xff;
          this.nz(this.a); return cyc;
        case 0xbe: if (!(this.psw & 1) || this.a > 0x99) { this.a = (this.a - 0x60) & 0xff; this.psw &= ~1; }
          if (!(this.psw & 8) || (this.a & 15) > 9) this.a = (this.a - 6) & 0xff;
          this.nz(this.a); return cyc;
        case 0x9f: this.a = this.nz((this.a >> 4) | (this.a << 4)); return cyc;
        // bits
        case 0x0e: case 0x4e: { const a = this.fetch16(), v = this.read(a); this.nz(this.a - v); this.write(a, op === 0x0e ? v | this.a : v & ~this.a); return cyc; }
        case 0x0a: case 0x2a: case 0x4a: case 0x6a: case 0x8a: case 0xaa: case 0xca: case 0xea: {
          const { addr, bit } = this.bit(this.fetch16());
          const v = this.read(addr), b = (v >> bit) & 1, c = this.psw & 1;
          switch (op) {
            case 0x0a: this.setC(c | b); break;
            case 0x2a: this.setC(c | (b ^ 1)); break;
            case 0x4a: this.setC(c & b); break;
            case 0x6a: this.setC(c & (b ^ 1)); break;
            case 0x8a: this.setC(c ^ b); break;
            case 0xaa: this.setC(b); break;
            case 0xca: this.write(addr, (v & ~(1 << bit)) | (c << bit)); break;
            default: this.write(addr, v ^ (1 << bit)); break;
          }
          return cyc;
        }
        // sauts
        case 0x2e: { const v = this.rd(this.fetch()); return cyc + this.branch(this.a !== v); }
        case 0xde: { const v = this.rd(this.fetch() + this.x); return cyc + this.branch(this.a !== v); }
        case 0x6e: { const d = this.dp(this.fetch()); const v = (this.read(d) - 1) & 0xff; this.write(d, v); return cyc + this.branch(v !== 0); }
        case 0xfe: this.y = (this.y - 1) & 0xff; return cyc + this.branch(this.y !== 0);
        case 0x5f: this.pc = this.fetch16(); return cyc;
        case 0x1f: { const a = (this.fetch16() + this.x) & 0xffff; this.pc = this.read(a) | (this.read((a + 1) & 0xffff) << 8); return cyc; }
        case 0x3f: { const t = this.fetch16(); this.push(this.pc >> 8); this.push(this.pc & 0xff); this.pc = t; return cyc; }
        case 0x4f: { const u = this.fetch(); this.push(this.pc >> 8); this.push(this.pc & 0xff); this.pc = 0xff00 | u; return cyc; }
        case 0x6f: { const l = this.pop(); this.pc = l | (this.pop() << 8); return cyc; }
        case 0x7f: { this.psw = this.pop(); const l = this.pop(); this.pc = l | (this.pop() << 8); return cyc; }
        case 0x0f: { this.push(this.pc >> 8); this.push(this.pc & 0xff); this.push(this.psw); this.psw = (this.psw | 0x10) & ~4;
          this.pc = this.read(0xffde) | (this.read(0xffdf) << 8); return cyc; }
        case 0xef: case 0xff: this.halted = true; return cyc;
        default: return cyc;
      }
    }

    // Avance le module de `spcCycles` cycles (minuteries et DSP compris).
    run(spcCycles) {
      let left = spcCycles;
      while (left > 0) {
        const c = this.step();
        left -= c;
        for (let t = 0; t < 3; t++) {
          if (!this.timerOn[t]) continue;
          this.timerTick[t] += c;
          const period = t === 2 ? 16 : 128;
          while (this.timerTick[t] >= period) {
            this.timerTick[t] -= period;
            this.timerStage[t] = (this.timerStage[t] + 1) & 0xff;
            if (this.timerStage[t] === this.timerTarget[t]) { this.timerStage[t] = 0; this.timerOut[t] = (this.timerOut[t] + 1) & 15; }
          }
        }
        this.sampleClock += c;
        while (this.sampleClock >= 32) {
          this.sampleClock -= 32;
          const [l, r] = this.dsp.sample();
          this.resample += this.sampleRate;
          while (this.resample >= 32000) {
            this.resample -= 32000;
            const s = (l + r) / 65536;
            this.hp = 0.996 * (this.hp + s - this.prev); this.prev = s;
            this.samples.push(this.hp);
          }
        }
      }
      return left;  // ≤ 0 : cycles faits en trop, à déduire de la prochaine avance
    }
    take() { const out = this.samples; this.samples = []; return out; }
  }

  root.AetherAPU16 = { APU16, SPC_HZ };
})(typeof window !== "undefined" ? window : globalThis);
