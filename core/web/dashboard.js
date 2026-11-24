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
  // Garde-fou : une requête sans réponse est abandonnée (le Hub répond lui-même en 4 min au plus).
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs || 270000);
  let response;
  try {
    response = await fetch(path, { ...options, headers, signal: controller.signal });
  } catch (error) {
    throw new Error(error.name === "AbortError" ? "le Hub n'a pas répondu à temps (requête abandonnée)" : error.message);
  } finally {
    clearTimeout(timer);
  }
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

// ---------- sous-onglets : un panneau [data-subtabs] montre une seule famille de sections [data-sub] ----------
const SUBTAB_KEY = "hub.sousonglets";
function subtabMemory() {
  try { return JSON.parse(localStorage.getItem(SUBTAB_KEY) || "{}") || {}; } catch { return {}; }
}
function currentSubtab(panelName) {
  const panel = document.querySelector(`.panel[data-panel="${panelName}"]`);
  const selected = panel && panel.querySelector(":scope > .subtabs [aria-selected='true']");
  return selected ? selected.dataset.sub : "";
}
function showSubtab(panel, label) {
  const sections = [...panel.querySelectorAll(":scope > section[data-sub]")];
  if (!sections.some((s) => s.dataset.sub === label)) label = sections[0]?.dataset.sub || "";
  for (const section of sections) section.classList.toggle("sub-off", section.dataset.sub !== label);
  for (const button of panel.querySelectorAll(":scope > .subtabs button")) {
    button.setAttribute("aria-selected", String(button.dataset.sub === label));
  }
  const memory = subtabMemory();
  memory[panel.dataset.panel] = label;
  try { localStorage.setItem(SUBTAB_KEY, JSON.stringify(memory)); } catch { /* mémoire facultative */ }
  document.dispatchEvent(new CustomEvent("subtab", { detail: { panel: panel.dataset.panel, label } }));
}
function setupSubtabs() {
  const memory = subtabMemory();
  for (const panel of document.querySelectorAll(".panel[data-subtabs]")) {
    const labels = [...new Set([...panel.querySelectorAll(":scope > section[data-sub]")].map((s) => s.dataset.sub))];
    if (labels.length < 2) continue;
    const bar = el("div", { class: "subtabs", role: "tablist", "aria-label": "Sous-onglets" });
    for (const label of labels) {
      const button = el("button", { type: "button", role: "tab", "data-sub": label, "aria-selected": "false" }, label);
      button.addEventListener("click", () => showSubtab(panel, label));
      bar.append(button);
    }
    panel.prepend(bar);
    showSubtab(panel, memory[panel.dataset.panel] || labels[0]);
  }
}
setupSubtabs();

// ---------- en-tête ----------
async function refreshHub() {
  try {
    const health = await api("/health");
    const minutes = Math.floor(health.uptime_s / 60);
    $("hub-line").textContent = `Hub en marche depuis ${minutes} min — ${health.os} — GPU via ${health.gpu_backend}`;
    const inoue = health.inoue || {};
    if (inoue.budget_gb !== undefined) {
      const pct = inoue.budget_gb ? Math.min(100, Math.round(100 * inoue.allocated_gb / inoue.budget_gb)) : 0;
      $("inoue-bar").style.width = `${pct}%`;
      $("inoue-line").textContent = `Réservé : ${inoue.allocated_gb} Go sur ${inoue.budget_gb} Go de budget `
        + `(VRAM totale ${inoue.total_gb} Go, mesurée en usage : ${inoue.measured_used_gb} Go, `
        + `dont ${inoue.unaccounted_gb ?? 0} Go hors réservations : jeux, navigateur, contextes CUDA)`
        + (inoue.degraded ? " — GPU non mesurés : tout est refusé par prudence" : "");
      $("inoue-warn").hidden = !inoue.over_budget;
      const entries = Object.entries(inoue.allocations || {});
      $("inoue-list").replaceChildren(...(entries.length
        ? entries.map(([who, gb]) => el("li", {}, `${who.replace(/^llm-small:/, "petit modèle ")
          .replace(/^llm:/, "modèle ")} : ${Number(gb).toFixed(1)} Go`))
        : [el("li", { class: "muted" }, "Aucune réservation en cours.")]));
    }
    const llm = health.llm || {};
    const loaded = (llm.loaded || []).map((m) => (typeof m === "string" ? m : m.name)).join(", ");
    // modèles en mémoire, déchargeables d'un clic (libérer la VRAM avant de jouer)
    $("llm-loaded").replaceChildren(...(llm.loaded || []).map((m) => {
      const button = el("button", { type: "button", class: "ghost" }, "Décharger");
      button.addEventListener("click", async () => {
        button.disabled = true;
        try { await post("/llm/unload", { model: m.name }); } catch (error) { alert(error.message); }
        refreshHub();
      });
      return el("li", {}, `${m.name} — ${m.vram_gb} Go de VRAM, contexte ${m.context} `, button);
    }));
    $("llm-line").textContent = llm.reachable
      ? `Ollama joignable (${llm.host}) — modèle par défaut : ${llm.default_model}, contexte ${llm.num_ctx}`
        + ` — chargé : ${loaded || "aucun"}`
      : `Ollama injoignable (${llm.host}) : ${llm.error || "?"}`;
    showStrata(llm.strata);
  } catch (error) {
    $("hub-line").textContent = `Hub injoignable : ${error.message}`;
  }
}

