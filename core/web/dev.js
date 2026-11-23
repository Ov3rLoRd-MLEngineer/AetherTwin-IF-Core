"use strict";
// Onglet Développement : lanceur de Claude Code local, terminaux du Hub, pont Hermes, tâches confiées, relais.
// Dépend de dashboard.js (chargé avant) : $, el, api, post, modulesByName.

const dev = { models: [], filter: "tous", selected: null, prefs: {}, terminals: [], term: "", roots: [], timer: 0 };

async function devCall(command, payload, button, box) {
  if (button) button.disabled = true;
  try {
    if (!modulesByName.dev_launcher || !modulesByName.dev_launcher.running) await post("/modules/dev_launcher/activate");
    const reply = await post(`/modules/dev_launcher/command/${command}`, payload || {});
    if (!reply.ok) throw new Error((reply.error || "erreur du module").replace(/^\w+Error: /, ""));
    return reply.result;
  } catch (error) {
    if (box) { box.hidden = false; box.replaceChildren(el("p", { class: "warn" }, `Erreur : ${error.message}`)); }
    return null;
  } finally {
    if (button) button.disabled = false;
  }
}

async function devWait(job, box) {
  let current = job;
  while (current && current.en_cours) {
    if (box) { box.hidden = false; box.replaceChildren(el("p", { class: "muted" }, `${current.libelle}… ${Math.round(current.duree || 0)} s`)); }
    await new Promise((resolve) => setTimeout(resolve, 2500));
    current = await devCall("travail", { cle: current.cle }, null, box);
  }
  if (current && current.erreur) {
    if (box) { box.hidden = false; box.replaceChildren(el("p", { class: "warn" }, `Erreur : ${current.erreur}`)); }
    return null;
  }
  return current ? current.resultat : null;
}

const kilo = (n) => (n ? (n >= 1000000 ? `${Math.round(n / 100000) / 10} M` : `${Math.round(n / 1024)} k`) : "");

// ---------- services ----------
function svc(state, title, line) {
  return el("div", { class: `svc ${state}` }, el("b", {}, title), el("span", {}, line));
}

function renderServices(state, models) {
  const s = state.services, h = state.hermes, o = models ? models.omniroute : null;
  const loaded = models ? models.ollama.modeles.filter((m) => m.charge) : [];
  $("dev-services").replaceChildren(
    svc(s.ollama.en_ligne ? "on" : "off", "Ollama", s.ollama.en_ligne
      ? `En ligne${models && models.ollama.version ? ` (v${models.ollama.version})` : ""} · ${loaded.length ? `chargé : ${loaded.map((m) => m.id).join(", ")}` : "aucun modèle chargé"}`
      : "Hors ligne : lance Ollama"),
    svc(s.omniroute.en_ligne ? "on" : "opt", "OmniRoute (facultatif)", s.omniroute.en_ligne
      ? `En ligne · ${o && o.source ? `liste ${o.source}` : "liste indisponible"}${s.omniroute.cle ? "" : " · clé absente"}`
      : "Arrêté : Ollama suffit"),
    svc(state.claude.installe ? "on" : "opt", "Claude Code", state.claude.installe ? "Installé (Claude Code local)" : state.claude.commande),
    svc(state.windows_terminal ? "on" : "opt", "Windows Terminal", state.windows_terminal ? "Disponible" : "Absent : console classique"),
    svc(h.installe ? (h.pont ? "on" : "opt") : "off", "Hermes Agent", h.installe ? (h.pont ? "Pont MCP branché" : "Pont MCP non branché") : "Introuvable"),
  );
}

// ---------- modèles ----------
function modelMeta(m) {
  if (m.route === "ollama") {
    const ctx = m.charge && m.contexte ? `contexte servi ${kilo(m.contexte)}`
      : m.contexte_regle ? `contexte ${kilo(m.contexte_regle)}` : "contexte par défaut d'Ollama";
    return [m.parametres, m.quantification, m.taille_go ? `${m.taille_go} Go` : "", ctx].filter(Boolean).join(" · ");
  }
  return [m.fournisseur, m.contexte ? `contexte ${kilo(m.contexte)}` : "", m.sortie_max ? `sortie ${kilo(m.sortie_max)}` : ""].filter(Boolean).join(" · ");
}

