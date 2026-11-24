"""Simulations du Professeur : pages HTML autonomes (canvas ou SVG, JavaScript en ligne, sans réseau).

Trois origines :
- **intégrées** (`modules/genesis_lab/sims/`) : système solaire, gaz parfait, fluides, cœur, neurone, circuit,
  projectile, ondes, fonctions, fractions ;
- **créées par le modèle local** (modèle « codeur » du Hub) à la demande, sur un sujet libre ;
- **programmées par le Claude Code local** : le Professeur écrit une demande (fichier Markdown) dans le dossier
  de Claude Code, l'utilisateur ouvre Claude Code d'un clic et lui dit de la traiter ; la page produite est
  importée au prochain affichage, après contrôle.

Toute page créée passe par `validate_html` : taille bornée, canvas ou SVG présent, et aucun moyen de joindre le
réseau ni de charger du code externe. Le Hub la sert ensuite dans un cadre isolé (CSP `sandbox allow-scripts`,
`default-src 'none'`) : même une page mal écrite ne peut rien lire ni envoyer.

Le lanceur de Claude Code n'est jamais lu : on se contente de l'ouvrir dans une nouvelle console.
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

BUILTIN_DIR = Path(__file__).with_name("sims")
MAX_BYTES = 300_000
SIM_ID = re.compile(r"^[a-z0-9_]{3,48}$")

BUILTIN: dict[str, dict[str, str]] = {
    "systeme_solaire": {"titre": "Le système solaire", "description": "Les 8 planètes en orbite, lois de Kepler."},
    "gaz_parfait": {"titre": "Le gaz parfait", "description": "Pression, volume, température : P·V = n·R·T."},
    "fluides": {"titre": "Les fluides", "description": "Vagues (liquide, particules) et baignoire."},
    "coeur": {"titre": "Le cœur", "description": "Cavités, valves, petite et grande circulation."},
    "neurone": {"titre": "Neurone et réflexe", "description": "Message nerveux, potentiels d'action, arc réflexe."},
    "circuit": {"titre": "Circuit électrique", "description": "Série, dérivation, loi d'Ohm."},
    "projectile": {"titre": "Mouvement d'un projectile", "description": "Chute libre, vecteurs vitesse, planètes."},
    "ondes": {"titre": "Les ondes", "description": "Onde progressive, interférences, effet Doppler."},
    "fonctions": {"titre": "Explorer une fonction", "description": "Affine, second degré, exp, sinus, tangente."},
    "fractions": {"titre": "Les fractions", "description": "Pizza, tablette, droite graduée, défis."},
}

# Ce qu'une page ne doit pas contenir : accès réseau, code externe, navigation, stockage, cadres.
FORBIDDEN: tuple[tuple[str, str], ...] = (
    (r"<script[^>]*\bsrc\s*=", "script externe"),
    (r"<(?:iframe|frame|object|embed|base|form|link)\b", "balise interdite"),
    (r"<meta[^>]+http-equiv", "balise meta interdite"),
    (r"\bfetch\s*\(", "accès réseau (fetch)"),
    (r"XMLHttpRequest|WebSocket|EventSource|sendBeacon|RTCPeerConnection", "accès réseau"),
    (r"\bimport\s*\(|^\s*import\s", "chargement de module"),
    (r"@import|url\s*\(\s*['\"]?\s*(?:https?:|//)", "ressource externe"),
    (r"(?:https?:)?//[a-z0-9.-]+\.[a-z]{2,}", "adresse externe"),
    (r"document\.cookie|localStorage|sessionStorage|indexedDB", "stockage"),
    (r"window\.open|location\s*(?:\.href)?\s*=|\.location\.(?:assign|replace)", "navigation"),
    (r"\beval\s*\(|new\s+Function\s*\(", "code dynamique"),
)
# Ajouté par le Hub à chaque page servie (intégrée ou créée) : bouton Pause commun (touche P) et hauteur du contenu
# envoyée au cadre du Professeur, qui s'ajuste. La pause retient les images d'animation et les minuteries, et
# décale l'horloge (performance.now, temps des images) pour que la simulation reparte sans saut.
HUB_TOOLS = "<script>" + (Path(__file__).with_name("sim_tools.js")).read_text(encoding="utf-8") + "</script>"


def with_hub_tools(page: bytes) -> bytes:
    """La page servie avec le bouton Pause et l'envoi de sa hauteur, placés avant tout autre script."""
    tools = HUB_TOOLS.encode("utf-8")
    match = re.search(rb"<head[^>]*>", page, re.IGNORECASE)
    if match:
        return page[:match.end()] + tools + page[match.end():]
    return tools + page


