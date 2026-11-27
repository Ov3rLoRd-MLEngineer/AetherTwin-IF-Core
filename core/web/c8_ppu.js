"use strict";
// Processeur vidéo (type 2C02) de l'atelier circuits : 262 lignes de 341 points, registres $2000-$2007,
// défilement par les registres internes v/t/x/w, fonds et sprites (8×8 ou 8×16), sprite 0, débordement, NMI.
// Chaque ligne visible est dessinée à son premier point avec l'état du défilement à cet instant ; le contact
// du sprite 0 est signalé au point exact où il a lieu.
//
// Le bus vidéo (motifs, écrans de fond) passe par `board` : la carte mère y simule le verrou d'adresses, la VRAM
// et la cartouche, et donc leurs pannes quand un composant manque.
(function (root) {
  // Palette NTSC calculée à partir du signal composite (niveaux de luminance et phase de chrominance du 2C02),
  // plutôt que recopiée d'une table : 64 couleurs en RGBA.
  function ntscPalette() {
    const out = new Uint32Array(64);
    const lo = [-0.117, 0.000, 0.308, 0.715], hi = [0.397, 0.681, 1.000, 1.000];
    const black = lo[1], white = hi[3];
    for (let p = 0; p < 64; p++) {
      const color = p & 0x0f, level = (p >> 4) & 3;
      let y = 0, i = 0, q = 0;
      for (let phase = 0; phase < 12; phase++) {
        const inPhase = (color + phase) % 12 < 6;
        let s = color > 0x0d ? black : color === 0 ? hi[level] : color === 0x0d ? lo[level] : inPhase ? hi[level] : lo[level];
        s = (s - black) / (white - black);
        y += s / 12;
        i += s * Math.cos(Math.PI * (phase + 4) / 6) / 12;
        q += s * Math.sin(Math.PI * (phase + 4) / 6) / 12;
      }
      const gamma = (v) => Math.round(255 * Math.pow(Math.min(1, Math.max(0, v)), 1 / 1.15));
      const r = gamma(y + 0.946882 * i + 0.623557 * q);
      const g = gamma(y - 0.274788 * i - 0.635691 * q);
      const b = gamma(y - 1.108545 * i + 1.709007 * q);
      out[p] = (255 << 24) | (b << 16) | (g << 8) | r;  // RGBA petit-boutiste
    }
    return out;
  }
  const PALETTE = ntscPalette();

  class PPU2C02 {
    constructor(board) {
      this.board = board;          // { vread(addr), vwrite(addr, v) } : bus vidéo de la carte mère
      this.frameBuffer = new Uint8Array(256 * 240);   // index de couleur (0-63) par pixel
      this.oam = new Uint8Array(256);
      this.palette = new Uint8Array(32);
      this.reset(true);
    }
    reset(power) {
      this.ctrl = 0; this.mask = 0; this.oamAddr = 0;
      this.v = 0; this.t = 0; this.x = 0; this.w = 0; this.buffer = 0;
      if (power) {
        this.status = 0xa0; this.scanline = 0; this.dot = 0; this.frame = 0; this.odd = false;
        // palette d'allumage (valeurs typiques d'un vrai 2C02)
        this.palette.set([0x09, 0x01, 0x00, 0x01, 0x00, 0x02, 0x02, 0x0d, 0x08, 0x10, 0x08, 0x24, 0x00, 0x00, 0x04, 0x2c,
          0x09, 0x01, 0x34, 0x03, 0x00, 0x04, 0x00, 0x14, 0x08, 0x3a, 0x00, 0x02, 0x00, 0x20, 0x2c, 0x08]);
        this.oam.fill(0);
      }
      this.nmiOut = false;
      this.openBus = 0;
      this.hitDot = -1;
      this.frameReady = false;
    }
    get rendering() { return (this.mask & 0x18) !== 0; }

    // ---------- registres côté processeur ----------
    readRegister(reg) {
      switch (reg & 7) {
        case 2: {
          const v = (this.status & 0xe0) | (this.openBus & 0x1f);
          this.status &= ~0x80; this.w = 0; this.nmiOut = false;
          this.openBus = v;
          return v;
        }
        case 4: this.openBus = this.oam[this.oamAddr]; return this.openBus;
        case 7: {
          const addr = this.v & 0x3fff;
          let v;
          if (addr >= 0x3f00) { v = this.readPalette(addr); this.buffer = this.board.vread(addr - 0x1000); }
          else { v = this.buffer; this.buffer = this.board.vread(addr); }
          this.v = (this.v + (this.ctrl & 0x04 ? 32 : 1)) & 0x7fff;
          this.openBus = v;
          return v;
        }
        default: return this.openBus;
      }
    }
    writeRegister(reg, value) {
      this.openBus = value;
      switch (reg & 7) {
        case 0: {
          const before = this.ctrl & 0x80;
          this.ctrl = value;
          this.t = (this.t & 0xf3ff) | ((value & 3) << 10);
          if (!before && (value & 0x80) && (this.status & 0x80)) this.nmiOut = true;  // NMI activée en plein vblank
          break;
        }
        case 1: this.mask = value; break;
        case 3: this.oamAddr = value; break;
        case 4: this.oam[this.oamAddr] = value; this.oamAddr = (this.oamAddr + 1) & 0xff; break;
        case 5:
          if (!this.w) { this.t = (this.t & 0xffe0) | (value >> 3); this.x = value & 7; }
          else { this.t = (this.t & 0x8c1f) | ((value & 7) << 12) | ((value & 0xf8) << 2); }
          this.w ^= 1;
          break;
        case 6:
          if (!this.w) this.t = (this.t & 0x00ff) | ((value & 0x3f) << 8);
          else { this.t = (this.t & 0xff00) | value; this.v = this.t; }
          this.w ^= 1;
          break;
        case 7: {
          const addr = this.v & 0x3fff;
          if (addr >= 0x3f00) this.writePalette(addr, value); else this.board.vwrite(addr, value);
          this.v = (this.v + (this.ctrl & 0x04 ? 32 : 1)) & 0x7fff;
          break;
        }
        default: break;
      }
    }
    paletteIndex(addr) { let i = addr & 0x1f; if ((i & 0x13) === 0x10) i &= ~0x10; return i; }
    readPalette(addr) { return this.palette[this.paletteIndex(addr)] & (this.mask & 1 ? 0x30 : 0x3f); }
    writePalette(addr, v) { this.palette[this.paletteIndex(addr)] = v & 0x3f; }

    // ---------- défilement (registre v) ----------
    incX() { if ((this.v & 0x1f) === 31) { this.v &= ~0x1f; this.v ^= 0x400; } else this.v += 1; }
    incY() {
      if ((this.v & 0x7000) !== 0x7000) { this.v += 0x1000; return; }
      this.v &= ~0x7000;
      let y = (this.v & 0x3e0) >> 5;
      if (y === 29) { y = 0; this.v ^= 0x800; } else if (y === 31) y = 0; else y += 1;
      this.v = (this.v & ~0x3e0) | (y << 5);
    }

    // ---------- une ligne visible ----------
    renderLine(line) {
      const out = this.frameBuffer, base = line * 256;
      const showBg = this.mask & 0x08, showSp = this.mask & 0x10;
      const bgLeft = this.mask & 0x02, spLeft = this.mask & 0x04;
      const bgPix = new Uint8Array(256);   // couleur 0-3 du fond (0 = transparent)
      const bgPal = new Uint8Array(256);
      if (showBg) {
        let v = this.v;
        const fineY = (v >> 12) & 7;
        const table = this.ctrl & 0x10 ? 0x1000 : 0;
        let px = -this.x;
        for (let tile = 0; tile < 33; tile++) {
          const ntAddr = 0x2000 | (v & 0x0fff);
          const index = this.board.vread(ntAddr);
          const atAddr = 0x23c0 | (v & 0x0c00) | ((v >> 4) & 0x38) | ((v >> 2) & 0x07);
          const shift = ((v >> 4) & 4) | (v & 2);
          const pal = (this.board.vread(atAddr) >> shift) & 3;
          const lo = this.board.vread(table + index * 16 + fineY);
          const hi = this.board.vread(table + index * 16 + fineY + 8);
          for (let b = 7; b >= 0; b--, px++) {
            if (px < 0 || px > 255) continue;
            bgPix[px] = ((lo >> b) & 1) | (((hi >> b) & 1) << 1);
            bgPal[px] = pal;
          }
          // coarse X suivant (avec changement d'écran de fond)
          if ((v & 0x1f) === 31) { v &= ~0x1f; v ^= 0x400; } else v += 1;
        }
        if (!bgLeft) for (let i = 0; i < 8; i++) bgPix[i] = 0;
      }
      // sprites de la ligne (8 au plus ; le 9e lève le drapeau de débordement)
      const spPix = new Uint8Array(256), spPal = new Uint8Array(256), spBehind = new Uint8Array(256), spZero = new Uint8Array(256);
      const tall = this.ctrl & 0x20, height = tall ? 16 : 8;
      let found = 0;
      this.hitDot = -1;
      for (let s = 0; s < 64; s++) {
        const y = this.oam[s * 4];
        const row = line - (y + 1);
        if (row < 0 || row >= height) continue;
        if (found === 8) { this.status |= 0x20; break; }
        found += 1;
        if (!showSp) continue;
        const tileByte = this.oam[s * 4 + 1], attr = this.oam[s * 4 + 2], sx = this.oam[s * 4 + 3];
        const r = attr & 0x80 ? height - 1 - row : row;
        let addr;
        if (tall) addr = ((tileByte & 1) << 12) | ((tileByte & 0xfe) << 4) | ((r & 8) << 1) | (r & 7);
        else addr = (this.ctrl & 0x08 ? 0x1000 : 0) | (tileByte << 4) | r;
        const lo = this.board.vread(addr), hi = this.board.vread(addr + 8);
        for (let i = 0; i < 8; i++) {
          const px = sx + i;
          if (px > 255) break;
          const b = attr & 0x40 ? i : 7 - i;
          const c = ((lo >> b) & 1) | (((hi >> b) & 1) << 1);
          if (!c || spPix[px] || (!spLeft && px < 8)) continue;
          spPix[px] = c; spPal[px] = attr & 3; spBehind[px] = attr & 0x20; spZero[px] = s === 0 ? 1 : 0;
        }
      }
      // composition
      const backdrop = this.palette[0];
      for (let px = 0; px < 256; px++) {
        const b = bgPix[px], s = spPix[px];
        if (s && b && spZero[px] && px !== 255 && showBg && showSp && this.hitDot < 0) this.hitDot = px + 1;
        let color;
        if (s && (!b || !spBehind[px])) color = this.palette[0x10 + spPal[px] * 4 + s];
        else if (b) color = this.palette[bgPal[px] * 4 + b];
        else color = backdrop;
        out[base + px] = color & (this.mask & 1 ? 0x30 : 0x3f);
      }
    }

    // Avance d'un point. Rend true quand une NMI doit être envoyée au processeur.
    tick() {
      const line = this.scanline, dot = this.dot;
      let nmi = false;
      if (line < 240) {
        if (dot === 1) {
          if (this.rendering) this.renderLine(line);
          else this.frameBuffer.fill(this.palette[0] & 0x3f, line * 256, line * 256 + 256);
        }
        if (dot === this.hitDot && this.rendering) this.status |= 0x40;
        if (this.rendering) {
          if (dot === 256) this.incY();
          else if (dot === 257) this.v = (this.v & ~0x041f) | (this.t & 0x041f);
        }
      } else if (line === 241 && dot === 1) {
        this.status |= 0x80;
        this.frameReady = true;
        if (this.ctrl & 0x80) nmi = true;
      } else if (line === 261) {
        if (dot === 1) { this.status &= ~0xe0; this.hitDot = -1; }
        if (this.rendering) {
          if (dot === 256) this.incY();
          else if (dot === 257) this.v = (this.v & ~0x041f) | (this.t & 0x041f);
          else if (dot >= 280 && dot <= 304) this.v = (this.v & ~0x7be0) | (this.t & 0x7be0);
          if (dot === 339 && this.odd) { this.dot = 340; }  // image impaire : un point de moins
        }
      }
      if (this.nmiOut) { this.nmiOut = false; nmi = true; }
      this.dot += 1;
      if (this.dot > 340) {
        this.dot = 0;
        this.scanline += 1;
        if (this.scanline > 261) { this.scanline = 0; this.frame += 1; this.odd = !this.odd; }
      }
      return nmi;
    }
  }

  root.AetherPPU = { PPU2C02, PALETTE };
})(typeof window !== "undefined" ? window : globalThis);