function renderModels() {
  const query = $("dev-search").value.trim().toLowerCase();
  const shown = dev.models.filter((m) => (dev.filter === "tous" || (dev.filter === "charges" ? m.charge : m.route === dev.filter))
    && (!query || `${m.id} ${m.nom} ${m.fournisseur}`.toLowerCase().includes(query)));
  const groups = {};
  for (const m of shown) (groups[m.fournisseur] ||= []).push(m);
  const nodes = [];
  for (const [provider, items] of Object.entries(groups)) {
    nodes.push(el("div", { class: "dev-group" }, `${provider} (${items.length})`));
    for (const m of items) {
      const badges = el("span", { class: "badges" });
      if (m.charge) badges.append(el("span", { class: "badge live" }, "chargé"));
      for (const cap of m.capacites || []) badges.append(el("span", { class: "badge" }, cap));
      badges.append(el("span", { class: "badge dev" }, m.route === "ollama" ? "direct" : "OmniRoute"));
      const row = el("button", { type: "button", class: "dev-model", role: "option",
        "aria-selected": String(dev.selected && dev.selected.id === m.id && dev.selected.route === m.route) },
      el("span", { class: "name" }, m.nom), badges, el("span", { class: "meta" }, modelMeta(m)));
      row.addEventListener("click", () => selectModel(m));
      nodes.push(row);
    }
  }
  $("dev-model-list").replaceChildren(...(nodes.length ? nodes : [el("p", { class: "muted dev-empty" },"Aucun modèle ne correspond.")]));
}

function selectModel(m) {
  dev.selected = m;
  const context = m.route === "ollama" ? (m.contexte || 32768) : Math.min(m.contexte || 200000, 200000);
  $("dev-context").value = context;
  $("dev-selected").replaceChildren(el("b", {}, m.nom), el("span", {}, modelMeta(m)),
    el("span", {}, m.route === "ollama" ? "Route : Ollama en direct (aucun routeur)" : "Route : OmniRoute"),
    m.route === "ollama" ? el("span", {}, "Claude Code est réglé sur ce contexte ; il doit rester au plus celui que sert Ollama "
      + "(num_ctx du modèle, ou 32 k par défaut). Claude Code demande environ 20 k pour lui-même : 64 k ou plus conseillés.") : "");
  renderModels();
}

async function loadDev() {
  const [state, models] = await Promise.all([devCall("etat", {}, null, $("dev-launch-result")), devCall("modeles", {})]);
  if (!state) return;
  renderServices(state, models);
  dev.prefs = state.preferences || {};
  dev.roots = state.dossiers_autorises || [];
  $("dev-task-folder").replaceChildren(el("option", { value: "" }, "Nouveau sous-dossier (automatique)"),
    ...dev.roots.map((r) => el("option", { value: r }, r)));
  renderHermes(state.hermes);
  renderRelay(state.relais);
  if (models) {
    dev.models = [...models.ollama.modeles, ...models.omniroute.modeles];
    const note = [];
    if (!models.ollama.en_ligne) note.push("Ollama ne répond pas.");
    if (models.omniroute.erreur) note.push(`OmniRoute : ${models.omniroute.erreur}.`);
    if (models.omniroute.source === "liste exportée") note.push("Liste OmniRoute : celle exportée par l'ancien lanceur (pour la liste en direct, mettre la clé dans la variable OMNIROUTE_API_KEY).");
    $("dev-model-note").textContent = note.join(" ");
  }
  if (!$("dev-folder").value) $("dev-folder").value = dev.prefs.dossier || state.claude.dossier || "";
  if (dev.prefs.mode) for (const r of document.querySelectorAll('input[name="dev-mode"]')) r.checked = r.value === dev.prefs.mode;
  if (dev.prefs.mcp === false) $("dev-mcp").checked = false;
  if (dev.prefs.outils_essentiels === false) $("dev-tools").checked = false;
  const wanted = dev.selected || dev.models.find((m) => m.id === dev.prefs.modele && m.route === dev.prefs.route);
  if (wanted) selectModel(dev.models.find((m) => m.id === wanted.id && m.route === wanted.route) || wanted);
  else renderModels();
  if (dev.prefs.contexte && dev.selected && dev.selected.id === dev.prefs.modele) {
    // Ollama coupe au contexte qu'il sert : une préférence plus grande ne servirait à rien.
    const served = dev.selected.route === "ollama" ? (dev.selected.contexte || 32768) : Infinity;
    $("dev-context").value = Math.min(dev.prefs.contexte, served);
  }
  loadTasks();
  loadTerminals();
}

