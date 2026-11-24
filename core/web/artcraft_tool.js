"use strict";
// Onglet « Outils », sous-onglet « ArtCraft » : installer, ouvrir et brancher en MCP les logiciels libres ArtCraft
// (intégration externe, module modules/artcraft). Dépend de dashboard.js (chargé avant) : $, post, currentSubtab.

(function artcraftTool() {
  const LABEL = "ArtCraft";
  const icons = new Map();   // appli → URL blob de l'icône officielle
  let loaded = false, timer = 0, current = "", activated = false;
  let queue = Promise.resolve();   // le Hub traite une commande à la fois par module (409 sinon) : on les enchaîne

  function command(name, payload = {}) {
    const run = queue.then(() => send(name, payload));
    queue = run.catch(() => {});
    return run;
  }
  async function send(name, payload) {
    if (!activated) { await post("/modules/artcraft/activate"); activated = true; }
    let reply;
    try { reply = await post(`/modules/artcraft/command/${name}`, payload); }
    catch (e) {   // module arrêté entre-temps (409) : on le relance une fois
      await post("/modules/artcraft/activate");
      reply = await post(`/modules/artcraft/command/${name}`, payload);
    }
    if (!reply.ok) throw new Error(reply.error || "erreur du module");
    return reply.result;
  }
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const megas = (n) => `${(n / 1048576).toFixed(1)} Mo`;

  async function iconFor(app) {
    if (icons.has(app)) return icons.get(app);
    const { png } = await command("icon", { app });
    const bytes = Uint8Array.from(atob(png), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: "image/png" }));
    icons.set(app, url);
    return url;
  }

  function button(text, action, cls = "") {
    const b = el("button", cls, text);
    b.type = "button";
    b.addEventListener("click", async () => {
      b.disabled = true;
      try { await action(); } catch (e) { $("artcraft-line").textContent = e.message; }
      finally { b.disabled = false; }
    });
    return b;
  }

  function card(app) {
    const node = el("div", "artcraft-card" + (app.installed ? " installed" : ""));
    const icon = el("div", "artcraft-icon " + (app.family.startsWith("Création") ? "creation" : "office"), app.name[0]);
    if (app.icon) iconFor(app.app).then((url) => {
      const img = el("img");
      img.alt = "";
      img.src = url;
      icon.classList.add("has-img");
      icon.replaceChildren(img);
    }).catch(() => {});
    const head = el("div");
    head.append(el("h4", "", app.name), el("div", "alt", `alternative libre à ${app.alternative}`));
    node.append(icon, head, el("p", "role", app.role));
    const job = app.job;
    const state = el("div", "state");
    if (job && job.running) {
      state.textContent = job.step + (job.total ? ` — ${megas(job.done)} / ${megas(job.total)}` : "");
      const bar = el("div", "bar"), fill = el("i");
      fill.style.width = job.total ? `${Math.min(100, (100 * job.done) / job.total).toFixed(1)}%` : "4%";
      bar.append(fill);
      node.append(state, bar);
    } else {
      if (job && job.error) { state.textContent = `Échec : ${job.error}`; state.classList.add("bad"); }
      else if (app.installed) { state.textContent = `Installé${app.version ? " — " + app.version : ""}`; state.classList.add("ok"); }
      else state.textContent = job && job.step ? job.step : "Pas installé";
      node.append(state);
    }
    const actions = el("div", "actions");
    if (!(job && job.running)) {
      if (app.installed && app.exe) actions.append(button("Ouvrir", () => command("launch", { app: app.app })));
      actions.append(button(app.installed ? "Mettre à jour" : "Installer", async () => {
        if (!confirm(`Télécharger ${app.name} depuis sa publication GitHub officielle (équipe ArtCraft) et l'installer ?`)) return;
        await command("install", { app: app.app });
        refresh();
      }, app.installed ? "ghost" : ""));
      if (app.installed && app.cli) actions.append(button("MCP", () => showMcp(app), "ghost"));
      if (app.portable) actions.append(button("Retirer", async () => {
        if (!confirm(`Supprimer la version portable de ${app.name} de ce PC ?`)) return;
        await command("uninstall", { app: app.app });
        refresh();
      }, "ghost"));
    }
    node.append(actions);
    const links = el("div", "links");
    for (const [text, href] of [["Page officielle", app.page], ["Code source", app.repo]]) {
      const a = el("a", "", text);
      a.href = href; a.target = "_blank"; a.rel = "noopener";
      links.append(a);
    }
    node.append(links);
    return node;
  }

  async function showMcp(app) {
    current = app.app;
    const info = await command("mcp", { app: app.app });
    $("artcraft-mcp").hidden = false;
    $("artcraft-mcp-title").textContent = `Serveur MCP de ${app.name}`;
    $("artcraft-mcp-line").value = info.claude_code;
    $("artcraft-mcp-folder").textContent = info.folder;
    showHermes(await command("hermes", { app: app.app }));
    $("artcraft-mcp").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  function showHermes(state) {
    const label = $("artcraft-hermes-state"), b = $("artcraft-hermes");
    if (!state.installe) { label.textContent = "Hermes Agent n'est pas installé : la ligne Claude Code ci-dessus suffit."; b.hidden = true; return; }
    label.textContent = state.branche ? `Hermes : branché (serveur MCP « ${state.name} »).` : "Hermes : pas encore branché sur ce logiciel.";
    b.hidden = Boolean(state.branche);
  }

  async function refresh() {
    clearTimeout(timer);
    try {
      const apps = await command("catalog");
      const grid = $("artcraft-grid");
      grid.replaceChildren();
      let family = "";
      for (const app of apps) {
        if (app.family !== family) { family = app.family; grid.append(el("h3", "artcraft-family", family)); }
        grid.append(card(app));
      }
      const count = apps.filter((a) => a.installed).length;
      $("artcraft-line").textContent = `${count} logiciel(s) installé(s) sur ${apps.length}.`
        + (apps.some((a) => !a.icon) ? " Icônes officielles pas encore sur ce PC : bouton « Icônes officielles »." : "");
      if (apps.some((a) => a.job && a.job.running)) timer = setTimeout(refresh, 1000);
    } catch (e) { $("artcraft-line").textContent = `ArtCraft : ${e.message}`; }
  }

  function open() {
    if (loaded) return;
    loaded = true;
    refresh();
  }
  $("artcraft-refresh").addEventListener("click", refresh);
  $("artcraft-icons").addEventListener("click", async () => {
    $("artcraft-icons").disabled = true;
    $("artcraft-line").textContent = "Téléchargement des icônes officielles…";
    try {
      const r = await command("icons");
      icons.clear();
      await refresh();
      if (r.failed.length) $("artcraft-line").textContent += ` Icônes manquantes : ${r.failed.join(" ; ")}`;
    } catch (e) { $("artcraft-line").textContent = e.message; }
    finally { $("artcraft-icons").disabled = false; }
  });
  $("artcraft-mcp-copy").addEventListener("click", () => {
    navigator.clipboard?.writeText($("artcraft-mcp-line").value).catch(() => $("artcraft-mcp-line").select());
  });
  $("artcraft-hermes").addEventListener("click", async () => {
    $("artcraft-hermes").disabled = true;
    try { showHermes(await command("hermes", { app: current, register: true })); }
    catch (e) { $("artcraft-hermes-state").textContent = `Hermes : ${e.message}`; }
    finally { $("artcraft-hermes").disabled = false; }
  });
  const visible = () => !document.querySelector('.panel[data-panel="outils"]').hidden && currentSubtab("outils") === LABEL;
  document.addEventListener("subtab", (event) => {
    if (event.detail.panel === "outils" && event.detail.label === LABEL) open();
  });
  document.querySelector('#tabs button[data-tab="outils"]')?.addEventListener("click", () => setTimeout(() => { if (visible()) open(); }, 0));
  if ((location.hash || "").slice(1) === "outils") setTimeout(() => { if (currentSubtab("outils") === LABEL) open(); }, 200);
})();