// ---------- Strata (moteur secondaire optionnel, gros modèles MoE) ----------
const STRATA_TEXT = {
  "désactivé": "désactivé (section strata de config/local.yaml)",
  "non installé": "non installé (strata.launcher dans config/local.yaml)",
  "arrêté": "arrêté : les questions strata/… passent sur Ollama",
  "démarrage": "démarrage en cours (chargement du modèle)…",
  "actif": "actif",
};
function showStrata(strata) {
  $("strata-line").hidden = !strata;
  $("strata-actions").hidden = !strata || !strata.enabled || !strata.installed;
  if (!strata) return;
  const models = (strata.models || []).join(", ");
  $("strata-line").textContent = `Strata (${strata.host}) : ${STRATA_TEXT[strata.status] || strata.status}`
    + (models ? ` — modèles : ${models}` : "")
    + (strata.status === "actif" ? " — tient la place du gros modèle : les gros modèles Ollama attendent son arrêt" : "");
  $("strata-start").disabled = ["actif", "démarrage"].includes(strata.status);
  $("strata-stop").disabled = strata.status !== "actif";
}
for (const [id, path, ask] of [["strata-start", "/strata/start", ""],
  ["strata-stop", "/strata/stop", "Arrêter Strata ? Son modèle sort de la mémoire (VRAM et RAM)."]]) {
  $(id).addEventListener("click", async () => {
    if (ask && !confirm(ask)) return;
    $(id).disabled = true;
    try { await post(path); } catch (error) { alert(error.message); }
    refreshHub();
  });
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
const chat = { history: [], busy: false };

// Markdown minimal, sans innerHTML : **gras**, *italique*, `code`, listes « - » ou « 1. », titres « # ».
function inlineMarkdown(text) {
  const parts = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith("**")) parts.push(el("strong", {}, token.slice(2, -2)));
    else if (token.startsWith("`")) parts.push(el("code", {}, token.slice(1, -1)));
    else parts.push(el("em", {}, token.slice(1, -1)));
    last = match.index + token.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function renderMarkdown(target, text) {
  const nodes = [];
  let list = null;
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const item = line.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
    if (item) {
      if (!list) { list = el(/^\s*\d/.test(line) ? "ol" : "ul"); nodes.push(list); }
      list.append(el("li", {}, ...inlineMarkdown(item[1])));
      continue;
    }
    list = null;
    const title = line.match(/^#{1,4}\s+(.*)$/);
    if (title) nodes.push(el("strong", { class: "md-title" }, ...inlineMarkdown(title[1])));
    else if (line.trim()) nodes.push(el("p", {}, ...inlineMarkdown(line)));
  }
  target.replaceChildren(...nodes);
}

function chatBubble(role, text) {
  const bubble = el("div", { class: `msg ${role}` }, text);
  $("chat").append(bubble);
  $("chat").scrollTop = $("chat").scrollHeight;
  return bubble;
}

$("chat-new").addEventListener("click", () => {
  chat.history = [];
  $("chat").replaceChildren();
  $("ask-prompt").focus();
});
$("ask-prompt").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("ask-form").requestSubmit();
  }
});

