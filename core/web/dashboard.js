"use strict";
// Tableau de bord du Hub : lit l'API locale (même origine), aucune ressource externe.

const $ = (id) => document.getElementById(id);
const OVERLAY_URL = "http://127.0.0.1:5757/obs-hud";

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child instanceof Node ? child : String(child ?? ""));
  return node;
}

async function api(path, options = {}) {
  const headers = options.headers || (options.body && typeof options.body === "string"
    ? { "Content-Type": "application/json" } : {});
  const response = await fetch(path, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `erreur ${response.status}`);
  return data;
}

const post = (path, body) => api(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const gib = (mib) => (mib / 1024).toFixed(1);
let modulesByName = {};

// ---------- onglets ----------
function showTab(name) {
  const tabs = [...document.querySelectorAll("#tabs button")];
  if (!tabs.some((t) => t.dataset.tab === name)) name = "accueil";
  for (const tab of tabs) tab.setAttribute("aria-selected", String(tab.dataset.tab === name));
  for (const panel of document.querySelectorAll(".panel")) panel.hidden = panel.dataset.panel !== name;
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  refreshAll();
}
for (const tab of document.querySelectorAll("#tabs button")) {
  tab.addEventListener("click", () => showTab(tab.dataset.tab));
}
const currentTab = () => (location.hash || "#accueil").slice(1);

// ---------- en-tête ----------
async function refreshHub() {
  try {
    const health = await api("/health");
    const minutes = Math.floor(health.uptime_s / 60);
    $("hub-line").textContent = `Hub en marche depuis ${minutes} min — ${health.os} — GPU via ${health.gpu_backend}`;
    const llm = health.llm || {};
    const loaded = (llm.loaded || []).map((m) => (typeof m === "string" ? m : m.name)).join(", ");
    $("llm-line").textContent = llm.reachable
      ? `Ollama joignable (${llm.host}) — modèle par défaut : ${llm.default_model}, contexte ${llm.num_ctx}`
        + ` — chargé : ${loaded || "aucun"}`
      : `Ollama injoignable (${llm.host}) : ${llm.error || "?"}`;
  } catch (error) {
    $("hub-line").textContent = `Hub injoignable : ${error.message}`;
  }
}

$("hub-stop").addEventListener("click", async () => {
  if (!confirm("Arrêter le Hub ? Les modules et WoW Assistant lancés par le Hub seront fermés.")) return;
  try {
    await post("/shutdown");
    $("hub-line").textContent = "Hub arrêté. Relance-le avec le raccourci AetherTwin du bureau.";
  } catch (error) {
    alert(error.message);
  }
});

// ---------- accueil ----------
async function refreshGpus() {
  try {
    const report = await api("/gpu");
    const box = $("gpus");
    box.replaceChildren();
    if (!report.gpus.length) {
      box.append(el("p", { class: "muted" }, `Aucune mesure GPU (${report.error || "mode dégradé"}).`));
      return;
    }
    for (const gpu of report.gpus) {
      const pct = gpu.vram_total_mib ? Math.round((100 * gpu.vram_used_mib) / gpu.vram_total_mib) : 0;
      const bar = el("div", { class: "bar" }, el("i"));
      bar.firstChild.style.width = `${pct}%`;
      const extra = [
        gpu.utilization_pct != null ? `charge ${Math.round(gpu.utilization_pct)} %` : null,
        gpu.temperature_c != null ? `${Math.round(gpu.temperature_c)} °C` : null,
        gpu.power_w != null ? `${Math.round(gpu.power_w)} W` : null,
      ].filter(Boolean).join(" · ");
      box.append(el("div", { class: "card" },
        el("b", {}, `GPU ${gpu.index} — ${gpu.name}`), bar,
        el("span", {}, `VRAM ${gib(gpu.vram_used_mib)} / ${gib(gpu.vram_total_mib)} Gio (${pct} %)`),
        el("div", { class: "muted" }, extra)));
    }
  } catch (error) {
    $("gpus").replaceChildren(el("p", { class: "muted" }, `Mesure impossible : ${error.message}`));
  }
}

async function toggleModule(name, button) {
  button.disabled = true;
  const module = modulesByName[name];
  try {
    const result = await post(`/modules/${name}/${module && module.active ? "deactivate" : "activate"}`);
    if (result.verdict && result.verdict !== "accordé") alert(`${name} : ${result.verdict} — ${result.reason}`);
  } catch (error) {
    alert(`${name} : ${error.message}`);
  }
  setTimeout(refreshModules, 800);
}

async function toggleApp(name, button) {
  button.disabled = true;
  const module = modulesByName[name];
  try {
    await post(`/modules/${name}/app/${module && module.app_running ? "stop" : "start"}`);
  } catch (error) {
    alert(`${name} : ${error.message}`);
  }
  setTimeout(refreshModules, 800);
}

function moduleState(module) {
  if (module.active && module.running) return [module.auto ? "actif (déclencheur)" : "actif", "state-on"];
  if (module.waiting_vram) return ["en attente de VRAM", "state-wait"];
  if (module.active) return ["démarrage…", "state-wait"];
  return ["arrêté", module.error ? "state-err" : ""];
}

async function refreshModules() {
  try {
    const modules = await api("/modules");
    modulesByName = Object.fromEntries(modules.map((m) => [m.name, m]));
    const body = $("modules");
    body.replaceChildren();
    for (const module of modules) {
      const [state, cls] = moduleState(module);
      const detail = module.error || (module.health && module.health.detail) || module.description;
      const actions = el("div", { class: "row" });
      const button = el("button", { class: module.active ? "ghost" : "" }, module.active ? "Arrêter" : "Lancer");
      button.addEventListener("click", () => toggleModule(module.name, button));
      actions.append(button);
      if (module.app) {
        const app = el("button", { class: "ghost" }, module.app_running ? `Fermer ${module.app}` : `Ouvrir ${module.app}`);
        app.addEventListener("click", () => toggleApp(module.name, app));
        actions.append(app);
      }
      body.append(el("tr", {},
        el("td", {}, el("b", {}, module.name), el("div", { class: "muted" }, `v${module.version}`)),
        el("td", { class: cls }, state), el("td", {}, detail), el("td", {}, actions)));
    }
    refreshGameButtons();
  } catch (error) {
    $("modules").replaceChildren(el("tr", {}, el("td", { colspan: "4" }, `Liste indisponible : ${error.message}`)));
  }
}

// ---------- jeu ----------
function refreshGameButtons() {
  const hud = modulesByName.gaming_hud;
  if (!hud) return;
  $("app-toggle").textContent = hud.app_running ? "Fermer WoW Assistant" : "Lancer WoW Assistant";
  $("app-toggle").className = hud.app_running ? "ghost" : "";
  $("app-toggle").disabled = false;
  $("app-line").textContent = hud.app_running ? "ouvert" : "fermé";
  $("hud-toggle").textContent = hud.active ? "Arrêter gaming_hud" : "Activer gaming_hud";
  $("hud-toggle").className = hud.active ? "ghost" : "";
  $("hud-toggle").disabled = false;
  $("hud-line").textContent = moduleState(hud)[0] + (hud.health && hud.health.detail ? ` — ${hud.health.detail}` : "");
}
$("app-toggle").addEventListener("click", (e) => toggleApp("gaming_hud", e.currentTarget));
$("hud-toggle").addEventListener("click", (e) => toggleModule("gaming_hud", e.currentTarget));

async function refreshGame() {
  try {
    const state = await api("/modules/gaming_hud/state");
    if (!state.adapter && !state.context) {
      $("hud-context").textContent = "Rien pour l'instant : active gaming_hud (et lance le jeu ou WoW Assistant).";
    } else {
      const age = state.received_at ? Math.round(Date.now() / 1000 - state.received_at) : null;
      $("hud-context").textContent = (state.context || "(état lu, mais rien à résumer)")
        + (age != null ? `\n\n— mis à jour il y a ${age} s, adaptateur ${state.adapter}` : "");
    }
    const on = Boolean(state.showcase);
    $("showcase-line").textContent = on ? "Showcase : ACTIF" : "Showcase : inactif";
    $("showcase-line").className = on ? "pill on" : "pill";
  } catch (error) {
    $("hud-context").textContent = `État indisponible : ${error.message}`;
  }
}
for (const [id, on] of [["showcase-on", true], ["showcase-off", false]]) {
  $(id).addEventListener("click", async () => {
    try {
      await post("/modules/gaming_hud/notify/showcase", { on });
      setTimeout(refreshGame, 600);
    } catch (error) {
      alert(error.message);
    }
  });
}
$("overlay-copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(OVERLAY_URL);
    $("overlay-copy").textContent = "Copiée !";
  } catch {
    $("overlay-copy").textContent = "Copie impossible : sélectionne l'URL";
  }
});
$("overlay-preview").addEventListener("click", () => {
  const box = $("overlay-box");
  box.hidden = !box.hidden;
  box.replaceChildren(...(box.hidden ? [] : [el("iframe", { src: OVERLAY_URL, title: "aperçu de l'overlay" })]));
});

