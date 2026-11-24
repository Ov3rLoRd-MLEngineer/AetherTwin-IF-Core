"use strict";
// Studio audio Æther (module voice) : synthé et séquenceur (pas à pas, rouleau de piano, export WAV), modulateur
// vocal en direct (mêmes effets que les voix de synthèse, sortie vers VB-Cable), profils de voix.
// Tout est local : Web Audio dans la page, le Hub pour les voix (/v1/audio/*, /voice/*, module voice).

(() => {
  const $ = (id) => document.getElementById(id);
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === undefined || value === null || value === false) continue;
      if (key === "class") node.className = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? "" : value);
    }
    node.append(...children.flat().filter((c) => c !== null && c !== undefined));
    return node;
  }
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  let statusTimer = 0;
  function status(text, error) {
    const box = $("status");
    box.textContent = text;
    box.classList.toggle("err", Boolean(error));
    clearTimeout(statusTimer);
    if (text && !error) statusTimer = setTimeout(() => { box.textContent = ""; }, 6000);
  }
  async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `erreur ${response.status}`);
    return data;
  }
  const postJson = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });
  async function voiceCommand(command, payload) {
    await postJson("/modules/voice/activate");
    const reply = await postJson(`/modules/voice/command/${command}`, payload);
    if (!reply.ok) throw new Error(reply.error || "erreur du module voix");
    return reply.result;
  }
  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      localStorage.setItem(key, value);
    } catch (error) { /* stockage indisponible */ }
    return null;
  }
  function download(blob, name) {
    const link = el("a", { href: URL.createObjectURL(blob), download: name });
    document.body.append(link);
    link.click();
    setTimeout(() => { URL.revokeObjectURL(link.href); link.remove(); }, 2000);
  }

  // ---------- thème et onglets ----------
  const theme = store("aether-audio-theme");
  if (theme) document.documentElement.dataset.theme = theme;
  $("btn-theme").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    store("aether-audio-theme", next);
    drawRoll();
  });
  const views = {};
  function showMode(mode) {
    document.querySelectorAll("#modes button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.mode === mode)));
    document.querySelectorAll(".view").forEach((v) => { v.hidden = v.dataset.view !== mode; });
    store("aether-audio-mode", mode);
    if (views[mode]) views[mode]();
  }
  $("modes").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-mode]");
    if (button) showMode(button.dataset.mode);
  });

  // =====================================================================================================
  // Effets de voix : mêmes réglages et bornes que modules/voice/effects.py
  // =====================================================================================================
  const FX = [
    { key: "pitch", label: "Hauteur", min: -12, max: 12, step: 0.5, unit: "½ ton" },
    { key: "bass", label: "Graves", min: -15, max: 15, step: 1, unit: "dB" },
    { key: "treble", label: "Aigus", min: -15, max: 15, step: 1, unit: "dB" },
    { key: "robot", label: "Robot", min: 0, max: 1, step: 0.05, unit: "" },
    { key: "radio", label: "Radio", min: 0, max: 1, step: 0.05, unit: "" },
    { key: "echo", label: "Écho", min: 0, max: 1, step: 0.05, unit: "" },
    { key: "reverb", label: "Salle", min: 0, max: 1, step: 0.05, unit: "" },
    { key: "tremolo", label: "Trémolo", min: 0, max: 1, step: 0.05, unit: "" },
    { key: "gain", label: "Volume", min: -24, max: 12, step: 1, unit: "dB" },
  ];
  const NEUTRAL = Object.fromEntries(FX.map((f) => [f.key, 0]));
  const fmt = (f, v) => (f.unit === "" ? `${Math.round(v * 100)} %` : `${v > 0 ? "+" : ""}${v} ${f.unit}`);

  function fxSliders(container, onChange) {
    const inputs = {};
    container.replaceChildren(...FX.map((f) => {
      const input = el("input", { type: "range", min: f.min, max: f.max, step: f.step, value: 0, "aria-label": f.label });
      const out = el("output", {}, fmt(f, 0));
      input.addEventListener("input", () => { out.textContent = fmt(f, Number(input.value)); onChange(get()); });
      inputs[f.key] = { input, out, f };
      return el("div", { class: "param" }, el("label", {}, f.label), input, out);
    }));
    function get() {
      return Object.fromEntries(FX.map((f) => [f.key, Number(inputs[f.key].input.value)]));
    }
    function set(values) {
      for (const f of FX) {
        const v = clamp(Number((values || {})[f.key] || 0), f.min, f.max);
        inputs[f.key].input.value = v;
        inputs[f.key].out.textContent = fmt(f, v);
      }
    }
    return { get, set };
  }
  const compact = (values) => Object.fromEntries(Object.entries(values).filter(([, v]) => v));

  function makeImpulse(ctx, seconds = 1.6, decay = 2.6) {
    const length = Math.floor(ctx.sampleRate * seconds);
    const buffer = ctx.createBuffer(2, length, ctx.sampleRate);
    for (let c = 0; c < 2; c += 1) {
      const data = buffer.getChannelData(c);
      for (let i = 0; i < length; i += 1) data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / length, decay);
    }
    return buffer;
  }
  function driveCurve(amount) {
    const drive = 1 + 6 * amount;
    const curve = new Float32Array(1024);
    for (let i = 0; i < curve.length; i += 1) {
      const x = (i / (curve.length - 1)) * 2 - 1;
      curve[i] = Math.tanh(drive * x) / Math.tanh(drive);
    }
    return curve;
  }

  // =====================================================================================================
  // Synthé et séquenceur
  // =====================================================================================================
  const NOTE_NAMES = ["Do", "Do♯", "Ré", "Ré♯", "Mi", "Fa", "Fa♯", "Sol", "Sol♯", "La", "La♯", "Si"];
  const noteName = (midi) => `${NOTE_NAMES[midi % 12]}${Math.floor(midi / 12) - 1}`;
  const freq = (midi) => 440 * Math.pow(2, (midi - 69) / 12);
  const COLORS = ["#2ec4d6", "#f2a541", "#b67cf2", "#5ad17f", "#ef6f8c", "#6f9cef"];
  const DRUMS = [["kick", "Grosse caisse"], ["snare", "Caisse claire"], ["hat", "Charleston"],
                 ["open", "Charleston ouvert"], ["clap", "Clap"], ["tom", "Tom"]];

  const PRESETS = {
    "Basse": { wave: "sawtooth", wave2: "square", mix2: 0.35, detune: -1200, attack: 0.005, decay: 0.18, sustain: 0.5,
               release: 0.08, filter: "lowpass", cutoff: 700, resonance: 6, envAmount: 1800, volume: 0.75 },
    "Lead": { wave: "square", wave2: "sawtooth", mix2: 0.4, detune: 8, attack: 0.01, decay: 0.2, sustain: 0.6,
              release: 0.15, filter: "lowpass", cutoff: 2400, resonance: 4, envAmount: 2500, volume: 0.45 },
    "Nappe": { wave: "sawtooth", wave2: "sawtooth", mix2: 0.6, detune: 12, attack: 0.45, decay: 0.6, sustain: 0.7,
               release: 0.9, filter: "lowpass", cutoff: 1500, resonance: 1, envAmount: 600, volume: 0.4 },
    "Pincé": { wave: "triangle", wave2: "square", mix2: 0.2, detune: 0, attack: 0.002, decay: 0.22, sustain: 0,
               release: 0.2, filter: "lowpass", cutoff: 1200, resonance: 8, envAmount: 4200, volume: 0.55 },
    "8 bits": { wave: "square", wave2: "square", mix2: 0, detune: 0, attack: 0.001, decay: 0.05, sustain: 0.8,
                release: 0.03, filter: "lowpass", cutoff: 12000, resonance: 0, envAmount: 0, volume: 0.35 },
    "Cloche": { wave: "sine", wave2: "sine", mix2: 0.5, detune: 1902, attack: 0.002, decay: 0.9, sustain: 0,
                release: 0.9, filter: "lowpass", cutoff: 8000, resonance: 0, envAmount: 0, volume: 0.5 },
    "Orgue": { wave: "sine", wave2: "triangle", mix2: 0.5, detune: 1200, attack: 0.01, decay: 0.1, sustain: 0.9,
               release: 0.08, filter: "lowpass", cutoff: 5000, resonance: 0, envAmount: 0, volume: 0.45 },
  };
  const MIX_DEFAULTS = { pan: 0, delaySend: 0.15, reverbSend: 0.2, mute: false };

  let nextId = 1;
  function synthTrack(name, preset, base, notes) {
    return { id: nextId++, kind: "synth", name, base, notes: notes || [],
             instrument: { ...PRESETS[preset], preset }, ...MIX_DEFAULTS };
  }
  function drumTrack(steps) {
    const rows = Object.fromEntries(DRUMS.map(([k]) => [k, Array(steps).fill(false)]));
    return { id: nextId++, kind: "drums", name: "Batterie", rows, kit: { tune: 0, decay: 1 }, volume: 0.8,
             ...MIX_DEFAULTS, delaySend: 0, reverbSend: 0.1 };
  }
  function demoSong() {
    nextId = 1;
    const drums = drumTrack(16);
    [0, 4, 8, 12].forEach((s) => { drums.rows.kick[s] = true; });
    [4, 12].forEach((s) => { drums.rows.snare[s] = true; });
    [2, 6, 10, 14].forEach((s) => { drums.rows.hat[s] = true; });
    drums.rows.open[15] = true;
    const bass = [[0, 45], [3, 45], [6, 48], [8, 41], [11, 41], [14, 43]].map(([step, pitch]) => ({ step, pitch, length: 2 }));
    const lead = [[0, 69, 2], [2, 72, 2], [4, 76, 3], [8, 74, 2], [10, 72, 2], [12, 71, 4]]
      .map(([step, pitch, length]) => ({ step, pitch, length }));
    return { format: "aether-audio", version: 1, name: "morceau", bpm: 110, steps: 16, swing: 0, delay: 0.3,
             reverb: 0.25, master: 0.6,
             tracks: [drums, synthTrack("Basse", "Basse", 36, bass), synthTrack("Mélodie", "Pincé", 60, lead)] };
  }

  function sanitizeSong(raw) {
    if (!raw || raw.format !== "aether-audio" || !Array.isArray(raw.tracks)) throw new Error("fichier de morceau inconnu");
    const song = demoSong();
    song.name = String(raw.name || "morceau").replace(/[^\w-]+/g, "_").slice(0, 40) || "morceau";
    song.bpm = clamp(Number(raw.bpm) || 110, 40, 240);
    song.steps = Number(raw.steps) === 32 ? 32 : 16;
    for (const key of ["swing", "delay", "reverb", "master"]) song[key] = clamp(Number(raw[key]) || 0, 0, 1);
    nextId = 1;
    song.tracks = raw.tracks.slice(0, 12).map((t) => {
      const mix = { pan: clamp(Number(t.pan) || 0, -1, 1), delaySend: clamp(Number(t.delaySend) || 0, 0, 1),
                    reverbSend: clamp(Number(t.reverbSend) || 0, 0, 1), mute: Boolean(t.mute) };
      if (t.kind === "drums") {
        const track = { ...drumTrack(32), ...mix, name: String(t.name || "Batterie").slice(0, 30),
                        volume: clamp(Number(t.volume ?? 0.8), 0, 1) };
        for (const [k] of DRUMS) track.rows[k] = Array.from({ length: 32 }, (_, i) => Boolean(t.rows?.[k]?.[i]));
        track.kit = { tune: clamp(Number(t.kit?.tune) || 0, -12, 12), decay: clamp(Number(t.kit?.decay) || 1, 0.3, 2.5) };
        return track;
      }
      const preset = PRESETS[t.instrument?.preset] ? t.instrument.preset : "Lead";
      const track = { ...synthTrack(String(t.name || "Synthé").slice(0, 30), preset, clamp(Number(t.base) || 60, 12, 96)), ...mix };
      const inst = t.instrument || {};
      for (const [key, value] of Object.entries(PRESETS[preset])) {
        track.instrument[key] = typeof value === "number" ? (Number.isFinite(Number(inst[key])) ? Number(inst[key]) : value)
          : (["sine", "square", "sawtooth", "triangle", "lowpass", "highpass", "bandpass"].includes(inst[key]) ? inst[key] : value);
      }
      track.notes = (Array.isArray(t.notes) ? t.notes : []).slice(0, 512).map((n) => ({
        step: clamp(Math.round(Number(n.step) || 0), 0, 31), pitch: clamp(Math.round(Number(n.pitch) || 60), 12, 108),
        length: clamp(Math.round(Number(n.length) || 1), 1, 32) }));
      return track;
    });
    if (!song.tracks.length) song.tracks = demoSong().tracks;
    return song;
  }

  let song = demoSong();
  let selected = song.tracks[1].id;
  try {
    const saved = store("aether-audio-song");
    if (saved) { song = sanitizeSong(JSON.parse(saved)); selected = song.tracks[0].id; }
  } catch (error) { song = demoSong(); }
  let saveTimer = 0;
  function changed() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => store("aether-audio-song", JSON.stringify(song)), 400);
  }
  const current = () => song.tracks.find((t) => t.id === selected) || song.tracks[0];

  // ---------- moteur ----------
  const noiseBuffers = new WeakMap();
  function noise(ctx) {
    if (!noiseBuffers.has(ctx)) {
      const buffer = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
      const data = buffer.getChannelData(0);
      for (let i = 0; i < data.length; i += 1) data[i] = Math.random() * 2 - 1;
      noiseBuffers.set(ctx, buffer);
    }
    return noiseBuffers.get(ctx);
  }

  function playNote(ctx, dest, inst, midi, time, duration, velocity = 0.9) {
    const f = freq(midi);
    const env = ctx.createGain();
    const filter = ctx.createBiquadFilter();
    filter.type = inst.filter;
    filter.Q.value = inst.resonance;
    const peak = clamp(inst.cutoff + inst.envAmount, 40, 18000);
    filter.frequency.setValueAtTime(clamp(inst.cutoff, 40, 18000), time);
    if (inst.envAmount) {
      filter.frequency.linearRampToValueAtTime(peak, time + inst.attack + 0.001);
      filter.frequency.setTargetAtTime(clamp(inst.cutoff, 40, 18000), time + inst.attack, Math.max(0.01, inst.decay / 3));
    }
    const level = inst.volume * velocity;
    const end = time + duration;
    env.gain.setValueAtTime(0, time);
    env.gain.linearRampToValueAtTime(level, time + inst.attack + 0.001);
    env.gain.setTargetAtTime(level * inst.sustain, time + inst.attack, Math.max(0.005, inst.decay / 3));
    env.gain.setValueAtTime(level * inst.sustain, Math.max(end, time + inst.attack + 0.002));
    env.gain.setTargetAtTime(0, Math.max(end, time + inst.attack + 0.002), Math.max(0.005, inst.release / 4));
    const stop = Math.max(end, time + inst.attack) + inst.release + 0.1;
    const oscs = [[inst.wave, 0, 1 - inst.mix2], [inst.wave2, inst.detune, inst.mix2]];
    for (const [wave, detune, mix] of oscs) {
      if (mix <= 0.001) continue;
      const osc = ctx.createOscillator();
      const g = ctx.createGain();
      osc.type = wave;
      osc.frequency.value = f;
      osc.detune.value = detune;
      g.gain.value = mix;
      osc.connect(g).connect(filter);
      osc.start(time);
      osc.stop(stop);
    }
    filter.connect(env).connect(dest);
  }

  function playDrum(ctx, dest, kind, time, kit, velocity = 1) {
    const tune = Math.pow(2, (kit.tune || 0) / 12);
    const d = kit.decay || 1;
    const out = ctx.createGain();
    out.gain.value = velocity;
    out.connect(dest);
    const noiseHit = (type, frequency, q, length, level) => {
      const src = ctx.createBufferSource();
      src.buffer = noise(ctx);
      const filter = ctx.createBiquadFilter();
      filter.type = type;
      filter.frequency.value = frequency * tune;
      filter.Q.value = q;
      const g = ctx.createGain();
      g.gain.setValueAtTime(level, time);
      g.gain.exponentialRampToValueAtTime(0.001, time + length * d);
      src.connect(filter).connect(g).connect(out);
      src.start(time);
      src.stop(time + length * d + 0.05);
      return g;
    };
    const toneHit = (type, from, to, length, level) => {
      const osc = ctx.createOscillator();
      osc.type = type;
      osc.frequency.setValueAtTime(from * tune, time);
      osc.frequency.exponentialRampToValueAtTime(to * tune, time + length * 0.6 * d);
      const g = ctx.createGain();
      g.gain.setValueAtTime(level, time);
      g.gain.exponentialRampToValueAtTime(0.001, time + length * d);
      osc.connect(g).connect(out);
      osc.start(time);
      osc.stop(time + length * d + 0.05);
    };
    if (kind === "kick") toneHit("sine", 150, 42, 0.45, 1);
    else if (kind === "snare") { noiseHit("bandpass", 1800, 0.8, 0.2, 0.7); toneHit("triangle", 220, 160, 0.12, 0.5); }
    else if (kind === "hat") noiseHit("highpass", 7500, 1, 0.05, 0.35);
    else if (kind === "open") noiseHit("highpass", 7000, 1, 0.3, 0.3);
    else if (kind === "tom") toneHit("sine", 190, 110, 0.35, 0.8);
    else if (kind === "clap") {
      for (const offset of [0, 0.012, 0.024]) {
        const g = noiseHit("bandpass", 1500, 1.5, 0.12 + offset, 0.6);
        g.gain.setValueAtTime(0, time);
        g.gain.setValueAtTime(0.6, time + offset);
      }
    }
  }

  function buildMix(ctx, destination) {
    const master = ctx.createGain();
    const limiter = ctx.createDynamicsCompressor();
    limiter.threshold.value = -6;
    limiter.ratio.value = 12;
    limiter.attack.value = 0.003;
    limiter.release.value = 0.15;
    master.connect(limiter).connect(destination);
    const delay = ctx.createDelay(2);
    const feedback = ctx.createGain();
    const delayOut = ctx.createGain();
    const delayIn = ctx.createGain();
    const delayFilter = ctx.createBiquadFilter();
    delayFilter.type = "lowpass";
    delayFilter.frequency.value = 3500;
    delayIn.connect(delay);
    delay.connect(delayFilter).connect(feedback).connect(delay);
    delayFilter.connect(delayOut).connect(master);
    const reverb = ctx.createConvolver();
    reverb.buffer = makeImpulse(ctx);
    const reverbIn = ctx.createGain();
    const reverbOut = ctx.createGain();
    reverbIn.connect(reverb).connect(reverbOut).connect(master);
    const mix = { ctx, master, delay, feedback, delayOut, delayIn, reverbIn, reverbOut, buses: new Map() };
    for (const track of song.tracks) addBus(mix, track);
    updateMix(mix);
    return mix;
  }
  function addBus(mix, track) {
    const { ctx } = mix;
    const input = ctx.createGain();
    const pan = ctx.createStereoPanner();
    const dSend = ctx.createGain();
    const rSend = ctx.createGain();
    input.connect(pan).connect(mix.master);
    pan.connect(dSend).connect(mix.delayIn);
    pan.connect(rSend).connect(mix.reverbIn);
    mix.buses.set(track.id, { input, pan, dSend, rSend });
  }
  function updateMix(mix) {
    if (!mix) return;
    const t = mix.ctx.currentTime;
    const beat = 60 / song.bpm;
    mix.master.gain.setTargetAtTime(song.master, t, 0.02);
    mix.delay.delayTime.setTargetAtTime(beat * 0.75, t, 0.02);
    mix.feedback.gain.setTargetAtTime(0.25 + 0.4 * song.delay, t, 0.02);
    mix.delayOut.gain.setTargetAtTime(song.delay * 0.8, t, 0.02);
    mix.reverbOut.gain.setTargetAtTime(song.reverb * 1.2, t, 0.02);
    const solo = song.tracks.some((tr) => tr.solo);
    for (const track of song.tracks) {
      if (!mix.buses.has(track.id)) addBus(mix, track);
      const bus = mix.buses.get(track.id);
      const audible = !track.mute && (!solo || track.solo);
      bus.input.gain.setTargetAtTime(audible ? (track.kind === "drums" ? track.volume : 1) : 0, t, 0.01);
      bus.pan.pan.setTargetAtTime(track.pan, t, 0.02);
      bus.dSend.gain.setTargetAtTime(track.delaySend, t, 0.02);
      bus.rSend.gain.setTargetAtTime(track.reverbSend, t, 0.02);
    }
  }
  function stepLength() { return 60 / song.bpm / 4; }
  function scheduleStep(mix, step, time) {
    for (const track of song.tracks) {
      const bus = mix.buses.get(track.id);
      if (!bus) continue;
      if (track.kind === "drums") {
        for (const [kind] of DRUMS) if (track.rows[kind][step]) playDrum(mix.ctx, bus.input, kind, time, track.kit);
      } else {
        for (const n of track.notes) {
          if (n.step === step && n.step < song.steps) {
            const length = Math.min(n.length, song.steps - n.step) * stepLength();
            playNote(mix.ctx, bus.input, track.instrument, n.pitch, time, length * 0.95);
          }
        }
      }
    }
  }

  // ---------- lecture en direct ----------
  let ctx = null;
  let liveMix = null;
  const player = { playing: false, step: 0, next: 0, timer: 0, shown: -1 };
  function audio() {
    if (!ctx) ctx = new AudioContext({ latencyHint: "interactive" });
    if (ctx.state === "suspended") ctx.resume();
    if (!liveMix) liveMix = buildMix(ctx, ctx.destination);
    return ctx;
  }
  function tick() {
    const ahead = ctx.currentTime + 0.12;
    while (player.next < ahead) {
      const swing = player.step % 2 ? song.swing * stepLength() * 0.5 : 0;
      scheduleStep(liveMix, player.step, player.next + swing);
      const shownStep = player.step;
      const delay = Math.max(0, (player.next - ctx.currentTime) * 1000);
      setTimeout(() => showPlayhead(shownStep), delay);
      player.step = (player.step + 1) % song.steps;
      player.next += stepLength();
    }
  }
  function play() {
    audio();
    player.playing = true;
    player.step = 0;
    player.next = ctx.currentTime + 0.06;
    player.timer = setInterval(tick, 25);
    tick();
    $("play").textContent = "■ Arrêt";
  }
  function stop() {
    player.playing = false;
    clearInterval(player.timer);
    $("play").textContent = "▶ Lecture";
    showPlayhead(-1);
  }
  $("play").addEventListener("click", () => (player.playing ? stop() : play()));

  // ---------- transport ----------
  function bindTransport() {
    $("bpm").value = song.bpm;
    $("steps").value = String(song.steps);
    $("swing").value = song.swing;
    $("fx-delay").value = song.delay;
    $("fx-reverb").value = song.reverb;
    $("master").value = song.master;
    $("song-name").value = song.name;
  }
  $("bpm").addEventListener("change", () => { song.bpm = clamp(Number($("bpm").value) || 110, 40, 240); $("bpm").value = song.bpm; updateMix(liveMix); changed(); });
  $("steps").addEventListener("change", () => {
    song.steps = Number($("steps").value) === 32 ? 32 : 16;
    for (const t of song.tracks) if (t.kind === "drums") for (const [k] of DRUMS) {
      t.rows[k] = Array.from({ length: 32 }, (_, i) => Boolean(t.rows[k][i]));
    }
    renderEditor();
    changed();
  });
  for (const [id, key] of [["swing", "swing"], ["fx-delay", "delay"], ["fx-reverb", "reverb"], ["master", "master"]]) {
    $(id).addEventListener("input", () => { song[key] = Number($(id).value); updateMix(liveMix); changed(); });
  }
  $("song-name").addEventListener("change", () => {
    song.name = $("song-name").value.replace(/[^\w-]+/g, "_").slice(0, 40) || "morceau";
    $("song-name").value = song.name;
    changed();
  });
  $("song-new").addEventListener("click", () => {
    if (!confirm("Remplacer le morceau par celui de démonstration ?")) return;
    stop();
    song = demoSong();
    selected = song.tracks[1].id;
    liveMix = null;
    bindTransport();
    renderAll();
    changed();
  });
  $("song-save").addEventListener("click", () => {
    download(new Blob([JSON.stringify(song, null, 1)], { type: "application/json" }), `${song.name}.aether-audio.json`);
  });
  $("song-open").addEventListener("click", () => $("song-file").click());
  $("song-file").addEventListener("change", async () => {
    const file = $("song-file").files[0];
    $("song-file").value = "";
    if (!file) return;
    try {
      if (file.size > 2_000_000) throw new Error("fichier trop gros");
      stop();
      song = sanitizeSong(JSON.parse(await file.text()));
      selected = song.tracks[0].id;
      liveMix = null;
      bindTransport();
      renderAll();
      changed();
      status(`Morceau « ${song.name} » ouvert.`);
    } catch (error) {
      status(`Ouverture impossible : ${error.message}`, true);
    }
  });

  // ---------- export WAV ----------
  function encodeWav(buffer) {
    const channels = buffer.numberOfChannels;
    const frames = buffer.length;
    const bytes = new DataView(new ArrayBuffer(44 + frames * channels * 2));
    const text = (offset, s) => { for (let i = 0; i < s.length; i += 1) bytes.setUint8(offset + i, s.charCodeAt(i)); };
    text(0, "RIFF"); bytes.setUint32(4, 36 + frames * channels * 2, true); text(8, "WAVE"); text(12, "fmt ");
    bytes.setUint32(16, 16, true); bytes.setUint16(20, 1, true); bytes.setUint16(22, channels, true);
    bytes.setUint32(24, buffer.sampleRate, true); bytes.setUint32(28, buffer.sampleRate * channels * 2, true);
    bytes.setUint16(32, channels * 2, true); bytes.setUint16(34, 16, true); text(36, "data");
    bytes.setUint32(40, frames * channels * 2, true);
    const data = Array.from({ length: channels }, (_, c) => buffer.getChannelData(c));
    let offset = 44;
    for (let i = 0; i < frames; i += 1) {
      for (let c = 0; c < channels; c += 1) {
        bytes.setInt16(offset, clamp(data[c][i], -1, 1) * 32767, true);
        offset += 2;
      }
    }
    return new Blob([bytes], { type: "audio/wav" });
  }
  $("song-export").addEventListener("click", async () => {
    const button = $("song-export");
    button.disabled = true;
    status("Rendu du WAV…");
    try {
      const loops = 4;
      const rate = 44100;
      const seconds = loops * song.steps * stepLength() + 2.5;
      const offline = new OfflineAudioContext(2, Math.ceil(seconds * rate), rate);
      const mix = buildMix(offline, offline.destination);
      let time = 0.05;
      for (let i = 0; i < loops * song.steps; i += 1) {
        const step = i % song.steps;
        scheduleStep(mix, step, time + (step % 2 ? song.swing * stepLength() * 0.5 : 0));
        time += stepLength();
      }
      const rendered = await offline.startRendering();
      download(encodeWav(rendered), `${song.name}.wav`);
      status(`WAV exporté : ${song.name}.wav (${seconds.toFixed(1)} s).`);
    } catch (error) {
      status(`Export impossible : ${error.message}`, true);
    } finally {
      button.disabled = false;
    }
  });

  // ---------- pistes ----------
  function renderTracks() {
    const list = song.tracks.map((track, index) => {
      const mute = el("button", { type: "button", class: track.mute ? "on" : "", title: "Couper la piste" }, "M");
      const solo = el("button", { type: "button", class: track.solo ? "on" : "", title: "Écouter seule" }, "S");
      mute.addEventListener("click", (event) => { event.stopPropagation(); track.mute = !track.mute; updateMix(liveMix); renderTracks(); changed(); });
      solo.addEventListener("click", (event) => { event.stopPropagation(); track.solo = !track.solo; updateMix(liveMix); renderTracks(); });
      const swatch = el("span", { class: "swatch" });
      swatch.style.background = COLORS[index % COLORS.length];
      const info = track.kind === "drums" ? "batterie" : `${track.instrument.preset} · ${track.notes.length} note(s)`;
      return el("div", { class: `track${track.id === selected ? " sel" : ""}`, role: "button", tabindex: "0",
                         onclick: () => { selected = track.id; renderAll(); } },
                swatch, el("span", { class: "name" }, track.name, el("small", {}, info)), mute, solo);
    });
    const add = el("div", { class: "track-add" },
      el("button", { type: "button", onclick: () => addTrack("synth") }, "+ Synthé"),
      el("button", { type: "button", onclick: () => addTrack("drums") }, "+ Batterie"));
    $("tracks").replaceChildren(...list, add);
  }
  function addTrack(kind) {
    if (song.tracks.length >= 12) { status("12 pistes au plus.", true); return; }
    const track = kind === "drums" ? drumTrack(32) : synthTrack(`Synthé ${song.tracks.length}`, "Lead", 60);
    song.tracks.push(track);
    selected = track.id;
    if (liveMix) updateMix(liveMix);
    renderAll();
    changed();
  }

  // ---------- rouleau de piano ----------
  const roll = { rows: 24, cell: 26, row: 16, label: 44, drag: null };
  const canvas = $("roll");
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function drawRoll() {
    const track = current();
    if (!track || track.kind !== "synth") return;
    const wrap = $("roll-wrap");
    roll.cell = Math.max(22, Math.floor((wrap.clientWidth - roll.label - 2) / song.steps));
    const width = roll.label + roll.cell * song.steps;
    const height = roll.row * roll.rows;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const g = canvas.getContext("2d");
    g.setTransform(ratio, 0, 0, ratio, 0, 0);
    g.fillStyle = css("--stage");
    g.fillRect(0, 0, width, height);
    for (let r = 0; r < roll.rows; r += 1) {
      const midi = track.base + roll.rows - 1 - r;
      const black = [1, 3, 6, 8, 10].includes(midi % 12);
      g.fillStyle = black ? css("--cell-alt") : css("--cell");
      g.fillRect(roll.label, r * roll.row, width - roll.label, roll.row - 1);
      g.fillStyle = midi % 12 === 0 ? css("--accent") : css("--muted");
      g.font = "10px Segoe UI, sans-serif";
      g.fillText(noteName(midi), 4, r * roll.row + 12);
    }
    g.fillStyle = css("--beat");
    for (let s = 0; s <= song.steps; s += 1) {
      g.fillRect(roll.label + s * roll.cell, 0, s % 4 === 0 ? 2 : 1, height);
    }
    if (player.shown >= 0) {
      g.fillStyle = "rgba(46, 196, 214, 0.18)";
      g.fillRect(roll.label + player.shown * roll.cell, 0, roll.cell, height);
    }
    const color = COLORS[song.tracks.indexOf(track) % COLORS.length];
    for (const n of track.notes) {
      const r = track.base + roll.rows - 1 - n.pitch;
      if (r < 0 || r >= roll.rows || n.step >= song.steps) continue;
      const x = roll.label + n.step * roll.cell + 1;
      const w = Math.min(n.length, song.steps - n.step) * roll.cell - 2;
      g.fillStyle = color;
      g.fillRect(x, r * roll.row + 1, w, roll.row - 3);
      g.fillStyle = "rgba(0,0,0,.35)";
      g.fillRect(x + w - 3, r * roll.row + 1, 3, roll.row - 3);
    }
  }
  function cellAt(event) {
    const box = canvas.getBoundingClientRect();
    const col = Math.floor((event.clientX - box.left - roll.label) / roll.cell);
    const row = Math.floor((event.clientY - box.top) / roll.row);
    if (col < 0 || col >= song.steps || row < 0 || row >= roll.rows) return null;
    return { step: col, pitch: current().base + roll.rows - 1 - row };
  }
  canvas.addEventListener("contextmenu", (event) => event.preventDefault());
  canvas.addEventListener("pointerdown", (event) => {
    const track = current();
    const cell = cellAt(event);
    if (!cell || track.kind !== "synth") return;
    const hit = track.notes.find((n) => n.pitch === cell.pitch && cell.step >= n.step && cell.step < n.step + n.length);
    if (event.button === 2) {
      if (hit) track.notes.splice(track.notes.indexOf(hit), 1);
      drawRoll(); renderTracks(); changed();
      return;
    }
    let note = hit;
    if (!note) {
      note = { step: cell.step, pitch: cell.pitch, length: 1 };
      track.notes.push(note);
      audio();
      playNote(ctx, liveMix.buses.get(track.id).input, track.instrument, cell.pitch, ctx.currentTime, 0.25);
    }
    roll.drag = note;
    canvas.setPointerCapture(event.pointerId);
    drawRoll();
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!roll.drag) return;
    const box = canvas.getBoundingClientRect();
    const col = Math.floor((event.clientX - box.left - roll.label) / roll.cell);
    const length = clamp(col - roll.drag.step + 1, 1, song.steps - roll.drag.step);
    if (length !== roll.drag.length) { roll.drag.length = length; drawRoll(); }
  });
  canvas.addEventListener("pointerup", () => {
    if (roll.drag) { roll.drag = null; renderTracks(); changed(); }
  });
  $("oct-up").addEventListener("click", () => { const t = current(); if (t.kind === "synth") { t.base = clamp(t.base + 12, 12, 96); renderEditor(); changed(); } });
  $("oct-down").addEventListener("click", () => { const t = current(); if (t.kind === "synth") { t.base = clamp(t.base - 12, 12, 96); renderEditor(); changed(); } });
  $("clear-track").addEventListener("click", () => {
    const t = current();
    if (!confirm(`Effacer toutes les notes de « ${t.name} » ?`)) return;
    if (t.kind === "synth") t.notes = [];
    else for (const [k] of DRUMS) t.rows[k] = Array(32).fill(false);
    renderAll();
    changed();
  });
  new ResizeObserver(() => drawRoll()).observe($("roll-wrap"));

  // ---------- batterie ----------
  function renderDrums() {
    const track = current();
    const box = $("drums");
    box.style.setProperty("--steps", song.steps);
    box.replaceChildren(...DRUMS.map(([kind, label]) => {
      const name = el("span", { class: "label", title: "Écouter" }, label);
      name.addEventListener("click", () => { audio(); playDrum(ctx, liveMix.buses.get(track.id).input, kind, ctx.currentTime, track.kit); });
      const cells = Array.from({ length: song.steps }, (_, s) => {
        const cell = el("button", { type: "button", class: `drum-cell${s % 4 === 0 ? " beat" : ""}${track.rows[kind][s] ? " on" : ""}`,
                                    "data-step": s, "aria-label": `${label}, pas ${s + 1}` });
        cell.addEventListener("click", () => {
          track.rows[kind][s] = !track.rows[kind][s];
          cell.classList.toggle("on", track.rows[kind][s]);
          if (track.rows[kind][s]) { audio(); playDrum(ctx, liveMix.buses.get(track.id).input, kind, ctx.currentTime, track.kit); }
          changed();
        });
        return cell;
      });
      return el("div", { class: "drum-row" }, name, cells);
    }));
  }
  function showPlayhead(step) {
    player.shown = player.playing ? step : -1;
    const track = current();
    if (track.kind === "drums") {
      document.querySelectorAll(".drum-cell.now").forEach((c) => c.classList.remove("now"));
      if (player.shown >= 0) document.querySelectorAll(`.drum-cell[data-step="${player.shown}"]`).forEach((c) => c.classList.add("now"));
    } else {
      drawRoll();
    }
  }

  // ---------- clavier ----------
  const KEY_CODES = ["KeyA", "KeyW", "KeyS", "KeyE", "KeyD", "KeyF", "KeyT", "KeyG", "KeyY", "KeyH", "KeyU", "KeyJ",
                     "KeyK", "KeyO", "KeyL", "KeyP", "Semicolon"];
  let keyLabels = {};
  if (navigator.keyboard && navigator.keyboard.getLayoutMap) {
    navigator.keyboard.getLayoutMap().then((map) => { keyLabels = Object.fromEntries(KEY_CODES.map((c) => [c, (map.get(c) || "").toUpperCase()])); renderKeyboard(); }).catch(() => {});
  }
  function renderKeyboard() {
    const track = current();
    const base = track.kind === "synth" ? track.base + 12 : 60;
    $("keyboard").replaceChildren(...Array.from({ length: 17 }, (_, i) => {
      const midi = base + i;
      const black = [1, 3, 6, 8, 10].includes(midi % 12);
      const key = el("div", { class: `key${black ? " black" : ""}`, "data-midi": midi }, keyLabels[KEY_CODES[i]] || "");
      key.addEventListener("pointerdown", () => pressKey(midi));
      return key;
    }));
  }
  function pressKey(midi) {
    const track = current();
    audio();
    if (track.kind === "drums") {
      const kind = DRUMS[(midi - 60 + 120) % DRUMS.length][0];
      playDrum(ctx, liveMix.buses.get(track.id).input, kind, ctx.currentTime, track.kit);
    } else {
      playNote(ctx, liveMix.buses.get(track.id).input, track.instrument, midi, ctx.currentTime, 0.3);
    }
    const key = document.querySelector(`.key[data-midi="${midi}"]`);
    if (key) { key.classList.add("down"); setTimeout(() => key.classList.remove("down"), 180); }
  }
  document.addEventListener("keydown", (event) => {
    if (event.repeat || event.ctrlKey || event.altKey || event.metaKey) return;
    if (document.querySelector('.view[data-view="synth"]').hidden) return;
    if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName) && document.activeElement.type !== "range") return;
    if (event.code === "Space") { event.preventDefault(); player.playing ? stop() : play(); return; }
    const index = KEY_CODES.indexOf(event.code);
    if (index < 0) return;
    const track = current();
    pressKey((track.kind === "synth" ? track.base + 12 : 60) + index);
  });

  // ---------- instrument ----------
  function param(label, value, min, max, step, onInput, show) {
    const input = el("input", { type: "range", min, max, step, value, "aria-label": label });
    const out = el("output", {}, show(value));
    input.addEventListener("input", () => { const v = Number(input.value); out.textContent = show(v); onInput(v); });
    return el("div", { class: "param" }, el("label", {}, label), input, out);
  }
  function choice(label, value, options, onChange) {
    const select = el("select", { "aria-label": label }, options.map(([v, text]) => el("option", { value: v, selected: v === value }, text)));
    select.addEventListener("change", () => onChange(select.value));
    return el("div", { class: "param" }, el("label", {}, label), select, el("span"));
  }
  const pct = (v) => `${Math.round(v * 100)}`;
  const sec = (v) => (v < 1 ? `${Math.round(v * 1000)}ms` : `${v.toFixed(1)}s`);
  const hz = (v) => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : `${Math.round(v)}`);
  const WAVES = [["sine", "Sinus"], ["triangle", "Triangle"], ["square", "Carré"], ["sawtooth", "Dent de scie"]];

  function renderInstrument() {
    const track = current();
    const box = $("instrument");
    const mixParams = [
      el("h3", {}, "Mixage"),
      param("Panoramique", track.pan, -1, 1, 0.05, (v) => { track.pan = v; updateMix(liveMix); changed(); }, (v) => (v === 0 ? "C" : v < 0 ? `G${pct(-v)}` : `D${pct(v)}`)),
      param("Écho", track.delaySend, 0, 1, 0.05, (v) => { track.delaySend = v; updateMix(liveMix); changed(); }, pct),
      param("Salle", track.reverbSend, 0, 1, 0.05, (v) => { track.reverbSend = v; updateMix(liveMix); changed(); }, pct),
    ];
    const nameInput = el("input", { class: "doc-name", value: track.name, maxlength: "30", "aria-label": "Nom de la piste" });
    nameInput.addEventListener("change", () => { track.name = nameInput.value.trim().slice(0, 30) || track.name; renderTracks(); renderHeader(); changed(); });
    const remove = el("button", { type: "button", class: "ghost" }, "Supprimer la piste");
    remove.addEventListener("click", () => {
      if (song.tracks.length <= 1 || !confirm(`Supprimer la piste « ${track.name} » ?`)) return;
      song.tracks.splice(song.tracks.indexOf(track), 1);
      selected = song.tracks[0].id;
      liveMix = null;
      if (player.playing) { stop(); }
      renderAll();
      changed();
    });
    const head = [el("h3", {}, "Piste"), el("div", { class: "row" }, nameInput), el("div", { class: "row" }, remove)];
    if (track.kind === "drums") {
      box.replaceChildren(...head, el("h3", {}, "Batterie"),
        param("Volume", track.volume, 0, 1, 0.05, (v) => { track.volume = v; updateMix(liveMix); changed(); }, pct),
        param("Accord", track.kit.tune, -12, 12, 1, (v) => { track.kit.tune = v; changed(); }, (v) => `${v > 0 ? "+" : ""}${v}`),
        param("Longueur", track.kit.decay, 0.3, 2.5, 0.05, (v) => { track.kit.decay = v; changed(); }, (v) => `×${v.toFixed(1)}`),
        ...mixParams);
      return;
    }
    const inst = track.instrument;
    const set = (key) => (v) => { inst[key] = v; changed(); };
    const presets = el("div", { class: "presets" }, Object.keys(PRESETS).map((name) => {
      const b = el("button", { type: "button", class: inst.preset === name ? "on" : "" }, name);
      b.addEventListener("click", () => { Object.assign(inst, PRESETS[name], { preset: name }); renderInstrument(); renderTracks(); changed(); pressKey(track.base + 12); });
      return b;
    }));
    box.replaceChildren(...head, el("h3", {}, "Préréglages"), presets,
      el("h3", {}, "Oscillateurs"),
      choice("Onde 1", inst.wave, WAVES, set("wave")),
      choice("Onde 2", inst.wave2, WAVES, set("wave2")),
      param("Mélange", inst.mix2, 0, 1, 0.05, set("mix2"), pct),
      param("Écart", inst.detune, -2400, 2400, 1, set("detune"), (v) => `${v}c`),
      el("h3", {}, "Enveloppe"),
      param("Attaque", inst.attack, 0.001, 2, 0.001, set("attack"), sec),
      param("Déclin", inst.decay, 0.01, 2, 0.01, set("decay"), sec),
      param("Maintien", inst.sustain, 0, 1, 0.01, set("sustain"), pct),
      param("Relâche", inst.release, 0.01, 3, 0.01, set("release"), sec),
      el("h3", {}, "Filtre"),
      choice("Type", inst.filter, [["lowpass", "Passe-bas"], ["highpass", "Passe-haut"], ["bandpass", "Passe-bande"]], set("filter")),
      param("Coupure", inst.cutoff, 60, 16000, 10, set("cutoff"), hz),
      param("Résonance", inst.resonance, 0, 20, 0.1, set("resonance"), (v) => v.toFixed(1)),
      param("Enveloppe", inst.envAmount, 0, 8000, 10, set("envAmount"), hz),
      el("h3", {}, "Volume"),
      param("Niveau", inst.volume, 0, 1, 0.01, set("volume"), pct),
      ...mixParams);
  }
  function renderHeader() {
    const track = current();
    $("editor-title").textContent = track.kind === "drums" ? `${track.name} — pas à pas` : `${track.name} — rouleau de piano`;
    $("editor-hint").textContent = track.kind === "drums" ? "Clic : activer un coup · clic sur un nom : écouter"
      : "Clic : poser une note · glisser : allonger · clic droit : effacer · Espace : lecture";
    $("oct-up").hidden = $("oct-down").hidden = track.kind === "drums";
  }
  function renderEditor() {
    const track = current();
    renderHeader();
    $("roll-wrap").hidden = track.kind === "drums";
    $("drums").hidden = track.kind !== "drums";
    if (track.kind === "drums") renderDrums(); else drawRoll();
    renderKeyboard();
  }
  function renderAll() {
    renderTracks();
    renderEditor();
    renderInstrument();
  }
  bindTransport();
  renderAll();
  views.synth = () => drawRoll();

  // =====================================================================================================
  // Modulateur vocal en direct
  // =====================================================================================================
  const mod = { ctx: null, stream: null, nodes: null, monitor: null, recorder: null, values: { ...NEUTRAL }, raf: 0 };
  const modSliders = fxSliders($("mod-sliders"), (values) => { mod.values = values; applyMod(); });
  let profiles = { profiles: [], default: "aether", mic: "ma_voix", speak_replies: false };

  async function loadProfiles() {
    try {
      profiles = await api("/voice/settings");
    } catch (error) {
      status(`Profils de voix : ${error.message}`, true);
    }
    const micro = profiles.profiles.filter((p) => p.kind === "micro");
    $("mod-profile").replaceChildren(...micro.map((p) => el("option", { value: p.id, selected: p.id === profiles.mic }, p.label)));
    const chosen = micro.find((p) => p.id === profiles.mic);
    if (chosen) { mod.values = { ...NEUTRAL, ...chosen.effects }; modSliders.set(mod.values); applyMod(); }
    $("mod-delete").disabled = !chosen || chosen.builtin;
    renderVoiceProfiles();
  }
  $("mod-profile").addEventListener("change", async () => {
    const p = profiles.profiles.find((q) => q.id === $("mod-profile").value);
    if (!p) return;
    mod.values = { ...NEUTRAL, ...p.effects };
    modSliders.set(mod.values);
    applyMod();
    $("mod-delete").disabled = p.builtin;
    try { profiles = await postJson("/voice/settings", { mic: p.id }); } catch (error) { status(error.message, true); }
  });
  $("mod-reset").addEventListener("click", () => { mod.values = { ...NEUTRAL }; modSliders.set(mod.values); applyMod(); });
  function slug(text) {
    return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9_-]+/g, "_")
      .replace(/^[_-]+|_+$/g, "").slice(0, 40);
  }
  $("mod-save").addEventListener("click", async () => {
    const current = profiles.profiles.find((p) => p.id === $("mod-profile").value);
    const label = prompt("Nom du profil de micro :", current && !current.builtin ? current.label : "Ma voix perso");
    if (!label) return;
    const id = slug(label);
    if (!id) { status("Nom invalide.", true); return; }
    try {
      await postJson("/voice/profiles", { id, label, kind: "micro", effects: compact(mod.values) });
      profiles = await postJson("/voice/settings", { mic: id });
      await loadProfiles();
      status(`Profil « ${label} » enregistré.`);
    } catch (error) {
      status(`Enregistrement impossible : ${error.message}`, true);
    }
  });
  $("mod-delete").addEventListener("click", async () => {
    const id = $("mod-profile").value;
    if (!confirm(`Supprimer le profil « ${id} » ?`)) return;
    try {
      await api(`/voice/profiles/${encodeURIComponent(id)}`, { method: "DELETE" });
      await loadProfiles();
    } catch (error) { status(error.message, true); }
  });

  async function listDevices() {
    if (!navigator.mediaDevices?.enumerateDevices) return { inputs: [], outputs: [] };
    const devices = await navigator.mediaDevices.enumerateDevices();
    return { inputs: devices.filter((d) => d.kind === "audioinput"), outputs: devices.filter((d) => d.kind === "audiooutput") };
  }
  async function fillDevices() {
    const { inputs, outputs } = await listDevices();
    // micro : celui déjà choisi, sinon celui retenu, sinon NVIDIA Broadcast (écho et voix autour retirés) s'il existe
    const broadcast = inputs.find((d) => /nvidia broadcast/i.test(d.label));
    const keepIn = $("mod-input").value || store("aether-audio-input") || broadcast?.deviceId || "";
    const keepOut = $("mod-output").value || store("aether-audio-output") || "";
    $("mod-input").replaceChildren(...inputs.map((d, i) => el("option", { value: d.deviceId, selected: d.deviceId === keepIn }, d.label || `Micro ${i + 1}`)));
    const outs = outputs.filter((d) => d.deviceId !== "default" && d.deviceId !== "communications");
    $("mod-output").replaceChildren(el("option", { value: "" }, "Sortie par défaut (haut-parleurs ou casque)"),
      ...outs.map((d, i) => el("option", { value: d.deviceId, selected: d.deviceId === keepOut }, d.label || `Sortie ${i + 1}`)));
    $("mod-broadcast").hidden = !broadcast;
    const cable = outs.find((d) => /cable input/i.test(d.label));
    $("vb-route").hidden = !cable || $("mod-output").value === cable.deviceId;
    return { inputs, outputs: outs, cable };
  }

  function buildModChain(context, source) {
    const n = {};
    n.input = context.createGain();
    source.connect(n.input);
    n.pitch = new AudioWorkletNode(context, "aether-pitch-shifter");
    n.bass = context.createBiquadFilter(); n.bass.type = "lowshelf"; n.bass.frequency.value = 250;
    n.treble = context.createBiquadFilter(); n.treble.type = "highshelf"; n.treble.frequency.value = 3000;
    n.input.connect(n.pitch).connect(n.bass).connect(n.treble);
    // robot : modulation en anneau à 70 Hz, mélangée au son direct
    n.robotDry = context.createGain(); n.robotRing = context.createGain(); n.robotRing.gain.value = 0;
    n.robotOsc = context.createOscillator(); n.robotOsc.frequency.value = 70;
    n.robotDepth = context.createGain(); n.robotOsc.connect(n.robotDepth).connect(n.robotRing.gain); n.robotOsc.start();
    n.afterRobot = context.createGain();
    n.treble.connect(n.robotDry).connect(n.afterRobot);
    n.treble.connect(n.robotRing).connect(n.afterRobot);
    // radio : bande 300–3 400 Hz et saturation douce
    n.radioDry = context.createGain(); n.radioWet = context.createGain();
    n.radioHp = context.createBiquadFilter(); n.radioHp.type = "highpass"; n.radioHp.frequency.value = 300;
    n.radioLp = context.createBiquadFilter(); n.radioLp.type = "lowpass"; n.radioLp.frequency.value = 3400;
    n.radioShape = context.createWaveShaper(); n.radioShape.oversample = "2x";
    n.afterRadio = context.createGain();
    n.afterRobot.connect(n.radioDry).connect(n.afterRadio);
    n.afterRobot.connect(n.radioHp).connect(n.radioLp).connect(n.radioShape).connect(n.radioWet).connect(n.afterRadio);
    // trémolo : 5 Hz
    n.tremolo = context.createGain();
    n.tremOsc = context.createOscillator(); n.tremOsc.frequency.value = 5;
    n.tremDepth = context.createGain(); n.tremOsc.connect(n.tremDepth).connect(n.tremolo.gain); n.tremOsc.start();
    n.afterRadio.connect(n.tremolo);
    // écho : 260 ms réinjectés
    n.afterEcho = context.createGain();
    n.delay = context.createDelay(1); n.delay.delayTime.value = 0.26;
    n.feedback = context.createGain(); n.echoWet = context.createGain();
    n.tremolo.connect(n.afterEcho);
    n.tremolo.connect(n.delay); n.delay.connect(n.feedback).connect(n.delay); n.delay.connect(n.echoWet).connect(n.afterEcho);
    // salle
    n.afterReverb = context.createGain();
    n.convolver = context.createConvolver(); n.convolver.buffer = makeImpulse(context, 1.2, 3);
    n.reverbWet = context.createGain();
    n.afterEcho.connect(n.afterReverb);
    n.afterEcho.connect(n.convolver).connect(n.reverbWet).connect(n.afterReverb);
    // volume, sans effet, limiteur
    n.gain = context.createGain();
    n.afterReverb.connect(n.gain);
    n.bypass = context.createGain(); n.bypass.gain.value = 0;
    n.input.connect(n.bypass);
    n.wet = context.createGain();
    n.gain.connect(n.wet);
    n.limiter = context.createDynamicsCompressor();
    n.limiter.threshold.value = -3; n.limiter.ratio.value = 20; n.limiter.knee.value = 0;
    n.limiter.attack.value = 0.002; n.limiter.release.value = 0.1;
    n.wet.connect(n.limiter); n.bypass.connect(n.limiter);
    n.analyser = context.createAnalyser(); n.analyser.fftSize = 1024;
    n.limiter.connect(n.analyser);
    n.speakers = context.createGain();
    n.limiter.connect(n.speakers).connect(context.destination);
    n.stream = context.createMediaStreamDestination();
    n.limiter.connect(n.stream);
    return n;
  }
  let lastRadio = -1;
  function applyMod() {
    const n = mod.nodes;
    if (!n) return;
    const t = mod.ctx.currentTime;
    const v = mod.values;
    const smooth = (p, value) => p.setTargetAtTime(value, t, 0.03);
    n.pitch.parameters.get("semitones").setValueAtTime(v.pitch, t);
    smooth(n.bass.gain, v.bass);
    smooth(n.treble.gain, v.treble);
    smooth(n.robotDry.gain, 1 - v.robot);
    smooth(n.robotDepth.gain, 1.6 * v.robot);
    smooth(n.radioDry.gain, 1 - v.radio);
    smooth(n.radioWet.gain, v.radio);
    if (Math.abs(v.radio - lastRadio) > 0.01) { n.radioShape.curve = driveCurve(v.radio); lastRadio = v.radio; }
    smooth(n.tremolo.gain, 1 - 0.5 * v.tremolo);
    smooth(n.tremDepth.gain, 0.5 * v.tremolo);
    smooth(n.feedback.gain, v.echo ? 0.35 + 0.3 * v.echo : 0);
    smooth(n.echoWet.gain, 0.6 * v.echo);
    smooth(n.reverbWet.gain, 0.6 * v.reverb);
    smooth(n.gain.gain, Math.pow(10, v.gain / 20));
    const bypass = $("mod-bypass").checked;
    smooth(n.wet.gain, bypass ? 0 : 1);
    smooth(n.bypass.gain, bypass ? 1 : 0);
    routeMonitor();
  }
  $("mod-bypass").addEventListener("change", applyMod);

  // Sortie choisie (VB-Cable…) = destination du contexte ; « m'écouter » ajoute une copie sur la sortie par défaut.
  function routeMonitor() {
    const n = mod.nodes;
    if (!n) return;
    const toDevice = Boolean($("mod-output").value);
    const monitor = $("mod-monitor").checked;
    n.speakers.gain.setTargetAtTime(toDevice || monitor ? 1 : 0, mod.ctx.currentTime, 0.02);
    if (toDevice && monitor) {
      if (!mod.monitor) {
        mod.monitor = new Audio();
        mod.monitor.srcObject = n.stream.stream;
      }
      mod.monitor.play().catch(() => {});
    } else if (mod.monitor) {
      mod.monitor.pause();
    }
  }
  $("mod-monitor").addEventListener("change", routeMonitor);
  async function applyOutput() {
    const id = $("mod-output").value;
    store("aether-audio-output", id);
    if (mod.ctx && typeof mod.ctx.setSinkId === "function") {
      try {
        await mod.ctx.setSinkId(id || "");
      } catch (error) {
        status(`Sortie impossible : ${error.message}`, true);
      }
    } else if (mod.ctx && id) {
      status("Ce navigateur ne sait pas choisir la sortie audio (Edge ou Chrome récents requis).", true);
    }
    routeMonitor();
    await fillDevices();
  }
  $("mod-output").addEventListener("change", applyOutput);
  $("vb-route").addEventListener("click", async () => {
    const { cable } = await fillDevices();
    if (!cable) return;
    $("mod-output").value = cable.deviceId;
    await applyOutput();
    status("Ta voix modifiée part dans VB-Cable : choisis « CABLE Output » comme micro dans Discord ou le jeu.");
  });

  function meter() {
    const n = mod.nodes;
    if (!n) return;
    const data = new Float32Array(n.analyser.fftSize);
    n.analyser.getFloatTimeDomainData(data);
    let peak = 0;
    for (const s of data) peak = Math.max(peak, Math.abs(s));
    $("mod-meter").style.width = `${Math.round(Math.min(1, peak) * 100)}%`;
    mod.raf = requestAnimationFrame(meter);
  }

  async function modStart() {
    const button = $("mod-start");
    if (mod.nodes) { modStop(); return; }
    button.disabled = true;
    try {
      mod.ctx = new AudioContext({ latencyHint: "interactive" });
      await mod.ctx.audioWorklet.addModule("/static/audio_worklet.js");
      const deviceId = $("mod-input").value;
      // NVIDIA Broadcast nettoie déjà le son : pas de seconde réduction de bruit du navigateur par-dessus
      const cleaned = /nvidia broadcast/i.test($("mod-input").selectedOptions[0]?.textContent || "");
      mod.stream = await navigator.mediaDevices.getUserMedia({ audio: {
        deviceId: deviceId ? { exact: deviceId } : undefined, echoCancellation: false,
        noiseSuppression: $("mod-noise").checked && !cleaned, autoGainControl: false, channelCount: 1 } });
      mod.nodes = buildModChain(mod.ctx, mod.ctx.createMediaStreamSource(mod.stream));
      lastRadio = -1;
      applyMod();
      await fillDevices();
      await applyOutput();
      meter();
      button.textContent = "■ Couper le micro";
      button.classList.add("recording");
      status(`Micro actif (latence ≈ ${Math.round((mod.ctx.baseLatency + (mod.ctx.outputLatency || 0)) * 1000 + 40)} ms).`);
    } catch (error) {
      modStop();
      status(`Micro inaccessible : ${error.message}`, true);
    } finally {
      button.disabled = false;
    }
  }
  function modStop() {
    cancelAnimationFrame(mod.raf);
    if (mod.recorder && mod.recorder.state === "recording") mod.recorder.stop();
    if (mod.monitor) { mod.monitor.pause(); mod.monitor.srcObject = null; mod.monitor = null; }
    if (mod.stream) mod.stream.getTracks().forEach((t) => t.stop());
    if (mod.ctx) mod.ctx.close().catch(() => {});
    Object.assign(mod, { ctx: null, stream: null, nodes: null });
    $("mod-meter").style.width = "0";
    $("mod-start").textContent = "🎙 Activer le micro";
    $("mod-start").classList.remove("recording");
  }
  $("mod-start").addEventListener("click", modStart);
  $("mod-input").addEventListener("change", () => {
    store("aether-audio-input", $("mod-input").value);
    if (mod.nodes) { modStop(); modStart(); }
  });
  $("mod-noise").addEventListener("change", () => { if (mod.nodes) { modStop(); modStart(); } });

  $("mod-record").addEventListener("click", () => {
    const button = $("mod-record");
    if (mod.recorder && mod.recorder.state === "recording") { mod.recorder.stop(); return; }
    if (!mod.nodes) { status("Active d'abord le micro.", true); return; }
    const chunks = [];
    const recorder = new MediaRecorder(mod.nodes.stream.stream);
    mod.recorder = recorder;
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    recorder.onstop = () => {
      button.textContent = "⏺ Enregistrer ma voix modifiée";
      button.classList.remove("recording");
      $("mod-record-state").textContent = "";
      if (chunks.length) download(new Blob(chunks, { type: recorder.mimeType || "audio/webm" }), "ma-voix.webm");
    };
    recorder.start();
    button.textContent = "■ Arrêter et télécharger";
    button.classList.add("recording");
    $("mod-record-state").textContent = "enregistrement…";
  });

  $("vb-check").addEventListener("click", async () => {
    const box = $("vb-state");
    box.textContent = "Vérification…";
    box.className = "muted";
    let server = null;
    try { server = await voiceCommand("vbcable"); } catch (error) { server = { installed: false, error: error.message }; }
    let cable = null;
    try { ({ cable } = await fillDevices()); } catch (error) { /* périphériques illisibles */ }
    if (server.installed || cable) {
      box.className = "ok";
      box.textContent = cable
        ? "VB-Cable est installé : la sortie « CABLE Input » est disponible."
        : `VB-Cable est installé (${(server.devices || []).join(", ")}). Active le micro une fois pour voir ses sorties.`;
    } else {
      box.className = "bad";
      box.textContent = server.error ? `Vérification impossible : ${server.error}`
        : "VB-Cable n'est pas installé (ou le PC n'a pas encore redémarré après l'installation).";
    }
  });
  views.mod = () => { fillDevices().catch(() => {}); };

  // =====================================================================================================
  // Voix : moteurs, profils de synthèse, réponses parlées, Hermes
  // =====================================================================================================
  let voiceList = [];
  let editing = null;
  const vpSliders = fxSliders($("vp-sliders"), () => {});
  let testContext = null;

  async function loadEngines() {
    const box = $("engine-state");
    box.textContent = "Lecture de l'état…";
    try {
      const s = await voiceCommand("status");
      voiceList = await voiceCommand("voices");
      const piperVoices = s.piper_voices.length;
      box.replaceChildren(
        el("div", {}, `Piper : ${s.piper ? `installé, ${piperVoices} voix` : "non installé"}`),
        el("div", {}, `Voix de Windows : ${s.sapi ? voiceList.filter((v) => v.engine === "sapi").map((v) => v.label).join(", ") || "aucune" : "indisponible"}`),
        el("div", {}, `Écoute (Whisper ${s.whisper_model}) : ${s.whisper ? (s.whisper_loaded ? "prête" : "chargée au premier usage") : "faster-whisper absent"}`));
      $("install").textContent = s.piper && piperVoices === s.catalog.length ? "Tout est installé" : "Installer Piper et les voix françaises";
      $("install").disabled = s.piper && piperVoices === s.catalog.length;
      fillVoiceSelect();
    } catch (error) {
      box.textContent = `Module voix indisponible : ${error.message}`;
    }
    try {
      const h = await voiceCommand("hermes");
      $("hermes-state").textContent = !h.installe ? "Hermes Agent n'est pas installé."
        : h.branche ? "Hermes : branché (serveur MCP « aethertwin_voice ») — il peut parler avec tes voix."
          : "Hermes : pas encore branché sur la voix.";
      $("hermes-register").hidden = !h.installe || h.branche;
    } catch (error) {
      $("hermes-state").textContent = `Hermes : ${error.message}`;
    }
  }
  $("install").addEventListener("click", async () => {
    const button = $("install");
    button.disabled = true;
    button.textContent = "Téléchargement… (≈ 300 Mo, quelques minutes)";
    try {
      const r = await voiceCommand("install", {});
      status(r.added.length ? `Installé : ${r.added.join(", ")}.` : "Rien à installer.");
    } catch (error) {
      status(`Installation : ${error.message}`, true);
    }
    loadEngines();
  });
  $("hermes-register").addEventListener("click", async () => {
    $("hermes-register").disabled = true;
    try { await voiceCommand("hermes_register"); } catch (error) { status(error.message, true); }
    $("hermes-register").disabled = false;
    loadEngines();
  });

  function renderVoiceProfiles() {
    const synth = profiles.profiles.filter((p) => p.kind === "synthese");
    $("default-voice").replaceChildren(...synth.map((p) => el("option", { value: p.id, selected: p.id === profiles.default }, p.label)));
    $("speak-replies").checked = profiles.speak_replies;
    const keep = editing?.id || synth[0]?.id;
    $("vp-select").replaceChildren(...synth.map((p) => el("option", { value: p.id, selected: p.id === keep }, p.label)));
    editProfile(synth.find((p) => p.id === keep) || synth[0]);
  }
  function editProfile(p) {
    if (!p) return;
    editing = { ...p, effects: { ...p.effects } };
    $("vp-id").value = p.id;
    $("vp-label").value = p.label;
    $("vp-engine").value = p.engine;
    $("vp-speed").value = p.speed;
    $("vp-speed-out").textContent = `×${Number(p.speed).toFixed(2)}`;
    vpSliders.set(p.effects);
    editing.convert = p.convert || "";
    fillConvertSelect();
    $("vp-delete").disabled = p.builtin;
    $("vp-delete").textContent = p.overrides ? "Revenir à l'original" : "Supprimer";
    $("vp-state").textContent = p.builtin ? "Profil intégré : tes changements l'enregistrent comme profil personnel." : "";
    fillVoiceSelect();
  }
  function fillVoiceSelect() {
    if (!editing) return;
    const engine = $("vp-engine").value;
    const voices = voiceList.filter((v) => v.engine === engine);
    const options = voices.map((v) => el("option", { value: v.id, selected: v.id === editing.voice }, `${v.label} (${v.language})`));
    if (engine === "sapi") options.unshift(el("option", { value: "", selected: !editing.voice }, "Voix par défaut de Windows"));
    if (!voices.some((v) => v.id === editing.voice) && editing.voice) {
      options.push(el("option", { value: editing.voice, selected: true }, `${editing.voice} (non installée)`));
    }
    $("vp-voice").replaceChildren(...options);
    fillSpeakers();
  }
  function fillSpeakers() {
    const voice = voiceList.find((v) => v.id === $("vp-voice").value);
    const names = voice?.speaker_names?.length ? voice.speaker_names : ["unique"];
    $("vp-speaker").replaceChildren(...names.map((name, i) => el("option", { value: i, selected: i === Number(editing?.speaker || 0) }, `${i} — ${name}`)));
    $("vp-speaker").disabled = names.length < 2;
  }
  $("vp-select").addEventListener("change", () => editProfile(profiles.profiles.find((p) => p.id === $("vp-select").value)));
  $("vp-engine").addEventListener("change", () => { editing.voice = ""; fillVoiceSelect(); });
  $("vp-voice").addEventListener("change", () => { editing.voice = $("vp-voice").value; editing.speaker = 0; fillSpeakers(); });
  $("vp-speed").addEventListener("input", () => { $("vp-speed-out").textContent = `×${Number($("vp-speed").value).toFixed(2)}`; });
  $("vp-new").addEventListener("click", () => {
    editProfile({ id: "", label: "Nouvelle voix", kind: "synthese", engine: "piper", voice: "fr_FR-siwis-medium",
                  speaker: 0, speed: 1, effects: {}, builtin: false });
    $("vp-id").focus();
  });
  function formProfile() {
    return { id: slug($("vp-id").value || $("vp-label").value), label: $("vp-label").value.trim() || $("vp-id").value,
             kind: "synthese", engine: $("vp-engine").value, voice: $("vp-voice").value,
             speaker: Number($("vp-speaker").value) || 0, speed: Number($("vp-speed").value), effects: compact(vpSliders.get()),
             convert: $("vp-convert").value || undefined };
  }
  $("vp-test").addEventListener("click", async () => {
    const button = $("vp-test");
    button.disabled = true;
    try {
      const response = await fetch("/v1/audio/speech", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input: $("vp-text").value || "Bonjour !", profile_data: formProfile() }),
      });
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || `erreur ${response.status}`);
      if (response.headers.get("X-Voice-Fallback") === "1") status("Piper ou cette voix manque : voix de Windows en attendant.", true);
      testContext = testContext || new AudioContext();
      const buffer = await testContext.decodeAudioData(await response.arrayBuffer());
      const source = testContext.createBufferSource();
      const gain = testContext.createGain();
      gain.gain.value = 0.8;
      source.buffer = buffer;
      source.connect(gain).connect(testContext.destination);
      source.start();
    } catch (error) {
      status(`Écoute impossible : ${error.message}`, true);
    } finally {
      button.disabled = false;
    }
  });
  $("vp-save").addEventListener("click", async () => {
    const p = formProfile();
    if (!p.id) { status("Donne un identifiant au profil.", true); return; }
    try {
      await postJson("/voice/profiles", p);
      editing = p;
      await loadProfiles();
      status(`Profil « ${p.label} » enregistré.`);
    } catch (error) {
      status(`Enregistrement impossible : ${error.message}`, true);
    }
  });
  $("vp-delete").addEventListener("click", async () => {
    const id = $("vp-select").value;
    if (!confirm(`Supprimer le profil personnel « ${id} » ?`)) return;
    try {
      await api(`/voice/profiles/${encodeURIComponent(id)}`, { method: "DELETE" });
      await loadProfiles();
    } catch (error) { status(error.message, true); }
  });
  $("default-voice").addEventListener("change", async () => {
    try { profiles = await postJson("/voice/settings", { default: $("default-voice").value }); } catch (error) { status(error.message, true); }
  });
  $("speak-replies").addEventListener("change", async () => {
    try { profiles = await postJson("/voice/settings", { speak_replies: $("speak-replies").checked }); } catch (error) { status(error.message, true); }
  });
  document.querySelectorAll("code").forEach((c) => { if (c.textContent.startsWith("http://127.0.0.1")) c.textContent = `${location.origin}/v1`; });
  let enginesLoaded = false;
  views.voices = () => { if (!enginesLoaded) { enginesLoaded = true; loadEngines(); loadVc().catch(() => {}); } };

  // =====================================================================================================
  // Ma voix (IA) : banque de voix enregistrées avec consentement, conversion kNN-VC (modules/voice/convert.py)
  // =====================================================================================================
  const vc = { rec: null, voices: [], prompt: null, wav: null, ctx: null };
  function fillConvertSelect() {
    const keep = editing?.convert || "";
    const ready = vc.voices.filter((v) => v.ready);
    const options = [el("option", { value: "" }, "Voix d'origine"),
      ...ready.map((v) => el("option", { value: v.id, selected: v.id === keep }, `→ ${v.label}`))];
    if (keep && !ready.some((v) => v.id === keep)) options.push(el("option", { value: keep, selected: true }, `→ ${keep} (pas prête)`));
    $("vp-convert").replaceChildren(...options);
  }
  async function vcStream() {
    // même micro que le modulateur ; NVIDIA Broadcast nettoie déjà : pas de filtre du navigateur par-dessus
    const devices = await navigator.mediaDevices.enumerateDevices().catch(() => []);
    const broadcast = devices.find((d) => d.kind === "audioinput" && /nvidia broadcast/i.test(d.label));
    const chosen = store("aether-audio-input") || broadcast?.deviceId || "";
    const cleaned = Boolean(broadcast) && chosen === broadcast.deviceId;
    const audio = { echoCancellation: !cleaned, noiseSuppression: !cleaned, autoGainControl: false, channelCount: 1 };
    try {
      return await navigator.mediaDevices.getUserMedia({ audio: { ...audio, deviceId: chosen ? { exact: chosen } : undefined } });
    } catch (error) {
      if (!chosen) throw error;
      return navigator.mediaDevices.getUserMedia({ audio });  // micro retenu débranché : micro par défaut
    }
  }
  function toggleRecord(button, label, onBlob) {
    if (vc.rec) { vc.rec.stop(); return; }
    vcStream().then((stream) => {
      const type = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm"]
        .find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
      const rec = new MediaRecorder(stream, type ? { mimeType: type } : {});
      const chunks = [];
      rec.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        vc.rec = null;
        button.textContent = label;
        button.classList.remove("recording");
        onBlob(new Blob(chunks, { type: rec.mimeType }));
      };
      vc.rec = rec;
      rec.start();
      button.textContent = "⏹ Arrêter";
      button.classList.add("recording");
    }).catch((error) => status(`Micro inaccessible : ${error.message}`, true));
  }
  const toDataUrl = (blob) => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
  async function loadVc(keep) {
    let s;
    try { s = await voiceCommand("vc_status"); } catch (error) { $("vc-state").textContent = `Module voix indisponible : ${error.message}`; return; }
    vc.voices = s.voices;
    vc.readySeconds = s.ready_seconds;
    $("vc-state").textContent = !s.torch ? "PyTorch absent : conversion indisponible."
      : s.installed ? `Conversion installée (${s.device === "cpu" ? "processeur" : "carte graphique"}${s.loaded ? ", chargée" : ", chargée à la première conversion"}).`
        : "Conversion non installée.";
    $("vc-install").hidden = s.installed || !s.torch;
    const selected = keep || $("vc-voice").value || store("aether-vc-voice") || "";
    $("vc-voice").replaceChildren(...(s.voices.length
      ? s.voices.map((v) => el("option", { value: v.id, selected: v.id === selected },
        `${v.label} — ${v.seconds} s lues${v.ready ? "" : ` (prête à ${s.ready_seconds} s)`}`))
      : [el("option", { value: "" }, "Aucune voix : crée la tienne")]));
    fillConvertSelect();
    await showVoice();
  }
  async function showVoice() {
    const vid = $("vc-voice").value;
    const ready = Boolean(vc.voices.find((v) => v.id === vid)?.ready);
    $("vc-delete").disabled = !vid;
    $("vc-rec").disabled = !vid;
    $("vc-conv-rec").disabled = !ready;
    if (!vid) {
      $("vc-prompt").textContent = "Crée une voix pour commencer.";
      $("vc-takes").replaceChildren();
      return;
    }
    store("aether-vc-voice", vid);
    const [voice, prompt] = await Promise.all([voiceCommand("vc_voice", { voice: vid }), voiceCommand("vc_prompt", { voice: vid })]);
    vc.prompt = prompt;
    $("vc-prompt").textContent = prompt.consent ? `Phrase de consentement, à dire toi-même : « ${prompt.text} »` : prompt.text;
    $("vc-prompt").classList.toggle("consent", prompt.consent);
    const read = voice.takes.filter((t) => t.prompt >= 0).reduce((sum, t) => sum + t.seconds, 0);
    $("vc-rec-state").textContent = !voice.consented ? "" : read < vc.readySeconds
      ? `${Math.round(read)} s lues sur ${vc.readySeconds} s minimum (3 à 5 min conseillées).`
      : `${Math.round(read)} s lues : voix prête${read < 180 ? " (encore quelques prises pour plus de fidélité)" : ""}.`;
    $("vc-takes").replaceChildren(...voice.takes.map((t, i) => el("li", {},
      el("span", {}, `${i === 0 ? "Consentement" : `Prise ${i}`} — ${t.seconds} s, texte reconnu à ${Math.round(t.match * 100)} %`),
      i === 0 ? "" : el("button", { type: "button", class: "ghost", "data-take": t.file.slice(0, 3) }, "Supprimer"))));
  }
  $("vc-voice").addEventListener("change", () => showVoice().catch((error) => status(error.message, true)));
  $("vc-install").addEventListener("click", async () => {
    const button = $("vc-install");
    button.disabled = true;
    button.textContent = "Téléchargement… (1,3 Go, quelques minutes)";
    try {
      const r = await voiceCommand("vc_install", {});
      status(r.fetched.length ? `Installé : ${r.fetched.join(", ")}.` : "Déjà installé.");
    } catch (error) { status(`Installation : ${error.message}`, true); }
    button.disabled = false;
    button.textContent = "Installer la conversion (1,3 Go)";
    loadVc();
  });
  $("vc-create").addEventListener("click", async () => {
    const name = $("vc-name").value.trim();
    const label = $("vc-label").value.trim() || `Ma voix (${name})`;
    try {
      const voice = await voiceCommand("vc_create", { id: slug(label) || slug(name), label, name, attest: $("vc-attest").checked });
      $("vc-attest").checked = false;
      status(`Voix « ${voice.label} » créée : dis d'abord la phrase de consentement.`);
      await loadVc(voice.id);
    } catch (error) { status(error.message, true); }
  });
  $("vc-delete").addEventListener("click", async () => {
    const vid = $("vc-voice").value;
    if (!vid || !confirm(`Supprimer la voix « ${vid} » et toutes ses prises ? (définitif)`)) return;
    try { await voiceCommand("vc_delete", { voice: vid }); store("aether-vc-voice", ""); await loadVc(); } catch (error) { status(error.message, true); }
  });
  $("vc-takes").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-take]");
    if (!button) return;
    try { await voiceCommand("vc_take_delete", { voice: $("vc-voice").value, take: Number(button.dataset.take) }); await loadVc(); } catch (error) { status(error.message, true); }
  });
  $("vc-rec").addEventListener("click", () => toggleRecord($("vc-rec"), "⏺ Lire et enregistrer", async (blob) => {
    const state = $("vc-rec-state");
    state.textContent = "Vérification par Whisper…";
    try {
      const r = await voiceCommand("vc_take", { voice: $("vc-voice").value, prompt: vc.prompt?.index ?? -1, audio: await toDataUrl(blob) });
      await loadVc($("vc-voice").value);
      state.textContent = `✓ ${r.seconds} s, texte reconnu à ${Math.round(r.match * 100)} %. ${state.textContent}`;
    } catch (error) { state.textContent = `✗ ${error.message}`; }
  }));
  function playWav(bytes) {
    vc.ctx = vc.ctx || new AudioContext();
    vc.ctx.decodeAudioData(bytes.buffer.slice(0)).then((buffer) => {
      const source = vc.ctx.createBufferSource();
      const gain = vc.ctx.createGain();
      gain.gain.value = 0.6;  // écoute discrète
      source.buffer = buffer;
      source.connect(gain).connect(vc.ctx.destination);
      source.start();
    }).catch((error) => status(`Lecture impossible : ${error.message}`, true));
  }
  $("vc-conv-rec").addEventListener("click", () => toggleRecord($("vc-conv-rec"), "⏺ Enregistrer une phrase à convertir", async (blob) => {
    const state = $("vc-conv-state");
    state.textContent = "Conversion…";
    try {
      const r = await voiceCommand("vc_convert", { voice: $("vc-voice").value, audio: await toDataUrl(blob) });
      if (!r.audio) throw new Error("enregistrement trop long pour revenir ici (1 min au plus)");
      vc.wav = Uint8Array.from(atob(r.audio), (c) => c.charCodeAt(0));
      state.textContent = `✓ ${r.duration} s converties en ${r.seconds} s.`;
      $("vc-conv-play").disabled = false;
      $("vc-conv-save").disabled = false;
      playWav(vc.wav);
    } catch (error) { state.textContent = `✗ ${error.message}`; }
  }));
  $("vc-conv-play").addEventListener("click", () => { if (vc.wav) playWav(vc.wav); });
  $("vc-conv-save").addEventListener("click", () => {
    if (vc.wav) download(new Blob([vc.wav], { type: "audio/wav" }), `voix-convertie-${$("vc-voice").value}.wav`);
  });
  views.myvoice = () => { loadVc().catch((error) => status(error.message, true)); };

  loadProfiles();
  const mode = store("aether-audio-mode");
  showMode(["synth", "mod", "voices", "myvoice"].includes(mode) ? mode : "synth");
})();