$("ask-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const prompt = $("ask-prompt").value.trim();
  if (!prompt || chat.busy) return;
  chat.busy = true;
  const button = $("ask-form").querySelector("button[type=submit]");
  button.disabled = true;
  $("ask-prompt").value = "";
  document.dispatchEvent(new CustomEvent("aether-ask"));  // voice.js : coupe la voix en cours
  chatBubble("user", prompt);
  const out = chatBubble("assistant", "Le modèle local réfléchit… (le premier chargement prend 10 à 20 s)");
  let text = "";
  try {
    // réponse mot à mot : une ligne JSON par morceau ; la conversation précédente est jointe
    const response = await fetch("/ask/stream", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, with_context: $("ask-context").checked, history: chat.history,
                             use_knowledge: $("ask-knowledge").checked }),
    });
    let sources = [];
    if (!response.ok || !response.body) throw new Error(`erreur ${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines.filter(Boolean)) {
        const msg = JSON.parse(line);
        if (msg.text !== undefined) {
          text += msg.text;
          renderMarkdown(out, text);
          document.dispatchEvent(new CustomEvent("aether-reply", { detail: { text, done: false } }));
          $("chat").scrollTop = $("chat").scrollHeight;
        } else if (msg.sources) {
          sources = msg.sources;
        } else if (msg.done) {
          document.dispatchEvent(new CustomEvent("aether-reply", { detail: { text, done: true } }));
          if (sources.length) {
            const line = el("span", { class: "meta" }, "Sources : ");
            sources.forEach((s, i) => {
              if (i) line.append(" · ");
              line.append(`[${s.n}] `, el("a", { href: s.url, target: "_blank", rel: "noopener" }, s.title),
                          ` (${s.license})`);
            });
            out.append(line);
          } else if ($("ask-knowledge").checked) {
            out.append(el("span", { class: "meta" }, "Rien de pertinent dans la base pour cette question."));
          }
          out.append(el("span", { class: "meta" }, `${msg.done.model}, ${msg.done.seconds} s`));
        } else if (msg.error) {
          throw new Error(msg.error);
        }
      }
    }
    chat.history.push({ role: "user", content: prompt }, { role: "assistant", content: text });
    chat.history = chat.history.slice(-12);
  } catch (error) {
    out.textContent = `Erreur : ${error.message}`;
    out.classList.add("warn");
  } finally {
    chat.busy = false;
    button.disabled = false;
    $("ask-prompt").focus();
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

// ---------- laboratoire FASTA (calcul déterministe de genesis_lab) ----------
// Exemple : début du gène de la GFP (séquence publique), suivi d'un codon stop, entouré de quelques bases.
const LAB_EXAMPLE = ">exemple_gfp debut du gene de la GFP (sequence publique)\n"
  + "CCTTAGATGGCTAGCAAAGGAGAAGAACTTTTCACTGGAGTTGTCCCAATTCTTGTTGAATTAGATGGTGATGTTAATGGGCACAAATTTTCTGTC\n"
  + "AGTGGAGAGGGTGAAGGTGATGCTACATACGGAAAGCTTACCCTTAAATTTATTTGCACTACTGGAAAATGATAACGGCCTT";

$("lab-example").addEventListener("click", () => { $("lab-fasta").value = LAB_EXAMPLE; $("lab-min").value = 30; });

$("lab-run").addEventListener("click", async (event) => {
  const box = $("lab-result");
  box.replaceChildren(el("p", { class: "muted" }, "Calcul…"));
  const records = await professor("compute", {
    tool: "bio.analyze_fasta",
    args: { text: $("lab-fasta").value, min_orf_aa: Number($("lab-min").value) || 30 },
  }, event.currentTarget);
  if (!records) { box.replaceChildren(el("p", { class: "warn" }, $("prof-result").textContent)); return; }
  box.replaceChildren(...records.map((r) => {
    const counts = Object.entries(r.base_counts).map(([b, n]) => `${b} ${n}`).join(" · ");
    const orfs = el("table", {}, el("thead", {}, el("tr", {}, ...["Brin", "Cadre", "Début", "Fin", "Acides aminés"]
      .map((h) => el("th", {}, h)))));
    const rows = el("tbody");
    for (const o of r.orfs) {
      rows.append(el("tr", {}, el("td", {}, o.strand), el("td", {}, String(o.frame)), el("td", {}, String(o.start)),
                      el("td", {}, String(o.end)), el("td", {}, String(o.protein.length))));
    }
    orfs.append(rows);
    return el("div", { class: "lab-record" },
      el("h3", {}, `${r.name}${r.description ? ` — ${r.description}` : ""}`),
      el("p", {}, `${r.length} bases · GC ${r.gc_percent} % · ${counts} · ${r.orf_count} ORF`),
      ...(r.orfs.length ? [orfs] : [el("p", { class: "muted" }, "Aucun ORF de cette longueur.")]),
      ...(r.longest_protein ? [el("p", { class: "muted" }, "Protéine du plus long ORF :"),
                                el("div", { class: "protein" }, r.longest_protein)] : []));
  }));
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
// Un chapitre : les pages choisies sont traduites l'une après l'autre (ordre des noms de fichiers),
// avec le même glossaire ; chaque page reste consultable et corrigeable depuis la galerie.
const chapter = { pages: [], current: -1 };

function pageSummary(metrics) {
  return `${metrics.bubbles} bulles traduites en ${metrics.total_s} s`
    + (metrics.rejected_by_ocr ? ` (${metrics.rejected_by_ocr} zones écartées : pas de texte)` : "")
    + (metrics.vram_peak_mib ? ` — VRAM au plus haut : ${gib(metrics.vram_peak_mib)} Gio` : "");
}

// enregistre une image du Hub sous un nom parlant (« page_12_fr.png ») dans les téléchargements du navigateur
function saveImage(url, originalName) {
  const stem = (originalName || "page").replace(/\.[^.]+$/, "").replace(/[^\w\-. ]+/g, "_");
  const link = el("a", { href: `${url}?t=${Date.now()}`, download: `${stem}_fr.png` });
  document.body.append(link);
  link.click();
  link.remove();
}

function showPage(index) {
  const page = chapter.pages[index];
  if (!page) return;
  $("scan-save-row").hidden = !chapter.pages.some((p) => p.outputUrl);
  $("scan-save").disabled = !page.outputUrl;
  chapter.current = index;
  $("scan-images").hidden = false;
  $("scan-before").src = page.inputUrl;
  $("scan-after").src = page.outputUrl ? `${page.outputUrl}?t=${Date.now()}` : "";
  if (!page.outputUrl) $("scan-after").removeAttribute("src");
  for (const [i, thumb] of [...$("scan-gallery").children].entries()) {
    thumb.setAttribute("aria-current", String(i === index));
  }
  if (page.bubbles) showBubbleEditor(page.bubbles, page.outputUrl.split("/").pop());
  else $("scan-bubbles").replaceChildren();
}

$("scan-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const files = [...$("scan-file").files].sort((a, b) => a.name.localeCompare(b.name, "fr", { numeric: true }));
  if (!files.length) return;
  const button = $("scan-form").querySelector("button[type=submit]");  // `event.submitter` est vide sans clic
  button.disabled = true;
  chapter.pages = files.map((file) => ({ name: file.name, inputUrl: URL.createObjectURL(file) }));
  $("scan-gallery").replaceChildren(...chapter.pages.map((page, i) => {
    const thumb = el("button", { type: "button", title: page.name }, el("img", { src: page.inputUrl, alt: "" }),
                     `${i + 1}. en attente`);
    thumb.addEventListener("click", () => showPage(i));
    return thumb;
  }));
  const query = new URLSearchParams({ series: $("scan-series").value.trim(), no_llm: $("scan-nollm").checked,
                                      lang: $("scan-lang").value, layout: $("scan-layout").value });
  let done = 0, failed = 0;
  const started = performance.now();
  for (const [i, file] of files.entries()) {
    const thumb = $("scan-gallery").children[i];
    thumb.lastChild.textContent = `${i + 1}. en cours…`;
    $("scan-line").textContent = `Page ${i + 1}/${files.length} : ${file.name} — détection, lecture, effacement, traduction…`;
    showPage(i);
    try {
      const reply = await api(`/scantrad/translate?${query}`, {
        method: "POST", body: file, headers: { "Content-Type": file.type || "image/png" },
      });
      if (!reply.ok) throw new Error(reply.error || "échec");
      Object.assign(chapter.pages[i], { outputUrl: reply.output_url, bubbles: reply.result.bubbles,
                                        metrics: reply.result.metrics });
      thumb.querySelector("img").src = `${reply.output_url}?t=${Date.now()}`;
      thumb.lastChild.textContent = `${i + 1}. ${reply.result.metrics.bubbles} bulles`;
      done += 1;
      showPage(i);
    } catch (error) {
      failed += 1;
      thumb.lastChild.textContent = `${i + 1}. erreur`;
      chapter.pages[i].error = error.message;
    }
  }
  const seconds = Math.round((performance.now() - started) / 1000);
  const last = chapter.pages[chapter.current];
  $("scan-line").textContent = files.length === 1 && last && last.metrics ? pageSummary(last.metrics)
    : `${done} page(s) traduite(s) en ${seconds} s${failed ? `, ${failed} en erreur` : ""}. `
      + "Clique sur une vignette pour la revoir ou la corriger.";
  if (files.length === 1 && last && last.error) $("scan-line").textContent = `Erreur : ${last.error}`;
  button.disabled = false;
});

// texte d'une page : chaque bulle, son texte d'origine et sa traduction, dans l'ordre de lecture
function pageText(name, bubbles) {
  const lines = [`=== ${name} ===`];
  for (const b of bubbles || []) {
    const tag = b.kind === "annexe" ? " (annexe)" : "";
    lines.push(`${b.index}${tag}. ${b.source || "—"}`, `   → ${b.translation || "—"}`);
  }
  return lines.join("\n");
}

function saveText(text, originalName) {
  const stem = (originalName || "page").replace(/\.[^.]+$/, "").replace(/[^\w\-. ]+/g, "_");
  const url = URL.createObjectURL(new Blob([`${text}\n`], { type: "text/plain;charset=utf-8" }));
  const link = el("a", { href: url, download: `${stem}_fr.txt` });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// lecture d'un .txt au format de l'export : « === nom === », puis « 3. texte d'origine » / « → traduction »
function parseTranslationText(text) {
  const pages = [];
  let page = null, last = null;
  for (const raw of text.replace(/\r/g, "").split("\n")) {
    const header = raw.match(/^===\s*(.+?)\s*===\s*$/);
    const entry = raw.match(/^\s*(\d+)(?:\s*\(annexe\))?\.\s?(.*)$/);
    const arrow = raw.match(/^\s*(?:→|->)\s?(.*)$/);
    if (header) { page = { name: header[1], entries: {} }; pages.push(page); last = null; continue; }
    if (!page) { page = { name: "", entries: {} }; pages.push(page); }
    if (entry) { last = entry[1]; page.entries[last] = { source: entry[2].trim(), translation: "" }; continue; }
    if (arrow && last) {
      const value = arrow[1].trim();
      page.entries[last].translation = value === "—" ? "" : value;
    }
  }
  return pages.filter((p) => Object.keys(p.entries).length);
}

async function readTextFile(input) {
  const file = input.files[0];
  input.value = "";  // on peut réimporter le même fichier
  if (!file) return null;
  if (file.size > 2 * 1024 * 1024) throw new Error("fichier de plus de 2 Mo");
  const pages = parseTranslationText(await file.text());
  if (!pages.length) throw new Error("aucune bulle reconnue : format attendu « 1. texte » puis « → traduction »");
  return pages;
}

$("scan-import").addEventListener("change", async () => {
  try {
    const pages = await readTextFile($("scan-import"));
    if (!pages) return;
    let applied = 0, skipped = 0;
    for (const section of pages) {
      // la page du même nom ; un fichier d'une seule page sans nom correspondant va sur la page affichée
      let index = chapter.pages.findIndex((p) => p.name === section.name && p.outputUrl);
      if (index < 0 && pages.length === 1) index = chapter.current;
      const page = chapter.pages[index];
      if (!page || !page.outputUrl) { skipped += 1; continue; }
      const translations = {};
      for (const [n, e] of Object.entries(section.entries)) {
        if (page.bubbles.some((b) => String(b.index) === n)) translations[n] = e.translation;
      }
      const reply = await post("/scantrad/retypeset", { output: page.outputUrl.split("/").pop(), translations });
      if (!reply.ok) throw new Error(reply.error || "échec");
      page.bubbles = reply.result.bubbles;
      const thumb = $("scan-gallery").children[index];
      if (thumb) thumb.querySelector("img").src = `${page.outputUrl}?t=${Date.now()}`;
      applied += 1;
    }
    showPage(chapter.current);
    $("scan-line").textContent = `${applied} page(s) mise(s) à jour depuis le fichier`
      + (skipped ? ` ; ${skipped} section(s) sans page traduite du même nom, ignorée(s)` : "") + ".";
  } catch (error) {
    $("scan-line").textContent = `Import impossible : ${error.message}`;
  }
});

$("man-import").addEventListener("change", async () => {
  try {
    const pages = await readTextFile($("man-import"));
    if (!pages) return;
    const section = pages.find((p) => p.name === manual.fileName) || pages[0];
    const count = Object.keys(section.entries).length;
    let applied = 0;
    for (const [n, e] of Object.entries(section.entries)) {
      const zone = manual.zones[Number(n) - 1];
      if (!zone) continue;
      zone.translation = e.translation;
      if (!zone.source && e.source !== "—") zone.source = e.source;
      applied += 1;
    }
    renderManualRows();
    manualLine(`${applied} traduction(s) importée(s) sur ${count}`
      + (applied < count ? ` (${count - applied} sans zone de même numéro : trace les zones d'abord)` : "")
      + ". Vérifie, puis « Réincruster ».");
  } catch (error) {
    manualLine(`Import impossible : ${error.message}`);
  }
});