// ---------- assistant ----------
$("ask-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter;
  const out = $("ask-answer");
  button.disabled = true;
  out.hidden = false;
  out.textContent = "Le modèle local réfléchit… (le premier chargement prend 10 à 20 s)";
  try {
    const result = await post("/ask", { prompt: $("ask-prompt").value, with_context: $("ask-context").checked });
    out.textContent = `${result.answer}\n\n— ${result.model}`;
  } catch (error) {
    out.textContent = `Erreur : ${error.message}`;
  } finally {
    button.disabled = false;
  }
});

// ---------- professeur ----------
let currentExercise = null;

async function professor(command, payload, button) {
  if (button) button.disabled = true;
  try {
    if (!modulesByName.genesis_lab || !modulesByName.genesis_lab.running) {
      await post("/modules/genesis_lab/activate");  // lancé à la demande
    }
    const reply = await post(`/modules/genesis_lab/command/${command}`, payload || {});
    if (!reply.ok) throw new Error(reply.error || "erreur du module");
    return reply.result;
  } catch (error) {
    const box = $("prof-result");
    box.hidden = false;
    box.textContent = `Erreur : ${error.message}`;
    return null;
  } finally {
    if (button) button.disabled = false;
  }
}

$("prof-new").addEventListener("click", async (event) => {
  const result = await professor("exercise", { domain: $("prof-domain").value }, event.currentTarget);
  if (!result) return;
  currentExercise = result;
  $("prof-result").hidden = true;
  $("prof-exercise").hidden = false;
  $("prof-question").textContent = `[niveau ${result.level}] ${result.question}`;
  $("prof-unit").textContent = result.unit || "";
  $("prof-given").value = "";
  $("prof-given").focus();
});

