"use strict";
// Onglet « Outils », sous-onglets « Labo de chimie » et « Explorateur de données » : la page de l'outil intégrée
// (chargée au premier affichage) et le bouton de fenêtre séparée. Dépend de dashboard.js : $, post, currentSubtab.

(function labsTool() {
  const LABS = [
    { label: "Labo de chimie", frame: "chem-frame", button: "chem-window", page: "/static/chem_app.html", module: "chem_lab" },
    { label: "Explorateur de données", frame: "data-frame", button: "data-window", page: "/static/data_app.html", module: "data_lab" },
  ];
  for (const lab of LABS) {
    let loaded = false;
    const open = () => { if (!loaded) { loaded = true; $(lab.frame).src = lab.page; } };
    $(lab.button).addEventListener("click", async () => {
      try { await post(`/modules/${lab.module}/app/start`); } catch (e) { alert(e.message); }
    });
    const visible = () => !document.querySelector('.panel[data-panel="outils"]').hidden && currentSubtab("outils") === lab.label;
    document.addEventListener("subtab", (event) => {
      if (event.detail.panel === "outils" && event.detail.label === lab.label) open();
    });
    document.querySelector('#tabs button[data-tab="outils"]')?.addEventListener("click", () => setTimeout(() => { if (visible()) open(); }, 0));
    if ((location.hash || "").slice(1) === "outils") setTimeout(() => { if (currentSubtab("outils") === lab.label) open(); }, 200);
  }
})();