$("scan-text").addEventListener("click", () => {
  const page = chapter.pages[chapter.current];
  if (page && page.bubbles) saveText(pageText(page.name, page.bubbles), page.name);
});
$("scan-text-all").addEventListener("click", () => {
  const done = chapter.pages.filter((p) => p.bubbles);
  if (done.length) saveText(done.map((p) => pageText(p.name, p.bubbles)).join("\n\n"), `${done[0].name}_chapitre`);
});

$("scan-save").addEventListener("click", () => {
  const page = chapter.pages[chapter.current];
  if (page && page.outputUrl) saveImage(page.outputUrl, page.name);
});
$("scan-save-all").addEventListener("click", async () => {
  for (const page of chapter.pages.filter((p) => p.outputUrl)) {
    saveImage(page.outputUrl, page.name);
    await new Promise((resolve) => setTimeout(resolve, 400));  // le navigateur accepte mieux des envois espacés
  }
});

// bulles éditables : corriger une traduction puis réincruster, sans relancer l'OCR ni le modèle
function showBubbleEditor(bubbles, outputName) {
  const box = $("scan-bubbles");
  box.replaceChildren();
  if (!bubbles.length) return;
  const table = el("table", { class: "bubble-edit" },
    el("thead", {}, el("tr", {}, el("th", {}, "#"), el("th", {}, "Texte lu"), el("th", {}, "Traduction"))));
  const body = el("tbody");
  for (const b of bubbles) {
    const input = el("input", { class: "full", value: b.translation || "", "data-index": String(b.index),
                                "aria-label": `traduction de la bulle ${b.index}` });
    body.append(el("tr", {}, el("td", {}, String(b.index)), el("td", { lang: "ja" }, b.source || "—"),
                    el("td", {}, input)));
  }
  table.append(body);
  const button = el("button", { type: "button" }, "Réincruster mes corrections");
  const line = el("span", { class: "muted" });
  button.addEventListener("click", async () => {
    button.disabled = true;
    line.textContent = "Réincrustation…";
    const translations = {};
    for (const input of body.querySelectorAll("input")) translations[input.dataset.index] = input.value;
    try {
      const reply = await post("/scantrad/retypeset", { output: outputName, translations });
      if (!reply.ok) throw new Error(reply.error || "échec");
      $("scan-after").src = `${reply.output_url}?t=${Date.now()}`;
      const page = chapter.pages[chapter.current];
      if (page && page.outputUrl === reply.output_url) {  // la galerie garde la version corrigée
        page.bubbles = reply.result.bubbles;
        const thumb = $("scan-gallery").children[chapter.current];
        if (thumb) thumb.querySelector("img").src = `${reply.output_url}?t=${Date.now()}`;
      }
      line.textContent = "Page mise à jour.";
    } catch (error) {
      line.textContent = `Erreur : ${error.message}`;
    } finally {
      button.disabled = false;
    }
  });
  box.append(table, el("div", { class: "row" }, button, line));
}

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

// ---------- scantrad, mode manuel ----------
// La page affichée est un canevas « base » (taille réelle de l'image) : la gomme y peint en blanc. Les zones
// sont dessinées par-dessus, numérotées dans l'ordre de tracé = ordre de lecture.
const manual = { name: "", base: null, zones: [], tool: "zones", drag: null, stroke: null, cursor: null,
                 undo: [], painted: false };
const MAX_UNDO = 12;

function manualLine(text) { $("man-line").textContent = text; }