SVG_NS = re.compile(r"http://www\.w3\.org/(?:2000/svg|1999/xhtml|1999/xlink)")


class SimError(ValueError):
    """Simulation inconnue, refusée ou indisponible."""


def slug(text: str, limit: int = 40) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "_", plain).strip("_")[:limit].strip("_") or "simulation"


def validate_html(html: str) -> str:
    """Renvoie la page si elle est acceptable, lève `SimError` sinon (avec la raison)."""
    if not isinstance(html, str) or not html.strip():
        raise SimError("page vide")
    if len(html.encode("utf-8")) > MAX_BYTES:
        raise SimError(f"page trop lourde (plus de {MAX_BYTES // 1000} ko)")
    lowered = html.lower()
    if "<html" not in lowered and "<!doctype" not in lowered:
        raise SimError("ce n'est pas une page HTML complète")
    if "<canvas" not in lowered and "<svg" not in lowered and "createelementns" not in lowered:
        raise SimError("la page ne dessine rien (ni canvas ni SVG)")
    if "<script" not in lowered:
        raise SimError("la page n'a pas de script : ce n'est pas une simulation")
    checked = SVG_NS.sub("", html)
    for pattern, reason in FORBIDDEN:
        if re.search(pattern, checked, re.I | re.M):
            raise SimError(f"page refusée : {reason}")
    return html


def extract_html(text: str) -> str:
    """Extrait la page d'une réponse de modèle (bloc ```html, ou du <!doctype> au </html>)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    block = re.search(r"```(?:html)?\s*\n(.*?)```", text, re.S | re.I)
    if block and "<" in block.group(1):
        text = block.group(1)
    start = re.search(r"<!doctype html|<html", text, re.I)
    end = text.lower().rfind("</html>")
    if start and end > start.start():
        return text[start.start():end + len("</html>")].strip()
    return text.strip()


RULES = """Contraintes (la page sera refusée sinon) :
- UN SEUL fichier HTML complet (<!doctype html> ... </html>), tout en ligne : CSS dans <style>,
  JavaScript dans <script> ;
- dessin sur <canvas> (ou SVG), animation avec requestAnimationFrame ;
- AUCUNE ressource externe ni adresse web, aucun fetch/XMLHttpRequest/WebSocket, aucun import, aucun eval,
  aucun localStorage/cookie, aucune iframe/form/link ; moins de 300 ko ;
- textes en français, adaptés à l'âge de l'élève ; des curseurs ou boutons pour faire varier les paramètres ;
- une zone d'explication sous le dessin qui dit ce qui se passe et pourquoi (la loi ou le phénomène) ;
- la physique ou la biologie doit être juste (ordres de grandeur, sens des variations, formules exactes) ;
- fond sombre ou clair lisible, largeur 100 % (canvas en width:100%)."""


def brief(sim_id: str, subject: str, level: str, details: str, chapter: str = "") -> str:
    """Demande écrite pour le Claude Code local (aucun secret, aucun chemin personnel)."""
    return f"""# Demande du Professeur d'AetherTwin : simulation « {subject} »

Identifiant : `{sim_id}`
Niveau de l'élève : {level or "non précisé"}
{f"Chapitre : {chapter}" if chapter else ""}

## Ce qu'il faut programmer
Une simulation interactive et pédagogique sur : **{subject}**.
{details.strip() or "Montre le phénomène, avec des paramètres que l'élève peut faire varier."}

## Où écrire le résultat
Écris le fichier `professeur/simulations/{sim_id}.html` (à côté du dossier `demandes`). Ne modifie rien d'autre.
Le Professeur l'importera automatiquement après contrôle.