// ---------- lancement ----------
async function launchClaude(event) {
  event.preventDefault();
  const box = $("dev-launch-result");
  if (!dev.selected) { box.hidden = false; box.replaceChildren(el("p", { class: "warn" }, "Choisis d'abord un modèle.")); return; }
  const mode = document.querySelector('input[name="dev-mode"]:checked').value;
  const result = await devCall("lancer", { modele: dev.selected.id, route: dev.selected.route, contexte: Number($("dev-context").value),
    dossier: $("dev-folder").value.trim(), mode, mcp: $("dev-mcp").checked, outils_essentiels: $("dev-tools").checked }, event.submitter, box);
  if (!result) return;
  box.hidden = false;
  const warning = result.avertissement ? [el("p", { class: "warn" }, `Attention : ${result.avertissement}`)] : [];
  if (result.mode === "windows") {
    box.replaceChildren(el("p", { class: "good" }, `Claude Code lancé dans ${result.ouvert}.`), ...warning);
    return;
  }
  box.replaceChildren(...warning);
  box.hidden = !warning.length;
  await openTerminal({ lancement: result.lancement, titre: result.titre }, event.submitter);
}

// ---------- terminaux ----------
async function openTerminal(body, button) {
  if (button) button.disabled = true;
  try {
    const session = await post("/terminals", body);
    dev.term = session.id;
    await loadTerminals();
  } catch (error) {
    const box = $("dev-launch-result");
    box.hidden = false;
    box.replaceChildren(el("p", { class: "warn" }, `Terminal : ${error.message}`));
  } finally {
    if (button) button.disabled = false;
  }
}

async function loadTerminals() {
  try { dev.terminals = await api("/terminals"); } catch { dev.terminals = []; }
  if (!dev.terminals.some((t) => t.id === dev.term)) dev.term = dev.terminals.length ? dev.terminals[dev.terminals.length - 1].id : "";
  $("dev-terminals").hidden = !dev.terminals.length;
  $("dev-term-tabs").replaceChildren(...dev.terminals.map((t) => {
    const b = el("button", { type: "button", role: "tab", "aria-selected": String(t.id === dev.term), class: t.actif ? "" : "ended" }, t.titre);
    b.addEventListener("click", () => { dev.term = t.id; loadTerminals(); });
    return b;
  }));
  const url = dev.term ? `/terminal#${encodeURIComponent(dev.term)}` : "about:blank";
  if ($("dev-term-frame").getAttribute("src") !== url) $("dev-term-frame").setAttribute("src", url);
  $("dev-term-full").href = url;
}

async function closeTerminal(event) {
  if (!dev.term) return;
  try { await post(`/terminals/${encodeURIComponent(dev.term)}/close`); } catch { /* déjà fermé */ }
  dev.term = "";
  loadTerminals();
}

// ---------- Hermes ----------
function renderHermes(h) {
  const box = $("dev-hermes");
  if (!h.installe) { box.replaceChildren(el("span", { class: "warn" }, "Hermes Agent est introuvable sur ce PC.")); return; }
  if (h.pont) { box.replaceChildren(el("span", { class: "good" }, "Pont MCP branché chez Hermes (outils claude_local_*, hub_*).")); return; }
  const b = el("button", { type: "button" }, "Brancher sur Hermes");
  b.addEventListener("click", async () => {
    const result = await devCall("brancher_hermes", {}, b, $("dev-ask-result"));
    if (result) {
      $("dev-ask-result").hidden = false;
      $("dev-ask-result").replaceChildren(el("p", { class: "good" }, "Pont MCP déclaré chez Hermes."),
        result.sauvegarde ? el("p", { class: "muted" }, "Configuration de Hermes sauvegardée avant la modification.") : "");
      renderHermes(result.hermes);
    }
  });
  box.replaceChildren(el("span", { class: "muted" }, "Le pont n'est pas encore déclaré chez Hermes (sa configuration sera sauvegardée avant)."), b);
}

async function askHermes(event) {
  event.preventDefault();
  const box = $("dev-ask-result");
  const started = await devCall("demander_hermes", { question: $("dev-question").value }, event.submitter, box);
  if (!started) return;
  const result = await devWait(started.travail, box);
  if (!result) return;
  box.hidden = false;
  box.replaceChildren(el("p", {}, el("b", {}, "Hermes : ")), el("div", {}, result.reponse));
}

// ---------- tâches confiées ----------
function taskNode(t) {
  const cls = t.etat === "terminée" ? "good" : t.etat === "en cours" ? "muted" : "badans";
  return el("details", { class: "dev-task" },
    el("summary", {}, el("b", {}, t.tache.split("\n")[0].slice(0, 140)), el("span", { class: cls }, t.etat),
      el("span", { class: "muted" }, `${t.origine} · ${t.modele} · ${Math.round(t.duree)} s`)),
    el("p", { class: "muted" }, `Dossier : ${t.dossier}${t.fichiers && t.fichiers.length ? ` · fichiers : ${t.fichiers.join(", ")}` : ""}`),
    el("pre", {}, t.sortie || "(pas encore de sortie)"));
}

