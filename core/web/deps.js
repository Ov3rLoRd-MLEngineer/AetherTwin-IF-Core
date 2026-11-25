// Dépendances (Studio image et Développement) et fiches Hand & Foot SegNet.
// Les liens et les fiches viennent du Hub (/setup/dependencies) ; une installation se lance par son identifiant
// dans une liste fermée côté Hub (/setup/run). Rien d'autre n'est exécuté depuis cette page.
(function deps() {
  const $ = (id) => document.getElementById(id);
  const el = (tag, attrs = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === false || value == null) continue;
      if (key === "class") node.className = value; else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) if (child != null && child !== "") node.append(child.nodeType ? child : String(child));
    return node;
  };
  const link = (href, text, cls = "seg-link") => el("a", { class: cls, href, target: "_blank", rel: "noopener noreferrer" }, text);
  let data = null;
  let timer = null;

  async function load() {
    const response = await fetch("/setup/dependencies", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    data = await response.json();
    render();
    clearTimeout(timer);
    if (data.taches.some((t) => t.etat === "en cours")) timer = setTimeout(() => load().catch(() => {}), 1500);
  }

  async function run(id, button) {
    button.disabled = true;
    try {
      const response = await fetch("/setup/run", { method: "POST", headers: { "Content-Type": "application/json" },
                                                   body: JSON.stringify({ tache: id }) });
      if (!response.ok) throw new Error(await response.text());
    } catch (error) {
      button.textContent = `Erreur : ${error.message}`;
    }
    load().catch(() => {});
  }

  function stateText(present) {
    if (present === true) return el("span", { class: "dep-state ok" }, "trouvé sur ce PC");
    if (present === false) return el("span", { class: "dep-state no" }, "absent");
    return el("span", { class: "dep-state" }, "non vérifiable");
  }

  function jobRow(job, note) {
    const running = job.etat === "en cours";
    const button = el("button", { type: "button", class: job.present ? "ghost small" : "small", disabled: running },
      running ? "Installation…" : job.present ? "Réinstaller" : `Installer (${job.taille})`);
    button.addEventListener("click", () => run(job.id, button));
    const status = job.etat === "échec" ? el("span", { class: "dep-state no" }, "échec")
      : running ? el("span", { class: "dep-state run" }, "en cours") : stateText(job.present);
    return el("div", { class: "dep" },
      el("div", { class: "dep-main" }, el("b", {}, job.nom), status),
      note ? el("span", { class: "muted" }, note) : "",
      job.detail && job.etat !== "absent" ? el("code", { class: "dep-log", title: job.journal.join("\n") }, job.detail) : "",
      el("div", { class: "dep-actions" }, button));
  }

  function externalRow(dep) {
    return el("div", { class: "dep" },
      el("div", { class: "dep-main" }, el("b", {}, dep.nom), stateText(dep.present)),
      el("span", { class: "muted" }, dep.role),
      el("div", { class: "dep-actions" }, link(dep.lien, dep.present ? "Site officiel" : "⬇ Télécharger", "guide-link small")));
  }

  const NOTES = { gpu: "Redémarre le Hub ensuite pour que la segmentation les prenne.",
                  voice: "Pour la dictée de l'Assistant et de la Traduction." };

  function renderList(container, groups, jobsFirst) {
    if (!container || !data) return;
    const jobs = data.taches.filter((t) => groups.includes(t.groupe)).map((t) => jobRow(t, NOTES[t.id]));
    const external = data.externes.filter((d) => groups.includes(d.groupe)).map(externalRow);
    container.replaceChildren(...(jobsFirst ? [...jobs, ...external] : [...external, ...jobs]));
  }

  function card(key) {
    const m = data.segnet[key];
    const weights = data.taches.find((t) => t.id === `weights_${key}`);
    return el("div", { class: "seg-hero" },
      el("div", { class: "seg-title" },
        el("span", { class: "seg-eyebrow" }, "Hand & Foot SegNet · modèle d'Ov3rLoRd"),
        el("h2", {}, m.nom, el("small", {}, ` — segmentation des ${m.sujet}`)),
        el("p", {}, m.resume),
        el("div", { class: "seg-links" },
          link(m.github, "GitHub · code d'inférence"), link(m.huggingface, "Hugging Face · poids et fiche"))),
      el("div", { class: "seg-stats" }, m.chiffres.map(([label, value]) =>
        el("div", { class: "seg-stat" }, el("b", {}, value), el("span", {}, label)))),
      el("div", { class: "seg-facts" },
        el("p", {}, el("b", {}, "Données. "), m.donnees),
        el("p", {}, el("b", {}, "Limites. "), m.limites),
        el("p", { class: "muted" }, `Licence : ${data.licence_poids}. Fichier : ${m.fichier}.`)),
      weights ? el("div", { class: "seg-weights" }, jobRow(weights)) : "");
  }

  function render() {
    for (const key of ["hand", "foot"]) {
      const box = $(`seg-card-${key}`);
      if (box && data.segnet[key]) box.replaceChildren(card(key));
    }
    renderList($("seg-deps"), ["image"], true);
    renderList($("dev-deps"), ["base", "ia", "dev"], false);
  }

  function shown() {
    const tab = (location.hash || "").slice(1);
    return tab === "studio" || tab === "developpement";
  }
  function maybeLoad() {
    if (!shown()) return;
    load().catch((error) => {
      for (const id of ["seg-card-hand", "seg-card-foot", "seg-deps", "dev-deps"]) {
        const box = $(id);
        if (box) box.replaceChildren(el("p", { class: "warn" }, `Dépendances indisponibles : ${error.message}`));
      }
    });
  }

  // Le sous-onglet choisi (HandSegNet / FootSegNet) règle la cible de l'outil de masque.
  function syncTarget(label) {
    const target = label === "FootSegNet" ? "foot" : "hand";
    const input = $("studio-target");
    if (input) input.value = target;
    const sub = $("seg-tool-sub");
    if (sub) sub.textContent = target === "foot" ? "avec FootSegNet : une boîte par pied" : "avec HandSegNet : une boîte par main";
  }
  document.addEventListener("subtab", (event) => {
    if (event.detail.panel === "studio") syncTarget(event.detail.label);
  });
  window.addEventListener("hashchange", maybeLoad);
  for (const tab of document.querySelectorAll("#tabs button")) tab.addEventListener("click", () => setTimeout(maybeLoad, 0));
  const studioTabs = document.querySelector('.panel[data-panel="studio"] .subtabs [aria-selected="true"]');
  syncTarget(studioTabs ? studioTabs.dataset.sub : "HandSegNet");
  maybeLoad();
})();
