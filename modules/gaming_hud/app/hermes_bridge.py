"""
Pont natif entre WoW Assistant et **Hermes Agent** (l'agent installé sur le PC : application Hermes, passerelle,
CLI `hermes`). WoW Assistant s'en sert comme coach : une conversation dédiée, la mémoire et les skills de Hermes,
et les données du jeu en direct grâce au serveur MCP `hermes_mcp.py`.

Deux façons de parler à Hermes, choisies automatiquement :
  - **API de la passerelle** (recommandé) : `http://127.0.0.1:<port>/api/sessions/{id}/chat/stream`. Une vraie
    session Hermes (visible dans l'application Hermes), réponse au fil de l'eau, outils utilisés affichés, et les
    demandes d'autorisation de Hermes (commande sensible) remontées dans WoW Assistant : rien n'est accordé sans
    un clic du joueur. Demande `API_SERVER_KEY` dans le `.env` de Hermes (bouton « Activer l'API »).
  - **CLI** (`hermes -z`, sans réglage) : une question = un lancement (≈ 20 s). Ce mode saute les autorisations de
    Hermes : on le limite donc à des outils sans danger (web, skills, mémoire, vision...) — pas de terminal, de
    fichiers ni de navigateur — plus les outils de jeu de WoW Assistant.

Les réglages de Hermes ne sont modifiés que par les boutons de l'onglet Hermes (le joueur clique), avec une copie
de sauvegarde du fichier touché. La clé de l'API n'est jamais affichée ni écrite ailleurs que dans le `.env` de
Hermes.
"""
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MCP_NAME = "wow_assistant"
MCP_SCRIPT = os.path.join(APP_DIR, "hermes_mcp.py")
SKILL_NAME = "wow-coach"
SKILL_SOURCE = os.path.join(APP_DIR, "hermes_skill", SKILL_NAME)
SKILL_CATEGORY = "gaming"
# outils autorisés en mode CLI (approbations sautées par Hermes) : rien qui exécute, écrive ou pilote le PC
SAFE_TOOLSETS = ("web", "skills", "memory", "session_search", "vision", "todo")
SESSION_TITLE = "WoW Assistant"
REASONING = (("low", "Rapide"), ("medium", "Équilibrée"), ("xhigh", "Poussée"), ("hermes", "Hermes"))
FAILED_MARKERS = ("couldn't finish this reply", "Your request was not processed", "Something went wrong")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def hermes_home():
    env = os.environ.get("HERMES_HOME")
    if env:
        return env
    local = os.path.join(os.environ.get("LOCALAPPDATA") or "", "hermes")
    if os.environ.get("LOCALAPPDATA") and os.path.isdir(local):
        return local
    return os.path.join(os.path.expanduser("~"), ".hermes")


def read_env(path):
    """Variables d'un fichier .env (KEY=VALUE, guillemets retirés). Valeurs gardées en mémoire seulement."""
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key.startswith("export "):
                    key = key[7:].strip()
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                out[key] = value
    except OSError:
        pass
    return out


def _pid_alive(pid):
    if not pid:
        return False
    if sys.platform == "win32":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259                                               # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _port_open(port, host="127.0.0.1", timeout=0.3):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def mcp_registered(config_text, name=MCP_NAME):
    """Le serveur MCP figure-t-il dans config.yaml (section mcp_servers) ? Lecture texte, sans dépendance YAML."""
    inside = False
    for line in config_text.splitlines():
        if re.match(r"^mcp_servers\s*:", line):
            inside = True
            continue
        if inside and line and not line[0].isspace() and not line.lstrip().startswith("#"):
            inside = False
        if inside and re.match(rf"^\s+{re.escape(name)}\s*:", line):
            return True
    return False


MIN_CONTEXT = 64000          # Hermes refuse les modèles servis avec moins de contexte


def model_context(config_text, model):
    """Contexte réglé dans Hermes pour ce modèle (section providers), 0 si non précisé."""
    if not model:
        return 0
    lines = config_text.splitlines()
    for i, line in enumerate(lines):
        if re.match(rf"^(\s+)['\"]?{re.escape(model)}['\"]?\s*:\s*$", line):
            indent = len(line) - len(line.lstrip())
            for nxt in lines[i + 1:]:
                if not nxt.strip():
                    continue
                if len(nxt) - len(nxt.lstrip()) <= indent:
                    break
                found = re.match(r"^\s+context_length\s*:\s*(\d+)", nxt)
                if found:
                    return int(found.group(1))
    return 0


