"use strict";
// Onglet « Outils », sous-onglet « Studio pixel » : le studio intégré (même page que sa fenêtre), bouton de fenêtre
// séparée, branchement de son serveur MCP chez Hermes. Dépend de dashboard.js (chargé avant) : $, post, currentSubtab.

(function pixelTool() {
  const LABEL = "Studio pixel";
  let loaded = false;
  async function pixelCommand(command) {
    await post("/modules/pixel_studio/activate");
    const reply = await post(`/modules/pixel_studio/command/${command}`, {});
    if (!reply.ok) throw new Error(reply.error || "erreur du module");
    return reply.result;
  }
  function showHermes(state) {
    const label = $("pixel-hermes-state"), button = $("pixel-hermes");
    if (!state.installe) { label.textContent = "Hermes Agent n'est pas installé : le studio reste disponible ici."; button.hidden = true; return; }
    label.textContent = state.branche
      ? "Hermes : branché — ses modèles dessinent des sprites avec le studio (serveur MCP « aethertwin_pixel »)."
      : "Hermes : pas encore branché sur le studio.";
    button.hidden = Boolean(state.branche);
  }
  async function open() {
    if (loaded) return;
    loaded = true;
    $("pixel-frame").src = "/static/pixel_app.html";
    try { showHermes(await pixelCommand("hermes")); } catch (e) { $("pixel-hermes-state").textContent = `Hermes : ${e.message}`; }
  }
  $("pixel-window").addEventListener("click", async () => {
    try { await post("/modules/pixel_studio/app/start"); } catch (e) { alert(e.message); }
  });
  $("pixel-hermes").addEventListener("click", async () => {
    $("pixel-hermes").disabled = true;
    try { showHermes(await pixelCommand("hermes_register")); } catch (e) { $("pixel-hermes-state").textContent = `Hermes : ${e.message}`; }
    finally { $("pixel-hermes").disabled = false; }
  });
  const visible = () => !document.querySelector('.panel[data-panel="outils"]').hidden && currentSubtab("outils") === LABEL;
  document.addEventListener("subtab", (event) => {
    if (event.detail.panel === "outils" && event.detail.label === LABEL) open();
  });
  document.querySelector('#tabs button[data-tab="outils"]')?.addEventListener("click", () => setTimeout(() => { if (visible()) open(); }, 0));
  if ((location.hash || "").slice(1) === "outils") setTimeout(() => { if (currentSubtab("outils") === LABEL) open(); }, 200);
})();
