"""
Connexion à l'assistant IA (Hermes pour le moment).
Trois modes, choisis dans les Paramètres généraux :
  - "hermes" : Hermes Agent installé sur le PC (hermes_bridge : session dédiée, skills, mémoire, outils de jeu)
  - "api" : serveur compatible OpenAI (Ollama, LM Studio, vLLM, Open WebUI, Omniroute, Hermes API Server...)
  - "exe" : programme local lancé sans shell (ex. hermes.exe), la question lui est passée en argument ou sur stdin

Les envois se font dans un fil d'arrière-plan : l'interface interroge simplement le Job.
"""
import base64
import json
import os
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request


class Job:
    """Résultat d'un envoi : done passe à True quand text ou error est renseigné."""

    def __init__(self):
        self.done = False
        self.text = ""
        self.error = ""


class _FixedSettings:
    """Réglages figés sur un serveur donné : interroge un serveur de la liste sans toucher aux réglages actifs."""

    def __init__(self, endpoint, api_key=""):
        self.values = {"llm.endpoint": endpoint, "llm.api_key": api_key}

    def get(self, key, default=""):
        return self.values.get(key, default)


PROVIDERS = ("Ollama", "Hub AetherTwin", "Strata", "Open WebUI", "OmniRoute", "LM Studio", "vLLM", "Autre")
_PORT_PROVIDERS = {"11434": "Ollama", "5750": "Hub AetherTwin", "8090": "Strata", "20128": "OmniRoute",
                   "1234": "LM Studio", "3000": "Open WebUI", "8080": "Open WebUI", "8000": "vLLM"}
# Strata (gros modèles « mélange d'experts », https://github.com/Niko1221/Strata) : serveur compatible OpenAI local.
# 8090 plutôt que son 8080 par défaut, souvent pris par Open WebUI (préréglage « AetherTwin » du Hub).
STRATA_ENDPOINT = "http://127.0.0.1:8090/v1"


def guess_provider(url):
    """Fournisseur probable d'un endpoint, d'après son port habituel (modifiable ensuite dans la liste)."""
    host = url.split("://", 1)[-1].split("/", 1)[0]
    port = host.rsplit(":", 1)[-1] if ":" in host else ""
    return _PORT_PROVIDERS.get(port, "Autre")


def list_models_at(endpoint, api_key=""):
    """(liste de noms, message d'erreur) pour un serveur précis (liste « Serveurs enregistrés »)."""
    return LLMClient(_FixedSettings(endpoint, api_key)).list_models()


def enabled_servers(settings, current_endpoint="", current_key=""):
    """Serveurs à interroger : ceux de la liste cochés « actifs », plus l'endpoint en cours s'il n'y est pas.
    Chaque serveur : {"url", "api_key"}."""
    out, seen = [], set()
    for server in settings.get("llm.servers", []) or []:
        url = str(server.get("url", "")).strip().rstrip("/")
        if url and server.get("enabled", True) and url not in seen:
            seen.add(url)
            out.append({"url": url, "api_key": str(server.get("api_key", "")),
                        "provider": str(server.get("provider") or guess_provider(url))})
    current = (current_endpoint or "").strip().rstrip("/")
    if current and current not in seen:
        out.insert(0, {"url": current, "api_key": current_key, "provider": guess_provider(current)})
    return out