function drawManual() {
  const canvas = $("man-canvas");
  if (!manual.base) return;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(manual.base, 0, 0);
  if (manual.maskShown) {  // zones peintes pour « Reconstruire », en rouge translucide
    ctx.save();
    ctx.globalAlpha = 0.5;
    ctx.drawImage(manual.maskShown, 0, 0);
    ctx.restore();
  }
  const unit = Math.max(2, canvas.width / 400);
  ctx.lineWidth = unit;
  ctx.font = `bold ${Math.round(unit * 9)}px sans-serif`;
  ctx.textBaseline = "top";
  const boxes = manual.zones.map((z) => z.box);
  if (manual.drag) {
    const [x1, y1, x2, y2] = manual.drag;
    boxes.push([Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1)]);
  }
  for (const [i, [x, y, w, h]] of boxes.entries()) {
    const zone = manual.zones[i];
    const annex = zone ? zone.kind === "annexe" : manual.tool === "annex";
    const color = annex ? "#ff9f43" : "#7a8cff";  // annexes en orange
    ctx.strokeStyle = manual.tool === "brush" ? `${color}73` : color;
    ctx.strokeRect(x, y, w, h);
    const label = annex ? `${i + 1} annexe` : String(i + 1);
    const pad = unit * 2;
    const tw = ctx.measureText(label).width + 2 * pad;
    const th = unit * 9 + 2 * pad;
    const ly = y >= th ? y - th : y;  // le numéro au-dessus de la zone : il ne cache pas le texte à lire
    ctx.fillStyle = color;
    ctx.fillRect(x, ly, tw, th);
    ctx.fillStyle = "#fff";
    ctx.fillText(label, x + pad, ly + pad);
  }
  if ((manual.tool === "brush" || manual.tool === "rebuild") && manual.cursor) {
    ctx.strokeStyle = manual.tool === "rebuild" ? "#ff2d55" : "#ff5a7a";
    ctx.beginPath();
    ctx.arc(manual.cursor[0], manual.cursor[1], brushRadius(), 0, 2 * Math.PI);
    ctx.stroke();
  }
}

function brushRadius() {  // le curseur est réglé en pixels d'écran, la gomme travaille en pixels de l'image
  const canvas = $("man-canvas");
  const shown = canvas.getBoundingClientRect().width || canvas.width;
  return (Number($("man-brush").value) / 2) * canvas.width / shown;
}

function manualPoint(event) {
  const canvas = $("man-canvas");
  const rect = canvas.getBoundingClientRect();
  return [Math.round((event.clientX - rect.left) * canvas.width / rect.width),
          Math.round((event.clientY - rect.top) * canvas.height / rect.height)];
}

function pushPaintUndo() {
  const ctx = manual.base.getContext("2d");
  manual.undo.push({ kind: "paint", data: ctx.getImageData(0, 0, manual.base.width, manual.base.height),
                     painted: manual.painted });
  const paints = manual.undo.filter((u) => u.kind === "paint");
  if (paints.length > MAX_UNDO) manual.undo.splice(manual.undo.indexOf(paints[0]), 1);  // mémoire bornée
}

function strokeOn(canvas, from, to, color) {
  const ctx = canvas.getContext("2d");
  ctx.strokeStyle = color;
  ctx.lineCap = "round";
  ctx.lineWidth = 2 * brushRadius();
  ctx.beginPath();
  ctx.moveTo(from[0], from[1]);
  ctx.lineTo(to[0], to[1]);
  ctx.stroke();
}

function paintAt(from, to) {
  if (manual.tool === "rebuild") {  // masque à redessiner : blanc pour le serveur, rouge pour l'écran
    if (!manual.mask) {
      for (const key of ["mask", "maskShown"]) {
        manual[key] = document.createElement("canvas");
        manual[key].width = manual.base.width;
        manual[key].height = manual.base.height;
      }
    }
    strokeOn(manual.mask, from, to, "#fff");
    strokeOn(manual.maskShown, from, to, "#ff2d55");
    return;
  }
  strokeOn(manual.base, from, to, "#fff");
  manual.painted = true;
}

function clearMask() { manual.mask = null; manual.maskShown = null; }

function setTool(tool) {
  manual.tool = tool;
  for (const [id, name] of [["man-tool-zones", "zones"], ["man-tool-annex", "annex"], ["man-tool-brush", "brush"],
                            ["man-tool-rebuild", "rebuild"]]) {
    $(id).setAttribute("aria-pressed", String(tool === name));
  }
  $("man-canvas").style.cursor = tool === "brush" || tool === "rebuild" ? "none" : "crosshair";
  drawManual();
}
$("man-tool-zones").addEventListener("click", () => setTool("zones"));
$("man-tool-annex").addEventListener("click", () => setTool("annex"));
$("man-tool-brush").addEventListener("click", () => setTool("brush"));
$("man-tool-rebuild").addEventListener("click", () => setTool("rebuild"));

function loadBase(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      const base = document.createElement("canvas");
      base.width = image.naturalWidth;
      base.height = image.naturalHeight;
      base.getContext("2d").drawImage(image, 0, 0);
      resolve(base);
    };
    image.onerror = () => reject(new Error("image illisible"));
    image.src = url;
  });
}

$("man-file").addEventListener("change", async () => {
  const file = $("man-file").files[0];
  if (!file) return;
  manualLine("Envoi de la page…");
  try {
    const up = await api("/scantrad/upload", { method: "POST", body: file,
                                               headers: { "Content-Type": file.type || "image/png" } });
    Object.assign(manual, { name: up.image, fileName: file.name, zones: [], undo: [], painted: false,
                            base: await loadBase(up.url), outputUrl: "", mask: null, maskShown: null });
    const canvas = $("man-canvas");
    canvas.width = manual.base.width;
    canvas.height = manual.base.height;
    $("man-view").hidden = false;
    $("man-zoom").hidden = false;
    setManualZoom(manualFitScale());
    requestAnimationFrame(() => setManualZoom(manualFitScale()));  // une fois la vue réellement mise en page
    $("man-result").hidden = true;
    setTool("zones");
    renderManualRows();
    manualLine("Trace une boîte autour de chaque bulle, dans l'ordre de lecture.");
  } catch (error) {
    manualLine(`Erreur : ${error.message}`);
  }
});

// zoom à la molette : de « toute la page visible » jusqu'à la taille réelle de l'image (pas au-delà),
// en gardant sous le curseur le point visé ; la vue défile quand l'image dépasse
function manualFitScale() {
  const width = $("man-view").clientWidth || $("man-view").parentElement.clientWidth || 800;
  return Math.min(1, width / manual.base.width);
}

function setManualZoom(scale) {
  manual.zoom = scale;
  const canvas = $("man-canvas");
  canvas.style.maxWidth = "none";
  canvas.style.width = `${Math.round(manual.base.width * scale)}px`;
}

window.addEventListener("resize", () => {  // fenêtre redimensionnée : l'image « ajustée » le reste
  if (manual.base && manual.zoom !== undefined && manual.zoom <= manualFitScale() + 0.02) setManualZoom(manualFitScale());
});

