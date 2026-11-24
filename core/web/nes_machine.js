"use strict";
// Carte mère de la console 8 bits de l'atelier : bus du processeur et bus vidéo, décodage d'adresses, cartouche
// iNES (mappeur 0), manettes, son (APU : 2 voies carrées, triangle, bruit) et copie OAM par DMA.
//
// La carte se monte composant par composant (`PARTS`). Ce qui manque n'est pas « interdit » : la machine tourne
// quand même et montre la vraie panne (bus flottant, motifs brouillés, plantage, neige à l'écran…). C'est le
// cœur pédagogique de l'atelier.
(function (root) {
  const { CPU6502 } = root.AetherCPU;
  const { PPU2C02 } = root.AetherPPU;

  // Composants de la carte mère : rôle, vraie référence, panne quand il manque.
  const PARTS = [
    { id: "power", label: "Alimentation 5 V", ref: "régulateur 7805", socket: "power",
      role: "Transforme le courant de l'adaptateur en 5 V stables pour toutes les puces.",
      missing: "Rien ne s'allume : aucune puce n'est alimentée." },
    { id: "clock", label: "Quartz 21,477 MHz", ref: "oscillateur NTSC", socket: "clock",
      role: "Donne le rythme : divisé par 12 pour le processeur (1,79 MHz) et par 4 pour la vidéo (5,37 MHz).",
      missing: "Sans horloge, aucune puce n'avance : pas d'image (neige), pas de programme." },
    { id: "cpu", label: "Processeur 6502 + son", ref: "type RP2A03", socket: "dip40-cpu",
      role: "Exécute le programme de la cartouche, pilote la vidéo, lit les manettes et produit le son.",
      missing: "La vidéo tourne seule : écran uni de la couleur de fond, rien ne bouge." },
    { id: "ram", label: "Mémoire de travail 2 Ko", ref: "SRAM 6116", socket: "dip24-ram",
      role: "Variables du jeu et pile du processeur ($0000-$07FF, recopiée jusqu'à $1FFF).",
      missing: "Le programme lit du bruit à la place de ses variables : il plante vite (la pile est perdue)." },
    { id: "decoder", label: "Décodeur d'adresses", ref: "74LS139", socket: "dip16-dec",
      role: "Regarde les lignes d'adresse A13-A15 et choisit qui répond : mémoire, vidéo ou cartouche.",
      missing: "Personne n'est sélectionné : le processeur ne lit que du bruit et démarre n'importe où." },
    { id: "ppu", label: "Processeur vidéo", ref: "type RP2C02", socket: "dip40-ppu",
      role: "Dessine 256×240 points, 60 fois par seconde : fonds en tuiles et 64 sprites.",
      missing: "Pas de signal vidéo : la télé affiche de la neige. Le programme attend une image qui ne vient jamais." },
    { id: "vram", label: "Mémoire vidéo 2 Ko", ref: "SRAM 6116", socket: "dip24-vram",
      role: "Les deux écrans de fond (quelles tuiles où, et leurs palettes).",
      missing: "Les écrans de fond lisent un bus flottant : motifs répétés à la place du décor." },
    { id: "latch", label: "Verrou d'adresses vidéo", ref: "74LS373", socket: "dip20-latch",
      role: "Le processeur vidéo envoie adresse puis donnée sur les mêmes fils : le verrou garde l'adresse.",
      missing: "Les adresses vidéo sont mélangées aux données : tuiles brouillées, image en morceaux." },
    { id: "slot", label: "Connecteur de cartouche", ref: "72 broches", socket: "slot",
      role: "Relie la cartouche aux deux bus (programme côté processeur, motifs côté vidéo).",
      missing: "La cartouche n'est reliée à rien : pas de programme ni de motifs." },
    { id: "cart", label: "Cartouche", ref: "ROM programme + ROM motifs", socket: "cart",
      role: "Le jeu : jusqu'à 32 Ko de programme et 8 Ko de motifs graphiques (mappeur 0).",
      missing: "Sans cartouche, le processeur lit un vecteur de démarrage au hasard." },
    { id: "pads", label: "Ports de manettes", ref: "2 × 7 broches", socket: "pads",
      role: "Les manettes envoient leurs 8 boutons un par un (registre à décalage 4021).",
      missing: "Les boutons ne répondent pas." },
    { id: "video", label: "Sortie vidéo composite", ref: "modulateur", socket: "video",
      role: "Mélange l'image et la synchro en un seul signal pour la télé.",
      missing: "La console tourne mais la télé ne reçoit rien : neige." },
  ];

  // ---------- cartouche iNES ----------
  function parseRom(bytes) {
    const b = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    if (b.length < 16 || b[0] !== 0x4e || b[1] !== 0x45 || b[2] !== 0x53 || b[3] !== 0x1a) {
      throw new Error("ce n'est pas une cartouche iNES (.nes)");
    }
    const prgSize = b[4] * 16384, chrSize = b[5] * 8192;
    const mapper = (b[6] >> 4) | (b[7] & 0xf0);
    if (b[6] & 0x04) throw new Error("cartouche avec « trainer » : non prise en charge");
    if (mapper !== 0) throw new Error(`mappeur ${mapper} : seule la carte de cartouche la plus simple (mappeur 0, « NROM ») est câblée pour l'instant`);
    if (!prgSize || prgSize > 32768) throw new Error("programme de 16 ou 32 Ko attendu");
    if (b.length < 16 + prgSize + chrSize) throw new Error("fichier tronqué");
    const prg = b.slice(16, 16 + prgSize);
    const chrRam = chrSize === 0;
    const chr = chrRam ? new Uint8Array(8192) : b.slice(16 + prgSize, 16 + prgSize + chrSize);
    return { prg, chr, chrRam, mirror: b[6] & 0x08 ? "four" : b[6] & 1 ? "vertical" : "horizontal", mapper };
  }

  // ---------- manette (registre à décalage) ----------
  const BUTTONS = ["A", "B", "Select", "Start", "Up", "Down", "Left", "Right"];
  class Pad {
    constructor() { this.state = 0; this.shift = 0; this.strobe = false; }
    press(button, down) {
      const bit = 1 << BUTTONS.indexOf(button);
      if (bit < 1) return;
      this.state = down ? this.state | bit : this.state & ~bit;
    }
    write(v) { this.strobe = Boolean(v & 1); if (this.strobe) this.shift = this.state; }
    read() {
      if (this.strobe) return this.state & 1;
      const bit = this.shift & 1;
      this.shift = (this.shift >> 1) | 0x80;
      return bit;
    }
  }

  // ---------- son (APU) ----------
  const LENGTHS = [10, 254, 20, 2, 40, 4, 80, 6, 160, 8, 60, 10, 14, 12, 26, 14, 12, 16, 24, 18, 48, 20, 96, 22, 192, 24, 72, 26, 16, 28, 32, 30];
  const DUTY = [[0, 1, 0, 0, 0, 0, 0, 0], [0, 1, 1, 0, 0, 0, 0, 0], [0, 1, 1, 1, 1, 0, 0, 0], [1, 0, 0, 1, 1, 1, 1, 1]];
  const TRI = [15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15];
  const NOISE = [4, 8, 16, 32, 64, 96, 128, 160, 202, 254, 380, 508, 762, 1016, 2034, 4068];
  class Pulse {
    constructor(second) { this.second = second; this.enabled = false; this.duty = 0; this.halt = false; this.constant = false;
      this.volume = 0; this.timer = 0; this.counter = 0; this.length = 0; this.step = 0;
      this.envStart = false; this.envDivider = 0; this.envDecay = 0;
      this.sweepOn = false; this.sweepPeriod = 0; this.sweepNeg = false; this.sweepShift = 0; this.sweepDivider = 0; this.sweepReload = false; }
    write(reg, v) {
      switch (reg) {
        case 0: this.duty = v >> 6; this.halt = Boolean(v & 0x20); this.constant = Boolean(v & 0x10); this.volume = v & 15; break;
        case 1: this.sweepOn = Boolean(v & 0x80); this.sweepPeriod = (v >> 4) & 7; this.sweepNeg = Boolean(v & 8); this.sweepShift = v & 7; this.sweepReload = true; break;
        case 2: this.timer = (this.timer & 0x700) | v; break;
        default: this.timer = (this.timer & 0xff) | ((v & 7) << 8); if (this.enabled) this.length = LENGTHS[v >> 3]; this.step = 0; this.envStart = true;
      }
    }
    target() { const change = this.timer >> this.sweepShift; return this.sweepNeg ? this.timer - change - (this.second ? 0 : 1) : this.timer + change; }
    clockTimer() { if (this.counter === 0) { this.counter = this.timer; this.step = (this.step + 1) & 7; } else this.counter -= 1; }
    clockEnvelope() {
      if (this.envStart) { this.envStart = false; this.envDecay = 15; this.envDivider = this.volume; return; }
      if (this.envDivider > 0) { this.envDivider -= 1; return; }
      this.envDivider = this.volume;
      if (this.envDecay > 0) this.envDecay -= 1; else if (this.halt) this.envDecay = 15;
    }
    clockLength() {
      if (!this.halt && this.length > 0) this.length -= 1;
      const t = this.target();
      if (this.sweepDivider === 0 && this.sweepOn && this.sweepShift && this.timer >= 8 && t <= 0x7ff) this.timer = t;
      if (this.sweepDivider === 0 || this.sweepReload) { this.sweepDivider = this.sweepPeriod; this.sweepReload = false; } else this.sweepDivider -= 1;
    }
    output() {
      if (!this.length || this.timer < 8 || this.target() > 0x7ff || !DUTY[this.duty][this.step]) return 0;
      return this.constant ? this.volume : this.envDecay;
    }
  }
  class Triangle {
    constructor() { this.enabled = false; this.control = false; this.linearReload = 0; this.linear = 0; this.reload = false;
      this.timer = 0; this.counter = 0; this.length = 0; this.step = 0; }
    write(reg, v) {
      if (reg === 0) { this.control = Boolean(v & 0x80); this.linearReload = v & 0x7f; }
      else if (reg === 2) this.timer = (this.timer & 0x700) | v;
      else if (reg === 3) { this.timer = (this.timer & 0xff) | ((v & 7) << 8); if (this.enabled) this.length = LENGTHS[v >> 3]; this.reload = true; }
    }
    clockTimer() {
      if (this.counter === 0) { this.counter = this.timer; if (this.length && this.linear && this.timer > 1) this.step = (this.step + 1) & 31; }
      else this.counter -= 1;
    }
    clockLinear() { if (this.reload) this.linear = this.linearReload; else if (this.linear) this.linear -= 1; if (!this.control) this.reload = false; }
    clockLength() { if (!this.control && this.length) this.length -= 1; }
    output() { return TRI[this.step]; }
  }
  class Noise {
    constructor() { this.enabled = false; this.halt = false; this.constant = false; this.volume = 0; this.mode = false;
      this.period = 4; this.counter = 0; this.length = 0; this.shift = 1; this.envStart = false; this.envDivider = 0; this.envDecay = 0; }
    write(reg, v) {
      if (reg === 0) { this.halt = Boolean(v & 0x20); this.constant = Boolean(v & 0x10); this.volume = v & 15; }
      else if (reg === 2) { this.mode = Boolean(v & 0x80); this.period = NOISE[v & 15]; }
      else if (reg === 3) { if (this.enabled) this.length = LENGTHS[v >> 3]; this.envStart = true; }
    }
    clockTimer() {
      if (this.counter === 0) {
        this.counter = this.period;
        const fb = (this.shift & 1) ^ ((this.shift >> (this.mode ? 6 : 1)) & 1);
        this.shift = (this.shift >> 1) | (fb << 14);
      } else this.counter -= 1;
    }
    clockEnvelope() { Pulse.prototype.clockEnvelope.call(this); }
    clockLength() { if (!this.halt && this.length) this.length -= 1; }
    output() { return !this.length || (this.shift & 1) ? 0 : this.constant ? this.volume : this.envDecay; }
  }
  class APU {
    constructor(sampleRate = 44100) {
      this.p1 = new Pulse(false); this.p2 = new Pulse(true); this.tri = new Triangle(); this.noise = new Noise();
      this.cycle = 0; this.frameMode = 0; this.frameStep = 0; this.frameCounter = 0; this.irqInhibit = true;
      this.sampleRate = sampleRate; this.samplePos = 0; this.samples = []; this.lowpass = 0; this.highpass = 0; this.prev = 0;
    }
    write(addr, v) {
      if (addr < 0x4004) this.p1.write(addr - 0x4000, v);
      else if (addr < 0x4008) this.p2.write(addr - 0x4004, v);
      else if (addr < 0x400c) this.tri.write(addr - 0x4008, v);
      else if (addr < 0x4010) this.noise.write(addr - 0x400c, v);
      else if (addr === 0x4015) {
        for (const [ch, bit] of [[this.p1, 1], [this.p2, 2], [this.tri, 4], [this.noise, 8]]) {
          ch.enabled = Boolean(v & bit);
          if (!ch.enabled) ch.length = 0;
        }
      } else if (addr === 0x4017) {
        this.frameMode = v >> 7; this.irqInhibit = Boolean(v & 0x40); this.frameCounter = 0; this.frameStep = 0;
        if (this.frameMode) { this.quarter(); this.half(); }
      }
    }
    status() {
      return (this.p1.length ? 1 : 0) | (this.p2.length ? 2 : 0) | (this.tri.length ? 4 : 0) | (this.noise.length ? 8 : 0);
    }
    quarter() { this.p1.clockEnvelope(); this.p2.clockEnvelope(); this.noise.clockEnvelope(); this.tri.clockLinear(); }
    half() { this.p1.clockLength(); this.p2.clockLength(); this.tri.clockLength(); this.noise.clockLength(); }
    // Avance de `cycles` cycles processeur ; produit des échantillons à `sampleRate`.
    run(cycles) {
      for (let i = 0; i < cycles; i++) {
        this.tri.clockTimer();
        if (this.cycle & 1) { this.p1.clockTimer(); this.p2.clockTimer(); this.noise.clockTimer(); }
        this.cycle += 1;
        // séquenceur de trames : ~240 Hz (7457 cycles)
        this.frameCounter += 1;
        if (this.frameCounter >= 7457) {
          this.frameCounter = 0;
          const steps = this.frameMode ? 5 : 4;
          const s = this.frameStep;
          if (!(this.frameMode && s === 3)) this.quarter();
          if (s === 1 || s === (this.frameMode ? 4 : 3)) this.half();
          this.frameStep = (s + 1) % steps;
        }
        this.samplePos += this.sampleRate;
        if (this.samplePos >= 1789773) {
          this.samplePos -= 1789773;
          const pulse = this.p1.output() + this.p2.output();
          const pulseOut = pulse ? 95.88 / (8128 / pulse + 100) : 0;
          const tnd = this.tri.output() / 8227 + this.noise.output() / 12241;
          const tndOut = tnd ? 159.79 / (1 / tnd + 100) : 0;
          let s = pulseOut + tndOut;
          // filtres de la sortie (passe-haut 90 Hz, passe-bas ~14 kHz) comme sur la console
          this.highpass = 0.996 * (this.highpass + s - this.prev); this.prev = s;
          this.lowpass += 0.815 * (this.highpass - this.lowpass);
          this.samples.push(this.lowpass);
        }
      }
    }
    take() { const out = this.samples; this.samples = []; return out; }
  }

  // ---------- la machine ----------
  class Machine {
    constructor(installed, rom) {
      this.installed = new Set(installed);
      this.has = (id) => this.installed.has(id);
      this.cart = rom ? parseRom(rom) : null;
      this.ram = new Uint8Array(2048);
      this.vram = new Uint8Array(2048);
      for (let i = 0; i < 2048; i++) { this.ram[i] = (i & 4) ? 0xff : 0; }  // contenu d'allumage typique
      this.pads = [new Pad(), new Pad()];
      this.apu = new APU();
      this.cpuBus = 0;      // dernière valeur vue sur le bus de données du processeur (bus « flottant »)
      this.ppuBus = 0;      // idem sur le bus vidéo
      this.activity = Object.fromEntries(PARTS.map((p) => [p.id, 0]));
      const self = this;
      this.ppu = new PPU2C02({ vread: (a) => self.vread(a), vwrite: (a, v) => self.vwrite(a, v) });
      this.cpu = new CPU6502({ read: (a) => self.read(a), write: (a, v) => self.write(a, v) });
      this.powered = this.has("power");
      this.clocked = this.powered && this.has("clock");
      this.signal = this.clocked && this.has("ppu") && this.has("video");
      if (this.clocked && this.has("cpu")) this.cpu.powerOn();
    }
    // Ce que voit le processeur, selon les puces présentes.
    selected(addr) {
      if (!this.has("decoder")) return addr >= 0x4000 && addr < 0x4020 ? "io" : null;  // les E/S sont dans le 2A03
      if (addr < 0x2000) return this.has("ram") ? "ram" : null;
      if (addr < 0x4000) return this.has("ppu") ? "ppu" : null;
      if (addr < 0x4020) return "io";
      if (addr >= 0x8000) return this.has("slot") && this.has("cart") && this.cart ? "cart" : null;
      return null;
    }
    read(addr) {
      const who = this.selected(addr);
      let v = this.cpuBus;
      if (who === "ram") { v = this.ram[addr & 0x7ff]; this.activity.ram += 1; }
      else if (who === "ppu") { v = this.ppu.readRegister(addr); this.activity.ppu += 1; }
      else if (who === "cart") { v = this.cart.prg[(addr - 0x8000) % this.cart.prg.length]; this.activity.cart += 1; this.activity.slot += 1; }
      else if (who === "io") {
        if (addr === 0x4015) v = (this.cpuBus & 0x20) | this.apu.status();
        else if (addr === 0x4016 || addr === 0x4017) {
          v = this.cpuBus & 0xe0;
          if (this.has("pads")) { v |= this.pads[addr - 0x4016].read(); this.activity.pads += 1; }
        }
      }
      this.activity.cpu += 1;
      if (this.has("decoder") && who !== "io") this.activity.decoder += 1;
      this.cpuBus = v;
      return v;
    }
    write(addr, v) {
      this.cpuBus = v;
      const who = this.selected(addr);
      this.activity.cpu += 1;
      if (who === "ram") { this.ram[addr & 0x7ff] = v; this.activity.ram += 1; }
      else if (who === "ppu") { this.ppu.writeRegister(addr, v); this.activity.ppu += 1; }
      else if (who === "io") {
        if (addr === 0x4014) this.dma(v);
        else if (addr === 0x4016) { this.pads[0].write(v); this.pads[1].write(v); }
        else this.apu.write(addr, v);
      }
      if (this.has("decoder") && who !== "io") this.activity.decoder += 1;
    }
    dma(page) {
      for (let i = 0; i < 256; i++) {
        const v = this.read((page << 8) | i);
        if (this.has("ppu")) this.ppu.writeRegister(4, v);
      }
      this.cpu.stall += 513 + (this.cpu.cycles & 1);
    }
    // Bus vidéo : motifs (cartouche) en $0000-$1FFF, écrans de fond (VRAM) en $2000-$2FFF.
    vread(addr) {
      addr &= 0x3fff;
      if (!this.has("latch")) addr = (addr & 0xff00) | this.ppuBus;  // l'adresse basse est restée « donnée »
      let v;
      if (addr < 0x2000) {
        if (this.has("slot") && this.has("cart") && this.cart) { v = this.cart.chr[addr]; this.activity.cart += 1; }
        else v = addr & 0xff;
      } else {
        const index = this.ntIndex(addr);
        if (this.has("vram") && index >= 0) { v = this.vram[index]; this.activity.vram += 1; } else v = addr & 0xff;
      }
      this.activity.latch += this.has("latch") ? 1 : 0;
      this.ppuBus = v;
      return v;
    }
    vwrite(addr, v) {
      addr &= 0x3fff;
      if (!this.has("latch")) addr = (addr & 0xff00) | this.ppuBus;
      this.ppuBus = v;
      if (addr < 0x2000) { if (this.cart && this.cart.chrRam && this.has("slot") && this.has("cart")) this.cart.chr[addr] = v; return; }
      const index = this.ntIndex(addr);
      if (this.has("vram") && index >= 0) { this.vram[index] = v; this.activity.vram += 1; }
    }
    // Miroir des écrans de fond : câblé sur la cartouche (A10 ou A11 vers la VRAM).
    ntIndex(addr) {
      const a = (addr - 0x2000) & 0x0fff;
      const mirror = this.cart && this.has("cart") && this.has("slot") ? this.cart.mirror : "horizontal";
      const table = a >> 10;
      const bank = mirror === "vertical" ? table & 1 : (table >> 1) & 1;
      return bank * 0x400 + (a & 0x3ff);
    }

    // Une image complète (~29 780 cycles processeur). Rend false si la machine ne peut pas tourner.
    runFrame() {
      for (const k in this.activity) this.activity[k] = 0;
      if (!this.clocked) return false;
      const hasCpu = this.has("cpu"), hasPpu = this.has("ppu");
      let budget = 29781;
      if (!hasCpu) {
        if (hasPpu) for (let i = 0; i < budget * 3; i++) this.ppu.tick();
        return true;
      }
      this.ppu.frameReady = false;
      while (budget > 0) {
        const cycles = this.cpu.step();
        budget -= cycles;
        this.apu.run(cycles);
        if (hasPpu) {
          for (let i = 0; i < cycles * 3; i++) if (this.ppu.tick()) this.cpu.nmi = true;
        }
      }
      this.activity.clock = 1; this.activity.power = 1;
      if (hasPpu) this.activity.ppu += 1;  // il dessine en continu, même sans accès du processeur
      this.activity.video = this.signal ? 1 : 0;
      return true;
    }
    press(player, button, down) { this.pads[player].press(button, down); }
  }

  root.AetherNES = { Machine, PARTS, BUTTONS, parseRom };
})(typeof window !== "undefined" ? window : globalThis);
