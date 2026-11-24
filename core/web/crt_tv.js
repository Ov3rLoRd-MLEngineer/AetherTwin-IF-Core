"use strict";
// Fenêtre « téléviseur » de l'atelier circuits : l'atelier (fenêtre parente) lui passe chaque image ; les touches
// pressées ici sont renvoyées à la console de l'atelier.
(function () {
  const $ = (id) => document.getElementById(id);
  const crt = new window.AetherCRT($("screen"), window.AetherPPU.PALETTE);
  let frame = null, mode = 0, lastShow = 0;
  for (const name of ["curve", "scan", "glow"]) {
    $(name).addEventListener("input", (e) => { crt.settings[name] = Number(e.target.value); });
  }
  window.AetherTV = {
    show(buffer, newMode, settings, powered) {
      lastShow = performance.now();
      frame = buffer; mode = newMode;
      $("led").classList.toggle("on", Boolean(powered));
      if (settings && !window.AetherTV.tuned) {
        window.AetherTV.tuned = true;
        for (const k of ["curve", "scan", "glow"]) { crt.settings[k] = settings[k]; $(k).value = settings[k]; }
      }
      crt.setMode(mode);
      crt.draw(mode === 2 ? frame : null);
    },
  };
  const parent = () => (window.opener && !window.opener.closed ? window.opener.AetherCircuit : null);
  function onKey(e, down) {
    const p = parent();
    if (p && p.key(e.code, down)) e.preventDefault();
    if (down && e.code === "F11") { e.preventDefault(); toggleFull(); }
  }
  function toggleFull() {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.querySelector(".cabinet").requestFullscreen().catch(() => {});
  }
  window.addEventListener("keydown", (e) => onKey(e, true));
  window.addEventListener("keyup", (e) => onKey(e, false));
  $("full").addEventListener("click", toggleFull);
  $("power").addEventListener("click", () => { const p = parent(); if (p) p.power(); });
  // si l'atelier ne nous envoie plus rien (fermé), on éteint l'écran nous-mêmes. Caché derrière le plein écran,
  // il est mis en veille par le navigateur : on fait alors avancer sa console à notre rythme (`pump`).
  (function idle() {
    const p = parent();
    if (p && p.pump) { try { p.pump(); } catch (e) { /* atelier en cours de fermeture */ } }
    if (performance.now() - lastShow > 500) {
      $("orphan").hidden = Boolean(parent());
      crt.setMode(0); crt.draw(null); $("led").classList.remove("on");
    }
    requestAnimationFrame(idle);
  })();
})();
