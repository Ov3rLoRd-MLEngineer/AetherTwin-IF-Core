"""Relais Cloud <-> Local : continuer à développer pendant les coupures de quota.

Cycle :
  1. Lance l'agent cloud (Claude Code, ou l'API Anthropic) et note l'heure T0 du premier prompt.
  2. Surveille les erreurs de quota (429, messages de limite d'usage, surcharge).
     Backoff court pour les erreurs transitoires ; bascule si le motif persiste.
  3. Bascule sur l'agent local (Ollama + Aider ou OpenCode) jusqu'à T0 + fenêtre.
  4. Arrête proprement l'agent local (commit `wip(local): …`) et rend la main au cloud
     avec un résumé (changelog + git log + diff) pour revue.

Robustesse : verrou d'instance unique, état persistant atomique (reprise après
redémarrage), journal horodaté, `--dry-run`, arrêt propre sur Ctrl+C.
Aucune clé en dur : les identifiants viennent de l'environnement.

Exemples :
    python scripts/relay_orchestrator.py --dry-run
    python scripts/relay_orchestrator.py --backend claude-code --local-agent aider
    python scripts/relay_orchestrator.py --status
"""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field, fields
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

DEFAULT_WINDOW_MINUTES = 302.0  # fenêtre de 5 h + 2 min de marge (voir README, « Développement 24 h/24 »)
DEFAULT_LOCAL_MODEL = "qwen3-coder:30b-a3b-q4_K_M"
DEFAULT_NUM_CTX = 32768
DEFAULT_OLLAMA_HOST = "127.0.0.1:11434"
DEFAULT_API_MODEL = "claude-opus-5-5"
HANDOFF_FILES = ("AGENT_HANDOFF.md", "PROJECT_STATUS.md", "ARCHITECTURE_MAP.md")
CHANGELOG = "logs/CHANGELOG_DEV.md"

# Limite d'usage atteinte : inutile d'insister, on bascule tout de suite.
QUOTA_PATTERNS = (
    r"usage limit",
    r"limit reached",
    r"hit your [\w\s-]*limit",
    r"out of (extra )?usage",
    r"quota (exceeded|atteint)",
)
# Erreur possiblement passagère : backoff court, puis bascule si elle persiste.
TRANSIENT_PATTERNS = (
    r"\b429\b",
    r"\b529\b",
    r"rate[_ ]limit",
    r"overloaded",
    r"too many requests",
)

log = logging.getLogger("relay")


# --------------------------------------------------------------------------- horloge
class Clock:
    """Horloge réelle. Remplaçable par `VirtualClock` (tests, --dry-run)."""

    def now(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))


class VirtualClock(Clock):
    """Horloge simulée : `sleep` avance le temps sans attendre."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = float(start)

    def now(self) -> float:
        return self._now

    def sleep(self, seconds: float) -> None:
        self._now += max(0.0, seconds)


def fmt_time(ts: float | None) -> str:
    if ts is None:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


# --------------------------------------------------------------------------- état persistant
@dataclass
class RelayState:
    """État du relais, écrit de façon atomique dans `logs/relay_state.json`."""

    version: int = 1
    phase: str = "idle"  # idle | cloud | local | done | error
    t0: float | None = None  # heure exacte du premier prompt de la fenêtre courante
    window_minutes: float = DEFAULT_WINDOW_MINUTES
    resume_at: float | None = None  # heure de retour au cloud
    local_base_commit: str | None = None  # HEAD au moment de la bascule (pour le diff de revue)
    cycles: int = 0  # nombre de bascules cloud -> local
    cloud_runs: int = 0
    last_event: str = ""
    updated_at: float = 0.0
    history: list[dict[str, Any]] = field(default_factory=list)

    def save(self, path: Path) -> None:
        """Écriture atomique : fichier temporaire, fsync, puis remplacement."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(asdict(self), handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Path) -> RelayState | None:
        """Charge l'état ; un fichier absent ou illisible donne `None` (le fichier abîmé est mis de côté)."""
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("racine JSON inattendue")
            known = {f.name for f in fields(cls)}
            return cls(**{k: v for k, v in raw.items() if k in known})
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError) as exc:
            log.warning("État illisible (%s) : %s. Il est mis de côté.", path, exc)
            with contextlib.suppress(OSError):
                os.replace(path, path.with_name(path.name + ".corrupt"))
            return None