$("prof-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentExercise) return;
  const box = $("prof-result");
  box.hidden = false;
  box.textContent = "Correction en cours…";
  const result = await professor("answer", {
    domain: currentExercise.domain, level: currentExercise.level, seed: currentExercise.seed,
    given: $("prof-given").value,
  }, event.submitter);
  if (!result) return;
  const sources = result.sources || [];
  const sourceLine = el("p", { class: "muted" }, `Niveau : ${result.level_before} → ${result.level_after}`);
  if (sources.length) {
    sourceLine.append(" — sources : ");
    sources.forEach((s, i) => {
      if (i) sourceLine.append(", ");
      sourceLine.append(el("a", { href: s.url, target: "_blank", rel: "noopener" }, s.title || s.url));
    });
  }
  box.replaceChildren(
    el("p", { class: result.correct ? "good" : "badans" },
      result.correct ? "Juste !" : `Pas tout à fait : la réponse attendue était ${result.expected} ${result.unit}`),
    el("p", {}, result.explanation), sourceLine);
});

$("prof-progress").addEventListener("click", async (event) => {
  const result = await professor("progress", {}, event.currentTarget);
  if (!result) return;
  const box = $("prof-result");
  box.hidden = false;
  box.textContent = Object.entries(result)
    .map(([domain, p]) => `${domain} : niveau ${p.level} (${p.level_name}), ${p.correct}/${p.done} justes`)
    .join("\n");
});

// ---------- connaissances ----------
async function refreshKnowledge() {
  try {
    const kb = await api("/knowledge");
    const s = kb.stats;
    const run = kb.running ? " — collecte en cours…" : "";
    const report = kb.last_report && kb.last_report.added !== undefined
      ? ` — dernière collecte : ${kb.last_report.added} ajoutés, ${kb.last_report.unchanged} inchangés, `
        + `${kb.last_report.refused.length} refusés, ${kb.last_report.errors.length} erreurs` : "";
    const vectors = s.vectorized ? `${s.vectorized} avec vecteurs (${s.embedder})` : "sans vecteurs : recherche par mots";
    $("kb-line").textContent = `${s.documents} documents, ${s.chunks} passages, ${vectors}${run}${report}`;
  } catch (error) {
    $("kb-line").textContent = `Base indisponible : ${error.message}`;
  }
}