async function loadTasks() {
  const data = await devCall("taches", {});
  if (!data) return;
  $("dev-tasks").replaceChildren(...(data.taches.length ? data.taches.map(taskNode) : [el("p", { class: "muted" }, "Aucune tâche pour l'instant.")]));
  clearTimeout(dev.timer);
  if (data.taches.some((t) => t.etat === "en cours") && currentTab() === "developpement") dev.timer = setTimeout(loadTasks, 5000);
}

async function delegate(event) {
  event.preventDefault();
  const task = await devCall("confier", { tache: $("dev-task").value, dossier: $("dev-task-folder").value, origine: "Hub" }, event.submitter, $("dev-ask-result"));
  if (!task) return;
  const box = $("dev-ask-result");
  box.hidden = false;
  box.replaceChildren(el("p", { class: "good" }, `Tâche ${task.id} confiée à ${task.modele}.`),
    ...(task.avertissement ? [el("p", { class: "warn" }, `Attention : ${task.avertissement}`)] : []));
  $("dev-task").value = "";
  loadTasks();
}

// ---------- relais ----------
function renderRelay(relais) {
  const nodes = [];
  if (relais.etat) nodes.push(el("p", { class: "muted" }, `Dernier relais complet : phase ${relais.etat.phase}, ${relais.etat.cycles} bascule(s) ; ${relais.etat.last_event || ""}`));
  const r = relais.essai;
  if (r) {
    nodes.push(el("div", { class: "dev-relay" },
      el("p", {}, el("span", { class: r.recu ? "good" : "badans" }, r.recu ? "Relais reçu par l'agent local" : "Pas d'accusé de réception"),
        ` · ${new Date(r.date * 1000).toLocaleString("fr-FR")} · ${r.modele} · ${Math.round(r.duree)} s · `,
        el("span", { class: r.depot_intact ? "good" : "badans" }, r.depot_intact ? "dépôt intact" : "le dépôt a changé"),
        ...(r.lu === undefined ? [] : [" · ", el("span", { class: r.lu ? "good" : "badans" },
          r.lu ? "AGENT_HANDOFF.md lu (titre recopié)" : "lecture du relais non prouvée")])),
      el("b", {}, "Réponse de l'agent local"), el("pre", {}, r.reponse_locale),
      el("b", {}, "Retour préparé pour Claude Code API (début)"), el("pre", {}, r.retour_cloud)));
  }
  $("dev-relay").replaceChildren(...nodes);
}

async function testRelay(event) {
  const box = $("dev-relay");
  const started = await devCall("test_relais", {}, event.currentTarget, box);
  if (!started) return;
  const report = await devWait(started.travail, box);
  if (report) renderRelay({ essai: report });
}

// ---------- liaisons ----------
$("dev-search").addEventListener("input", renderModels);
for (const chip of document.querySelectorAll(".dev-chips .chip")) {
  chip.addEventListener("click", () => {
    dev.filter = chip.dataset.filter;
    for (const c of document.querySelectorAll(".dev-chips .chip")) c.setAttribute("aria-pressed", String(c === chip));
    renderModels();
  });
}
for (const chip of document.querySelectorAll("[data-ctx]")) chip.addEventListener("click", () => { $("dev-context").value = chip.dataset.ctx; });
$("dev-launch").addEventListener("submit", launchClaude);
$("dev-shell").addEventListener("click", (event) => openTerminal({ dossier: $("dev-folder").value.trim(), titre: "Invite de commandes" }, event.currentTarget));
$("dev-term-close").addEventListener("click", closeTerminal);
$("dev-refresh").addEventListener("click", loadDev);
$("dev-ask-form").addEventListener("submit", askHermes);
$("dev-task-form").addEventListener("submit", delegate);
$("dev-relay-test").addEventListener("click", testRelay);

let devStarted = false;
function devMaybeStart() {
  if ((location.hash || "").slice(1) !== "developpement") return;
  if (!devStarted) { devStarted = true; loadDev(); } else { loadTerminals(); loadTasks(); }
}
window.addEventListener("hashchange", devMaybeStart);
for (const tab of document.querySelectorAll("#tabs button")) tab.addEventListener("click", () => setTimeout(devMaybeStart, 0));
devMaybeStart();