# --------------------------------------------------------------------------- verrou d'instance unique
class LockError(RuntimeError):
    """Un autre orchestrateur est déjà actif."""


def pid_is_alive(pid: int) -> bool:
    """Vrai si le processus existe. N'envoie jamais de signal sous Windows (os.kill y tuerait le processus)."""
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class SingleInstanceLock:
    """Fichier verrou créé de façon exclusive. Un verrou laissé par un processus mort est repris."""

    def __init__(self, path: Path, pid: int | None = None,
                 alive: Callable[[int], bool] = pid_is_alive) -> None:
        self.path = path
        self.pid = pid if pid is not None else os.getpid()
        self._alive = alive
        self._held = False

    def _owner(self) -> int | None:
        try:
            return int(json.loads(self.path.read_text(encoding="utf-8"))["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                owner = self._owner()
                if owner is not None and (owner == self.pid or self._alive(owner)):
                    raise LockError(f"Un orchestrateur est déjà actif (PID {owner}, verrou {self.path}).") from None
                log.warning("Verrou orphelin (PID %s) : repris.", owner)
                with contextlib.suppress(OSError):
                    os.unlink(self.path)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"pid": self.pid, "started": time.time()}, handle)
            self._held = True
            return
        raise LockError(f"Impossible de prendre le verrou {self.path}.")

    def release(self) -> None:
        if self._held and self._owner() == self.pid:
            with contextlib.suppress(OSError):
                os.unlink(self.path)
        self._held = False

    def __enter__(self) -> SingleInstanceLock:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


# --------------------------------------------------------------------------- agent cloud
class Status(StrEnum):
    DONE = "done"  # le prompt a été traité
    QUOTA = "quota"  # fenêtre de quota atteinte : basculer
    TRANSIENT = "transient"  # 429 / surcharge possiblement passagère : backoff
    ERROR = "error"  # autre erreur : arrêt


@dataclass
class CloudResult:
    status: Status
    detail: str = ""
    retry_after: float | None = None


def classify_text(text: str) -> Status | None:
    """Reconnaît un message de limite d'usage (QUOTA) ou une erreur de débit (TRANSIENT)."""
    for pattern in QUOTA_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return Status.QUOTA
    for pattern in TRANSIENT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return Status.TRANSIENT
    return None