$("kb-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const box = $("kb-result");
  box.hidden = false;
  try {
    const result = await api(`/knowledge/search?q=${encodeURIComponent($("kb-query").value)}&k=3`);
    box.replaceChildren();
    if (result.degraded) box.append(el("p", { class: "muted" }, `Mode dégradé : ${result.degraded}`));
    if (!result.hits.length) box.append(el("p", {}, "Aucun passage trouvé."));
    for (const hit of result.hits) {
      const link = el("a", { href: hit.url, target: "_blank", rel: "noopener" }, hit.title);
      box.append(el("p", {}, link, el("span", { class: "muted" }, ` — ${hit.license}, score ${hit.score} (${hit.mode})`)),
        el("p", {}, `${hit.text.slice(0, 400)}…`));
    }
  } catch (error) {
    box.textContent = `Erreur : ${error.message}`;
  }
});

$("kb-ingest").addEventListener("click", async () => {
  try {
    $("kb-line").textContent = (await post("/knowledge/ingest")).detail;
  } catch (error) {
    $("kb-line").textContent = `Erreur : ${error.message}`;
  }
});

// ---------- scantrad ----------
$("scan-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = $("scan-file").files[0];
  if (!file) return;
  const button = event.submitter;
  button.disabled = true;
  $("scan-line").textContent = "Traduction en cours… (détection, lecture, effacement, traduction)";
  $("scan-bubbles").replaceChildren();
  $("scan-images").hidden = false;
  $("scan-before").src = URL.createObjectURL(file);
  $("scan-after").removeAttribute("src");
  try {
    const query = new URLSearchParams({ series: $("scan-series").value.trim(), no_llm: $("scan-nollm").checked });
    const reply = await api(`/scantrad/translate?${query}`, {
      method: "POST", body: file, headers: { "Content-Type": file.type || "image/png" },
    });
    if (!reply.ok) throw new Error(reply.error || "échec");
    const { metrics, bubbles } = reply.result;
    $("scan-after").src = `${reply.output_url}?t=${Date.now()}`;
    $("scan-line").textContent = `${metrics.bubbles} bulles traduites en ${metrics.total_s} s`
      + (metrics.rejected_by_ocr ? ` (${metrics.rejected_by_ocr} zones écartées : pas de texte)` : "")
      + (metrics.vram_peak_mib ? ` — VRAM au plus haut : ${gib(metrics.vram_peak_mib)} Gio` : "");
    const list = el("ol", { class: "bubble-list" });
    for (const b of bubbles) list.append(el("li", {}, `${b.source || "—"}  →  ${b.translation || "—"}`));
    $("scan-bubbles").replaceChildren(list);
  } catch (error) {
    $("scan-line").textContent = `Erreur : ${error.message}`;
  } finally {
    button.disabled = false;
  }
});

const toLines = (map) => Object.entries(map).map(([jp, fr]) => `${jp} = ${fr}`).join("\n");
function fromLines(text) {
  const out = {};
  for (const line of text.split("\n")) {
    const [jp, ...rest] = line.split("=");
    if (jp.trim() && rest.join("=").trim()) out[jp.trim()] = rest.join("=").trim();
  }
  return out;
}
$("glo-load").addEventListener("click", async () => {
  try {
    const g = await api(`/scantrad/glossary/${encodeURIComponent($("glo-series").value.trim())}`);
    $("glo-characters").value = toLines(g.characters);
    $("glo-terms").value = toLines(g.terms);
    $("glo-tone").value = g.tone;
    $("glo-line").textContent = "chargé";
  } catch (error) {
    $("glo-line").textContent = `Erreur : ${error.message}`;
  }
});
$("glo-save").addEventListener("click", async () => {
  try {
    await api(`/scantrad/glossary/${encodeURIComponent($("glo-series").value.trim())}`, {
      method: "PUT",
      body: JSON.stringify({ characters: fromLines($("glo-characters").value), terms: fromLines($("glo-terms").value),
                             tone: $("glo-tone").value }),
    });
    $("glo-line").textContent = "enregistré";
    $("scan-series").value = $("glo-series").value;
  } catch (error) {
    $("glo-line").textContent = `Erreur : ${error.message}`;
  }
});

