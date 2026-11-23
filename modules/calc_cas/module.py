"""Module du Hub : calculatrice à calcul formel (CAS), graphes, statistiques, outil pour les agents locaux.

Commandes reçues sur le bus (réponse sur `module.calc_cas.result`, avec le même `request_id`) :

    eval        {"text": "integrate(x^2, x)"}            résultat exact + approché (texte, LaTeX, MathML)
    vars        {}                                        variables et fonctions définies (« a := 3 », « f(x) := … »)
    delete      {"name": "a"}                             supprime une définition
    reset       {}                                        efface variables, fonctions et historique
    history     {}                                        derniers calculs
    plot        {"curves": [...], "window": {...}}        points des courbes (y, param, polar)
    analyze     {"what": "zeros"|"extrema"|"intersections", "expr", "other"?, "xmin", "xmax"}
    stats       {"x": [...], "y"?: [...], "freq"?: [...]} statistiques à une / deux variables
    regress     {"x", "y", "model"}                       régression (linear, quadratic, cubic, exponential…)
    tools       {}                                        définitions des outils pour agents (schémas JSON)
    tool        {"name": "cas_compute", "arguments": {...}}   appel d'outil par un agent (session séparée)
    ask         {"question": "…"}                         le modèle local délègue ses calculs au CAS
    examples    {}                                        exemples de démonstration

Tous les calculs passent par un processus séparé avec délai maximal (`worker.py`) : un calcul pathologique est
interrompu et le module répond quand même. Variables, fonctions et historique sont gardés dans
`data/calc_cas/session.json` (ignoré par Git).

Configuration (section `calc_cas` de `config/local.yaml`), tout est facultatif :

    timeout_s: 10                          # délai maximal d'un calcul
    hub_api: "http://127.0.0.1:5750"       # modèle local du Hub, pour `ask` (vide = désactivé)
    model: ""                              # vide = modèle par défaut du Hub
    session: "data/calc_cas/session.json"
"""
from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.module_api import Event, Health, ModuleBase
from modules.calc_cas import agent, demos
from modules.calc_cas.worker import CasRunner

REPO_ROOT = Path(__file__).resolve().parents[2]
HISTORY_MAX = 200


def hub_llm(hub_api: str, model: str = "", timeout_s: float = 180.0) -> Callable[[list[dict[str, str]]], str]:
    """Appel du modèle local **par le Hub** (API compatible OpenAI), jamais directement."""
    def call(messages: list[dict[str, str]]) -> str:
        body: dict[str, Any] = {"messages": messages, "think": False, "temperature": 0.2}
        if model:
            body["model"] = model
        request = urllib.request.Request(hub_api.rstrip("/") + "/v1/chat/completions",  # noqa: S310
                                         data=json.dumps(body).encode("utf-8"),
                                         headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310 — API locale du Hub
            return str(json.loads(response.read().decode("utf-8"))["choices"][0]["message"]["content"])
    return call


class CalcCasModule(ModuleBase):
    def start(self) -> None:
        self.save_path = Path(str(self.config.get("session") or REPO_ROOT / "data" / "calc_cas" / "session.json"))
        self.runner = CasRunner(timeout_s=float(self.config.get("timeout_s", 10)))
        hub = str(self.config.get("hub_api", "http://127.0.0.1:5750"))
        self.llm = hub_llm(hub, str(self.config.get("model", ""))) if hub else None
        self.history: list[dict[str, Any]] = []
        self.load_error = ""
        try:
            if self.save_path.is_file():
                saved = json.loads(self.save_path.read_text(encoding="utf-8"))
                self.history = [h for h in saved.get("history", []) if isinstance(h, dict)][-HISTORY_MAX:]
                defs = saved.get("definitions", {})
                if isinstance(defs, dict):
                    self.runner.definitions["user"] = {str(k): str(v) for k, v in defs.items()}
        except (OSError, ValueError, AttributeError) as exc:
            self.load_error = f"session illisible ({exc}) : nouvelle session"
        try:
            self.runner.start()  # import de SymPy en arrière-plan : le premier calcul attendra qu'il soit prêt
        except OSError as exc:
            self.load_error = f"moteur de calcul non lancé : {exc}"

    def stop(self) -> None:
        self._save()
        self.runner.stop()

    def health(self) -> Health:
        if self.runner.broken:
            return Health(ok=True, degraded=True, detail=f"moteur de calcul indisponible ({self.runner.broken})")
        detail = (f"{len(self.history)} calculs, {len(self.runner.definitions.get('user', {}))} définitions"
                  + (f", {self.runner.restarts} calcul(s) interrompu(s)" if self.runner.restarts else ""))
        if self.load_error:
            detail = f"{self.load_error} — {detail}"
        return Health(ok=True, degraded=self.llm is None, detail=detail + ("" if self.llm else " — sans modèle"))

    def _save(self) -> None:
        try:
            self.save_path.parent.mkdir(parents=True, exist_ok=True)
            self.save_path.write_text(json.dumps({"definitions": self.runner.definitions.get("user", {}),
                                                  "history": self.history[-HISTORY_MAX:]}, ensure_ascii=False,
                                                 indent=1), encoding="utf-8")
        except OSError:
            pass  # sauvegarde impossible (disque) : le calcul reste valable

    def handle_event(self, event: Event) -> None:
        prefix = f"module.{self.name}.cmd."
        if not event.topic.startswith(prefix):
            return
        command, payload = event.topic[len(prefix):], event.payload
        try:
            reply = {"ok": True, "result": self.run(command, payload)}
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as exc:
            reply = {"ok": False, "error": str(exc) or type(exc).__name__}
        self.publish(Event(f"module.{self.name}.result", {"request_id": payload.get("request_id"),
                                                           "command": command, **reply}, source=self.name))

    def run(self, command: str, payload: dict[str, Any]) -> Any:
        """Exécute une commande (aussi appelée directement par les tests)."""
        if command == "eval":
            text = payload.get("text")
            if not isinstance(text, str):
                raise ValueError("`text` (texte) obligatoire")
            result = self.runner.call("eval", text=text)
            self.history.append(result)
            self.history = self.history[-HISTORY_MAX:]
            self._save()
            return result
        if command == "vars":
            return self.runner.call("vars")
        if command == "delete":
            deleted = self.runner.call("delete", name=str(payload.get("name", "")))
            self._save()
            return deleted
        if command == "reset":
            self.runner.call("reset", target="user")
            self.history = []
            self._save()
            return True
        if command == "history":
            return self.history
        if command == "plot":
            return self.runner.call("plot", curves=payload.get("curves"), window=payload.get("window"),
                                    samples=int(payload.get("samples", 600)))
        if command == "analyze":
            return self.runner.call("analyze", **{k: payload.get(k) for k in ("what", "expr", "other", "xmin", "xmax")
                                                 if payload.get(k) is not None})
        if command in ("stats", "regress"):
            return self.runner.call(command, **{k: payload.get(k) for k in ("x", "y", "freq", "model")
                                               if payload.get(k) is not None})
        if command == "tools":
            return agent.TOOL_SPECS
        if command == "tool":
            return agent.call_tool(self.runner, str(payload.get("name", "")), payload.get("arguments"))
        if command == "ask":
            if self.llm is None:
                raise RuntimeError("aucun modèle local configuré (calc_cas.hub_api)")
            try:
                return agent.ask(str(payload.get("question", "")), self.llm, self.runner)
            except OSError as exc:
                raise RuntimeError(f"modèle local injoignable par le Hub : {exc}") from exc
        if command == "examples":
            return demos.catalog()
        raise ValueError(f"commande inconnue : {command!r}")
