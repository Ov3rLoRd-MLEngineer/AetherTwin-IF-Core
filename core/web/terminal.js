"use strict";
// Terminal du Hub : xterm.js relié à une session du démon par WebSocket. L'identifiant de session est passé
// dans l'ancre de l'adresse (#<id>), jamais envoyé ailleurs qu'au Hub.
(function () {
  const sid = decodeURIComponent((location.hash || "").slice(1));
  const status = document.getElementById("term-status");
  const term = new Terminal({
    cursorBlink: true, fontSize: 14, scrollback: 5000, allowProposedApi: false,
    fontFamily: '"Cascadia Mono", "Cascadia Code", Consolas, monospace',
    theme: { background: "#0d1117", foreground: "#e6edf3", cursor: "#58a6ff", selectionBackground: "#264f78" },
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(document.getElementById("term"));
  fit.fit();

  function say(text, cls) { status.textContent = text; status.className = `term-status ${cls || ""}`; }
  if (!/^[\w-]{20,64}$/.test(sid)) { say("Session de terminal invalide", "bad"); return; }

  let socket = null, retries = 0;
  function send(obj) { if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(obj)); }
  function sendSize() { send({ t: "r", rows: term.rows, cols: term.cols }); }

  function connect() {
    socket = new WebSocket(`ws://${location.host}/terminals/${encodeURIComponent(sid)}/ws`);
    socket.onopen = () => { retries = 0; say("", "ok"); sendSize(); term.focus(); };
    socket.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.t === "o") term.write(msg.d);
    };
    socket.onclose = (event) => {
      if (event.code === 4404) { say("Terminal fermé", "bad"); return; }
      if (retries++ < 20) { say("Reconnexion…"); setTimeout(() => { term.reset(); connect(); }, 1000); }
      else say("Connexion perdue", "bad");
    };
  }
  term.onData((data) => send({ t: "i", d: data }));
  new ResizeObserver(() => { fit.fit(); sendSize(); }).observe(document.getElementById("term"));
  connect();
})();