$("man-view").addEventListener("wheel", (event) => {
  if (!manual.base) return;
  event.preventDefault();
  const fit = manualFitScale();
  const old = manual.zoom || fit;
  const next = Math.min(1, Math.max(fit, old * (event.deltaY < 0 ? 1.25 : 0.8)));
  if (Math.abs(next - old) < 1e-3) return;
  const view = $("man-view");
  const rect = $("man-canvas").getBoundingClientRect();
  const viewRect = view.getBoundingClientRect();
  const imageX = (event.clientX - rect.left) / old, imageY = (event.clientY - rect.top) / old;  // point visé
  setManualZoom(next);
  view.scrollLeft = imageX * next - (event.clientX - viewRect.left);
  view.scrollTop = imageY * next - (event.clientY - viewRect.top);
  drawManual();
}, { passive: false });

$("man-canvas").addEventListener("mousedown", (event) => {
  if (!manual.base || event.button !== 0) return;
  const point = manualPoint(event);
  if (manual.tool === "brush" || manual.tool === "rebuild") {
    if (manual.tool === "brush") pushPaintUndo();
    manual.stroke = point;
    paintAt(point, point);
  } else {
    manual.drag = [...point, ...point];
  }
  drawManual();
});
$("man-canvas").addEventListener("mousemove", (event) => {
  if (!manual.base) return;
  const point = manualPoint(event);
  manual.cursor = point;
  if (manual.stroke) {
    paintAt(manual.stroke, point);
    manual.stroke = point;
  } else if (manual.drag) {
    manual.drag = [manual.drag[0], manual.drag[1], ...point];
  }
  drawManual();
});
$("man-canvas").addEventListener("mouseleave", () => { manual.cursor = null; drawManual(); });
window.addEventListener("mouseup", () => {
  if (manual.stroke) {
    manual.stroke = null;
    drawManual();
    return;
  }
  if (!manual.drag) return;
  const [x1, y1, x2, y2] = manual.drag;
  manual.drag = null;
  if (Math.abs(x2 - x1) > 8 && Math.abs(y2 - y1) > 8) {
    manual.zones.push({ box: [Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1)],
                        source: "", translation: "", kind: manual.tool === "annex" ? "annexe" : "bulle",
                        style: "contour" });
    manual.undo.push({ kind: "zone" });
    renderManualRows();
  }
  drawManual();
});

$("man-undo").addEventListener("click", () => {
  if (manual.tool === "rebuild" && manual.mask) {  // outil Reconstruire : « Annuler » efface le rouge peint
    clearMask();
    drawManual();
    return;
  }
  const last = manual.undo.pop();
  if (!last) return manualLine("Rien à annuler.");
  if (last.kind === "zone") manual.zones.pop();
  else {
    manual.base.getContext("2d").putImageData(last.data, 0, 0);
    manual.painted = last.painted;
  }
  renderManualRows();
  drawManual();
});

$("man-clear").addEventListener("click", () => {
  manual.zones = [];
  manual.undo = manual.undo.filter((u) => u.kind !== "zone");
  renderManualRows();
  drawManual();
});

function renderManualRows() {
  const box = $("man-rows");
  box.replaceChildren();
  if (!manual.zones.length) return;
  const body = el("tbody");
  for (const [i, zone] of manual.zones.entries()) {
    const source = el("input", { class: "full", lang: "ja", value: zone.source, "aria-label": `texte lu, zone ${i + 1}` });
    source.addEventListener("input", () => { zone.source = source.value; });
    const target = el("input", { class: "full", value: zone.translation, "aria-label": `traduction, zone ${i + 1}` });
    target.addEventListener("input", () => { zone.translation = target.value; });
    const move = (delta) => {
      const j = i + delta;
      if (j < 0 || j >= manual.zones.length) return;
      [manual.zones[i], manual.zones[j]] = [manual.zones[j], manual.zones[i]];
      renderManualRows();
      drawManual();
    };
    const up = el("button", { type: "button", class: "ghost small", title: "plus tôt dans la lecture" }, "↑");
    const down = el("button", { type: "button", class: "ghost small", title: "plus tard dans la lecture" }, "↓");
    const remove = el("button", { type: "button", class: "ghost small", title: "retirer la zone" }, "×");
    up.addEventListener("click", () => move(-1));
    down.addEventListener("click", () => move(1));
    remove.addEventListener("click", () => {
      manual.zones.splice(i, 1);
      manual.undo = manual.undo.filter((u) => u.kind !== "zone");  // l'annulation de zones ne vise plus juste
      renderManualRows();
      drawManual();
    });
    const number = el("td", {}, String(i + 1));
    const cells = [number, el("td", { class: "nowrap" }, up, down, remove), el("td", {}, source), el("td", {}, target)];
    if (zone.kind === "annexe") {  // onomatopée, texte hors bulle : réécrite par-dessus, ou effacée comme une bulle
      const style = el("select", { "aria-label": `réincrustation de l'annexe ${i + 1}` },
        el("option", { value: "contour" }, "par-dessus le dessin (contour)"),
        el("option", { value: "efface" }, "effacer puis écrire"));
      style.value = zone.style || "contour";
      style.addEventListener("change", () => { zone.style = style.value; });
      number.append(el("br"), el("span", { class: "annex" }, "annexe"));
      cells[3].append(style);
    }
    body.append(el("tr", {}, ...cells));
  }
  box.append(el("table", { class: "bubble-edit" },
    el("thead", {}, el("tr", {}, el("th", {}, "#"), el("th", {}, "Ordre"), el("th", {}, "Texte lu"),
                     el("th", {}, "Traduction"))), body));
}

async function manualStep(button, waiting, fn) {
  if (!manual.name) return manualLine("Choisis d'abord une page.");
  button.disabled = true;
  manualLine(waiting);
  try {
    await fn();
  } catch (error) {
    manualLine(`Erreur : ${error.message}`);
  } finally {
    button.disabled = false;
  }
}

async function manualCall(command, body) {  // langue, type de page et série : ceux choisis en haut de l'onglet
  const reply = await post(`/scantrad/manual/${command}`, {
    lang: $("scan-lang").value, layout: $("scan-layout").value, series: $("scan-series").value.trim(), ...body });
  if (!reply.ok) throw new Error(reply.error || "échec");
  return reply;
}

$("man-suggest").addEventListener("click", (event) => manualStep(event.currentTarget,
  "Détection automatique…", async () => {
    const reply = await manualCall("suggest", { image: manual.name });
    manual.zones = reply.result.boxes.map((box) => ({ box, source: "", translation: "", kind: "bulle", style: "contour" }));
    manual.undo = manual.undo.filter((u) => u.kind !== "zone");
    renderManualRows();
    drawManual();
    manualLine(`${manual.zones.length} zones proposées : retire, ajoute ou réordonne avant de lire le texte.`);
  }));