// ---------- studio (mangastudio) ----------
const studio = { image: null, name: "", boxes: [], drag: null };

async function refreshStudio() {
  try {
    const s = await api("/mangastudio/status");
    const ready = Object.values(s.models).filter((m) => m.ready).map((m) => m.model);
    $("studio-status").textContent = ready.length
      ? `Modèles prêts : ${ready.join(", ")}.`
      : `Mode simulation (GrabCut d'OpenCV) : ${s.missing_dependencies.length
        ? `dépendances absentes (${s.missing_dependencies.join(", ")})` : "poids introuvables"}. `
        + "Les masques ne reflètent pas la qualité de HandSegNet/FootSegNet.";
    $("studio-status").className = ready.length ? "muted" : "warn";
  } catch (error) {
    $("studio-status").textContent = `État indisponible : ${error.message}`;
  }
}

function drawStudio() {
  const canvas = $("studio-canvas");
  if (!studio.image) return;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(studio.image, 0, 0);
  ctx.lineWidth = Math.max(2, canvas.width / 400);
  ctx.strokeStyle = "#ff40a0";
  for (const [x1, y1, x2, y2] of studio.boxes.concat(studio.drag ? [studio.drag] : [])) {
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
  }
}

function canvasPoint(event) {
  const canvas = $("studio-canvas");
  const rect = canvas.getBoundingClientRect();
  return [Math.round((event.clientX - rect.left) * canvas.width / rect.width),
          Math.round((event.clientY - rect.top) * canvas.height / rect.height)];
}

$("studio-file").addEventListener("change", async () => {
  const file = $("studio-file").files[0];
  if (!file) return;
  $("studio-line").textContent = "Envoi de l'image…";
  try {
    const up = await api("/mangastudio/upload", { method: "POST", body: file,
                                                  headers: { "Content-Type": file.type || "image/png" } });
    studio.name = up.image;
    studio.boxes = [];
    const image = new Image();
    image.onload = () => {
      const canvas = $("studio-canvas");
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      studio.image = image;
      canvas.hidden = false;
      drawStudio();
      $("studio-line").textContent = "Trace une boîte autour d'une main ou d'un pied.";
    };
    image.src = up.url;
  } catch (error) {
    $("studio-line").textContent = `Erreur : ${error.message}`;
  }
});

$("studio-canvas").addEventListener("mousedown", (event) => {
  const [x, y] = canvasPoint(event);
  studio.drag = [x, y, x, y];
});
$("studio-canvas").addEventListener("mousemove", (event) => {
  if (!studio.drag) return;
  const [x, y] = canvasPoint(event);
  studio.drag = [studio.drag[0], studio.drag[1], x, y];
  drawStudio();
});
window.addEventListener("mouseup", () => {
  if (!studio.drag) return;
  const [x1, y1, x2, y2] = studio.drag;
  if (Math.abs(x2 - x1) > 4 && Math.abs(y2 - y1) > 4) {
    studio.boxes.push([Math.min(x1, x2), Math.min(y1, y2), Math.max(x1, x2), Math.max(y1, y2)]);
  }
  studio.drag = null;
  drawStudio();
  $("studio-line").textContent = `${studio.boxes.length} boîte(s).`;
});
$("studio-clear").addEventListener("click", () => {
  studio.boxes = [];
  drawStudio();
  $("studio-line").textContent = "Boîtes effacées.";
});

$("studio-run").addEventListener("click", async (event) => {
  if (!studio.name || !studio.boxes.length) {
    $("studio-line").textContent = "Choisis une image et trace au moins une boîte.";
    return;
  }
  const button = event.currentTarget;
  button.disabled = true;
  $("studio-line").textContent = "Segmentation… (le premier appel charge le modèle)";
  try {
    const reply = await post("/mangastudio/segment", { image: studio.name, target: $("studio-target").value,
                                                       boxes: studio.boxes });
    if (!reply.ok) throw new Error(reply.error || "échec");
    const r = reply.result;
    $("studio-result").hidden = false;
    $("studio-preview").src = `${r.preview_url}?t=${Date.now()}`;
    $("studio-mask").src = `${r.mask_url}?t=${Date.now()}`;
    const scores = r.scores.filter((s) => s != null).map((s) => s.toFixed(2)).join(", ");
    $("studio-line").textContent = `${r.backend}${r.simulated ? ` — SIMULATION (${r.reason})` : ""} : `
      + `${r.mask_pixels} pixels en ${r.seconds} s${scores ? ` — confiance du modèle : ${scores}` : ""}`;
  } catch (error) {
    $("studio-line").textContent = `Erreur : ${error.message}`;
  } finally {
    button.disabled = false;
  }
});