class LLMClient:
    TIMEOUT = 180

    def __init__(self, settings, hermes=None):
        self.settings = settings
        self._hermes = hermes

    @property
    def hermes(self):
        """Client Hermes Agent (créé à la première utilisation)."""
        if self._hermes is None:
            from hermes_bridge import HermesClient
            self._hermes = HermesClient(self.settings)
        return self._hermes

    # ------------------------------------------------------------------ configuration
    def _cfg(self, key):
        return self.settings.get(f"llm.{key}", "")

    def uses_hermes(self):
        return self._cfg("mode") == "hermes"

    def is_configured(self):
        if self.uses_hermes():
            return self.hermes.is_configured()
        if self._cfg("mode") == "exe":
            return bool(self._cfg("exe_path"))
        return bool(self._cfg("endpoint")) and bool(self._cfg("model"))

    def describe(self):
        if self.uses_hermes():
            return self.hermes.describe()
        if self._cfg("mode") == "exe":
            return f"Exécutable : {self._cfg('exe_path')}"
        return f"{self._cfg('endpoint') or 'endpoint non défini'}  ·  {self._cfg('model') or 'modèle non défini'}"

    # ------------------------------------------------------------------ URLs
    def _base(self):
        return self._cfg("endpoint").strip().rstrip("/")

    def chat_url(self):
        base = self._base()
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1") or base.endswith("/api"):
            return base + "/chat/completions"
        return base + "/v1/chat/completions"

    def models_urls(self):
        base = self._base()
        for suffix in ("/chat/completions",):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
        roots = [base]
        if base.endswith("/v1") or base.endswith("/api"):
            roots.append(base[:-3])
        urls = []
        for root in roots:
            urls += [root + "/v1/models", root + "/api/models", root + "/api/tags", root + "/models"]
        if base.endswith("/v1"):
            urls.insert(0, base + "/models")
        seen, out = set(), []
        for u in urls:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    def _headers(self):
        headers = {"Content-Type": "application/json", "User-Agent": "WoWAssistant/1.5"}
        if self._cfg("api_key"):
            headers["Authorization"] = "Bearer " + self._cfg("api_key")
        return headers

    # ------------------------------------------------------------------ modèles disponibles
    def list_models(self):
        """(liste de noms, message d'erreur). Essaie /v1/models (OpenAI, Open WebUI), /api/models, /api/tags (Ollama)."""
        if not self._base():
            return [], "Endpoint non défini"
        last_error = ""
        for url in self.models_urls():
            try:
                request = urllib.request.Request(url, headers=self._headers())
                with urllib.request.urlopen(request, timeout=8) as response:
                    data = json.loads(response.read().decode("utf-8"))
                names = _extract_model_names(data)
                if names:
                    return sorted(set(names)), ""
            except (urllib.error.URLError, OSError, ValueError) as e:
                last_error = str(e)
        return [], last_error or "Aucun modèle trouvé"

    # ------------------------------------------------------------------ envoi
    def ask(self, prompt, images=None, history=None):
        """images : liste de (type MIME, base64) à joindre à la question (vision).
        history : derniers échanges [(rôle, texte)] (utile à Hermes en mode CLI, qui n'a pas de session)."""
        if self.uses_hermes():
            return self.hermes.ask(prompt, images, history)
        job = Job()
        threading.Thread(target=self._run, args=(prompt, list(images or []), job), daemon=True).start()
        return job

    def _run(self, prompt, images, job):
        try:
            if self._cfg("mode") == "exe":
                job.text = self._ask_exe(prompt, images)
            else:
                job.text = self._ask_api(prompt, images)
        except Exception as e:   # réseau, programme introuvable, réponse inattendue...
            job.error = str(e) or e.__class__.__name__
        finally:
            job.done = True

    def _ask_api(self, prompt, images=()):
        if not self.is_configured():
            raise RuntimeError("Assistant non configuré : renseignez l'endpoint et le modèle dans les Paramètres généraux.")
        messages = []
        system = self._cfg("system_prompt")
        import i18n
        if system and i18n.language() == "en" and "Réponds en français" in system:
            system = "You are an expert World of Warcraft assistant. Answer in English, clearly and concisely."
        if system:
            messages.append({"role": "system", "content": system})
        if images:   # format "vision" compatible OpenAI (Ollama, Open WebUI, LM Studio...)
            content = [{"type": "text", "text": prompt}]
            content += [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}} for mime, data in images]
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": prompt})
        body = json.dumps({"model": self._cfg("model"), "messages": messages, "stream": False}).encode("utf-8")
        request = urllib.request.Request(self.chat_url(), data=body, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.TIMEOUT) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:300]
            raise RuntimeError(f"Erreur HTTP {e.code} : {detail}")
        if isinstance(data, dict):
            if data.get("choices"):
                return str(data["choices"][0].get("message", {}).get("content", "")).strip()
            if isinstance(data.get("message"), dict):   # format natif Ollama
                return str(data["message"].get("content", "")).strip()
        raise RuntimeError("Réponse inattendue du serveur")

    def _ask_exe(self, prompt, images=()):
        exe = self._cfg("exe_path").strip().strip('"')
        if not exe:
            raise RuntimeError("Aucun exécutable défini dans les Paramètres généraux.")
        template = self._cfg("exe_args") or "{prompt}"
        tokens = [t.strip('"') for t in _split_args(template)]
        paths = []
        try:
            # images : fichiers temporaires, passés avec {image} (la première) ou {images} (toutes) ;
            # sans ces mots-clés, leurs chemins sont ajoutés à la question
            for mime, data in images:
                fd, path = tempfile.mkstemp(suffix=".jpg")
                with os.fdopen(fd, "wb") as f:
                    f.write(base64.b64decode(data))
                paths.append(path)
            has_image_token = any("{image" in t for t in tokens)
            if paths and not has_image_token:
                prompt += "\n\n(Images jointes : " + " ; ".join(paths) + ")"
            use_stdin = not any("{prompt}" in t for t in tokens)
            args = [exe]
            for token in tokens:
                if token == "{images}":
                    args += paths
                else:
                    args.append(token.replace("{prompt}", prompt).replace("{image}", paths[0] if paths else ""))
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            result = subprocess.run(args, input=prompt if use_stdin else None, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=self.TIMEOUT, creationflags=flags)
        finally:
            for path in paths:
                try:
                    os.remove(path)
                except OSError:
                    pass
        text = (result.stdout or "").strip()
        if result.returncode != 0 and not text:
            raise RuntimeError((result.stderr or f"Code de sortie {result.returncode}").strip()[:400])
        return text or "(réponse vide)"


def _split_args(template):
    """Découpe sans shell : les mots entre guillemets restent ensemble."""
    tokens, current, quote = [], "", ""
    for ch in template:
        if quote:
            if ch == quote:
                quote = ""
            else:
                current += ch
        elif ch in "\"'":
            quote = ch
        elif ch.isspace():
            if current:
                tokens.append(current)
                current = ""
        else:
            current += ch
    if current:
        tokens.append(current)
    return tokens


def _extract_model_names(data):
    """Formats : OpenAI {data:[{id}]}, Open WebUI {data:[{id,name}]}, Ollama {models:[{name}]}, liste simple."""
    names = []
    items = []
    if isinstance(data, dict):
        items = data.get("data") or data.get("models") or []
    elif isinstance(data, list):
        items = data
    for item in items:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            name = item.get("id") or item.get("name") or item.get("model")
            if name:
                names.append(str(name))
    return names