def last_error(home, since):
    """Dernière erreur notée par Hermes (logs/errors.log) depuis l'heure `since` : « Type : message »."""
    path = os.path.join(home, "logs", "errors.log")
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - 65536))
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    stamp, found = "", ""
    limit = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(since - 2))
    for line in tail.splitlines():
        head = re.match(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", line)
        if head:
            stamp = head.group(1)
        err = re.match(r"^([A-Za-z_.]*(?:Error|Exception)): (.+)", line)
        if err and stamp >= limit:
            found = f"{err.group(1)}: {err.group(2)}"
    return found


def explain_error(text):
    """Erreurs connues de Hermes expliquées en français, avec quoi faire."""
    small = re.search(r"context window of ([\d,. ]+) tokens.*?minimum ([\d,. ]+)", text or "")
    if small:
        return (f"Le modèle de Hermes n'a que {small.group(1).strip()} jetons de contexte ; Hermes en demande au moins "
                f"{small.group(2).strip()}. Dans Hermes : Paramètres > Fournisseurs > Points de terminaison > "
                "Contexte : 64000 ou plus (assez de mémoire vidéo nécessaire).")
    if "reasoning effort" in (text or "").lower():
        return ("Le modèle refuse le niveau de réflexion demandé par Hermes (souvent « high » avec Qwen 3.5). Onglet "
                "Hermes > Réflexion : Rapide ou Équilibrée ; dans Hermes, choisir Medium à côté du modèle.")
    if "Connection refused" in (text or "") or "ConnectError" in (text or ""):
        return "Hermes n'arrive pas à joindre son serveur de modèles (Ollama lancé ?). Détail : " + text[:200]
    return text


class HermesInfo:
    """État de Hermes sur ce PC (relu au plus toutes les 5 s)."""

    def __init__(self, home=None):
        self.home = home or hermes_home()
        self._at = 0.0
        self.state = {}
        self._key = ""

    def refresh(self, force=False):
        if not force and time.monotonic() - self._at < 5:
            return self.state
        self._at = time.monotonic()
        home = self.home
        exe = os.path.join(home, "bin", "hermes.exe" if sys.platform == "win32" else "hermes")
        if not os.path.isfile(exe):
            exe = shutil.which("hermes") or ""
        gateway = {}
        try:
            with open(os.path.join(home, "gateway_state.json"), encoding="utf-8") as f:
                gateway = json.load(f)
        except (OSError, ValueError):
            pass
        env = read_env(os.path.join(home, ".env"))
        self._key = env.get("API_SERVER_KEY", "")
        port = env.get("API_SERVER_PORT", "8642") or "8642"
        try:
            with open(os.path.join(home, "config.yaml"), encoding="utf-8", errors="replace") as f:
                config = f.read()
        except OSError:
            config = ""
        model = re.search(r"^model:\s*\n(?:\s+.*\n)*?\s+default:\s*['\"]?([^'\"\n]+)", config, re.M)
        enabled = env.get("API_SERVER_ENABLED", "").lower() in ("1", "true", "yes", "on")
        self.state = {
            "found": os.path.isdir(home) and (bool(exe) or bool(gateway)),
            "home": home, "exe": exe,
            "version": gateway.get("code_version", ""),
            "gateway": gateway.get("gateway_state") == "running" and _pid_alive(gateway.get("pid")),
            "model": model.group(1).strip() if model else "",
            "api_enabled": enabled, "api_key": bool(self._key), "api_port": int(port) if port.isdigit() else 8642,
            "api_up": enabled and bool(self._key) and _port_open(port),
            "skill": os.path.isfile(self.skill_path()),
            "mcp": mcp_registered(config),
            "context": model_context(config, model.group(1).strip() if model else ""),
        }
        return self.state

    def key(self):
        return self._key

    def desktop_app(self):
        """Application de bureau Hermes (Hermes.exe), pour la relancer après l'activation de l'API."""
        base = os.path.join(self.home, "hermes-agent", "apps", "desktop", "release")
        for sub in ("win-unpacked", ""):
            path = os.path.join(base, sub, "Hermes.exe")
            if os.path.isfile(path):
                return path
        return ""

    def skill_path(self):
        return os.path.join(self.home, "skills", SKILL_CATEGORY, SKILL_NAME, "SKILL.md")


# ---------------------------------------------------------------------------------------------- réponses
class HermesJob:
    """Une question en cours. Compatible avec llm.Job (done, text, error) ; en plus : texte partiel au fil de
    l'eau, outils utilisés, demande d'autorisation en attente, session, mode utilisé."""

    def __init__(self, transport):
        self.transport = transport
        self.done = False
        self.text = ""
        self.error = ""
        self.events = []          # [(heure, genre, texte)] : outils, réflexion, autorisations
        self.approval = None      # {"run_id", "command", "description", "choices"} en attente du joueur
        self.session_id = ""
        self.run_id = ""
        self.started = time.time()
        self.stopped = False
        self._proc = None

    def note(self, kind, text):
        self.events.append((time.time(), kind, text))
        del self.events[:-40]

    def status(self):
        if self.approval:
            return "En attente de votre autorisation"
        if self.events and self.events[-1][1] in ("tool", "start"):
            return self.events[-1][2]
        return "Hermes réfléchit…" if not self.text else "Hermes répond…"


class HermesClient:
    TIMEOUT = 600

    def __init__(self, settings, info=None, opener=None, runner=None):
        self.settings = settings
        self.info = info or HermesInfo()
        self._open = opener or urllib.request.urlopen
        self._run = runner or subprocess.Popen

    # ------------------------------------------------------------------ choix du mode
    def transport(self):
        st = self.info.refresh()
        wanted = self.settings.get("hermes.transport", "auto") if self.settings is not None else "auto"
        if wanted in ("auto", "api") and st.get("api_up"):
            return "api"
        if wanted in ("auto", "cli") and st.get("exe"):
            return "cli"
        return ""

    def describe(self):
        st = self.info.refresh()
        mode = self.transport()
        if not st.get("found"):
            return "Hermes Agent introuvable sur ce PC"
        label = {"api": "API de la passerelle", "cli": "CLI (hermes -z)"}.get(mode, "indisponible")
        return f"Hermes {st.get('version') or ''} · {label}" + (f" · {st['model']}" if st.get("model") else "")

    def is_configured(self):
        return bool(self.transport())

    # ------------------------------------------------------------------ question
    def ask(self, prompt, images=None, history=None):
        mode = self.transport()
        job = HermesJob(mode)
        if not mode:
            job.error = ("Hermes Agent introuvable ou arrêté : installez / lancez Hermes, ou choisissez un autre "
                         "assistant dans les Paramètres généraux.")
            job.done = True
            return job
        target = self._ask_api if mode == "api" else self._ask_cli
        threading.Thread(target=self._guard, args=(target, job, prompt, list(images or []), list(history or [])),
                         daemon=True).start()
        return job

    def _guard(self, target, job, prompt, images, history):
        try:
            target(job, prompt, images, history)
        except Exception as e:
            if not job.stopped:
                job.error = str(e) or e.__class__.__name__
        finally:
            if job.stopped and not job.text:
                job.error = job.error or "Arrêté."
            job.approval = None
            job.done = True

    # ------------------------------------------------------------------ API de la passerelle
    def _url(self, path):
        return f"http://127.0.0.1:{self.info.refresh().get('api_port', 8642)}{path}"

    def _request(self, method, path, body=None, stream=False, timeout=30):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Authorization": "Bearer " + self.info.key(), "Content-Type": "application/json",
                   "User-Agent": "WoWAssistant/2.0"}
        if stream:
            headers["Accept"] = "text/event-stream"
        req = urllib.request.Request(self._url(path), data=data, headers=headers, method=method)
        return self._open(req, timeout=timeout)

    def reasoning(self):
        """Niveau de réflexion demandé à chaque question ("" = celui de Hermes)."""
        level = self.settings.get("hermes.reasoning", "medium") if self.settings is not None else "medium"
        return level if level in {k for k, _ in REASONING} - {"hermes"} else ""

    def _session(self, fresh=False):
        sid = "" if fresh else (self.settings.get("hermes.session_id", "") if self.settings is not None else "")
        if sid:
            return sid
        body = {"title": f"{SESSION_TITLE} {time.strftime('%d/%m %H:%M')}"}
        try:
            with self._request("POST", "/api/sessions", body) as r:
                sid = json.loads(r.read().decode("utf-8"))["session"]["id"]
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise
            with self._request("POST", "/api/sessions", {}) as r:         # titre refusé (doublon) : sans titre
                sid = json.loads(r.read().decode("utf-8"))["session"]["id"]
        if self.settings is not None:
            self.settings.set("hermes.session_id", sid)
            self.settings.save()
        return sid

    def _ask_api(self, job, prompt, images, history):
        message = prompt
        if images:
            message = [{"type": "text", "text": prompt}] + [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}} for mime, data in images]
        sid = self._session()
        body = {"message": message}
        if self.reasoning():
            body["model_options"] = {"reasoning_effort": self.reasoning()}
        try:
            response = self._request("POST", f"/api/sessions/{sid}/chat/stream", body, stream=True,
                                     timeout=self.TIMEOUT)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise RuntimeError(_http_error(e))
            sid = self._session(fresh=True)                                # session supprimée dans Hermes
            response = self._request("POST", f"/api/sessions/{sid}/chat/stream", body,
                                     stream=True, timeout=self.TIMEOUT)
        job.session_id = sid
        with response:
            job._proc = response
            for name, payload in parse_sse(response):
                self._on_event(job, name, payload)
                if name == "done" or job.stopped:
                    break

    def _on_event(self, job, name, p):
        if p.get("run_id"):
            job.run_id = p["run_id"]
        if name == "assistant.delta":
            job.text += p.get("delta", "")
        elif name == "assistant.completed":
            job.text = p.get("content") or job.text
        elif name == "tool.started":
            job.note("tool", _tool_label(p.get("tool_name"), p.get("preview")))
        elif name == "tool.failed":
            job.note("fail", "Échec : " + _tool_label(p.get("tool_name"), p.get("preview")))
        elif name == "tool.progress" and p.get("tool_name") == "_thinking":
            job.note("think", "Réflexion…")
        elif name == "assistant.commentary":
            job.note("comment", p.get("text", "")[:200])
        elif name == "approval.request":
            job.approval = {"run_id": p.get("run_id") or job.run_id, "request_id": p.get("request_id"),
                            "command": p.get("command") or "", "description": p.get("description") or "",
                            "choices": p.get("choices") or ["once", "deny"]}
            job.note("approval", "Autorisation demandée : " + (p.get("description") or p.get("command") or "")[:160])
        elif name in ("run.failed", "error"):
            job.error = explain_error(str(p.get("message") or p.get("error") or "Échec de Hermes"))
        elif name == "run.cancelled":
            job.error = job.error or "Interrompu."

    def approve(self, job, choice):
        """Réponse du joueur à une demande d'autorisation de Hermes : once, session, always ou deny."""
        pending = job.approval
        if not pending:
            return False
        body = {"choice": choice}
        if pending.get("request_id"):
            body["request_id"] = pending["request_id"]
        try:
            with self._request("POST", f"/v1/runs/{pending['run_id']}/approval", body) as r:
                r.read()
        except (urllib.error.URLError, OSError) as e:
            job.note("fail", f"Autorisation non transmise : {e}")
            return False
        job.note("approval", {"deny": "Refusé."}.get(choice, "Autorisé (" + choice + ")."))
        job.approval = None
        return True

    def stop(self, job):
        job.stopped = True
        if job.transport == "api" and job.run_id:
            try:
                with self._request("POST", f"/v1/runs/{job.run_id}/stop", {}) as r:
                    r.read()
            except (urllib.error.URLError, OSError):
                pass
        proc = job._proc
        if proc is not None:
            try:
                (proc.kill if hasattr(proc, "kill") else proc.close)()
            except Exception:
                pass

    def new_session(self):
        if self.settings is not None:
            self.settings.set("hermes.session_id", "")
            self.settings.save()

    # ------------------------------------------------------------------ CLI (hermes -z)
    def cli_args(self, prompt):
        st = self.info.refresh()
        toolsets = list(SAFE_TOOLSETS) + ([f"mcp-{MCP_NAME}"] if st.get("mcp") else [])
        args = [st["exe"], "-z", prompt, "-t", ",".join(toolsets)]
        if self.reasoning():
            args += ["--reasoning", self.reasoning()]
        if st.get("skill"):
            args += ["-s", SKILL_NAME]
        return args

    def _ask_cli(self, job, prompt, images, history):
        if history:      # pas de session en mode CLI : les derniers échanges sont rappelés dans la question
            recap = "\n".join(f"{'Joueur' if role == 'user' else 'Hermes'} : {text[:600]}" for role, text in history[-6:])
            prompt = f"Échanges précédents (rappel) :\n{recap}\n\nNouvelle question :\n{prompt}"
        if images:
            prompt += "\n\n(Le joueur a joint une capture d'écran : non transmise en mode CLI. Activez l'API de " \
                      "Hermes pour l'analyse d'images.)"
        job.note("start", "Lancement de Hermes (CLI)…")
        proc = self._run(self.cli_args(prompt), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, cwd=tempfile.gettempdir(), creationflags=NO_WINDOW)
        job._proc = proc
        try:
            out, err = proc.communicate(timeout=self.TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise RuntimeError("Hermes n'a pas répondu à temps.")
        text = (out or b"").decode("utf-8", "replace").strip()
        if any(marker in text for marker in FAILED_MARKERS) and len(text) < 600:
            detail = last_error(self.info.home, job.started)
            raise RuntimeError(explain_error(detail) if detail else
                               "Hermes n'a pas pu répondre (détails : commande « hermes logs »).")
        if proc.returncode and not text:
            raise RuntimeError((err or b"").decode("utf-8", "replace").strip()[-400:] or f"code {proc.returncode}")
        job.text = text or "(réponse vide)"


def _tool_label(name, preview):
    name = str(name or "outil")
    if name.startswith("mcp_"):
        name = (name.split(MCP_NAME + "_", 1)[-1] if MCP_NAME in name else name[4:]).lstrip("_")
    labels = {"web_search": "Recherche web", "web_extract": "Lecture d'une page", "skill_view": "Skill",
              "memory": "Mémoire", "session_search": "Anciennes conversations", "vision_analyze": "Analyse d'image",
              "wow_character": "Données : personnage", "wow_quests": "Données : quêtes",
              "wow_inventory": "Données : objets", "wow_professions": "Données : métiers",
              "wow_talents": "Données : talents", "wow_progress": "Données : progression",
              "wow_collections": "Données : collections", "wow_bestiary": "Données : bestiaire",
              "wow_recent_activity": "Données : activité", "wow_status": "Données : fraîcheur",
              "wow_routine": "Données : semaine", "wow_knowledge_search": "Connaissances : recherche",
              "wow_knowledge_save": "Connaissances : enregistrement",
              "terminal": "Commande", "browser_navigate": "Navigateur"}
    label = labels.get(name, name)
    preview = re.sub(r"\s+", " ", str(preview or "")).strip()
    return f"{label} : {preview[:90]}" if preview else label


def _http_error(e):
    try:
        detail = json.loads(e.read().decode("utf-8", "ignore")).get("error", {}).get("message", "")
    except (ValueError, AttributeError, OSError):
        detail = ""
    if e.code == 401:
        return "Clé de l'API Hermes refusée (API_SERVER_KEY)."
    return f"Hermes : erreur HTTP {e.code}" + (f" — {detail[:200]}" if detail else "")


def parse_sse(stream):
    """Événements d'un flux SSE : (nom, données JSON)."""
    name, data = "", []
    for raw in stream:
        line = raw.decode("utf-8", "replace").rstrip("\r\n") if isinstance(raw, bytes) else raw.rstrip("\r\n")
        if not line:
            if data:
                try:
                    payload = json.loads("\n".join(data))
                except ValueError:
                    payload = {"text": "\n".join(data)}
                yield name or payload.get("event", "message"), payload if isinstance(payload, dict) else {}
            name, data = "", []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        try:
            yield name or "message", json.loads("\n".join(data))
        except ValueError:
            pass


# ---------------------------------------------------------------------------------------------- installation
def _backup(path):
    if os.path.isfile(path):
        dest = f"{path}.wow-assistant-{time.strftime('%Y%m%d-%H%M%S')}.bak"
        shutil.copy2(path, dest)
        return dest
    return ""


def install_skill(info):
    """Copie le skill « wow-coach » dans les skills de Hermes (remplace seulement notre propre dossier)."""
    dest = os.path.dirname(info.skill_path())
    if not os.path.isfile(os.path.join(SKILL_SOURCE, "SKILL.md")):
        return False, "Skill introuvable dans le dossier de l'appli (hermes_skill)."
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    shutil.copytree(SKILL_SOURCE, dest)
    info.refresh(force=True)
    return True, f"Skill « {SKILL_NAME} » installé dans Hermes."


def register_mcp(info, python=None, runner=subprocess.run):
    """Ajoute les outils de jeu à Hermes avec sa propre commande (`hermes mcp add`), config.yaml sauvegardé avant."""
    st = info.refresh(force=True)
    if not st.get("exe"):
        return False, "Commande hermes introuvable."
    _backup(os.path.join(info.home, "config.yaml"))
    python = python or sys.executable
    if python.lower().endswith("pythonw.exe"):
        python = python[:-5] + ".exe"           # le serveur MCP parle sur la sortie standard
    args = [st["exe"], "mcp", "add", MCP_NAME, "--command", python, "--args", "-I", MCP_SCRIPT]
    result = runner(args, input="y\n", capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=300, creationflags=NO_WINDOW)
    st = info.refresh(force=True)
    if st.get("mcp"):
        return True, "Outils de jeu ajoutés à Hermes (13 outils : 11 en lecture seule sur le jeu, 2 pour la base de connaissances du coach)."
    tail = ((result.stdout or "") + (result.stderr or "")).strip().splitlines()[-3:]
    return False, "Échec de « hermes mcp add » : " + " / ".join(tail)


def restart_gateway(info, runner=subprocess.run, wait=60):
    """Relance la passerelle de Hermes (`hermes gateway restart`) : c'est elle qui lit le .env au démarrage. Fermer
    l'application Hermes ne l'arrête pas (service en arrière-plan)."""
    st = info.refresh(force=True)
    if not st.get("exe"):
        return False, "Commande hermes introuvable."
    result = runner([st["exe"], "gateway", "restart"], capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=180, creationflags=NO_WINDOW)
    end = time.monotonic() + wait
    while time.monotonic() < end:
        st = info.refresh(force=True)
        if st.get("api_up") or not (st.get("api_enabled") and st.get("api_key")):
            break
        time.sleep(1)
    if st.get("api_up"):
        return True, ("Passerelle relancée : API en marche. Si l'application Hermes était ouverte, fermez-la et "
                      "rouvrez-la (elle a perdu sa connexion).")
    if st.get("gateway"):
        return True, "Passerelle relancée."
    tail = ((result.stdout or "") + (result.stderr or "")).strip().splitlines()[-2:]
    return False, "Relance de la passerelle : " + (" / ".join(tail) or "sans réponse")


def open_desktop(info, runner=subprocess.Popen):
    """Lance l'application Hermes détachée : sans console partagée avec WoW Assistant (sinon le terminal de
    l'appli reste ouvert après sa fermeture et reçoit les messages de Hermes)."""
    path = info.desktop_app()
    if not path:
        return False, "Application Hermes introuvable."
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
             | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0))
    try:
        runner([path], cwd=os.path.dirname(path), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
               stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags)
    except OSError:
        try:          # pas le droit de sortir du « job » du lanceur : sans cette option
            runner([path], cwd=os.path.dirname(path), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, close_fds=True,
                   creationflags=flags & ~getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0))
        except OSError as e:
            return False, f"Ouverture de Hermes impossible : {e}"
    return True, "Application Hermes ouverte."


def enable_api(info):
    """Active l'API de la passerelle : API_SERVER_ENABLED=true et une clé aléatoire (si absente) dans le .env de
    Hermes, sauvegardé avant. La passerelle doit être relancée (fermer / rouvrir l'application Hermes)."""
    path = os.path.join(info.home, ".env")
    env = read_env(path)
    lines = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        pass
    _backup(path)
    wanted = {"API_SERVER_ENABLED": "true"}
    if len(env.get("API_SERVER_KEY", "")) < 32:
        wanted["API_SERVER_KEY"] = secrets.token_hex(32)
    out, done = [], set()
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in wanted:
            out.append(f"{key}={wanted[key]}")
            done.add(key)
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in wanted.items() if k not in done]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    os.replace(tmp, path)
    info.refresh(force=True)
    return True, "API activée dans Hermes : cliquez « Relancer la passerelle » pour la démarrer."