// ---------- éther (if_game) ----------
const ether = { shown: false };

function etherRender(result, said) {
  const log = $("ether-log");
  if (said) log.append(el("p", { class: "me" }, `> ${said}`));
  if (result.narration) log.append(el("p", {}, result.narration));
  log.scrollTop = log.scrollHeight;
  $("ether-place").textContent = result.place;
  $("ether-stats").textContent = `tour ${result.turn} · lumière d'Inoue ${result.energy}/${result.max_energy}`
    + ` · ${result.explored} lieux · ${result.riddles_solved} énigmes · sac : ${result.inventory.join(", ") || "vide"}`
    + (result.origin === "modèle local" ? " · lieu inventé par le modèle local" : "");
  const exits = $("ether-exits");
  exits.replaceChildren();
  for (const [direction, target] of Object.entries(result.exits)) {
    const button = el("button", { class: "ghost" }, target ? direction : `${direction} ?`);
    button.addEventListener("click", () => etherAct(direction));
    exits.append(button);
  }
}

async function etherCall(command, payload) {
  if (!modulesByName.if_game || !modulesByName.if_game.running) await post("/modules/if_game/activate");
  const reply = await post(`/modules/if_game/command/${command}`, payload || {});
  if (!reply.ok) throw new Error(reply.error || "erreur du jeu");
  return reply.result;
}

async function etherAct(text) {
  $("ether-input").disabled = true;
  try {
    etherRender(await etherCall("act", { text }), text);
  } catch (error) {
    $("ether-log").append(el("p", { class: "warn" }, `Erreur : ${error.message}`));
  } finally {
    $("ether-input").disabled = false;
    $("ether-input").focus();
  }
}

$("ether-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const text = $("ether-input").value.trim();
  if (!text) return;
  $("ether-input").value = "";
  etherAct(text);
});
$("ether-new").addEventListener("click", async () => {
  try {
    $("ether-log").replaceChildren();
    etherRender(await etherCall("new", { seed: Number($("ether-seed").value) || 0 }));
  } catch (error) {
    $("ether-log").append(el("p", { class: "warn" }, `Erreur : ${error.message}`));
  }
});

async function refreshEther() {
  try {
    const result = await etherCall("state", {});
    $("ether-log").replaceChildren(...result.journal.map((line) => el("p", {}, line)));
    etherRender({ ...result, narration: "" });
  } catch (error) {
    $("ether-log").replaceChildren(el("p", { class: "warn" }, `Jeu indisponible : ${error.message}`));
  }
}

// ---------- journal ----------
async function refreshEvents() {
  try {
    const events = await api("/events?limit=100");
    const body = $("events");
    body.replaceChildren();
    for (const event of events.reverse()) {
      const time = new Date(event.ts * 1000).toLocaleTimeString("fr-FR");
      const payload = JSON.stringify(event.payload);
      body.append(el("tr", {}, el("td", {}, time), el("td", {}, event.topic),
        el("td", {}, payload.length > 160 ? `${payload.slice(0, 160)}…` : payload)));
    }
  } catch (error) {
    $("events").replaceChildren(el("tr", {}, el("td", { colspan: "3" }, `Journal indisponible : ${error.message}`)));
  }
}

// ---------- rafraîchissement ----------
function refreshAll() {
  refreshHub();
  refreshModules();
  const tab = currentTab();
  if (tab === "accueil") refreshGpus();
  if (tab === "jeu") refreshGame();
  if (tab === "connaissances") refreshKnowledge();
  if (tab === "journal") refreshEvents();
  if (tab === "studio" && !studio.statusShown) { studio.statusShown = true; refreshStudio(); }
  if (tab === "ether" && !ether.shown) { ether.shown = true; refreshEther(); }
}
showTab(currentTab());
setInterval(refreshAll, 3000);
