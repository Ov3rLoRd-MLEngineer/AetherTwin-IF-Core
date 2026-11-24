"use strict";
// Processeur graphique de la console 16 bits de l'atelier : 64 Ko de mémoire vidéo, 256 couleurs choisies parmi
// 32 768 (5 bits par composante), 4 plans de fond en tuiles (modes 0 à 6) ou un plan tournant et zoomable
// (mode 7), 128 sprites, deux fenêtres, mélange de couleurs (addition, soustraction, moitié) et luminosité.
//
// L'image est rendue ligne par ligne (256 points × 224 lignes) quand le faisceau arrive en fin de ligne : les
// changements de registres d'une ligne à l'autre (HDMA, interruptions de ligne) sont donc vus, comme sur la
// console. Les modes haute résolution (5 et 6) sont affichés à 256 points (un point sur deux).
(function (root) {
  // couleur 15 bits → 32 bits RGBA (petit-boutiste : 0xAABBGGRR), selon la luminosité 0-15
  const LUT = [];
  for (let b = 0; b < 16; b++) {
    const t = new Uint32Array(32768);
    for (let c = 0; c < 32768; c++) {
      const conv = (v) => Math.round(((v << 3) | (v >> 2)) * b / 15);
      t[c] = 0xff000000 | (conv((c >> 10) & 31) << 16) | (conv((c >> 5) & 31) << 8) | conv(c & 31);
    }
    LUT.push(t);
  }
  // tailles des sprites (petit, grand) selon OBSEL : [largeur, hauteur]
  const OBJ_SIZES = [[[8, 8], [16, 16]], [[8, 8], [32, 32]], [[8, 8], [64, 64]], [[16, 16], [32, 32]],
                     [[16, 16], [64, 64]], [[32, 32], [64, 64]], [[16, 32], [32, 64]], [[16, 32], [32, 32]]];
  // profondeur de couleur (bits par point) des plans 1 à 4 selon le mode
  const BPP = [[2, 2, 2, 2], [4, 4, 2, 0], [4, 4, 0, 0], [8, 4, 0, 0], [8, 2, 0, 0], [4, 2, 0, 0], [4, 0, 0, 0], [8, 0, 0, 0]];
  // Ordre d'affichage, de l'avant vers l'arrière : "1H" = plan 1 priorité haute, "S3" = sprites de priorité 3.
  const ORDER = {
    0: ["S3", "1H", "2H", "S2", "1L", "2L", "S1", "3H", "4H", "S0", "3L", "4L"],
    1: ["S3", "1H", "2H", "S2", "1L", "2L", "S1", "3H", "S0", "3L"],
    "1+": ["3H", "S3", "1H", "2H", "S2", "1L", "2L", "S1", "S0", "3L"],
    2: ["S3", "1H", "S2", "2H", "S1", "1L", "S0", "2L"],
    6: ["S3", "1H", "S2", "S1", "1L", "S0"],
    7: ["S3", "S2", "S1", "1L", "S0"],
  };
  const Z = {};
  for (const key in ORDER) {
    const z = {};
    ORDER[key].forEach((name, i) => { z[name] = ORDER[key].length - i; });
    Z[key] = z;
  }
  const zTable = (mode, bg3prio) => (mode === 1 ? Z[bg3prio ? "1+" : 1] : mode === 0 ? Z[0] : mode === 6 ? Z[6]
    : mode === 7 ? Z[7] : Z[2]);

  class PPU16 {
    constructor() {
      this.vram = new Uint16Array(32768);
      this.cgram = new Uint16Array(256);
      this.oam = new Uint8Array(544);
      this.frame = new Uint32Array(256 * 240);
      this.reset();
    }
    reset() {
      this.forceBlank = true; this.brightness = 0;
      this.objSize = 0; this.objBase = 0; this.objGap = 0;
      this.oamAddr = 0; this.oamReload = 0; this.oamLatch = 0; this.oamPriority = false;
      this.mode = 0; this.bg3prio = false; this.tile16 = [false, false, false, false];
      this.mosaicSize = 1; this.mosaicOn = [false, false, false, false];
      this.sc = [0, 0, 0, 0]; this.scSize = [0, 0, 0, 0]; this.chr = [0, 0, 0, 0];
      this.hofs = [0, 0, 0, 0]; this.vofs = [0, 0, 0, 0]; this.ofsLatch = 0; this.hofsLatch = 0;
      this.vmain = 0; this.vaddr = 0; this.vlatch = 0;
      this.m7sel = 0; this.m7 = [0, 0, 0, 0, 0, 0]; this.m7latch = 0; this.m7hofs = 0; this.m7vofs = 0;
      this.cgaddr = 0; this.cgflip = false; this.cglatch = 0; this.cgread = false;
      this.wsel = [0, 0, 0, 0, 0, 0]; this.wh = [0, 0, 0, 0]; this.wlog = [0, 0, 0, 0, 0, 0];
      this.tm = 0; this.ts = 0; this.tmw = 0; this.tsw = 0;
      this.cgwsel = 0; this.cgadsub = 0; this.fixed = 0; this.setini = 0;
      this.mpy = 0; this.hcounter = 0; this.vcounter = 0; this.counterLatched = false; this.hflip = false; this.vflip = false;
      this.ppu1Bus = 0; this.ppu2Bus = 0;
      this.timeOver = false; this.rangeOver = false;
      this.line = 0;
    }

    // ---------- écriture des registres $2100-$2133 ----------
    write(reg, v) {
      switch (reg) {
        case 0x00: this.forceBlank = (v & 0x80) !== 0; this.brightness = v & 15; break;
        case 0x01: this.objSize = v >> 5; this.objGap = (((v >> 3) & 3) + 1) << 12; this.objBase = (v & 7) << 13; break;
        case 0x02: this.oamReload = (this.oamReload & 0x200) | (v << 1); this.oamAddr = this.oamReload; break;
        case 0x03: this.oamReload = ((v & 1) << 9) | (this.oamReload & 0x1fe); this.oamPriority = (v & 0x80) !== 0;
          this.oamAddr = this.oamReload; break;
        case 0x04: {
          const a = this.oamAddr;
          if (a >= 0x200) this.oam[a & 0x21f] = v;
          else if (!(a & 1)) this.oamLatch = v;
          else { this.oam[a - 1] = this.oamLatch; this.oam[a] = v; }
          this.oamAddr = (a + 1) & 0x3ff;
          break;
        }
        case 0x05: this.mode = v & 7; this.bg3prio = (v & 8) !== 0;
          for (let i = 0; i < 4; i++) this.tile16[i] = (v & (0x10 << i)) !== 0; break;
        case 0x06: this.mosaicSize = (v >> 4) + 1; for (let i = 0; i < 4; i++) this.mosaicOn[i] = (v & (1 << i)) !== 0; break;
        case 0x07: case 0x08: case 0x09: case 0x0a: this.sc[reg - 7] = (v & 0xfc) << 8; this.scSize[reg - 7] = v & 3; break;
        case 0x0b: this.chr[0] = (v & 15) << 12; this.chr[1] = (v >> 4) << 12; break;
        case 0x0c: this.chr[2] = (v & 15) << 12; this.chr[3] = (v >> 4) << 12; break;
        case 0x0d: case 0x0f: case 0x11: case 0x13: {
          const i = (reg - 0x0d) >> 1;
          this.hofs[i] = ((v << 8) | (this.ofsLatch & ~7) | (this.hofsLatch & 7)) & 0x3ff;
          this.ofsLatch = v; this.hofsLatch = v;
          if (i === 0) { this.m7hofs = ((v << 8) | this.m7latch) & 0x1fff; this.m7latch = v; }
          break;
        }
        case 0x0e: case 0x10: case 0x12: case 0x14: {
          const i = (reg - 0x0e) >> 1;
          this.vofs[i] = ((v << 8) | this.ofsLatch) & 0x3ff;
          this.ofsLatch = v;
          if (i === 0) { this.m7vofs = ((v << 8) | this.m7latch) & 0x1fff; this.m7latch = v; }
          break;
        }
        case 0x15: this.vmain = v; break;
        case 0x16: this.vaddr = (this.vaddr & 0xff00) | v; this.vlatch = this.vram[this.vmap() & 0x7fff]; break;
        case 0x17: this.vaddr = (this.vaddr & 0x00ff) | (v << 8); this.vlatch = this.vram[this.vmap() & 0x7fff]; break;
        case 0x18: { const a = this.vmap() & 0x7fff; if (this.vramOpen()) this.vram[a] = (this.vram[a] & 0xff00) | v;
          if (!(this.vmain & 0x80)) this.vinc(); break; }
        case 0x19: { const a = this.vmap() & 0x7fff; if (this.vramOpen()) this.vram[a] = (this.vram[a] & 0x00ff) | (v << 8);
          if (this.vmain & 0x80) this.vinc(); break; }
        case 0x1a: this.m7sel = v; break;
        case 0x1b: case 0x1c: case 0x1d: case 0x1e: case 0x1f: case 0x20: {
          const i = reg - 0x1b;
          this.m7[i] = ((v << 8) | this.m7latch) & 0xffff;
          this.m7latch = v;
          const a = (this.m7[0] << 16) >> 16, b = (this.m7[1] << 16) >> 24;
          this.mpy = (a * b) & 0xffffff;
          break;
        }
        case 0x21: this.cgaddr = v; this.cgflip = false; break;
        case 0x22:
          if (!this.cgflip) this.cglatch = v;
          else { this.cgram[this.cgaddr] = ((v & 0x7f) << 8) | this.cglatch; this.cgaddr = (this.cgaddr + 1) & 0xff; }
          this.cgflip = !this.cgflip;
          break;
        case 0x23: this.wsel[0] = v & 15; this.wsel[1] = v >> 4; break;
        case 0x24: this.wsel[2] = v & 15; this.wsel[3] = v >> 4; break;
        case 0x25: this.wsel[4] = v & 15; this.wsel[5] = v >> 4; break;
        case 0x26: case 0x27: case 0x28: case 0x29: this.wh[reg - 0x26] = v; break;
        case 0x2a: for (let i = 0; i < 4; i++) this.wlog[i] = (v >> (i * 2)) & 3; break;
        case 0x2b: this.wlog[4] = v & 3; this.wlog[5] = (v >> 2) & 3; break;
        case 0x2c: this.tm = v; break;
        case 0x2d: this.ts = v; break;
        case 0x2e: this.tmw = v; break;
        case 0x2f: this.tsw = v; break;
        case 0x30: this.cgwsel = v; break;
        case 0x31: this.cgadsub = v; break;
        case 0x32: {
          const i = v & 31;
          if (v & 0x20) this.fixed = (this.fixed & ~31) | i;
          if (v & 0x40) this.fixed = (this.fixed & ~(31 << 5)) | (i << 5);
          if (v & 0x80) this.fixed = (this.fixed & ~(31 << 10)) | (i << 10);
          break;
        }
        case 0x33: this.setini = v; break;
        default: break;
      }
    }
    vramOpen() { return this.forceBlank || this.line >= 225; }
    vmap() {
      const a = this.vaddr;
      switch ((this.vmain >> 2) & 3) {
        case 1: return (a & 0xff00) | ((a & 0x001f) << 3) | ((a >> 5) & 7);
        case 2: return (a & 0xfe00) | ((a & 0x003f) << 3) | ((a >> 6) & 7);
        case 3: return (a & 0xfc00) | ((a & 0x007f) << 3) | ((a >> 7) & 7);
        default: return a;
      }
    }
    vinc() { this.vaddr = (this.vaddr + [1, 32, 128, 128][this.vmain & 3]) & 0xffff; }

    // ---------- lecture des registres $2134-$213F ----------
    read(reg, openBus) {
      switch (reg) {
        case 0x34: return (this.ppu1Bus = this.mpy & 0xff);
        case 0x35: return (this.ppu1Bus = (this.mpy >> 8) & 0xff);
        case 0x36: return (this.ppu1Bus = (this.mpy >> 16) & 0xff);
        case 0x37: this.latchCounters(); return openBus;
        case 0x38: {
          const a = this.oamAddr;
          const v = a >= 0x200 ? this.oam[a & 0x21f] : this.oam[a];
          this.oamAddr = (a + 1) & 0x3ff;
          return (this.ppu1Bus = v);
        }
        case 0x39: { const v = this.vlatch & 0xff; if (!(this.vmain & 0x80)) { this.vlatch = this.vram[this.vmap() & 0x7fff]; this.vinc(); }
          return (this.ppu1Bus = v); }
        case 0x3a: { const v = this.vlatch >> 8; if (this.vmain & 0x80) { this.vlatch = this.vram[this.vmap() & 0x7fff]; this.vinc(); }
          return (this.ppu1Bus = v); }
        case 0x3b: {
          const c = this.cgram[this.cgaddr];
          let v;
          if (!this.cgread) v = c & 0xff; else { v = (c >> 8) | (this.ppu2Bus & 0x80); this.cgaddr = (this.cgaddr + 1) & 0xff; }
          this.cgread = !this.cgread;
          return (this.ppu2Bus = v);
        }
        case 0x3c: { const v = this.hflip ? (this.hcounter >> 8) | (this.ppu2Bus & 0xfe) : this.hcounter & 0xff;
          this.hflip = !this.hflip; return (this.ppu2Bus = v); }
        case 0x3d: { const v = this.vflip ? (this.vcounter >> 8) | (this.ppu2Bus & 0xfe) : this.vcounter & 0xff;
          this.vflip = !this.vflip; return (this.ppu2Bus = v); }
        case 0x3e: return (this.ppu1Bus = (this.timeOver ? 0x80 : 0) | (this.rangeOver ? 0x40 : 0) | (this.ppu1Bus & 0x10) | 1);
        case 0x3f: {
          const v = (this.counterLatched ? 0x40 : 0) | (this.ppu2Bus & 0x20) | 3;  // version 3, image NTSC
          this.counterLatched = false; this.hflip = false; this.vflip = false;
          return (this.ppu2Bus = v);
        }
        default: return openBus;
      }
    }
    latchCounters() {
      if (this.dotSource) { const [h, v] = this.dotSource(); this.hcounter = h; this.vcounter = v; }
      this.counterLatched = true;
    }

    // ---------- fenêtres ----------
    // sélecteur 4 bits : [W1 inversée, W1 active, W2 inversée, W2 active] → vrai si x est « dans » la fenêtre
    windowAt(sel, logic, x) {
      const w1on = sel & 2, w2on = sel & 8;
      if (!w1on && !w2on) return false;
      const in1 = ((x >= this.wh[0] && x <= this.wh[1]) ? 1 : 0) ^ (sel & 1);
      const in2 = ((x >= this.wh[2] && x <= this.wh[3]) ? 1 : 0) ^ ((sel >> 2) & 1);
      if (w1on && !w2on) return in1 === 1;
      if (w2on && !w1on) return in2 === 1;
      switch (logic) {
        case 0: return (in1 | in2) === 1;
        case 1: return (in1 & in2) === 1;
        case 2: return (in1 ^ in2) === 1;
        default: return (in1 ^ in2) === 0;
      }
    }

    // ---------- plans de fond ----------
    // Remplit col (index de palette CGRAM, 0 = transparent) et pri (bit de priorité) pour la ligne y du plan bg.
    renderBg(bg, y, bpp, col, pri) {
      col.fill(0); pri.fill(0);
      const vram = this.vram, big = this.tile16[bg];
      const hires = this.mode === 5 || this.mode === 6;
      const tw = big || hires ? 16 : 8, th = big ? 16 : 8;
      const mosaic = this.mosaicOn[bg] ? this.mosaicSize : 1;
      const yy = ((mosaic > 1 ? y - (y % mosaic) : y) + this.vofs[bg]) & 0x3ff;
      const size = this.scSize[bg], base = this.sc[bg], chr = this.chr[bg];
      const words = bpp * 4;  // mots par tuile 8×8
      const palBase = this.mode === 0 ? bg * 32 : 0;
      const ty = Math.floor(yy / th);
      for (let x = 0; x < 256; x++) {
        const sx = mosaic > 1 ? x - (x % mosaic) : x;
        const xx = ((hires ? sx * 2 : sx) + (hires ? this.hofs[bg] * 2 : this.hofs[bg])) & (hires ? 0x7ff : 0x3ff);
        const tx = Math.floor(xx / tw);
        // écran de 32×32 tuiles ; 64 de large et/ou de haut selon scSize
        let map = base + ((ty & 31) << 5) + (tx & 31);
        if ((size & 1) && (tx & 32)) map += 0x400;
        if ((size & 2) && (ty & 32)) map += (size & 1) ? 0x800 : 0x400;
        const entry = vram[map & 0x7fff];
        let px = xx % tw, py = yy % th;
        if (entry & 0x4000) px = tw - 1 - px;
        if (entry & 0x8000) py = th - 1 - py;
        let tile = entry & 0x3ff;
        if (px >= 8) tile += 1;
        if (py >= 8) tile += 16;
        const addr = (chr + ((tile & 0x3ff) * words) + (py & 7)) & 0x7fff;
        const bit = 7 - (px & 7);
        let c = 0;
        for (let plane = 0; plane < bpp; plane += 2) {
          const w = vram[(addr + plane * 4) & 0x7fff];
          c |= (((w >> bit) & 1) | (((w >> (bit + 8)) & 1) << 1)) << plane;
        }
        if (!c) continue;
        const pal = (entry >> 10) & 7;
        col[x] = bpp === 8 ? c : palBase + pal * (1 << bpp) + c;
        pri[x] = (entry >> 13) & 1;
      }
    }
    renderMode7(y, col, pri) {
      col.fill(0); pri.fill(0);
      const s = (v, bits) => (v << (32 - bits)) >> (32 - bits);
      const a = s(this.m7[0], 16), b = s(this.m7[1], 16), c = s(this.m7[2], 16), d = s(this.m7[3], 16);
      const cx = s(this.m7[4], 13), cy = s(this.m7[5], 13);
      const hofs = s(this.m7hofs, 13), vofs = s(this.m7vofs, 13);
      const clip = (v) => ((v & 0x2000) ? (v | ~0x3ff) : (v & 0x3ff));
      const yy = (this.m7sel & 2) ? 255 - y : y;
      const ox = clip(hofs - cx), oy = clip(vofs - cy);
      const px0 = ((a * ox) & ~63) + ((b * oy) & ~63) + ((b * yy) & ~63) + (cx << 8);
      const py0 = ((c * ox) & ~63) + ((d * oy) & ~63) + ((d * yy) & ~63) + (cy << 8);
      const over = this.m7sel >> 6, vram = this.vram;
      for (let x = 0; x < 256; x++) {
        const xx = (this.m7sel & 1) ? 255 - x : x;
        let X = (px0 + a * xx) >> 8, Y = (py0 + c * xx) >> 8;
        let tile;
        const outside = X < 0 || Y < 0 || X > 1023 || Y > 1023;
        if (outside && over === 2) continue;
        if (outside && over === 3) tile = 0;
        else { X &= 1023; Y &= 1023; tile = vram[((Y >> 3) << 7) | (X >> 3)] & 0xff; }
        const v = vram[(tile << 6) | ((Y & 7) << 3) | (X & 7)] >> 8;
        if (v) col[x] = v;
      }
    }

    // ---------- sprites ----------
    renderObj(y, col, pri) {
      col.fill(0); pri.fill(0);
      const sizes = OBJ_SIZES[this.objSize], oam = this.oam, vram = this.vram;
      const first = this.oamPriority ? (this.oamReload >> 2) & 127 : 0;
      let count = 0;
      this.rangeOver = false;
      for (let k = 0; k < 128; k++) {
        const n = (first + k) & 127;
        const high = (oam[0x200 + (n >> 2)] >> ((n & 3) * 2)) & 3;
        const [w, h] = sizes[(high >> 1) & 1];
        let sx = oam[n * 4] | ((high & 1) << 8);
        if (sx >= 256) sx -= 512;
        const sy = oam[n * 4 + 1];
        let row = (y - sy) & 0xff;
        if (row >= h) continue;
        if (sx <= -w || sx >= 256) continue;
        if (++count > 32) { this.rangeOver = true; break; }
        const attr = oam[n * 4 + 3];
        const tileBase = oam[n * 4 + 2] | ((attr & 1) << 8);
        if (attr & 0x80) row = h - 1 - row;
        const palBase = 128 + ((attr >> 1) & 7) * 16, prio = (attr >> 4) & 3;
        for (let i = 0; i < w; i++) {
          const x = sx + i;
          if (x < 0 || x > 255 || col[x]) continue;
          const cxp = (attr & 0x40) ? w - 1 - i : i;
          const t = (tileBase & 0x100) | (((tileBase & 0xf0) + ((row >> 3) << 4)) & 0xf0) | ((tileBase + (cxp >> 3)) & 0x0f);
          const addr = (this.objBase + ((t & 0x100) ? this.objGap : 0) + ((t & 0xff) << 4) + (row & 7)) & 0x7fff;
          const bit = 7 - (cxp & 7);
          const w0 = vram[addr], w1 = vram[(addr + 8) & 0x7fff];
          const c = ((w0 >> bit) & 1) | (((w0 >> (bit + 8)) & 1) << 1) | (((w1 >> bit) & 1) << 2) | (((w1 >> (bit + 8)) & 1) << 3);
          if (!c) continue;
          col[x] = palBase + c;
          pri[x] = prio;
        }
      }
    }

    // ---------- une ligne de l'image ----------
    renderLine(line) {
      // line : 1 à 224 (ligne 0 jamais affichée) ; l'image de 224 lignes est centrée dans les 240 du téléviseur
      const out = line - 1 + 8;
      if (out < 0 || out >= 240) return;
      const dst = out * 256;
      if (this.forceBlank || !this.brightness) { this.frame.fill(0xff000000, dst, dst + 256); return; }
      const y = line - 1 + 1;  // le plan de fond affiche la ligne « line » avec le défilement vertical
      const mode = this.mode, bpps = BPP[mode], z = zTable(mode, this.bg3prio);
      const buf = this.buffers || (this.buffers = {
        col: [0, 1, 2, 3, 4].map(() => new Uint16Array(256)), pri: [0, 1, 2, 3, 4].map(() => new Uint8Array(256)),
        main: new Uint16Array(256), mainZ: new Uint8Array(256), mainLayer: new Uint8Array(256), mainPal: new Uint8Array(256),
        sub: new Uint16Array(256), subZ: new Uint8Array(256), subLayer: new Uint8Array(256),
      });
      const used = this.tm | this.ts;
      for (let bg = 0; bg < 4; bg++) {
        if (!(used & (1 << bg))) continue;
        if (mode === 7) { if (bg === 0) this.renderMode7(line, buf.col[0], buf.pri[0]); continue; }
        if (bpps[bg]) this.renderBg(bg, y, bpps[bg], buf.col[bg], buf.pri[bg]);
      }
      if (used & 0x10) this.renderObj(line - 1, buf.col[4], buf.pri[4]);
      // écran principal et sous-écran
      const compose = (enable, winMask, color, zbuf, layer, palOut) => {
        const back = this.cgram[0];
        color.fill(back); zbuf.fill(0); layer.fill(5);
        for (let l = 0; l < 5; l++) {
          if (!(enable & (1 << l))) continue;
          if (l < 4 && (mode === 7 ? l > 0 : !bpps[l])) continue;
          const col = buf.col[l], pri = buf.pri[l];
          const masked = (winMask >> l) & 1;
          const zs = l === 4 ? [z.S0 || 0, z.S1 || 0, z.S2 || 0, z.S3 || 0] : [z[(l + 1) + "L"] || 0, z[(l + 1) + "H"] || 0];
          for (let x = 0; x < 256; x++) {
            const c = col[x];
            if (!c) continue;
            const zz = zs[pri[x]];
            if (!zz || zz <= zbuf[x]) continue;
            if (masked && this.windowAt(this.wsel[l], this.wlog[l], x)) continue;
            zbuf[x] = zz; layer[x] = l;
            color[x] = (bpps[l] === 8 && l < 4 && (this.cgwsel & 1)) ? this.direct(c) : this.cgram[c];
            if (palOut) palOut[x] = c;
          }
        }
      };
      compose(this.tm, this.tmw, buf.main, buf.mainZ, buf.mainLayer, buf.mainPal);
      const useSub = (this.cgwsel & 2) !== 0;
      if (useSub) compose(this.ts, this.tsw, buf.sub, buf.subZ, buf.subLayer, null);
      const lut = LUT[this.brightness], frame = this.frame;
      const sub = this.cgadsub & 0x80, half = this.cgadsub & 0x40;
      const blackRule = this.cgwsel >> 6, mathRule = (this.cgwsel >> 4) & 3;
      for (let x = 0; x < 256; x++) {
        let c = buf.main[x];
        const l = buf.mainLayer[x];
        const inColorWindow = (blackRule || mathRule) ? this.windowAt(this.wsel[5], this.wlog[5], x) : false;
        const black = blackRule === 3 || (blackRule === 1 && !inColorWindow) || (blackRule === 2 && inColorWindow);
        if (black) c = 0;
        const allowed = !(mathRule === 3 || (mathRule === 1 && !inColorWindow) || (mathRule === 2 && inColorWindow));
        const layerBit = l === 5 ? 0x20 : l === 4 ? 0x10 : 1 << l;
        const objOk = l !== 4 || buf.mainPal[x] >= 192;
        if (allowed && (this.cgadsub & layerBit) && objOk) {
          let other = this.fixed, halve = half;
          if (useSub) {
            if (buf.subLayer[x] !== 5) other = buf.sub[x];
            else halve = 0;  // sous-écran vide : couleur fixe, sans la moitié
          }
          if (black) halve = 0;
          c = this.mix(c, other, sub, halve);
        }
        frame[dst + x] = lut[c & 0x7fff];
      }
    }
    direct(c) {
      return ((c & 7) << 2) | (((c >> 3) & 7) << 7) | (((c >> 6) & 3) << 13);
    }
    mix(a, b, sub, half) {
      let r = a & 31, g = (a >> 5) & 31, bl = (a >> 10) & 31;
      const r2 = b & 31, g2 = (b >> 5) & 31, b2 = (b >> 10) & 31;
      if (sub) { r -= r2; g -= g2; bl -= b2; } else { r += r2; g += g2; bl += b2; }
      if (half) { r >>= 1; g >>= 1; bl >>= 1; }
      r = Math.max(0, Math.min(31, r)); g = Math.max(0, Math.min(31, g)); bl = Math.max(0, Math.min(31, bl));
      return r | (g << 5) | (bl << 10);
    }
    blankFrame() { this.frame.fill(0xff000000); }
  }

  root.AetherPPU16 = { PPU16, LUT };
})(typeof window !== "undefined" ? window : globalThis);
