// Studio audio Æther : changement de hauteur en direct (modulateur vocal), dans le fil audio du navigateur.
// Ligne à retard à deux têtes de lecture qui glissent (« granulaire ») avec fondu enchaîné : latence ≈ 40 ms,
// durée inchangée, même réglage « pitch » (demi-tons, -12 … +12) que les effets du serveur (modules/voice/effects.py).
class AetherPitchShifter extends AudioWorkletProcessor {
  static get parameterDescriptors() {
    return [{ name: "semitones", defaultValue: 0, minValue: -12, maxValue: 12, automationRate: "k-rate" }];
  }

  constructor() {
    super();
    this.size = 1 << 15;                       // tampon circulaire (≈ 0,7 s à 48 kHz)
    this.buffer = new Float32Array(this.size);
    this.write = 0;
    this.phase = 0;
    this.window = Math.round(sampleRate * 0.04);  // fenêtre de 40 ms
  }

  read(position) {
    const mask = this.size - 1;
    const i = Math.floor(position);
    const frac = position - i;
    const a = this.buffer[i & mask];
    const b = this.buffer[(i + 1) & mask];
    return a + (b - a) * frac;
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    const output = outputs[0];
    if (!output.length) return true;
    const source = input.length ? input[0] : null;
    const semitones = parameters.semitones[0];
    const ratio = Math.pow(2, semitones / 12);
    const bypass = Math.abs(semitones) < 0.01;
    const out = output[0];
    const mask = this.size - 1;
    const step = (1 - ratio) / this.window;
    for (let n = 0; n < out.length; n += 1) {
      const sample = source ? source[n] : 0;
      this.buffer[this.write & mask] = sample;
      if (bypass) {
        out[n] = sample;
      } else {
        this.phase = (this.phase + step) % 1;
        if (this.phase < 0) this.phase += 1;
        let value = 0;
        for (const offset of [0, 0.5]) {
          const p = (this.phase + offset) % 1;
          const gain = 0.5 - 0.5 * Math.cos(2 * Math.PI * p);  // les deux têtes se complètent (somme = 1)
          value += gain * this.read(this.write - 2 - p * this.window);
        }
        out[n] = value;
      }
      this.write = (this.write + 1) % this.size;
    }
    for (let c = 1; c < output.length; c += 1) output[c].set(out);
    return true;
  }
}

registerProcessor("aether-pitch-shifter", AetherPitchShifter);
