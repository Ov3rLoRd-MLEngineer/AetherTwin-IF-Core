"use strict";
// Carte de la console 16 bits de l'atelier (« Japon grise 16 bits 1990 ») : processeur 65C816 avec ses contrôleurs
// DMA, deux puces vidéo, 128 Ko de mémoire de travail, 64 Ko de mémoire vidéo, un module son autonome et une
// cartouche. Comme pour l'établi 8 bits, la carte se monte pièce par pièce (`PARTS`) : une pièce absente ne bloque
// pas tout, elle produit la panne qu'elle produirait sur une vraie carte.
//
// Le temps se compte en cycles de l'horloge maître (21,477 MHz) : chaque accès du processeur coûte 6, 8 ou 12
// cycles selon la zone, une ligne vidéo en dure 1 364 et une image 262 lignes. Le module son, sur sa propre
// horloge (1,024 MHz), est rattrapé quand le programme lui parle et à chaque fin de ligne.
(function (root) {
  const { CPU65816 } = root.AetherCPU16;
  const { PPU16 } = root.AetherPPU16;
  const { APU16, SPC_HZ } = root.AetherAPU16;
  const MASTER_HZ = 21477272;
  const LINE = 1364, LINES = 262, HBLANK = 1096;

  const PARTS = [
    { id: "power", label: "Alimentation 5 V", ref: "régulateur 7805", socket: "power",
      role: "Transforme le courant de l'adaptateur en 5 V stables pour toutes les puces.",
      missing: "Rien ne s'allume : aucune puce n'est alimentée." },
    { id: "clock", label: "Quartz 21,477 MHz", ref: "oscillateur NTSC", socket: "clock",
      role: "Horloge maître : divisée par 6, 8 ou 12 pour le processeur (3,58 / 2,68 / 1,79 MHz selon la zone lue) et par 4 pour la vidéo.",
      missing: "Sans horloge, aucune puce n'avance : pas d'image (neige), pas de programme." },
    { id: "cpu", label: "Processeur 65C816", ref: "65C816 + DMA", socket: "qfp-cpu",
      role: "Exécute le programme (registres de 8 ou 16 bits, 16 Mo d'adresses), multiplie, divise, lit les manettes et copie la mémoire par DMA.",
      missing: "La vidéo reste dans son état d'allumage (« écran éteint ») : image noire, rien ne bouge." },
    { id: "wram", label: "RAM de travail 128 Ko", ref: "DRAM 128K", socket: "wram",
      role: "Variables, pile et tampons du jeu ($7E0000-$7FFFFF, les 8 premiers Ko aussi visibles dans chaque banque basse).",
      missing: "Le programme lit le bus flottant à la place de ses variables : la pile est perdue, il plante." },
    { id: "ppu1", label: "Puce vidéo 1", ref: "PPU1", socket: "qfp-ppu1",
      role: "Lit la mémoire vidéo : tuiles des 4 plans de fond, 128 sprites, rotation du mode 7.",
      missing: "Plus aucun motif : seule la couleur de fond (palette 0) sort, le programme tourne en aveugle." },
    { id: "ppu2", label: "Puce vidéo 2", ref: "PPU2", socket: "qfp-ppu2",
      role: "Mélange les plans, applique fenêtres, transparences et luminosité, et produit la synchro de l'image.",
      missing: "Pas de synchro ni de couleur : la télé n'a aucun signal (neige)." },
    { id: "vram", label: "Mémoire vidéo 64 Ko", ref: "2 × SRAM 32K", socket: "vram",
      role: "Les motifs des tuiles et des sprites et les cartes des plans de fond.",
      missing: "Les plans lisent des cellules au hasard : motifs parasites à la place du décor." },
    { id: "sound", label: "Module son", ref: "SPC700 + DSP + 64 Ko", socket: "sound",
      role: "Un second processeur avec sa mémoire : il reçoit sa musique par 4 ports et joue 8 voix échantillonnées (écho, enveloppes).",
      missing: "Silence, et le programme qui attend la réponse du module (« $BBAA ») reste bloqué au démarrage." },
    { id: "slot", label: "Connecteur de cartouche", ref: "62 broches", socket: "slot",
      role: "Relie la cartouche au bus d'adresses 24 bits du processeur.",
      missing: "La cartouche n'est reliée à rien : le processeur lit un vecteur de démarrage au hasard." },
    { id: "cart", label: "Cartouche", ref: "ROM + mémoire de sauvegarde", socket: "cart",
      role: "Le jeu : jusqu'à 4 Mo de programme et de graphismes, rangés en banques (cartes « LoROM » ou « HiROM »).",
      missing: "Sans cartouche, aucun programme : le processeur part dans le décor." },
    { id: "pads", label: "Ports de manettes", ref: "2 × 7 broches", socket: "pads",
      role: "Chaque manette envoie ses 12 boutons en série ; la console les lit seule à chaque image.",
      missing: "Les boutons ne répondent pas." },
    { id: "video", label: "Sortie vidéo", ref: "encodeur composite", socket: "video",
      role: "Transforme le rouge, le vert, le bleu et la synchro en signal pour la télé.",
      missing: "La console tourne mais la télé ne reçoit rien : neige." },
  ];

  // ---------- cartouche ----------
  function headerScore(b, base) {
    if (b.length < base + 0x40) return -1;
    let score = 0;
    const check = b[base + 0x1e] | (b[base + 0x1f] << 8), comp = b[base + 0x1c] | (b[base + 0x1d] << 8);
    if ((check ^ comp) === 0xffff) score += 4;
    const map = b[base + 0x15] & 0xef;
    if ((base === 0x7fc0 && map === 0x20) || (base === 0xffc0 && map === 0x21)) score += 3;
    const reset = b[base + 0x3c] | (b[base + 0x3d] << 8);
    if (reset >= 0x8000) score += 2;
    let printable = 0;
    for (let i = 0; i < 21; i++) { const c = b[base + i]; if (c >= 0x20 && c < 0x7f) printable += 1; }
    if (printable >= 18) score += 1;
    return score;
  }
  function parseRom(bytes) {
    let b = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    if (b.length % 1024 === 512) b = b.slice(512);  // en-tête de 512 octets des copieurs
    if (b.length < 0x8000) throw new Error("fichier trop court pour une cartouche (32 Ko au minimum)");
    if (b.length > 0x400000) throw new Error("cartouche de plus de 4 Mo : non prise en charge");
    const lo = headerScore(b, 0x7fc0), hi = headerScore(b, 0xffc0);
    const hiRom = hi > lo;
    const h = hiRom ? 0xffc0 : 0x7fc0;
    const type = b[h + 0x16];
    if (type > 2 && type !== 0xff) {
      throw new Error("cartouche avec une puce supplémentaire (coprocesseur) : seules les cartes simples (ROM + sauvegarde) sont câblées");
    }
    const sramCode = b[h + 0x18];
    const sram = new Uint8Array(sramCode && sramCode <= 8 ? 1024 << sramCode : 0);
    let title = "";
    for (let i = 0; i < 21; i++) { const c = b[h + i]; title += c >= 0x20 && c < 0x7f ? String.fromCharCode(c) : " "; }
    // ROM de taille non puissance de 2 : on la répète pour remplir l'espace (comme les miroirs de la vraie carte)
    let size = 1; while (size < b.length) size <<= 1;
    const rom = new Uint8Array(size);
    for (let i = 0; i < size; i += b.length) rom.set(b.subarray(0, Math.min(b.length, size - i)), i);
    return { rom, sram, hiRom, title: title.trim(), mask: size - 1 };
  }

  // ---------- manettes ----------
  // ordre des bits sur le fil série : B Y Select Start Haut Bas Gauche Droite A X L R
  const BUTTONS = ["B", "Y", "Select", "Start", "Up", "Down", "Left", "Right", "A", "X", "L", "R"];
  class Pad {
    constructor() { this.state = 0; this.shift = 0; this.latch = false; }
    press(button, down) {
      const i = BUTTONS.indexOf(button);
      if (i < 0) return;
      const bit = 0x8000 >> i;
      this.state = down ? this.state | bit : this.state & ~bit;
    }
    word() { return this.state & 0xfff0; }
    write(v) { this.latch = Boolean(v & 1); if (this.latch) this.shift = this.word(); }
    read() {
      if (this.latch) this.shift = this.word();
      const v = (this.shift >> 15) & 1;
      this.shift = ((this.shift << 1) | 1) & 0xffff;
      return v;
    }
  }

  const DMA_PATTERN = [[0], [0, 1], [0, 0], [0, 0, 1, 1], [0, 1, 2, 3], [0, 1, 0, 1], [0, 0], [0, 0, 1, 1]];

  class Machine {
    constructor(installed, rom, sampleRate = 44100) {
      this.installed = new Set(installed);
      this.has = (id) => this.installed.has(id);
      this.cart = rom ? parseRom(rom) : null;
      this.wram = new Uint8Array(131072);
      for (let i = 0; i < this.wram.length; i++) this.wram[i] = (i & 2) ? 0x55 : 0;  // contenu d'allumage typique
      this.wramAddr = 0;
      this.pads = [new Pad(), new Pad()];
      this.joy = [0, 0, 0, 0];
      this.ppu = new PPU16();
      this.apu = new APU16(sampleRate);
      this.mdr = 0;            // bus de données « flottant »
      this.hpos = 0; this.vpos = 0; this.frames = 0;
      this.hblankDone = false; this.irqDone = false;
      this.apuOwed = 0;
      this.nmitimen = 0; this.nmiFlag = false; this.irqFlag = false; this.htime = 0x1ff; this.vtime = 0x1ff;
      this.wrio = 0xff; this.mpyA = 0xff; this.dividend = 0xffff; this.rddiv = 0; this.rdmpy = 0;
      this.memsel = 0; this.autoJoy = 0; this.hdmaen = 0;
      this.dma = Array.from({ length: 8 }, () => ({ r: new Uint8Array(16).fill(0xff), doTransfer: false, done: true }));
      this.activity = Object.fromEntries(PARTS.map((p) => [p.id, 0]));
      this.noise = 0x1234;
      const self = this;
      this.ppu.dotSource = () => [self.hpos >> 2, self.vpos];
      this.cpu = new CPU65816({ read: (a) => self.read(a), write: (a, v) => self.write(a, v), io: () => { self.hpos += 6; self.apuOwed += 6; } });
      this.powered = this.has("power");
      this.clocked = this.powered && this.has("clock");
      this.signal = this.clocked && this.has("ppu2") && this.has("video");
      if (!this.has("vram")) this.scrambleVram();
      if (this.clocked && this.has("cpu")) this.cpu.reset();
    }
    get frame() { return this.ppu.frame; }
    scrambleVram() {
      let s = this.noise;
      for (let i = 0; i < this.ppu.vram.length; i++) { s = (s * 1103515245 + 12345) & 0x7fffffff; this.ppu.vram[i] = s >> 15; }
      this.noise = s;
    }

    // ---------- bus A (adresses 24 bits) ----------
    speed(a) {
      const bank = a >> 16, addr = a & 0xffff;
      if (bank >= 0x40 && bank < 0x80) return 8;
      if (bank >= 0xc0) return this.memsel ? 6 : 8;
      if (addr < 0x2000) return 8;
      if (addr < 0x4000) return 6;
      if (addr < 0x4200) return 12;
      if (addr < 0x6000) return 6;
      if (addr < 0x8000) return 8;
      return bank >= 0x80 && this.memsel ? 6 : 8;
    }
    romIndex(a) {
      const c = this.cart, bank = (a >> 16) & 0xff, addr = a & 0xffff;
      if (c.hiRom) {
        if ((bank & 0x7f) < 0x40 && addr < 0x8000) return -1;
        return (((bank & 0x3f) << 16) | addr) & c.mask;
      }
      if (addr < 0x8000 && !((bank & 0x7f) >= 0x40 && (bank & 0x7f) < 0x70)) return -1;
      return ((((bank & 0x7f) << 15) | (addr & 0x7fff))) & c.mask;
    }
    sramIndex(a) {
      const c = this.cart, bank = (a >> 16) & 0xff, addr = a & 0xffff;
      if (!c.sram.length) return -1;
      if (c.hiRom) {
        if ((bank & 0x7f) >= 0x20 && (bank & 0x7f) < 0x40 && addr >= 0x6000 && addr < 0x8000) {
          return ((((bank & 0x1f) << 13) | (addr - 0x6000))) % c.sram.length;
        }
        return -1;
      }
      if (((bank >= 0x70 && bank < 0x7e) || bank >= 0xf0) && addr < 0x8000) return (((bank & 0x0f) << 15) | addr) % c.sram.length;
      return -1;
    }
    cartOk() { return this.cart && this.has("slot") && this.has("cart"); }
    read(a) {
      const t = this.speed(a);
      this.hpos += t; this.apuOwed += t;
      return (this.mdr = this.peekBus(a, false));
    }
    write(a, v) {
      const t = this.speed(a);
      this.hpos += t; this.apuOwed += t;
      this.mdr = v;
      this.poke(a, v);
    }
    // Lecture sans compter de temps (aussi utilisée par le débogueur quand `quiet` est vrai : pas d'effet de bord)
    peekBus(a, quiet) {
      const bank = (a >> 16) & 0xff, addr = a & 0xffff;
      if (bank === 0x7e || bank === 0x7f) return this.wramRead(((bank & 1) << 16) | addr);
      if ((bank & 0x7f) < 0x40) {
        if (addr < 0x2000) return this.wramRead(addr);
        if (addr >= 0x2100 && addr < 0x2200) return quiet ? this.mdr : this.readB(addr & 0xff);
        if (addr >= 0x4000 && addr < 0x4400) return quiet ? this.mdr : this.readIo(addr);
      }
      if (!this.cartOk()) return this.mdr;
      const s = this.sramIndex(a);
      if (s >= 0) { this.activity.cart += 1; return this.cart.sram[s]; }
      const r = this.romIndex(a);
      if (r >= 0) { this.activity.cart += 1; this.activity.slot += 1; return this.cart.rom[r]; }
      return this.mdr;
    }
    peek(a) { return this.peekBus(a & 0xffffff, true); }
    poke(a, v) {
      const bank = (a >> 16) & 0xff, addr = a & 0xffff;
      if (bank === 0x7e || bank === 0x7f) { this.wramWrite(((bank & 1) << 16) | addr, v); return; }
      if ((bank & 0x7f) < 0x40) {
        if (addr < 0x2000) { this.wramWrite(addr, v); return; }
        if (addr >= 0x2100 && addr < 0x2200) { this.writeB(addr & 0xff, v); return; }
        if (addr >= 0x4000 && addr < 0x4400) { this.writeIo(addr, v); return; }
      }
      if (!this.cartOk()) return;
      const s = this.sramIndex(a);
      if (s >= 0) this.cart.sram[s] = v;
    }
    wramRead(i) {
      if (!this.has("wram")) return this.mdr;
      this.activity.wram += 1;
      return this.wram[i];
    }
    wramWrite(i, v) { if (this.has("wram")) { this.wram[i] = v; this.activity.wram += 1; } }

    // ---------- bus B ($2100-$21FF) : vidéo, son, port de la mémoire de travail ----------
    readB(reg) {
      if (reg >= 0x34 && reg < 0x40) {
        if (!this.has("ppu1") && reg < 0x3c) return this.mdr;
        if (!this.has("ppu2") && reg >= 0x3b) return this.mdr;
        this.activity.ppu1 += 1;
        return this.ppu.read(reg, this.mdr);
      }
      if (reg >= 0x40 && reg < 0x80) {
        if (!this.has("sound")) return this.mdr;
        this.syncApu();
        this.activity.sound += 1;
        return this.apu.cpuRead(reg & 3);
      }
      if (reg === 0x80) { const v = this.wramRead(this.wramAddr); this.wramAddr = (this.wramAddr + 1) & 0x1ffff; return v; }
      return this.mdr;
    }
    writeB(reg, v) {
      if (reg < 0x34) {
        const chip = reg >= 0x21 || reg === 0x00 ? "ppu2" : "ppu1";
        if (!this.has(chip)) return;
        this.activity[chip] += 1;
        if ((reg === 0x18 || reg === 0x19) && !this.has("vram")) return;
        this.ppu.write(reg, v);
        return;
      }
      if (reg >= 0x40 && reg < 0x80) {
        if (!this.has("sound")) return;
        this.syncApu();
        this.activity.sound += 1;
        this.apu.cpuWrite(reg & 3, v);
        return;
      }
      switch (reg) {
        case 0x80: this.wramWrite(this.wramAddr, v); this.wramAddr = (this.wramAddr + 1) & 0x1ffff; break;
        case 0x81: this.wramAddr = (this.wramAddr & 0x1ff00) | v; break;
        case 0x82: this.wramAddr = (this.wramAddr & 0x100ff) | (v << 8); break;
        case 0x83: this.wramAddr = (this.wramAddr & 0x0ffff) | ((v & 1) << 16); break;
        default: break;
      }
    }

    // ---------- registres internes du processeur ($4016-$4017, $4200-$421F, $4300-$437F) ----------
    readIo(addr) {
      if (addr === 0x4016 || addr === 0x4017) {
        if (!this.has("pads")) return this.mdr & 0xfc;
        this.activity.pads += 1;
        return (this.mdr & 0xfc) | this.pads[addr - 0x4016].read() | (addr === 0x4017 ? 0x1c : 0);
      }
      if (addr >= 0x4300 && addr < 0x4380) {
        const ch = this.dma[(addr >> 4) & 7], r = addr & 15;
        return r < 11 ? ch.r[r] : this.mdr;
      }
      switch (addr) {
        case 0x4210: { const v = (this.nmiFlag ? 0x80 : 0) | (this.mdr & 0x70) | 2; this.nmiFlag = false; return v; }
        case 0x4211: { const v = (this.irqFlag ? 0x80 : 0) | (this.mdr & 0x7f); this.irqFlag = false; this.cpu.irqLine = false; return v; }
        case 0x4212: {
          const vb = this.vpos >= 225, hb = this.hpos >= HBLANK || this.hpos < 4;
          return (vb ? 0x80 : 0) | (hb ? 0x40 : 0) | (this.mdr & 0x3e) | (this.autoJoy > 0 ? 1 : 0);
        }
        case 0x4213: return this.wrio;
        case 0x4214: return this.rddiv & 0xff;
        case 0x4215: return this.rddiv >> 8;
        case 0x4216: return this.rdmpy & 0xff;
        case 0x4217: return this.rdmpy >> 8;
        default:
          if (addr >= 0x4218 && addr < 0x4220) { const w = this.joy[(addr - 0x4218) >> 1]; return addr & 1 ? w >> 8 : w & 0xff; }
          return this.mdr;
      }
    }
    writeIo(addr, v) {
      if (addr === 0x4016) { this.pads[0].write(v); this.pads[1].write(v); return; }
      if (addr >= 0x4300 && addr < 0x4380) { const r = addr & 15; if (r < 11) this.dma[(addr >> 4) & 7].r[r] = v; return; }
      switch (addr) {
        case 0x4200:
          if ((v & 0x80) && !(this.nmitimen & 0x80) && this.nmiFlag) this.cpu.nmiPending = true;
          this.nmitimen = v;
          if (!(v & 0x30)) { this.irqFlag = false; this.cpu.irqLine = false; }
          break;
        case 0x4201: if ((this.wrio & 0x80) && !(v & 0x80) && this.has("ppu2")) this.ppu.latchCounters(); this.wrio = v; break;
        case 0x4202: this.mpyA = v; break;
        case 0x4203: this.rdmpy = this.mpyA * v; this.rddiv = v; break;
        case 0x4204: this.dividend = (this.dividend & 0xff00) | v; break;
        case 0x4205: this.dividend = (this.dividend & 0xff) | (v << 8); break;
        case 0x4206:
          if (v === 0) { this.rddiv = 0xffff; this.rdmpy = this.dividend; }
          else { this.rddiv = Math.floor(this.dividend / v); this.rdmpy = this.dividend % v; }
          break;
        case 0x4207: this.htime = (this.htime & 0x100) | v; break;
        case 0x4208: this.htime = (this.htime & 0xff) | ((v & 1) << 8); break;
        case 0x4209: this.vtime = (this.vtime & 0x100) | v; break;
        case 0x420a: this.vtime = (this.vtime & 0xff) | ((v & 1) << 8); break;
        case 0x420b: this.runDma(v); break;
        case 0x420c: this.hdmaen = v; break;
        case 0x420d: this.memsel = v & 1; break;
        default: break;
      }
    }

    // ---------- DMA et HDMA ----------
    // Accès sans compter de temps (les transferts comptent 8 cycles par octet à part).
    busA(a) { return this.peekBus(a, false); }
    transferByte(ch, aAddr, bReg) {
      if (ch.r[0] & 0x80) {  // B → A
        const v = this.readB(bReg);
        const bank = (aAddr >> 16) & 0xff, off = aAddr & 0xffff;
        const isReg = (bank & 0x7f) < 0x40 && ((off >= 0x2100 && off < 0x2200) || (off >= 0x4000 && off < 0x4400));
        if (!isReg) this.poke(aAddr, v);
      } else {
        const bank = (aAddr >> 16) & 0xff, off = aAddr & 0xffff;
        const isReg = (bank & 0x7f) < 0x40 && ((off >= 0x2100 && off < 0x2200) || (off >= 0x4000 && off < 0x4400));
        this.writeB(bReg, isReg ? this.mdr : this.busA(aAddr));
      }
      this.hpos += 8; this.apuOwed += 8;
    }
    runDma(mask) {
      if (!this.has("cpu")) return;
      for (let i = 0; i < 8; i++) {
        if (!(mask & (1 << i))) continue;
        const ch = this.dma[i], r = ch.r;
        const pattern = DMA_PATTERN[r[0] & 7], fixed = (r[0] & 0x08) !== 0, dec = (r[0] & 0x10) !== 0;
        let addr = r[2] | (r[3] << 8), count = r[5] | (r[6] << 8) || 0x10000, k = 0;
        this.hpos += 8; this.apuOwed += 8;
        while (count > 0) {
          this.transferByte(ch, (r[4] << 16) | addr, (r[1] + pattern[k & (pattern.length - 1)]) & 0xff);
          if (!fixed) addr = (addr + (dec ? -1 : 1)) & 0xffff;
          k += 1; count -= 1;
        }
        r[2] = addr & 0xff; r[3] = addr >> 8; r[5] = 0; r[6] = 0;
        this.activity.cpu += 1;
      }
    }
    hdmaInit() {
      for (let i = 0; i < 8; i++) {
        const ch = this.dma[i], r = ch.r;
        ch.done = !(this.hdmaen & (1 << i));
        if (ch.done) continue;
        r[8] = r[2]; r[9] = r[3];
        this.hdmaLoad(ch);
      }
    }
    hdmaTable(ch) {
      const r = ch.r, a = r[8] | (r[9] << 8);
      const v = this.busA((r[4] << 16) | a);
      const n = (a + 1) & 0xffff; r[8] = n & 0xff; r[9] = n >> 8;
      return v;
    }
    hdmaLoad(ch) {
      const r = ch.r;
      r[10] = this.hdmaTable(ch);
      if (r[0] & 0x40) { r[5] = this.hdmaTable(ch); r[6] = this.hdmaTable(ch); }
      if (r[10] === 0) ch.done = true;
      ch.doTransfer = true;
    }
    hdmaLine() {
      if (!this.has("cpu")) return;
      for (let i = 0; i < 8; i++) {
        const ch = this.dma[i], r = ch.r;
        if (ch.done || !(this.hdmaen & (1 << i))) continue;
        if (ch.doTransfer) {
          const pattern = DMA_PATTERN[r[0] & 7];
          for (let k = 0; k < pattern.length; k++) {
            let src;
            if (r[0] & 0x40) { const a = r[5] | (r[6] << 8); src = (r[7] << 16) | a; const n = (a + 1) & 0xffff; r[5] = n & 0xff; r[6] = n >> 8; }
            else { const a = r[8] | (r[9] << 8); src = (r[4] << 16) | a; const n = (a + 1) & 0xffff; r[8] = n & 0xff; r[9] = n >> 8; }
            this.writeB((r[1] + pattern[k]) & 0xff, this.busA(src));
            this.hpos += 8; this.apuOwed += 8;
          }
        }
        r[10] = (r[10] - 1) & 0xff;
        ch.doTransfer = (r[10] & 0x80) !== 0;
        if ((r[10] & 0x7f) === 0) this.hdmaLoad(ch);
      }
    }

    // ---------- module son ----------
    syncApu() {
      const spc = (this.apuOwed * SPC_HZ) / MASTER_HZ;
      if (spc < 2) return;
      this.apuOwed = 0;
      if (!this.has("sound")) return;
      const left = this.apu.run(spc);
      this.apuOwed = (left * MASTER_HZ) / SPC_HZ;  // ≤ 0 : avance déjà faite
    }

    // ---------- déroulé d'une ligne ----------
    catchUp() {
      for (;;) {
        // interruption programmée (position horizontale et/ou ligne)
        const hEn = (this.nmitimen & 0x10) !== 0, vEn = (this.nmitimen & 0x20) !== 0;
        if ((hEn || vEn) && !this.irqDone && (!vEn || this.vpos === this.vtime)) {
          const target = hEn ? this.htime * 4 + 14 : 10;
          if (this.hpos >= target && (!hEn || this.htime < 340)) {
            this.irqDone = true; this.irqFlag = true; this.cpu.irqLine = true;
            continue;
          }
        }
        if (!this.hblankDone && this.hpos >= HBLANK) { this.hblankDone = true; this.hblank(); continue; }
        if (this.hpos >= LINE) { this.hpos -= LINE; this.newLine(); continue; }
        return;
      }
    }
    hblank() {
      const v = this.vpos;
      if (v >= 1 && v <= 224) {
        this.ppu.line = v;
        if (this.has("ppu1") && this.has("ppu2")) this.ppu.renderLine(v);
        else if (this.has("ppu2")) this.backdropLine(v);
      }
      if (v <= 224) this.hdmaLine();
    }
    backdropLine(v) {
      const p = this.ppu, row = (v - 1 + 8) * 256;
      const c = p.forceBlank ? 0xff000000 : root.AetherPPU16.LUT[p.brightness][p.cgram[0] & 0x7fff];
      p.frame.fill(c, row, row + 256);
    }
    newLine() {
      this.syncApu();
      this.vpos += 1;
      this.hblankDone = false; this.irqDone = false;
      if (this.autoJoy > 0) this.autoJoy -= 1;
      if (this.vpos === 225) {
        this.nmiFlag = true;
        if (this.nmitimen & 0x80) this.cpu.nmiPending = true;
        if (!this.ppu.forceBlank) this.ppu.oamAddr = this.ppu.oamReload;
        if (this.nmitimen & 1) this.readPads();
        this.frameDone = true;
      }
      if (this.vpos >= LINES) {
        this.vpos = 0; this.frames += 1;
        this.nmiFlag = false;
        this.ppu.rangeOver = false; this.ppu.timeOver = false;
        this.hdmaInit();
      }
      this.ppu.line = this.vpos;
    }
    readPads() {
      this.autoJoy = 3;
      if (!this.has("pads")) { this.joy = [0, 0, 0, 0]; return; }
      this.joy = [this.pads[0].word(), this.pads[1].word(), 0, 0];
      this.pads[0].shift = 0xffff; this.pads[1].shift = 0xffff;
      this.activity.pads += 1;
    }

    // Une image complète (262 lignes). Rend false si la machine ne peut pas tourner.
    runFrame() {
      for (const k in this.activity) this.activity[k] = 0;
      if (!this.clocked) return false;
      if (!this.has("vram")) this.scrambleVram();
      this.frameDone = false;
      const hasCpu = this.has("cpu");
      let guard = 0;
      while (!this.frameDone && guard < LINE * LINES * 2) {
        const before = this.hpos;
        if (hasCpu && !this.cpu.stopped) this.cpu.step(); else this.hpos += 40;
        guard += Math.max(6, this.hpos - before);
        if (!hasCpu) this.apuOwed += 40;
        this.catchUp();
      }
      this.activity.clock = 1; this.activity.power = 1;
      if (this.has("ppu1")) this.activity.ppu1 += 1;
      if (this.has("ppu2")) this.activity.ppu2 += 1;
      if (this.has("sound")) this.activity.sound += 1;
      this.activity.video = this.signal ? 1 : 0;
      if (hasCpu) this.activity.cpu += 1;
      return true;
    }
    stepInstruction() {
      if (!this.clocked || !this.has("cpu")) return;
      this.cpu.step();
      this.catchUp();
    }
    takeAudio() { return this.apu.take(); }
    press(player, button, down) { this.pads[player].press(button, down); }
  }

  root.AetherC16 = { Machine, PARTS, BUTTONS, parseRom, MASTER_HZ };
})(typeof window !== "undefined" ? window : globalThis);