def parse_retry_after(value: str | None) -> float | None:
    try:
        return max(0.0, float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def resolve_command(cmd: Sequence[str]) -> list[str]:
    """Résout l'exécutable via le PATH (sous Windows : .cmd/.exe ; un .ps1 passe par PowerShell)."""
    found = shutil.which(cmd[0])
    if not found:
        return list(cmd)
    if found.lower().endswith(".ps1"):
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", found, *cmd[1:]]
    return [found, *cmd[1:]]


class CloudBackend(Protocol):
    def run(self, prompt: str) -> CloudResult: ...


class ClaudeCodeBackend:
    """Lance Claude Code en mode non interactif. Le prompt passe par l'entrée standard (jamais par un shell)."""

    def __init__(self, cmd: Sequence[str], cwd: Path, timeout_s: float,
                 runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> None:
        self.cmd = list(cmd)
        self.cwd = cwd
        self.timeout_s = timeout_s
        self._runner = runner

    def run(self, prompt: str) -> CloudResult:
        try:
            proc = self._runner(resolve_command(self.cmd), input=prompt, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", cwd=str(self.cwd), timeout=self.timeout_s)
        except FileNotFoundError as exc:
            return CloudResult(Status.ERROR, f"Commande introuvable : {exc}")
        except subprocess.TimeoutExpired:
            return CloudResult(Status.ERROR, f"Délai dépassé ({self.timeout_s:.0f} s)")
        return self.classify(proc.returncode, proc.stdout or "", proc.stderr or "")

    @staticmethod
    def classify(returncode: int, stdout: str, stderr: str) -> CloudResult:
        """Une sortie réussie peut contenir « 429 » dans son texte : on ne cherche les motifs que sur un échec."""
        text, is_error = stdout, returncode != 0
        with contextlib.suppress(ValueError):  # --output-format json : {"is_error": bool, "result": str}
            payload = json.loads(stdout.strip().splitlines()[-1]) if stdout.strip() else None
            if isinstance(payload, dict) and "is_error" in payload:
                is_error = is_error or bool(payload["is_error"])
                text = str(payload.get("result", ""))
        if not is_error:
            short = text.strip()
            if len(short) < 400 and classify_text(short) is Status.QUOTA:
                return CloudResult(Status.QUOTA, short[:400])
            return CloudResult(Status.DONE, short[-400:])
        detail = (text + "\n" + stderr).strip()
        found = classify_text(detail)
        return CloudResult(found or Status.ERROR, detail[-600:] or f"Code de sortie {returncode}")


class ApiBackend:
    """Appel direct de l'API Anthropic via le SDK officiel (paquet `anthropic`, optionnel).

    Limite assumée : un appel d'API ne modifie aucun fichier. Ce backend sert à
    obtenir une réponse écrite dans `logs/` ; pour un agent qui édite le dépôt,
    utiliser `--backend claude-code`. Les identifiants sont résolus par le SDK
    depuis l'environnement (ANTHROPIC_API_KEY…), jamais depuis ce fichier.
    """

    def __init__(self, model: str, output_path: Path, base_url: str | None = None,
                 timeout_s: float = 600.0, max_tokens: int = 16000,
                 quota_retry_after_s: float = 300.0) -> None:
        self.model = model
        self.output_path = output_path
        self.base_url = base_url
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self.quota_retry_after_s = quota_retry_after_s

    def run(self, prompt: str) -> CloudResult:
        try:
            import anthropic
        except ImportError:
            return CloudResult(Status.ERROR, "Paquet `anthropic` absent : pip install anthropic")
        try:
            kwargs: dict[str, Any] = {"max_retries": 0, "timeout": self.timeout_s}  # le backoff est géré ici
            if self.base_url:
                kwargs["base_url"] = self.base_url
            client = anthropic.Anthropic(**kwargs)
            message = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                thinking={"type": "adaptive"},
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.RateLimitError as exc:
            retry_after = parse_retry_after(exc.response.headers.get("retry-after"))
            hard = classify_text(str(exc)) is Status.QUOTA or (retry_after or 0) > self.quota_retry_after_s
            return CloudResult(Status.QUOTA if hard else Status.TRANSIENT, f"429 : {exc}"[:600], retry_after)
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:  # 529 overloaded_error, 5xx
                return CloudResult(Status.TRANSIENT, f"{exc.status_code} : {exc}"[:600],
                                   parse_retry_after(exc.response.headers.get("retry-after")))
            return CloudResult(Status.ERROR, f"{exc.status_code} : {exc}"[:600])
        except anthropic.APIConnectionError as exc:
            return CloudResult(Status.TRANSIENT, f"Connexion impossible : {exc}"[:600])
        except anthropic.AnthropicError as exc:  # identifiants absents, configuration invalide
            return CloudResult(Status.ERROR, str(exc)[:600])
        if message.stop_reason == "refusal":
            return CloudResult(Status.ERROR, "Requête refusée par le modèle (stop_reason=refusal)")
        text = "\n".join(block.text for block in message.content if block.type == "text")
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(text, encoding="utf-8")
        return CloudResult(Status.DONE, f"Réponse écrite dans {self.output_path}")


# --------------------------------------------------------------------------- agent local
class LocalAgent(Protocol):
    def available(self) -> tuple[bool, str]: ...
    def start(self, prompt: str) -> None: ...
    def is_running(self) -> bool: ...
    def exit_code(self) -> int | None: ...
    def stop(self) -> None: ...


def ollama_base_url(host: str) -> str:
    return host if host.startswith(("http://", "https://")) else f"http://{host}"


def ollama_has_model(host: str, model: str, timeout_s: float = 5.0) -> tuple[bool, str]:
    """Interroge /api/tags du serveur Ollama configuré (machine locale ou réseau local)."""
    url = ollama_base_url(host).rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, f"Ollama injoignable ({url}) : {exc}"
    names = {str(m.get("name", "")) for m in data.get("models", []) if isinstance(m, dict)}
    if model in names:
        return True, ""
    return False, f"Modèle {model} non installé sur {url} (ollama pull {model})"


class SubprocessLocalAgent:
    """Aider ou OpenCode, branché sur Ollama. Sortie redirigée vers un journal (peu fiable sous Git Bash)."""

    def __init__(self, kind: str, model: str, num_ctx: int, ollama_host: str, repo: Path, logs_dir: Path,
                 model_check: Callable[[str, str], tuple[bool, str]] = ollama_has_model) -> None:
        self.kind = kind
        self.model = model
        self.num_ctx = num_ctx
        self.ollama_host = ollama_host
        self.repo = repo
        self.logs_dir = logs_dir
        self._model_check = model_check
        self._proc: subprocess.Popen[bytes] | None = None
        self._log_handle: Any = None

    def build_command(self, prompt: str) -> list[str]:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        if self.kind == "opencode":
            return ["opencode", "run", "--model", f"ollama/{self.model}", prompt]
        prompt_file = self.logs_dir / "relay_local_prompt.md"
        prompt_file.write_text(prompt, encoding="utf-8")
        settings = self.logs_dir / "aider_model_settings.yml"
        settings.write_text(  # num_ctx obligatoire : le contexte par défaut d'un 30 B fait échouer le chargement
            f"- name: ollama_chat/{self.model}\n  extra_params:\n    num_ctx: {self.num_ctx}\n", encoding="utf-8")
        cmd = ["aider", "--model", f"ollama_chat/{self.model}", "--model-settings-file", str(settings),
               "--yes-always", "--no-show-model-warnings", "--message-file", str(prompt_file)]
        for name in HANDOFF_FILES:
            if (self.repo / name).is_file():
                cmd += ["--read", name]
        return cmd

    def available(self) -> tuple[bool, str]:
        binary = "opencode" if self.kind == "opencode" else "aider"
        if not shutil.which(binary):
            return False, f"`{binary}` introuvable dans le PATH"
        return self._model_check(self.ollama_host, self.model)

    def start(self, prompt: str) -> None:
        cmd = resolve_command(self.build_command(prompt))
        env = dict(os.environ, OLLAMA_API_BASE=ollama_base_url(self.ollama_host))
        self._log_handle = open(self.logs_dir / "relay_local_agent.log", "ab")  # noqa: SIM115
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        self._proc = subprocess.Popen(cmd, cwd=str(self.repo), env=env, stdin=subprocess.DEVNULL,
                                      stdout=self._log_handle, stderr=subprocess.STDOUT, creationflags=flags)

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def exit_code(self) -> int | None:
        return None if self._proc is None else self._proc.poll()

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=10)
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None


# --------------------------------------------------------------------------- Git
class GitRepo:
    """Sous-ensemble de Git utile au relais : point de reprise et diff de revue."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=str(self.root), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120)

    def head(self) -> str | None:
        proc = self._git("rev-parse", "HEAD")
        return proc.stdout.strip() if proc.returncode == 0 else None

    def has_changes(self) -> bool:
        return bool(self._git("status", "--porcelain").stdout.strip())

    def wip_commit(self, message: str) -> str | None:
        """Commit intermédiaire de tout le travail en cours. Retourne le nouveau HEAD, ou None s'il n'y a rien."""
        if not self.has_changes():
            return None
        self._git("add", "-A")
        proc = self._git("commit", "-m", message)
        if proc.returncode != 0:
            log.warning("Commit intermédiaire impossible : %s", (proc.stderr or proc.stdout).strip()[:300])
            return None
        return self.head()

    def log_since(self, base: str | None, limit: int = 40) -> str:
        args = ["log", "--oneline", f"-{limit}"] + ([f"{base}..HEAD"] if base else [])
        return self._git(*args).stdout.strip()

    def diff_stat(self, base: str | None) -> str:
        return self._git("diff", "--stat", f"{base}..HEAD").stdout.strip() if base else ""

    def diff(self, base: str | None, max_chars: int) -> str:
        if not base:
            return ""
        text = self._git("diff", f"{base}..HEAD").stdout
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n[... diff tronqué à {max_chars} caractères : git diff {base[:10]}..HEAD]"
        return text


# --------------------------------------------------------------------------- prompts de passation
DEFAULT_MISSION = (
    "Lis CLAUDE.md, puis PROJECT_STATUS.md et ARCHITECTURE_MAP.md. Poursuis la prochaine tâche "
    "prioritaire non terminée. Après chaque brique : tests, mise à jour des 3 fichiers de suivi, commit."
)


def build_local_prompt(tasks: str) -> str:
    return (
        "Tu es l'agent LOCAL du projet AetherTwin. Tu prends le relais de l'agent cloud.\n"
        "1. Lis AGENT_HANDOFF.md. Puis PROJECT_STATUS.md. Puis ARCHITECTURE_MAP.md.\n"
        "2. Ne charge pas tout le dépôt. Ouvre seulement les fichiers de la tâche.\n"
        "3. Fais UNE tâche à la fois, dans l'ordre de la liste ci-dessous.\n"
        "4. Lance les tests : .venv\\Scripts\\python.exe -m pytest\n"
        f"5. Écris une entrée dans {CHANGELOG} (agent : Local, fichiers, raison, résultat des tests).\n"
        "6. Fais un commit : wip(local): <ce que tu as fait>\n"
        "7. N'écris jamais « fonctionne » pour ce que tu n'as pas exécuté.\n\n"
        "TÂCHES COURANTES :\n" + (tasks.strip() or "(voir la section « Prochaines tâches » de AGENT_HANDOFF.md)")
    )


def tail_text(path: Path, max_chars: int) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-max_chars:]
    except OSError:
        return ""


def build_resume_prompt(mission: str, changelog_tail: str, git_log: str, diff_stat: str, diff: str) -> str:
    return (
        "Reprise du relais : l'agent local a travaillé pendant la coupure de quota.\n"
        "Commence par une REVUE DU DIFF ci-dessous (diff seulement, ne relis pas tout le dépôt) : "
        "corrige ou annule ce qui est faux, puis poursuis la mission.\n\n"
        f"## Mission\n{mission}\n\n"
        f"## Commits de l'agent local (git log)\n{git_log or '(aucun commit)'}\n\n"
        f"## Fin de {CHANGELOG}\n{changelog_tail or '(vide)'}\n\n"
        f"## Fichiers modifiés (git diff --stat)\n{diff_stat or '(aucun)'}\n\n"
        f"## Diff à relire\n{diff or '(aucun)'}\n"
    )


# --------------------------------------------------------------------------- orchestrateur
@dataclass
class RelayConfig:
    repo: Path
    state_path: Path
    lock_path: Path
    window_minutes: float = DEFAULT_WINDOW_MINUTES
    max_transient_retries: int = 4  # au-delà, un 429 est considéré comme persistant
    backoff_base_s: float = 5.0
    backoff_max_s: float = 120.0
    poll_s: float = 30.0
    min_resume_delay_s: float = 900.0  # si T0 + fenêtre est déjà passé
    max_local_runs: int = 20
    max_cycles: int = 0  # 0 = illimité
    max_cloud_runs: int = 1  # relances « continue » après un passage cloud réussi
    diff_max_chars: int = 20000
    mission: str = DEFAULT_MISSION
    tasks: str = ""


class RelayOrchestrator:
    """Machine à états du relais. Toutes les dépendances sont injectées (tests sans réseau ni processus)."""

    def __init__(self, config: RelayConfig, cloud: CloudBackend, local: LocalAgent, git: Any,
                 clock: Clock | None = None, lock: SingleInstanceLock | None = None) -> None:
        self.cfg = config
        self.cloud = cloud
        self.local = local
        self.git = git
        self.clock = clock or Clock()
        self.lock = lock or SingleInstanceLock(config.lock_path)
        self.state = RelayState(window_minutes=config.window_minutes)

    # -- utilitaires
    @property
    def window_s(self) -> float:
        return self.cfg.window_minutes * 60.0

    def _save(self) -> None:
        self.state.updated_at = self.clock.now()
        self.state.save(self.cfg.state_path)

    def _event(self, message: str) -> None:
        log.info(message)
        self.state.last_event = message
        self.state.history.append({"at": self.clock.now(), "phase": self.state.phase, "event": message})
        del self.state.history[:-200]
        self._save()

    # -- point d'entrée
    def run(self) -> int:
        """Codes de sortie : 0 terminé · 2 erreur · 3 autre instance active · 130 interrompu."""
        try:
            with self.lock:
                try:
                    return self._run_locked()
                except KeyboardInterrupt:
                    self._event("Interrompu (Ctrl+C) : état sauvegardé, reprise possible au prochain lancement.")
                    return 130
        except LockError as exc:
            log.error("%s", exc)
            return 3

    def _run_locked(self) -> int:
        st = RelayState.load(self.cfg.state_path)
        prompt = self.cfg.mission
        if st is not None and st.phase in ("cloud", "local"):
            self.state = st
            self.state.window_minutes = self.cfg.window_minutes
            self._event(f"Reprise après redémarrage (phase {st.phase}, T0 {fmt_time(st.t0)}).")
            if st.phase == "local":
                self._local_phase()
                prompt = self._resume_prompt()
                self.state.t0 = None
            else:
                prompt = ("Tu as été interrompu en cours de travail (redémarrage). Relis PROJECT_STATUS.md "
                          f"et `git status`, puis reprends.\n\n## Mission\n{self.cfg.mission}")
        else:
            self.state = RelayState(window_minutes=self.cfg.window_minutes)

        runs_in_row = 0
        while True:
            now = self.clock.now()
            if self.state.t0 is None or now >= self.state.t0 + self.window_s:
                self.state.t0 = now
            self.state.phase, self.state.resume_at = "cloud", None
            self._event(f"Agent cloud lancé. T0 = {fmt_time(self.state.t0)} "
                        f"(retour prévu au plus tard à {fmt_time(self.state.t0 + self.window_s)}).")
            result = self._cloud_with_backoff(prompt)
            self.state.cloud_runs += 1

            if result.status is Status.DONE:
                runs_in_row += 1
                if runs_in_row < self.cfg.max_cloud_runs:
                    prompt = f"Continue la mission là où tu t'es arrêté.\n\n## Mission\n{self.cfg.mission}"
                    continue
                self.state.phase = "done"
                self._event(f"Agent cloud terminé : {result.detail[:200]}")
                return 0

            if result.status is Status.QUOTA:
                runs_in_row = 0
                if self.cfg.max_cycles and self.state.cycles >= self.cfg.max_cycles:
                    self.state.phase = "error"
                    self._event(f"Nombre maximal de bascules atteint ({self.cfg.max_cycles}). Arrêt.")
                    return 2
                now = self.clock.now()
                resume_at = self.state.t0 + self.window_s
                if result.retry_after:
                    resume_at = max(resume_at, now + result.retry_after)
                if resume_at < now + 60:
                    resume_at = now + self.cfg.min_resume_delay_s
                self.state.resume_at = resume_at
                self._event(f"Fenêtre de quota atteinte ({result.detail[:160]}). "
                            f"Bascule sur l'agent local jusqu'à {fmt_time(resume_at)}.")
                self._local_phase()
                prompt = self._resume_prompt()
                self.state.t0 = None
                continue

            self.state.phase = "error"
            self._event(f"Erreur de l'agent cloud : {result.detail[:300]}")
            return 2

    # -- phase cloud
    def _cloud_with_backoff(self, prompt: str) -> CloudResult:
        """429 transitoire : backoff court et nouvel essai. Motif persistant : fenêtre de quota atteinte."""
        result = CloudResult(Status.ERROR, "aucun essai")
        for attempt in range(self.cfg.max_transient_retries + 1):
            result = self.cloud.run(prompt)
            if result.status is not Status.TRANSIENT:
                return result
            if attempt == self.cfg.max_transient_retries:
                break
            delay = min(self.cfg.backoff_max_s, self.cfg.backoff_base_s * (2 ** attempt))
            if result.retry_after:
                delay = min(self.cfg.backoff_max_s, max(delay, result.retry_after))
            self._event(f"Erreur transitoire ({result.detail[:120]}). "
                        f"Essai {attempt + 1}/{self.cfg.max_transient_retries}, attente {delay:.0f} s.")
            self.clock.sleep(delay)
        return CloudResult(Status.QUOTA, f"erreur persistante après {self.cfg.max_transient_retries} "
                                         f"nouveaux essais : {result.detail[:200]}", result.retry_after)

    # -- phase locale
    def _local_phase(self) -> None:
        st = self.state
        if st.phase != "local":
            st.phase = "local"
            st.local_base_commit = self.git.head()
            st.cycles += 1
            self._save()
        resume_at = st.resume_at if st.resume_at is not None else self.clock.now()
        usable, reason = self.local.available()
        if not usable:
            self._event(f"Agent local indisponible ({reason}). Attente passive jusqu'à {fmt_time(resume_at)}.")
        prompt = build_local_prompt(self.cfg.tasks)
        runs, quick_failures, started_at = 0, 0, None
        try:
            while self.clock.now() < resume_at:
                if usable and not self.local.is_running():
                    code = self.local.exit_code()
                    if started_at is not None and code not in (None, 0) and self.clock.now() - started_at < 60:
                        quick_failures += 1
                    if quick_failures >= 3 or runs >= self.cfg.max_local_runs:
                        usable = False
                        self._event(f"Agent local mis en pause ({runs} passages, {quick_failures} échecs "
                                    f"immédiats). Attente passive jusqu'à {fmt_time(resume_at)}.")
                    else:
                        self.local.start(prompt)
                        runs += 1
                        started_at = self.clock.now()
                        self._event(f"Agent local lancé (passage {runs}).")
                self.clock.sleep(min(self.cfg.poll_s, max(0.0, resume_at - self.clock.now())))
        finally:
            self.local.stop()
            sha = self.git.wip_commit("wip(local): point de reprise du relais avant retour au cloud")
            self._event("Agent local arrêté. " + (f"Commit intermédiaire {sha[:10]}." if sha
                                                  else "Rien à committer."))

    def _resume_prompt(self) -> str:
        base = self.state.local_base_commit
        return build_resume_prompt(
            self.cfg.mission,
            tail_text(self.cfg.repo / CHANGELOG, 4000),
            self.git.log_since(base),
            self.git.diff_stat(base),
            self.git.diff(base, self.cfg.diff_max_chars),
        )


# --------------------------------------------------------------------------- simulation (--dry-run)
class SimulatedCloud:
    """Agent cloud factice : quota atteint au premier passage, succès au second. Aucun appel de service."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def run(self, prompt: str) -> CloudResult:
        self.prompts.append(prompt)
        if len(self.prompts) == 1:
            return CloudResult(Status.QUOTA, "[simulation] limite d'usage atteinte")
        return CloudResult(Status.DONE, "[simulation] mission terminée")


class SimulatedLocal:
    """Agent local factice : chaque passage dure `run_s` secondes d'horloge simulée."""

    def __init__(self, clock: Clock, run_s: float = 1800.0) -> None:
        self.clock, self.run_s = clock, run_s
        self.starts = 0
        self.stopped = 0
        self._until: float | None = None

    def available(self) -> tuple[bool, str]:
        return True, ""

    def start(self, prompt: str) -> None:
        self.starts += 1
        self._until = self.clock.now() + self.run_s

    def is_running(self) -> bool:
        return self._until is not None and self.clock.now() < self._until

    def exit_code(self) -> int | None:
        return None if self._until is None or self.is_running() else 0

    def stop(self) -> None:
        self.stopped += 1
        self._until = None


class NullGit:
    """Git factice pour la simulation : ne lit ni n'écrit rien."""

    def head(self) -> str | None:
        return None

    def wip_commit(self, message: str) -> str | None:
        return None

    def log_since(self, base: str | None, limit: int = 40) -> str:
        return ""

    def diff_stat(self, base: str | None) -> str:
        return ""

    def diff(self, base: str | None, max_chars: int) -> str:
        return ""


# --------------------------------------------------------------------------- ligne de commande
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Relais Cloud <-> Local pour développer 24 h/24.")
    p.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent, help="racine du dépôt")
    p.add_argument("--backend", choices=("claude-code", "api"), default="claude-code")
    p.add_argument("--mission-file", type=Path, help="prompt de mission (défaut : logs/relay_mission.md)")
    p.add_argument("--tasks-file", type=Path, help="liste de tâches pour l'agent local (défaut : logs/relay_tasks.md)")
    p.add_argument("--window-minutes", type=float, default=DEFAULT_WINDOW_MINUTES,
                   help="durée entre T0 et le retour au cloud (défaut : 302 = 5 h + 2 min)")
    p.add_argument("--local-agent", choices=("aider", "opencode"), default="aider")
    p.add_argument("--local-model", default=DEFAULT_LOCAL_MODEL)
    p.add_argument("--num-ctx", type=int, default=DEFAULT_NUM_CTX)
    p.add_argument("--ollama-host", default=os.environ.get("OLLAMA_HOST") or DEFAULT_OLLAMA_HOST,
                   help="hôte:port d'Ollama (local ou réseau local)")
    p.add_argument("--claude-bin", default="claude")
    p.add_argument("--claude-arg", action="append", default=[],
                   help="argument supplémentaire pour Claude Code (répétable), ex. --claude-arg=--permission-mode "
                        "--claude-arg=acceptEdits")
    p.add_argument("--api-model", default=os.environ.get("ANTHROPIC_MODEL") or DEFAULT_API_MODEL)
    p.add_argument("--api-base-url", default=None)
    p.add_argument("--max-transient-retries", type=int, default=4)
    p.add_argument("--backoff-base", type=float, default=5.0)
    p.add_argument("--poll-seconds", type=float, default=30.0)
    p.add_argument("--max-cycles", type=int, default=0, help="nombre maximal de bascules (0 = illimité)")
    p.add_argument("--max-cloud-runs", type=int, default=1)
    p.add_argument("--dry-run", action="store_true", help="simule un cycle complet, sans service ni processus")
    p.add_argument("--status", action="store_true", help="affiche l'état enregistré et quitte")
    p.add_argument("--force-unlock", action="store_true", help="supprime un verrou resté après un plantage")
    return p


def setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    log.handlers.clear()
    for handler in (logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()):
        handler.setFormatter(formatter)
        log.addHandler(handler)
    log.setLevel(logging.INFO)


def read_optional(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo: Path = args.repo.resolve()
    logs = repo / "logs"
    suffix = ".dryrun" if args.dry_run else ""
    state_path = logs / f"relay_state{suffix}.json"
    lock_path = logs / f"relay{suffix}.lock"

    if args.status:
        state = RelayState.load(state_path)
        if state is None:
            print("Aucun état enregistré.")
            return 0
        print(f"phase       : {state.phase}\nT0          : {fmt_time(state.t0)}\n"
              f"retour cloud: {fmt_time(state.resume_at)}\nbascules    : {state.cycles}\n"
              f"dernier évén: {state.last_event}")
        return 0

    setup_logging(logs / f"relay{suffix}.log")
    if args.force_unlock:
        with contextlib.suppress(OSError):
            lock_path.unlink()

    config = RelayConfig(
        repo=repo, state_path=state_path, lock_path=lock_path, window_minutes=args.window_minutes,
        max_transient_retries=args.max_transient_retries, backoff_base_s=args.backoff_base,
        poll_s=args.poll_seconds, max_cycles=args.max_cycles, max_cloud_runs=args.max_cloud_runs,
        mission=read_optional(args.mission_file or logs / "relay_mission.md").strip() or DEFAULT_MISSION,
        tasks=read_optional(args.tasks_file or logs / "relay_tasks.md"),
    )

    clock: Clock
    cloud: CloudBackend
    local: LocalAgent
    git: Any
    if args.dry_run:
        with contextlib.suppress(OSError):  # une simulation repart toujours de zéro
            state_path.unlink()
        clock = VirtualClock(time.time())
        cloud, local, git = SimulatedCloud(), SimulatedLocal(clock), NullGit()
        log.info("MODE SIMULATION : aucun service appelé, aucun processus lancé, horloge accélérée.")
    else:
        clock = Clock()
        git = GitRepo(repo)
        local = SubprocessLocalAgent(args.local_agent, args.local_model, args.num_ctx, args.ollama_host, repo, logs)
        if args.backend == "api":
            cloud = ApiBackend(args.api_model, logs / "relay_api_last_response.md", base_url=args.api_base_url)
        else:
            cloud = ClaudeCodeBackend([args.claude_bin, "-p", "--output-format", "json", *args.claude_arg],
                                      cwd=repo, timeout_s=args.window_minutes * 60.0)

    def on_sigterm(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    with contextlib.suppress(ValueError, AttributeError):  # hors fil principal (tests) : ignoré
        signal.signal(signal.SIGTERM, on_sigterm)

    return RelayOrchestrator(config, cloud, local, git, clock=clock).run()


if __name__ == "__main__":
    sys.exit(main())
