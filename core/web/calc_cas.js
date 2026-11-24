"use strict";
// Onglet « Outils » : la calculatrice Æther CAS intégrée (même page que sa fenêtre), bouton de fenêtre séparée,
// branchement de son serveur MCP chez Hermes (les modèles s'en servent par MCP, pas par cet onglet).
// Dépend de dashboard.js (chargé avant) : $, post.

(function calcTool() {
  let loaded = false;
  async function calcCommand(command) {
    await post("/modules/calc_cas/activate");
    const reply = await post(`/modules/calc_cas/command/${command}`, {});
    if (!reply.ok) throw new Error(reply.error || "erreur du module");
    return reply.result;
  }
  function showHermes(state) {
    const label = $("calc-hermes-state"), button = $("calc-hermes");
    if (!state.installe) { label.textContent = "Hermes Agent n'est pas installé : la calculatrice reste disponible ici."; button.hidden = true; return; }
    label.textContent = state.branche
      ? "Hermes : branché — ses modèles calculent avec la calculatrice (serveur MCP « aethertwin_calc »)."
      : "Hermes : pas encore branché sur la calculatrice.";
    button.hidden = Boolean(state.branche);
  }
  async function open() {
    if (loaded) return;
    loaded = true;
    $("calc-frame").src = "/static/calc_app.html";
    try { showHermes(await calcCommand("hermes")); } catch (e) { $("calc-hermes-state").textContent = `Hermes : ${e.message}`; }
  }
  $("calc-window").addEventListener("click", async () => {
    try { await post("/modules/calc_cas/app/start"); } catch (e) { alert(e.message); }
  });
  $("calc-hermes").addEventListener("click", async () => {
    $("calc-hermes").disabled = true;
    try { showHermes(await calcCommand("hermes_register")); } catch (e) { $("calc-hermes-state").textContent = `Hermes : ${e.message}`; }
    finally { $("calc-hermes").disabled = false; }
  });
  document.querySelector('#tabs button[data-tab="outils"]')?.addEventListener("click", open);
  if ((location.hash || "").slice(1) === "outils") setTimeout(open, 200);
})();
