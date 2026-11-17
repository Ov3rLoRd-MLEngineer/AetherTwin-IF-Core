"use strict";
// Tableau de bord du Hub : lit l'API locale (même origine), aucune ressource externe.

const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "onclick") node.addEventListener("click", value);
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child instanceof Node ? child : String(child ?? ""));
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: options.body ? { "Content-Type": "application/json" } : {},
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `erreur ${response.status}`);
  return data;
}

const gib = (mib) => (mib / 1024).toFixed(1);

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
        el("b", {}, `GPU ${gpu.index} — ${gpu.name}`),
        bar,
        el("span", {}, `VRAM ${gib(gpu.vram_used_mib)} / ${gib(gpu.vram_total_mib)} Gio (${pct} %)`),
        el("div", { class: "muted" }, extra)));
    }
  } catch (error) {
    $("gpus").replaceChildren(el("p", { class: "muted" }, `Mesure impossible : ${error.message}`));
  }
}

async function toggleModule(module, button) {
  button.disabled = true;
  try {
    const action = module.active ? "deactivate" : "activate";
    const result = await api(`/modules/${module.name}/${action}`, { method: "POST" });
    if (result.verdict && result.verdict !== "accordé") alert(`${module.name} : ${result.verdict} — ${result.reason}`);
  } catch (error) {
    alert(`${module.name} : ${error.message}`);
  }
  setTimeout(refreshModules, 800);
}

async function refreshModules() {
  try {
    const modules = await api("/modules");
    const body = $("modules");
    body.replaceChildren();
    for (const module of modules) {
      let state = "arrêté", cls = "";
      if (module.active && module.running) { state = module.auto ? "actif (déclencheur)" : "actif"; cls = "state-on"; }
      else if (module.waiting_vram) { state = "en attente de VRAM"; cls = "state-wait"; }
      else if (module.active) { state = "démarrage…"; cls = "state-wait"; }
      if (module.error) cls = "state-err";
      const detail = module.error || (module.health && module.health.detail) || module.description;
      const button = el("button", { class: module.active ? "ghost" : "" }, module.active ? "Arrêter" : "Lancer");
      button.addEventListener("click", () => toggleModule(module, button));
      body.append(el("tr", {},
        el("td", {}, el("b", {}, module.name), el("div", { class: "muted" }, `v${module.version}`)),
        el("td", { class: cls }, state),
        el("td", {}, detail),
        el("td", {}, button)));
    }
  } catch (error) {
    $("modules").replaceChildren(el("tr", {}, el("td", { colspan: "4" }, `Liste indisponible : ${error.message}`)));
  }
}

$("ask-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter;
  const out = $("ask-answer");
  button.disabled = true;
  out.hidden = false;
  out.textContent = "Le modèle local réfléchit… (le premier chargement prend 10 à 20 s)";
  try {
    const result = await api("/ask", {
      method: "POST",
      body: JSON.stringify({ prompt: $("ask-prompt").value, with_context: $("ask-context").checked }),
    });
    out.textContent = `${result.answer}\n\n— ${result.model}`;
  } catch (error) {
    out.textContent = `Erreur : ${error.message}`;
  } finally {
    button.disabled = false;
  }
});

let currentExercise = null;

async function professor(command, payload, button) {
  if (button) button.disabled = true;
  try {
    const reply = await api(`/modules/genesis_lab/command/${command}`, {
      method: "POST", body: JSON.stringify(payload || {}),
    });
    if (!reply.ok) throw new Error(reply.error || "erreur du module");
    return reply.result;
  } catch (error) {
    const box = $("prof-result");
    box.hidden = false;
    box.textContent = error.message.includes("pas lancé")
      ? "Le module genesis_lab n'est pas lancé : clique sur « Lancer » dans la liste des modules."
      : `Erreur : ${error.message}`;
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
  box.replaceChildren(
    el("p", { class: result.correct ? "good" : "badans" },
      result.correct ? "Juste !" : `Pas tout à fait : la réponse attendue était ${result.expected} ${result.unit}`),
    el("p", {}, result.explanation),
    el("p", { class: "muted" },
      `Niveau : ${result.level_before} → ${result.level_after}`
      + (result.sources && result.sources.length ? ` — sources : ${result.sources.map((s) => s.title || s.url).join(", ")}` : "")));
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

function refreshAll() {
  refreshHub();
  refreshGpus();
  refreshModules();
}
refreshAll();
setInterval(refreshAll, 3000);
