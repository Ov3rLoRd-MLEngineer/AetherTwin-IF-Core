// Voix dans l'assistant du Hub : micro (Whisper local) et réponses lues à voix haute (Piper ou voix de Windows),
// phrase par phrase pendant que le modèle écrit. Tout passe par le Hub (/v1/audio/*), rien ne sort du PC.
// Le son est joué par Web Audio (la CSP du Hub interdit les éléments <audio> sur blob:), ce qui permet aussi de
// choisir la sortie (VB-Cable) dans le studio audio.
(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const mic = byId("ask-mic");
  if (!mic) return;
  const speakBox = byId("ask-speak");
  const voiceSelect = byId("ask-voice");
  const hush = byId("ask-hush");
  const volume = byId("ask-volume");
  const prompt = byId("ask-prompt");
  const form = byId("ask-form");

  // ---------- réglages partagés (profils de voix, sans lancer le module) ----------
  async function settingsCall(body) {
    const response = await fetch("/voice/settings", body === undefined ? {} : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `erreur ${response.status}`);
    return data;
  }

  function note(text, warn) {
    const chat = byId("chat");
    const line = document.createElement("div");
    line.className = "msg voice-note" + (warn ? " warn" : "");
    line.textContent = text;
    chat.append(line);
    chat.scrollTop = chat.scrollHeight;
  }

  // ---------- lecture ----------
  let context = null;
  const queue = [];          // promesses de tampons audio, dans l'ordre des phrases
  let playing = null;        // source en cours
  let generation = 0;        // change à chaque coupure : les synthèses en retard sont jetées
  let spokenUpTo = 0;        // position déjà confiée à la synthèse dans le texte prononçable

  let output = null;         // volume de la voix (réglette, mémorisée dans ce navigateur)
  try {
    const saved = localStorage.getItem("aether-voice-volume");
    if (saved !== null) volume.value = saved;
  } catch (error) { /* stockage indisponible : 60 % */ }

  function audioContext() {
    if (!context) {
      context = new AudioContext();
      output = context.createGain();
      output.gain.value = Number(volume.value) / 100;
      output.connect(context.destination);
    }
    if (context.state === "suspended") context.resume();
    return context;
  }

  async function synth(text, gen) {
    const response = await fetch("/v1/audio/speech", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input: text, voice: voiceSelect.value || undefined }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || `erreur ${response.status}`);
    }
    if (response.headers.get("X-Voice-Fallback") === "1" && gen === generation && !synth.warned) {
      synth.warned = true;
      note("Voix de Windows en attendant Piper (Outils → Studio audio → Voix → Installer).");
    }
    return audioContext().decodeAudioData(await response.arrayBuffer());
  }

  async function pump() {
    if (playing || !queue.length) return;
    const gen = generation;
    let buffer;
    try {
      buffer = await queue[0];
    } catch (error) {
      queue.shift();
      if (gen === generation) note(`Voix : ${error.message}`, true);
      return pump();
    }
    if (gen !== generation) return;
    queue.shift();
    const source = audioContext().createBufferSource();
    source.buffer = buffer;
    audioContext();
    source.connect(output);
    playing = source;
    hush.hidden = false;
    source.onended = () => {
      if (playing === source) playing = null;
      if (!queue.length && !playing) hush.hidden = true;
      pump();
    };
    source.start();
  }

  function say(text) {
    if (!/[\p{L}\p{N}]/u.test(text)) return;
    const gen = generation;
    const pending = synth(text, gen);
    pending.catch(() => {});  // l'erreur est montrée au moment de la lecture
    queue.push(pending);
    hush.hidden = false;
    pump();
  }

  function silence() {
    generation += 1;
    queue.length = 0;
    spokenUpTo = 0;
    if (playing) {
      try { playing.stop(); } catch (error) { /* déjà fini */ }
      playing = null;
    }
    hush.hidden = true;
  }

  // Texte prononçable : sans blocs de code ; un bloc pas encore fermé arrête la lecture à son début.
  function speakable(text) {
    const closed = text.replace(/```[\s\S]*?```/g, " ");
    const open = closed.indexOf("```");
    return open >= 0 ? closed.slice(0, open) : closed;
  }

  function feed(text, done) {
    if (!speakBox.checked) return;
    const usable = speakable(text);
    const rest = usable.slice(spokenUpTo);
    let cut = -1;
    const boundary = /[.!?…:;\n](?=\s)/g;
    for (let m = boundary.exec(rest); m; m = boundary.exec(rest)) cut = m.index + 1;
    if (done) cut = rest.length;
    if (cut <= 0) return;
    // phrases groupées jusqu'à ~300 caractères : moins de coupures, pas trop d'attente
    const chunk = rest.slice(0, cut);
    spokenUpTo += cut;
    let piece = "";
    for (const sentence of chunk.split(/(?<=[.!?…:;\n])\s+/)) {
      if (piece && piece.length + sentence.length > 300) {
        say(piece);
        piece = "";
      }
      piece += (piece ? " " : "") + sentence;
    }
    if (piece.trim()) say(piece);
  }

  document.addEventListener("aether-ask", () => { silence(); });
  document.addEventListener("aether-reply", (event) => feed(event.detail.text, event.detail.done));
  hush.addEventListener("click", silence);
  volume.addEventListener("input", () => {
    if (output) output.gain.value = Number(volume.value) / 100;
    volume.title = `Volume de la voix : ${volume.value} %`;
    try { localStorage.setItem("aether-voice-volume", volume.value); } catch (error) { /* rien */ }
  });
  byId("chat-new").addEventListener("click", silence);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !hush.hidden) silence();
  });

  // ---------- réglages (profil des réponses, lecture activée) ----------
  async function loadSettings() {
    try {
      const state = await settingsCall();
      voiceSelect.replaceChildren(...state.profiles.filter((p) => p.kind === "synthese").map((p) => {
        const option = document.createElement("option");
        option.value = p.id;
        option.textContent = p.label;
        return option;
      }));
      voiceSelect.value = state.default;
      speakBox.checked = state.speak_replies;
    } catch (error) {
      voiceSelect.replaceChildren();
      voiceSelect.title = `Voix indisponible : ${error.message}`;
    }
  }
  async function saveSettings() {
    try {
      await settingsCall({ default: voiceSelect.value, speak_replies: speakBox.checked });
    } catch (error) {
      note(`Voix : ${error.message}`, true);
    }
  }
  speakBox.addEventListener("change", () => {
    if (!speakBox.checked) silence();
    else audioContext();  // geste de l'utilisateur : le navigateur autorise le son
    saveSettings();
  });
  voiceSelect.addEventListener("change", () => {
    saveSettings();
    if (speakBox.checked) {
      silence();
      say("Voici ma nouvelle voix.");
    }
  });

  // ---------- micro ----------
  let recorder = null;
  let chunks = [];

  // Micro de dictée : NVIDIA Broadcast s'il est installé (écho des enceintes et voix autour retirés), sans
  // traitement du navigateur par-dessus ; sinon le micro par défaut avec les filtres du navigateur.
  async function micConstraints() {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const broadcast = devices.find((d) => d.kind === "audioinput" && /nvidia broadcast/i.test(d.label));
      if (broadcast) return { deviceId: { exact: broadcast.deviceId }, echoCancellation: false, noiseSuppression: false };
    } catch (error) { /* micro par défaut */ }
    return { echoCancellation: true, noiseSuppression: true };
  }

  async function startRecording() {
    audioContext();
    silence();
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: await micConstraints() });
    } catch (error) {
      note(`Micro inaccessible : ${error.message}`, true);
      return;
    }
    const type = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm"]
      .find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
    const current = new MediaRecorder(stream, type ? { mimeType: type } : {});
    recorder = current;
    chunks = [];
    current.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
    current.onstop = () => {
      stream.getTracks().forEach((track) => track.stop());
      transcribe(new Blob(chunks, { type: current.mimeType || "audio/webm" }));
    };
    current.start();
    mic.classList.add("recording");
    mic.textContent = "■ Envoyer";
    mic.title = "Clic pour arrêter et envoyer (Échap pour annuler)";
    setTimeout(() => { if (current.state === "recording") current.stop(); }, 120000);  // 2 min au plus
  }

  async function transcribe(blob) {
    recorder = null;
    mic.classList.remove("recording");
    mic.textContent = "… écoute";
    mic.disabled = true;
    try {
      if (blob.size < 800) throw new Error("enregistrement trop court");
      const response = await fetch("/v1/audio/transcriptions?language=fr", {
        method: "POST", headers: { "Content-Type": blob.type.split(";")[0] }, body: blob,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `erreur ${response.status}`);
      const text = (data.text || "").trim();
      if (!text) throw new Error("rien entendu");
      prompt.value = prompt.value.trim() ? `${prompt.value.trim()} ${text}` : text;
      form.requestSubmit();
    } catch (error) {
      note(`Micro : ${error.message}`, true);
    } finally {
      mic.disabled = false;
      mic.textContent = "🎙 Parler";
      mic.title = "Parler au micro : clic pour commencer, clic pour envoyer";
    }
  }

  mic.addEventListener("click", () => {
    if (recorder && recorder.state === "recording") recorder.stop();
    else startRecording();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && recorder && recorder.state === "recording") {
      const current = recorder;
      current.onstop = () => current.stream.getTracks().forEach((track) => track.stop());
      current.stop();
      recorder = null;
      mic.classList.remove("recording");
      mic.textContent = "🎙 Parler";
    }
  });

  loadSettings();
})();
