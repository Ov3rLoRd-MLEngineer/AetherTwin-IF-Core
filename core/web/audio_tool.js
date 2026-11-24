"use strict";
// Onglet « Outils », sous-onglet « Studio audio » : le studio intégré (même page que sa fenêtre) et le bouton de
// fenêtre séparée. Dépend de dashboard.js (chargé avant) : $, post, currentSubtab.

(function audioTool() {
  const LABEL = "Studio audio";
  let loaded = false;
  function open() {
    if (loaded) return;
    loaded = true;
    $("audio-frame").src = "/static/audio_app.html";
  }
  $("audio-window").addEventListener("click", async () => {
    try { await post("/modules/voice/app/start"); } catch (e) { alert(e.message); }
  });
  const visible = () => !document.querySelector('.panel[data-panel="outils"]').hidden && currentSubtab("outils") === LABEL;
  document.addEventListener("subtab", (event) => {
    if (event.detail.panel === "outils" && event.detail.label === LABEL) open();
  });
  document.querySelector('#tabs button[data-tab="outils"]')?.addEventListener("click", () => setTimeout(() => { if (visible()) open(); }, 0));
  if ((location.hash || "").slice(1) === "outils") setTimeout(() => { if (currentSubtab("outils") === LABEL) open(); }, 200);
})();