$("man-erase").addEventListener("click", (event) => manualStep(event.currentTarget,
  "Effacement du texte dans les bulles…", async () => {
    // seulement les bulles (et les annexes réglées sur « effacer ») : une annexe « par-dessus » garde son dessin
    const boxes = manual.zones.filter((z) => z.kind !== "annexe" || z.style === "efface").map((z) => z.box);
    if (!boxes.length) throw new Error("trace d'abord des bulles");
    const reply = await manualCall("erase", { image: manual.name, boxes });
    const erased = await loadBase(`${reply.cleaned_url}?t=${Date.now()}`);
    pushPaintUndo();
    // la gomme déjà passée est gardée : on ne recopie que l'intérieur des zones
    const ctx = manual.base.getContext("2d");
    for (const [x, y, w, h] of boxes) ctx.drawImage(erased, x, y, w, h, x, y, w, h);
    manual.painted = true;
    drawManual();
    manualLine("Texte effacé dans les bulles (« Annuler » le remet). Passe la gomme sur ce qui reste.");
  }));

$("man-rebuild").addEventListener("click", (event) => manualStep(event.currentTarget,
  "LaMa redessine les zones peintes en rouge… (quelques secondes par zone, sur le processeur)", async () => {
    if (!manual.mask) throw new Error("choisis « Reconstruire » et peins d'abord en rouge ce qui doit disparaître");
    // la page telle qu'elle est à l'écran (gomme comprise) sert de base, le masque dit quoi redessiner
    const base = await new Promise((resolve) => manual.base.toBlob(resolve, "image/png"));
    await api(`/scantrad/manual/cleaned?image=${encodeURIComponent(manual.name)}`, {
      method: "POST", body: base, headers: { "Content-Type": "image/png" } });
    const flat = document.createElement("canvas");
    flat.width = manual.mask.width;
    flat.height = manual.mask.height;
    const fctx = flat.getContext("2d");
    fctx.fillStyle = "#000";
    fctx.fillRect(0, 0, flat.width, flat.height);
    fctx.drawImage(manual.mask, 0, 0);
    const mask = await new Promise((resolve) => flat.toBlob(resolve, "image/png"));
    const reply = await api(`/scantrad/manual/rebuild?image=${encodeURIComponent(manual.name)}`, {
      method: "POST", body: mask, headers: { "Content-Type": "image/png" } });
    if (!reply.ok) throw new Error(reply.error || "échec");
    const rebuilt = await loadBase(`${reply.cleaned_url}?t=${Date.now()}`);
    pushPaintUndo();
    manual.base.getContext("2d").drawImage(rebuilt, 0, 0);
    manual.painted = true;
    clearMask();
    drawManual();
    manualLine(`Redessiné par ${reply.result.engine}. « Annuler » revient en arrière.`);
  }));

$("man-read").addEventListener("click", (event) => manualStep(event.currentTarget,
  "Lecture du texte de chaque zone… (premier appel : chargement du modèle de vision)", async () => {
    if (!manual.zones.length) throw new Error("trace d'abord des zones");
    const started = performance.now();
    const reply = await manualCall("read", { image: manual.name, boxes: manual.zones.map((z) => z.box) });
    reply.result.sources.forEach((text, i) => { manual.zones[i].source = text; });
    renderManualRows();
    const empty = reply.result.sources.filter((t) => !t).length;
    manualLine(`${manual.zones.length} zones lues en ${Math.round((performance.now() - started) / 1000)} s`
      + (empty ? ` (${empty} sans texte reconnu : écris-le à la main si besoin)` : "")
      + ". Corrige si besoin, puis « Traduire ».");
  }));

$("man-translate").addEventListener("click", (event) => manualStep(event.currentTarget,
  "Traduction… Pendant ce temps, tu peux passer la gomme.", async () => {
    const zones = [...manual.zones];
    if (!zones.some((z) => z.source.trim())) throw new Error("aucun texte à traduire : lis d'abord le texte");
    const reply = await manualCall("translate", { texts: zones.map((z) => z.source) });
    reply.result.translations.forEach((text, i) => { if (text) zones[i].translation = text; });
    renderManualRows();
    manualLine("Traduit. Vérifie, puis « Réincruster ».");
  }));

$("man-compose").addEventListener("click", (event) => manualStep(event.currentTarget, "Réincrustation…",
  async () => {
    if (!manual.zones.length) throw new Error("trace d'abord des zones");
    if (manual.painted) {
      const blob = await new Promise((resolve) => manual.base.toBlob(resolve, "image/png"));
      await api(`/scantrad/manual/cleaned?image=${encodeURIComponent(manual.name)}`, {
        method: "POST", body: blob, headers: { "Content-Type": "image/png" } });
    }
    const reply = await manualCall("compose", { image: manual.name, auto_erase: $("man-auto").checked,
                                                bubbles: manual.zones });
    $("man-result").hidden = false;
    manual.outputUrl = reply.output_url;
    $("man-after").src = `${reply.output_url}?t=${Date.now()}`;
    manualLine("Page traduite. Tu peux encore corriger une ligne ou gommer, puis réincruster à nouveau.");
  }));

$("man-save").addEventListener("click", () => { if (manual.outputUrl) saveImage(manual.outputUrl, manual.fileName); });
$("man-text").addEventListener("click", () => {
  const rows = manual.zones.map((z, i) => ({ index: i + 1, kind: z.kind, source: z.source, translation: z.translation }));
  if (rows.length) saveText(pageText(manual.fileName || "page", rows), manual.fileName);
});

// ---------- traduction générale (texte, image, voix) ----------
const translator = { recorder: null, chunks: [], last: null };

function trLine(text) { $("tr-line").textContent = text; }

function showTranslation(reply) {
  translator.last = reply;
  $("tr-source").value = reply.source;
  $("tr-result").textContent = reply.translation;
  trLine(`Traduit du ${reply.language}${reply.seconds ? ` en ${reply.seconds} s` : ""}`
    + `${reply.model ? ` par ${reply.model}` : ""}.`);
}

async function trRun(waiting, fn) {
  trLine(waiting);
  $("tr-result").textContent = "";
  try {
    showTranslation(await fn());
  } catch (error) {
    trLine(`Erreur : ${error.message}`);
  }
}

$("tr-text").addEventListener("click", () => trRun("Traduction…", () =>
  post("/translate/text", { text: $("tr-source").value, lang: $("tr-lang").value })));

async function translateImage(blob) {
  $("tr-preview").src = URL.createObjectURL(blob);
  $("tr-preview").hidden = false;
  await trRun("Lecture de l'image par le modèle de vision, puis traduction…", () =>
    api(`/translate/image?lang=${encodeURIComponent($("tr-lang").value)}`, {
      method: "POST", body: blob, headers: { "Content-Type": blob.type || "image/png" } }));
}
$("tr-file").addEventListener("change", () => { const f = $("tr-file").files[0]; if (f) translateImage(f); });
// coller une capture d'écran (Ctrl+V) quand l'onglet Traduction est affiché
document.addEventListener("paste", (event) => {
  if (currentTab() !== "traduction" || document.activeElement === $("tr-source")) return;
  const item = [...(event.clipboardData || {}).items || []].find((i) => i.type.startsWith("image/"));
  if (item) { event.preventDefault(); translateImage(item.getAsFile()); }
});