{RULES}
"""


class SimLibrary:
    """Bibliothèque des simulations : intégrées, créées par le modèle, programmées par le Claude Code local."""

    def __init__(self, data_dir: Path, coder: Callable[[list[dict[str, str]]], str] | None = None,
                 claude_dir: Path | None = None, claude_launcher: Path | None = None,
                 spawner: Callable[..., Any] = subprocess.Popen, now: Callable[[], float] = time.time,
                 reviewer: Callable[[list[dict[str, str]]], str] | None = None) -> None:
        self.dir = Path(data_dir) / "simulations"
        self.coder, self.now, self.spawner = coder, now, spawner
        self.reviewer = reviewer or coder  # le modèle du Professeur relit, le codeur corrige
        self.claude_dir = Path(claude_dir) if claude_dir else None
        self.claude_launcher = Path(claude_launcher) if claude_launcher else None
        self.jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    # -- lecture
    def _meta(self, sim_id: str) -> dict[str, Any]:
        try:
            data = json.loads((self.dir / f"{sim_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        return data if isinstance(data, dict) else {}

    def list(self) -> list[dict[str, Any]]:
        self.collect_claude()
        items = [{"id": key, **value, "origine": "intégrée"} for key, value in BUILTIN.items()
                 if (BUILTIN_DIR / f"{key}.html").exists()]
        if self.dir.is_dir():
            for path in sorted(self.dir.glob("*.html")):
                meta = self._meta(path.stem)
                items.append({"id": path.stem, "titre": meta.get("titre", path.stem),
                              "description": meta.get("description", ""), "origine": meta.get("origine", "créée"),
                              "chapitre": meta.get("chapitre", ""), "date": meta.get("date"),
                              "version": int(meta.get("version") or 1),
                              "retours": [r.get("texte", "") for r in meta.get("retours") or []]})
        return items

    def for_chapter(self, chapter_id: str) -> list[dict[str, Any]]:
        return [item for item in self.list() if item.get("chapitre") == chapter_id]

    def path(self, sim_id: str) -> Path:
        if not SIM_ID.match(sim_id or ""):
            raise SimError("identifiant de simulation invalide")
        for path in (BUILTIN_DIR / f"{sim_id}.html", self.dir / f"{sim_id}.html"):
            if path.is_file():
                return path
        raise SimError("simulation introuvable")

    def _new_id(self, subject: str) -> str:
        base = slug(subject)
        candidate, n = base, 2
        while candidate in BUILTIN or (self.dir / f"{candidate}.html").exists() \
                or (self.claude_dir and (self._requests_dir() / f"{candidate}.md").exists()):
            candidate, n = f"{base}_{n}", n + 1
        return candidate

    def _store(self, sim_id: str, html: str, meta: dict[str, Any]) -> dict[str, Any]:
        validate_html(html)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / f"{sim_id}.html").write_text(html, encoding="utf-8")
        meta = {**meta, "date": self.now()}
        (self.dir / f"{sim_id}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"id": sim_id, **meta}

    def delete(self, sim_id: str) -> dict[str, Any]:
        if sim_id in BUILTIN:
            raise SimError("une simulation intégrée ne se supprime pas")
        path = self.path(sim_id)
        path.unlink()
        (self.dir / f"{sim_id}.json").unlink(missing_ok=True)
        for old in self._versions(sim_id):
            old.unlink()
        return {"id": sim_id, "supprimee": True}

    # -- création par le modèle local
    def generate(self, subject: str, level: str = "", details: str = "", chapter: str = "") -> dict[str, Any]:
        """Fait écrire la page par le modèle codeur (deux essais : le second avec la raison du refus)."""
        if self.coder is None:
            raise SimError("modèle local indisponible (le Hub ne répond pas)")
        subject = subject.strip()[:160]
        if not subject:
            raise SimError("sujet vide")
        messages = [{"role": "system", "content": "Tu es un développeur web et un professeur de sciences. "
                                                  "Tu réponds uniquement par le code HTML demandé."},
                    {"role": "user", "content": f"Programme une simulation interactive sur : {subject}.\n"
                                                f"Élève : {level or 'collège'}. {details.strip()}\n\n{RULES}"}]
        error = ""
        for _ in range(2):
            answer = self.coder(messages)
            html = extract_html(answer)
            try:
                validate_html(html)
            except SimError as exc:
                error = str(exc)
                messages += [{"role": "assistant", "content": answer[:20000]},
                             {"role": "user", "content": f"La page a été refusée : {error}. Corrige et renvoie la page "
                                                         "complète, en respectant toutes les contraintes."}]
                continue
            sim_id = self._new_id(subject)
            return self._store(sim_id, html, {"titre": subject, "description": details.strip()[:300],
                                              "origine": "modèle local", "chapitre": chapter, "niveau": level})
        raise SimError(f"le modèle n'a pas produit de page acceptable ({error})")

    # -- retours : relecture par le Professeur, corrections par le modèle codeur, retour en arrière
    def review(self, sim_id: str) -> dict[str, Any]:
        """Le modèle du Professeur lit le code et liste ce qui est faux (science, pédagogie, interface)."""
        if self.reviewer is None:
            raise SimError("modèle local indisponible (le Hub ne répond pas)")
        html = self.path(sim_id).read_text(encoding="utf-8", errors="replace")
        meta = self._meta(sim_id) or BUILTIN.get(sim_id, {})
        answer = self.reviewer([
            {"role": "system", "content": "Tu es professeur de sciences et tu relis le code d'une simulation "
                                          "pédagogique. Tu réponds en français, sans code."},
            {"role": "user", "content": f"Simulation « {meta.get('titre', sim_id)} » "
                                        f"(élève : {meta.get('niveau') or 'collège'}). Lis le code et liste, "
                                        "numérotées, au plus 5 erreurs à corriger : d'abord la science (positions, "
                                        "sens des variations, formules, ordres de grandeur, ce que voit un "
                                        "observateur), puis l'explication affichée, puis l'interface (curseurs, "
                                        "boutons qui ne font rien). Une ligne par erreur, avec la correction "
                                        "attendue. Si tout est juste, réponds seulement « Rien à corriger ».\n\n"
                                        f"CODE :\n{html[:60000]}"}])
        text = re.sub(r"<think>.*?</think>", "", answer or "", flags=re.S).strip()
        if not text:
            raise SimError("le modèle n'a rien répondu")
        return {"id": sim_id, "retour": text[:3000], "rien": bool(re.match(r"\W*rien à corriger", text, re.I))}

    def _versions_dir(self) -> Path:
        return self.dir / "versions"

    def _versions(self, sim_id: str) -> list[Path]:
        if not self._versions_dir().is_dir():
            return []
        found = self._versions_dir().glob(f"{sim_id}.v*.html")
        return sorted(found, key=lambda p: int(p.stem.rsplit(".v", 1)[1]) if p.stem.rsplit(".v", 1)[1].isdigit()
                      else 0)

    def improve(self, sim_id: str, feedback: str) -> dict[str, Any]:
        """Le modèle codeur corrige la page d'après le retour (et les retours déjà donnés).

        Une simulation intégrée n'est jamais modifiée : sa version corrigée devient une nouvelle simulation.
        L'ancienne version d'une simulation créée est gardée (`versions/`) : « Revenir » la rétablit.
        """
        if self.coder is None:
            raise SimError("modèle local indisponible (le Hub ne répond pas)")
        feedback = feedback.strip()[:3000]
        if not feedback:
            raise SimError("retour vide : dis ce qui ne va pas")
        current = self.path(sim_id).read_text(encoding="utf-8", errors="replace")
        meta = dict(self._meta(sim_id)) if sim_id not in BUILTIN else {
            "titre": BUILTIN[sim_id]["titre"] + " (modifiée)", "description": BUILTIN[sim_id]["description"],
            "origine": "modèle local", "chapitre": "", "niveau": "", "base": sim_id}
        history = meta.get("retours") or []
        earlier = "".join(f"- {item['texte']}\n" for item in history[-5:])
        messages = [{"role": "system", "content": "Tu es un développeur web et un professeur de sciences. "
                                                  "Tu réponds uniquement par le code HTML demandé."},
                    {"role": "user", "content": f"Voici une simulation interactive sur « {meta.get('titre', sim_id)} »"
                                                f" (élève : {meta.get('niveau') or 'collège'}).\n\n"
                                                + (f"Retours déjà pris en compte (à garder) :\n{earlier}\n"
                                                   if earlier else "")
                                                + f"NOUVEAU RETOUR DE L'ENSEIGNANT, à corriger en priorité :\n"
                                                  f"{feedback}\n\nRenvoie la page complète corrigée. Garde ce "
                                                  f"qui marche déjà.\n\n{RULES}\n\nPAGE ACTUELLE :\n{current}"}]
        error = ""
        for _ in range(2):
            answer = self.coder(messages)
            html = extract_html(answer)
            try:
                validate_html(html)
            except SimError as exc:
                error = str(exc)
                messages += [{"role": "assistant", "content": answer[:20000]},
                             {"role": "user", "content": f"La page a été refusée : {error}. Corrige et renvoie la page "
                                                         "complète, en respectant toutes les contraintes."}]
                continue
            with self._lock:
                if sim_id in BUILTIN:
                    target = self._new_id(meta["titre"])
                else:
                    target = sim_id
                    self._versions_dir().mkdir(parents=True, exist_ok=True)
                    number = int(meta.get("version") or 1)
                    (self._versions_dir() / f"{sim_id}.v{number}.html").write_text(current, encoding="utf-8")
                meta["version"] = int(meta.get("version") or 1) + (sim_id not in BUILTIN)
                meta["retours"] = [*history, {"texte": feedback, "date": self.now()}][-20:]
                return self._store(target, html, meta)
        raise SimError(f"le modèle n'a pas produit de page acceptable ({error})")

    def undo(self, sim_id: str) -> dict[str, Any]:
        """Rétablit la version précédente d'une simulation corrigée."""
        if sim_id in BUILTIN:
            raise SimError("une simulation intégrée n'a pas de version précédente")
        self.path(sim_id)
        versions = self._versions(sim_id)
        if not versions:
            raise SimError("pas de version précédente")
        with self._lock:
            previous = versions[-1]
            meta = self._meta(sim_id)
            meta["version"] = max(1, int(meta.get("version") or 2) - 1)
            meta["retours"] = (meta.get("retours") or [])[:-1]
            stored = self._store(sim_id, previous.read_text(encoding="utf-8"), meta)
            previous.unlink()
        return stored

    def generate_async(self, subject: str, level: str = "", details: str = "", chapter: str = "") -> dict[str, Any]:
        """Lance `generate` en arrière-plan (plusieurs minutes avec un modèle local) ; suivi par `job`."""
        key = slug(subject)
        with self._lock:
            job = self.jobs.get(key)
            if job and job.get("en_cours"):
                return job
            job = {"cle": key, "sujet": subject, "en_cours": True, "debut": self.now(), "resultat": None, "erreur": ""}
            self.jobs[key] = job

        def run() -> None:
            try:
                job["resultat"] = self.generate(subject, level, details, chapter)
            except Exception as exc:  # noqa: BLE001 — l'erreur est montrée à l'élève
                job["erreur"] = str(exc)
            job["en_cours"] = False

        threading.Thread(target=run, name=f"sim-{key}", daemon=True).start()
        return job

    # -- Claude Code local
    def _requests_dir(self) -> Path:
        return Path(self.claude_dir or ".") / "professeur" / "demandes"

    def _outputs_dir(self) -> Path:
        return Path(self.claude_dir or ".") / "professeur" / "simulations"

    def claude_available(self) -> bool:
        return bool(self.claude_dir and self.claude_dir.is_dir())

    def ask_claude(self, subject: str, level: str = "", details: str = "", chapter: str = "") -> dict[str, Any]:
        """Écrit la demande pour le Claude Code local ; renvoie ce qu'il faut lui dire."""
        if not self.claude_available():
            raise SimError("dossier du Claude Code local introuvable (section genesis_lab, claude_local_dir)")
        subject = subject.strip()[:160]
        if not subject:
            raise SimError("sujet vide")
        sim_id = self._new_id(subject)
        self._requests_dir().mkdir(parents=True, exist_ok=True)
        self._outputs_dir().mkdir(parents=True, exist_ok=True)
        (self._requests_dir() / f"{sim_id}.md").write_text(brief(sim_id, subject, level, details, chapter),
                                                            encoding="utf-8")
        meta = {"titre": subject, "description": details.strip()[:300], "chapitre": chapter, "niveau": level,
                "date": self.now()}
        (self._requests_dir() / f"{sim_id}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return {"id": sim_id, "statut": "en attente",
                "consigne": f"Lis professeur/demandes/{sim_id}.md et fais ce qui est demandé."}

    def collect_claude(self) -> list[dict[str, Any]]:
        """État des demandes ; importe (après contrôle) les pages que Claude Code a écrites."""
        if not self.claude_available() or not self._requests_dir().is_dir():
            return []
        states = []
        for request in sorted(self._requests_dir().glob("*.md")):
            sim_id = request.stem
            if not SIM_ID.match(sim_id):
                continue
            try:
                meta = json.loads((self._requests_dir() / f"{sim_id}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {"titre": sim_id}
            state = {"id": sim_id, "titre": meta.get("titre", sim_id), "statut": "en attente"}
            output = self._outputs_dir() / f"{sim_id}.html"
            if (self.dir / f"{sim_id}.html").exists():
                state["statut"] = "importée"
            elif output.is_file():
                try:
                    self._store(sim_id, output.read_text(encoding="utf-8", errors="replace"),
                                {"titre": meta.get("titre", sim_id), "description": meta.get("description", ""),
                                 "origine": "Claude Code local", "chapitre": meta.get("chapitre", ""),
                                 "niveau": meta.get("niveau", "")})
                    state["statut"] = "importée"
                except SimError as exc:
                    state["statut"] = "refusée"
                    state["raison"] = str(exc)
            states.append(state)
        return states

    def open_claude(self) -> dict[str, Any]:
        """Ouvre le Claude Code local dans une nouvelle console (le lanceur n'est pas lu)."""
        launcher = self.claude_launcher
        if not launcher or not launcher.is_file() or launcher.suffix.lower() not in (".bat", ".cmd", ".exe"):
            raise SimError("lanceur du Claude Code local introuvable (section genesis_lab, claude_local_launcher)")
        self.spawner(["cmd", "/c", "start", "", str(launcher)], cwd=str(launcher.parent),
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"ouvert": True}
