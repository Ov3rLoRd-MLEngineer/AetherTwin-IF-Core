// Atelier circuits : sortie son de la console 8 bits (fil audio du navigateur).
// Le fil principal envoie des blocs d'échantillons (Float32Array) ; on les lit dans une file circulaire.
// Si la file se vide, on tient le dernier niveau (pas de clic) ; si elle déborde, on jette le plus ancien.
class AetherConsoleSound extends AudioWorkletProcessor {
  constructor() {
    super();
    this.size = 1 << 14;
    this.ring = new Float32Array(this.size);
    this.read = 0;
    this.write = 0;
    this.last = 0;
    this.port.onmessage = (event) => {
      const data = event.data;
      if (data === "flush") { this.read = this.write; return; }
      const mask = this.size - 1;
      for (let i = 0; i < data.length; i += 1) {
        this.ring[this.write & mask] = data[i];
        this.write += 1;
      }
      if (this.write - this.read > this.size - 1) this.read = this.write - (this.size >> 1);
    };
  }

  process(inputs, outputs) {
    const out = outputs[0][0];
    if (!out) return true;
    const mask = this.size - 1;
    for (let n = 0; n < out.length; n += 1) {
      if (this.read < this.write) { this.last = this.ring[this.read & mask]; this.read += 1; }
      else this.last *= 0.995;
      out[n] = this.last;
    }
    for (let c = 1; c < outputs[0].length; c += 1) outputs[0][c].set(out);
    return true;
  }
}
registerProcessor("aether-console-sound", AetherConsoleSound);