async function refreshVoice() {
  try {
    const voice = await api("/translate/voice");
    $("tr-voice-state").textContent = voice.available ? ""
      : "reconnaissance vocale non installée (scripts\\setup.ps1 -Voice)";
    $("tr-record").disabled = !voice.available;
  } catch (error) {
    $("tr-voice-state").textContent = "";
  }
}

$("tr-record").addEventListener("click", async () => {
  if (translator.recorder) { translator.recorder.stop(); return; }  // second clic : fin de l'enregistrement
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    translator.chunks = [];
    translator.recorder = new MediaRecorder(stream);
    translator.recorder.addEventListener("dataavailable", (e) => translator.chunks.push(e.data));
    translator.recorder.addEventListener("stop", () => {
      stream.getTracks().forEach((t) => t.stop());
      translator.recorder = null;
      $("tr-record").textContent = "🎙 Enregistrer un message";
      $("tr-record").setAttribute("aria-pressed", "false");
      const audio = new Blob(translator.chunks, { type: translator.chunks[0] ? translator.chunks[0].type : "audio/webm" });
      trRun("Reconnaissance de la voix (sur cette machine), puis traduction…", () =>
        api(`/translate/voice?lang=${encodeURIComponent($("tr-lang").value)}`, {
          method: "POST", body: audio, headers: { "Content-Type": "application/octet-stream" } }));
    });
    translator.recorder.start();
    $("tr-record").textContent = "⏹ Arrêter et traduire";
    $("tr-record").setAttribute("aria-pressed", "true");
    trLine("Enregistrement… parle, puis clique sur « Arrêter et traduire ».");
  } catch (error) {
    trLine(`Micro indisponible : ${error.message}`);
  }
});

$("tr-copy").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("tr-result").textContent); trLine("Traduction copiée."); }
  catch (error) { trLine(`Copie impossible : ${error.message}`); }
});
$("tr-save").addEventListener("click", () => {
  if (!translator.last) return;
  saveText(`${translator.last.source}\n\n→ ${translator.last.translation}`, "traduction");
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
$("studio-detect").addEventListener("click", async (event) => {
  if (!studio.name) {
    $("studio-line").textContent = "Choisis d'abord une image.";
    return;
  }
  const button = event.currentTarget;
  button.disabled = true;
  $("studio-line").textContent = "Le modèle de vision cherche… (premier appel : chargement du modèle)";
  try {
    const found = await post("/mangastudio/detect", { image: studio.name, target: $("studio-target").value });
    studio.boxes = found.boxes;
    drawStudio();
    $("studio-line").textContent = found.boxes.length
      ? `${found.boxes.length} boîte(s) proposée(s) par ${found.model} en ${found.seconds} s : corrige-les si besoin.`
      : "Rien trouvé : trace les boîtes à la main.";
  } catch (error) {
    $("studio-line").textContent = `Erreur : ${error.message}`;
  } finally {
    button.disabled = false;
  }
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
const ether = { shown: false, scene: null };

function etherRender(result, said) {
  if (window.EtherScene) {
    ether.scene = ether.scene || window.EtherScene.create($("ether-canvas"), (text) => etherAct(text, false), {
      riddle: () => { $("ether-input").value = "répondre "; },
      map: (on) => $("ether-map").setAttribute("aria-pressed", String(on)),
    });
    const moved = ether.lastPlace !== undefined && ether.lastPlace !== result.place_id;
    ether.lastPlace = result.place_id;
    ether.scene.update(result);
    if (ether.audio) {
      ether.audio.setTheme(ether.scene.themeName(), ether.scene.mood());
      if (moved) ether.audio.chime();
    }
  }
  const log = $("ether-log");
  if (said) log.append(el("p", { class: "me" }, `> ${said}`));
  if (result.narration) log.append(el("p", {}, result.narration));
  log.scrollTop = log.scrollHeight;
  $("ether-place").textContent = result.place;
  const bag = result.bag || [];
  const count = bag.reduce((n, [, k]) => n + k, 0);
  const shownBag = bag.slice(0, 6).map(([item, k]) => (k > 1 ? `${item} ×${k}` : item)).join(", ");
  $("ether-stats").textContent = `tour ${result.turn} · lumière d'Inoue ${result.energy}/${result.max_energy}`
    + ` · ${result.explored} lieux · ${result.riddles_solved} énigmes · sac : `
    + (count ? `${count} objets (${shownBag}${bag.length > 6 ? `, et ${bag.length - 6} autres sortes` : ""})` : "vide")
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

// `typed` : action tapée dans le champ (on y laisse le curseur) ; sinon elle vient de la scène, qui garde le clavier
async function etherAct(text, typed = true) {
  $("ether-input").disabled = true;
  try {
    etherRender(await etherCall("act", { text }), text);
  } catch (error) {
    $("ether-log").append(el("p", { class: "warn" }, `Erreur : ${error.message}`));
    if (ether.scene) ether.scene.failed();
  } finally {
    $("ether-input").disabled = false;
    if (typed) $("ether-input").focus();
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

$("ether-sound").addEventListener("click", () => {
  ether.audio = ether.audio || window.EtherScene.createAudio();
  ether.audio.setVolume(Number($("ether-volume").value) / 100);
  if (ether.scene) ether.audio.setTheme(ether.scene.themeName(), ether.scene.mood());
  const on = ether.audio.toggle();
  $("ether-sound").textContent = on ? "Son : activé" : "Son : coupé";
  $("ether-sound").setAttribute("aria-pressed", String(on));
});
try {  // volume retenu d'une visite à l'autre (préférence de ce navigateur seulement)
  const saved = localStorage.getItem("ether-volume");
  if (saved !== null) $("ether-volume").value = saved;
} catch (error) { /* stockage indisponible : volume par défaut */ }
$("ether-volume").addEventListener("input", () => {
  if (ether.audio) ether.audio.setVolume(Number($("ether-volume").value) / 100);
  try { localStorage.setItem("ether-volume", $("ether-volume").value); } catch (error) { /* sans importance */ }
});
$("ether-map").addEventListener("click", () => {
  const on = $("ether-map").getAttribute("aria-pressed") !== "true";
  $("ether-map").setAttribute("aria-pressed", String(on));
  if (ether.scene) ether.scene.setMap(on);
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
  if (tab === "traduction") refreshVoice();
}
showTab(currentTab());
setInterval(refreshAll, 3000);
