# ARCHITECTURE_MAP — AetherTwin (I&F Core)

Deux parties :

- **Flux et rôles** (ci-dessous) : rédigés à la main.
- **Arborescence et signatures publiques** (en bas) : générées par
  `scripts/gen_architecture_map.py` via `ast`. Ne les modifie pas à la main.
  Un test (`tests/test_architecture_map.py`) échoue si elles sont périmées.

État au 16/11/2026 : seuls `scripts/` et `tests/` contiennent du code. `core/` et
`modules/` sont des paquets vides (jalons J2 et J3). Les schémas marqués
« cible » décrivent ce qui est prévu, pas ce qui existe.

## Vue d'ensemble (cible)

```mermaid
flowchart TB
    subgraph Hub["core/daemon.py — centre"]
        BUS["bus d'événements local"]
        REG["registre de modules"]
        INOUE["Inoue — budget VRAM, ordonnancement"]
        FUMA["Fuma — watchdog, mode nocturne"]
    end
    GPU["core/hardware/gpu_monitor.py (pynvml | inconnu)"] --> INOUE
    OLLAMA[("Ollama — hôte:port configurable")] <--> ROUTER["core/llm_router.py"]
    ROUTER <--> BUS
    BUS <--> HUD["modules/gaming_hud"]
    BUS <--> SCAN["modules/scantrad"]
    BUS <--> STUDIO["modules/mangastudio"]
    BUS <--> LAB["modules/genesis_lab"]
    BUS <--> GAME["modules/if_game"]
    FUMA -. redémarre .-> HUD
    INOUE -. autorise / met en file .-> SCAN
    INOUE -. autorise / met en file .-> STUDIO
```

Chaque module tourne dans un **processus séparé** et ne parle au Hub que par le bus
local (`127.0.0.1`). Statut : **À FAIRE** (J2).

## Flux du relais Cloud ⇄ Local (existant, testé en simulation)

Fichier : `scripts/relay_orchestrator.py`.

```mermaid
stateDiagram-v2
    [*] --> Cloud: lancement, T0 enregistré
    Cloud --> Cloud: 429 transitoire (backoff 5 s, 10 s, 20 s, 40 s)
    Cloud --> Local: limite d'usage, ou 429 persistant
    Local --> Local: l'agent local enchaîne les tâches
    Local --> Cloud: T0 + fenêtre (302 min) — arrêt propre, commit wip(local), résumé + diff
    Cloud --> [*]: mission terminée
    Cloud --> [*]: erreur non récupérable (code 2)
```

Données échangées :

| Fichier | Écrit par | Lu par | Rôle |
|---|---|---|---|
| `logs/relay_state.json` | orchestrateur (écriture atomique) | orchestrateur au redémarrage | phase, T0, heure de retour, commit de base |
| `logs/relay.lock` | orchestrateur | autre instance | un seul orchestrateur actif |
| `logs/relay.log` | orchestrateur | Jérémy | journal horodaté |
| `logs/relay_mission.md` | Jérémy (facultatif) | agent cloud | prompt de mission |
| `logs/relay_tasks.md` | agent cloud | agent local | liste de tâches courante |
| `AGENT_HANDOFF.md`, `PROJECT_STATUS.md`, `ARCHITECTURE_MAP.md` | les deux agents | agent local (`--read`) | passation |
| `logs/CHANGELOG_DEV.md` | les deux agents | agent cloud à la reprise | ce qui a été fait |

Points de conception :

- Toutes les dépendances de `RelayOrchestrator` sont injectées (`CloudBackend`,
  `LocalAgent`, Git, `Clock`) : les tests utilisent une horloge virtuelle et des
  doublures, sans réseau externe ni attente réelle.
- Le prompt de Claude Code passe par l'entrée standard, jamais par un shell.
- À la reprise, Claude reçoit le **diff seulement** (tronqué à 20 000 caractères).

## Flux de données de WoW Assistant (code d'origine, à porter en J3)

Référence figée : `_import/wow_assistant_v9/`.

```mermaid
flowchart LR
    ADDON["Addon Lua HermesAssistant (en jeu)"] -->|"/reload, déconnexion, /ha save"| SV["SavedVariables/HermesAssistant.lua"]
    SV -->|lecture seule| GC["game_connection.GameConnection"]
    GC --> LP["lua_parser"]
    GC --> CACHE["snapcache — une section vide n'écrase jamais une section connue"]
    CACHE --> MODELS["character · quests · craft · inventory · gamedata"]
    MODELS --> CTX["gamedata.make_context"]
    CTX --> UI["ui.UI — fenêtre principale + overlay (2e fenêtre SDL)"]
    UI --> WM["widgets.WidgetManager"]
    LOG["Logs/WoWCombatLog*.txt"] --> FOCUS["focus.CombatMonitor"] --> WM
    UI --> LLM["llm.LLMClient — API compatible OpenAI ou hermes.exe"]
```

Cible J3 : `GameConnection` + parseur + cache deviennent `adapters/wow_retail.py`
derrière l'interface `GameAdapter` ; `LLMClient` devient client de `core/llm_router.py`.

<!-- AUTO:BEGIN -->
## Arborescence (générée)

```
core/
  __init__.py
  api.py
  bus.py
  config.py
  daemon.py
  guardians/
    __init__.py
    fuma.py
    inoue.py
  hardware/
    __init__.py
    gpu_monitor.py
  module_api.py
  module_runner.py
  scheduler.py
modules/
  __init__.py
  gaming_hud/
    __init__.py
    __main__.py
    adapters/
      __init__.py
      base.py
      log_tail.py
      privacy.py
      screen_ocr.py
      wow_retail.py
    addon/
      HermesAssistant/
        HermesAssistant.lua
        HermesAssistant.toc
    app/
      activity.json
      character.py
      clipboard.py
      config.py
      craft.py
      focus.py
      game_connection.py
      gamedata.py
      history.json
      history.py
      hotkeys.py
      icons_draw.py
      inventory.py
      Lancer WoW Assistant.bat
      llm.py
      lua_parser.py
      main.py
      mousepos.py
      overlay.py
      quests.py
      README.md
      recipes.json
      requirements.txt
      settings.json
      settings.py
      snapcache.py
      tabs.py
      tabs_collections.py
      tabs_data.py
      tabutil.py
      theme.py
      ui.py
      vision.py
      voice.py
      webhost.py
      webwidget.py
      widgets.py
      widgets_builtin.py
      wowhead.py
      wowhead_links.json
    manifest.json
    module.py
    rules/
      log_tail.example.yaml
scripts/
  __init__.py
  gen_architecture_map.py
  relay_orchestrator.py
  setup.ps1
config/
  allowlist.yaml
  hardware_profiles.yaml
  local.example.yaml
tests/
  __init__.py
  core/
    __init__.py
    test_bus_scheduler.py
    test_daemon.py
    test_gpu_monitor.py
    test_guardians.py
    test_module_api.py
  data/
    .gitkeep
  gaming_hud/
    __init__.py
    conftest.py
    test_adapters.py
    test_module.py
    test_ui_fixes.py
  test_architecture_map.py
  test_relay_orchestrator.py
  test_repo_hygiene.py
docs/
  .gitkeep
research/
  .gitkeep
assets/
  .gitkeep
logs/
  CHANGELOG_DEV.md
.github/
  workflows/
    tests.yml
```

## Signatures publiques (générées)

*Non listé : `modules/gaming_hud/app/` (code d'origine de WoW Assistant, voir la partie « flux »).*

### `core/api.py`

API HTTP locale du démon (FastAPI). Servie sur 127.0.0.1 uniquement par `core.daemon`.

- **`class AskRequest(BaseModel)`**
- `def create_app(daemon: Daemon) -> FastAPI`

### `core/bus.py`

Bus d'événements local du Hub : publication / abonnement entre processus, sur 127.0.0.1 uniquement.

- **`class EventBus`** — Centre du bus. `publish` sert les abonnés locaux puis les clients distants abonnés au sujet.
  - `def start(self) -> tuple[str, int]`
  - `def stop(self) -> None`
  - `def child_env(self) -> dict[str, str]` — Variables à donner à un processus de module pour qu'il rejoigne le bus.
  - `def subscribe(self, pattern: str, callback: Callable[[Event], None]) -> None`
  - `def publish(self, event: Event) -> None`
  - `def clients(self) -> list[str]`
- **`class BusClient`** — Client du bus, utilisé dans le processus d'un module.
  - `def from_env(cls, name: str, env: dict[str, str] | None=None) -> BusClient`
  - `def subscribe(self, *patterns: str, timeout: float=5.0) -> None` — S'abonne et attend la confirmation du bus : aucun événement publié ensuite n'est perdu.
  - `def publish(self, event: Event) -> None`
  - `def recv(self, timeout: float | None=None) -> Event | None`
  - `def close(self) -> None`

### `core/config.py`

Configuration locale du Hub : `config/local.yaml` (ignoré par Git), jamais de secret dans le dépôt.

- `def config_path() -> Path`
- `def load_config(path: Path | None=None) -> dict[str, Any]` — Configuration complète ; `{}` si le fichier est absent, illisible ou n'est pas un dictionnaire.
- `def section(name: str, path: Path | None=None) -> dict[str, Any]` — Une section de la configuration (ex. « ollama », « gaming_hud ») ; `{}` si elle n'existe pas.

### `core/daemon.py`

Le démon : centre de l'architecture en étoile.

- `def psutil_process_names() -> set[str] | None` — Noms (en minuscules) des processus en cours ; `None` si `psutil` est absent (mode dégradé).
- **`class ManagedModule`**
  - `def running(self) -> bool`
- **`class Daemon`** — Registre de modules + bus + gardiens. Toutes les sources externes sont injectables (tests).
  - `def start(self) -> None`
  - `def stop(self) -> None`
  - `def reload_modules(self) -> None` — (Re)lit les manifestes de `modules/`. Un manifeste invalide est signalé, pas fatal.
  - `def activate(self, name: str, auto: bool=False) -> Decision` — Demande la VRAM à Inoue puis lance le module dans son processus. Idempotent.
  - `def deactivate(self, name: str, timeout_s: float=8.0) -> None` — Arrêt propre (ordre sur le bus), puis arrêt forcé si le module ne répond pas. Rend la VRAM.
  - `def tick(self) -> dict[str, Any]` — Un tour : processus, déclencheurs, watchdog, alertes GPU, tâches de nuit. Retourne ce qui a changé.
  - `def status(self) -> dict[str, Any]`
  - `def modules_status(self) -> list[dict[str, Any]]`
- `def main(argv: list[str] | None=None) -> int`

### `core/guardians/fuma.py`

Fuma — gardien de la stabilité et du mode nocturne.

- **`class Alert`**
  - `def to_dict(self) -> dict[str, Any]`
- **`class Fuma`** — Watchdog, limites thermiques et mode nocturne du Hub.
  - `def watch(self, name: str, health: Callable[[], Health], restart: Callable[[], None]) -> None`
  - `def unwatch(self, name: str) -> None`
  - `def tick(self) -> list[str]` — Un tour de surveillance. Retourne les noms des modules redémarrés pendant ce tour.
  - `def revive(self, name: str) -> None` — Remet à zéro les essais d'un module mis au repos (action manuelle).
  - `def check_gpus(self, gpus: list[GpuInfo]) -> list[Alert]`
  - `def is_night(self) -> bool` — Vrai dans la plage de nuit. Une plage qui passe minuit (23 h → 7 h) est gérée.
  - `def schedule_night_task(self, name: str, run: Callable[[], Any]) -> None` — Planifie une tâche lourde pour la nuit (ingestion vectorielle, indexation…).
  - `def run_night_tasks(self, force: bool=False) -> list[str]` — Exécute les tâches en attente si c'est la nuit (ou si `force`). Retourne celles qui ont tourné.
  - `def state(self) -> dict[str, Any]`

### `core/guardians/inoue.py`

Inoue — gardienne de l'énergie et de la VRAM.

- **`class Verdict(StrEnum)`**
- **`class Decision`**
- **`class Inoue`** — Budget VRAM du Hub. Sans GPU détecté, le budget vaut 0 : seuls les modules sans besoin VRAM démarrent.
  - `def total_gb(self) -> float`
  - `def budget_gb(self) -> float` — VRAM attribuable : total moins la marge de sécurité.
  - `def allocated_gb(self) -> float`
  - `def available_gb(self) -> float`
  - `def request(self, name: str, min_gb: float, comfort_gb: float | None=None) -> Decision` — Demande de VRAM. Accorde le confortable s'il tient, sinon le minimum, sinon met en file.
  - `def release(self, name: str) -> list[tuple[str, Decision]]` — Libère l'attribution d'un module, puis sert la file d'attente dans l'ordre d'arrivée.
  - `def plan_llm_load(self, model: str, vram_gb: float) -> tuple[Decision, list[str]]` — Prépare le chargement d'un gros modèle de langage.
  - `def confirm_llm_unloaded(self, model: str) -> list[tuple[str, Decision]]`
  - `def state(self) -> dict[str, Any]`

### `core/hardware/gpu_monitor.py`

Moniteur GPU : mesure la topologie réelle au lieu de la présumer.

- **`class GpuInfo`** — État instantané d'un GPU. Une mesure indisponible vaut `None`, jamais une valeur inventée.
  - `def vram_free_mib(self) -> int`
  - `def to_dict(self) -> dict[str, Any]`
- **`class GpuBackend(Protocol)`**
  - `def read(self) -> list[GpuInfo]`
- `def parse_nvidia_smi_csv(output: str) -> list[GpuInfo]` — Analyse la sortie de `nvidia-smi --query-gpu=… --format=csv,noheader,nounits`.
- **`class NvidiaSmiBackend`** — Lit `nvidia-smi` (commande fixe, sans shell).
  - `def usable() -> bool`
  - `def read(self) -> list[GpuInfo]`
- **`class PynvmlBackend`** — Lit NVML via `pynvml`. L'import est différé : le paquet est optionnel.
  - `def read(self) -> list[GpuInfo]`
- **`class UnknownBackend`** — Repli : aucun GPU NVIDIA détectable. N'empêche jamais le démarrage.
  - `def read(self) -> list[GpuInfo]`
- `def detect_backend() -> GpuBackend` — Choisit le meilleur backend disponible, sans jamais lever d'exception.
- **`class GpuMonitor`** — Point d'entrée unique pour l'état des GPU (utilisé par Inoue, Fuma et l'API du daemon).
  - `def backend_name(self) -> str`
  - `def snapshot(self) -> list[GpuInfo]` — État de chaque GPU. En cas d'erreur de lecture : liste vide et `last_error` renseigné.
  - `def total_vram_mib(self) -> int`
  - `def report(self) -> dict[str, Any]` — Résumé sérialisable (API `/gpu`, overlay OBS).

### `core/module_api.py`

Contrat de module du Hub : manifeste, événements, cycle de vie.

- **`class ManifestError(ValueError)`** — Manifeste absent, illisible ou invalide.
- **`class Triggers`** — Ce qui active le module : processus (ex. « obs64.exe »), titres de fenêtres, ports.
- **`class Manifest`** — Déclaration d'un module. Les besoins VRAM sont lus par Inoue avant tout démarrage.
  - `def to_dict(self) -> dict[str, Any]`
- `def parse_manifest(raw: Any) -> Manifest` — Valide un manifeste déjà décodé. Lève `ManifestError` avec un message précis.
- `def load_manifest(module_dir: Path) -> Manifest` — Lit et valide `<module_dir>/manifest.json`.
- `def discover_manifests(modules_root: Path) -> tuple[dict[str, Manifest], dict[str, str]]` — Parcourt `modules/`. Retourne (manifestes valides, erreurs par dossier). Un module cassé n'arrête rien.
- **`class Event`** — Message du bus. `topic` est hiérarchique : « process.started », « gpu.alert », « module.gaming_hud.state ».
  - `def to_dict(self) -> dict[str, Any]`
  - `def from_dict(cls, raw: dict[str, Any]) -> Event`
  - `def matches(self, pattern: str) -> bool` — « gpu.* » ou « gpu » couvre « gpu.alert » ; « * » couvre tout.
- **`class Health`** — Santé d'un module. `degraded` = démarré sans une dépendance optionnelle (GPU, jeu, OBS, poids…).
  - `def to_dict(self) -> dict[str, Any]`
- **`class ModuleBase(ABC)`** — Classe de base de tout module. `publish` est fourni par le lanceur (bus du Hub).
  - `def name(self) -> str`
  - `def start(self) -> None` — Démarre le module. Doit réussir en mode dégradé si une dépendance optionnelle manque.
  - `def stop(self) -> None` — Arrête proprement et libère les ressources (VRAM comprise).
  - `def health(self) -> Health` — État de santé, interrogé par Fuma.
  - `def handle_event(self, event: Event) -> None` — Reçoit un événement du bus.
  - `def widget_schema(self) -> dict[str, Any]` — Schéma JSON de l'interface générée à la volée par le daemon (titre, sections, boutons).

### `core/module_runner.py`

Lanceur d'un module dans son propre processus : `python -m core.module_runner <dossier_du_module>`.

- `def load_module_class(entry: str) -> type[ModuleBase]`
- `def run(module_dir: Path, client: BusClient | None=None, health_interval_s: float=HEALTH_INTERVAL_S) -> int`

### `core/scheduler.py`

File d'attente GPU unique pour les tâches de vision et de diffusion (scantrad, mangastudio).

- **`class VramRefused(RuntimeError)`** — La tâche demande plus de VRAM que le budget, ou n'a pas obtenu de place à temps.
- **`class GpuScheduler`** — Exécute les tâches GPU une par une, dans l'ordre d'arrivée.
  - `def submit(self, name: str, vram_gb: float, fn: Callable[[], Any]) -> Future[Any]` — Met une tâche en file. Le résultat (ou l'erreur) arrive par le `Future` retourné.
  - `def state(self) -> dict[str, Any]`
  - `def shutdown(self) -> None`

### `modules/gaming_hud/__init__.py`

gaming_hud — HUD de jeu du Hub (évolution de WoW Assistant).

- `def ensure_app_path() -> Path` — Rend importables les modules de l'application d'origine (imports à plat). Idempotent.
- `def run_app() -> None` — Lance WoW Assistant à l'identique (fenêtre Pygame, overlay, voix, vision).

### `modules/gaming_hud/__main__.py`

`python -m modules.gaming_hud` : lance l'application d'origine (exécution autonome, sans le Hub).

*(aucun symbole public)*

### `modules/gaming_hud/adapters/__init__.py`

Adaptateurs de jeu. Voir `base.GameAdapter`.

*(aucun symbole public)*

### `modules/gaming_hud/adapters/base.py`

Interface commune « adaptateur de jeu ».

- **`class GameAdapter(Protocol)`** — Contrat d'un adaptateur de jeu.
  - `def detect(self) -> bool` — Le jeu est-il installé ou en cours d'exécution ? Ne lève jamais d'exception.
  - `def read_state(self) -> dict[str, Any]` — État normalisé, en lecture seule. Un état partiel ou vide est un résultat valide.
  - `def schema(self) -> dict[str, Any]` — Description des sections de l'état (pour l'interface et pour le LLM).
  - `def widgets(self) -> list[dict[str, Any]]` — Widgets proposés par l'adaptateur : `[{"id", "title", "section", "note"}]`.
  - `def privacy_filter(self, state: dict[str, Any], mode: str) -> dict[str, Any]` — Copie de l'état sans données privées. `mode` : « off » ou « showcase ».
  - `def context_for_llm(self, state: dict[str, Any]) -> str` — Résumé textuel court de l'état, joint aux questions posées à l'assistant.
- `def check_mode(mode: str) -> str`

### `modules/gaming_hud/adapters/log_tail.py`

Adaptateur générique : suit un fichier journal texte et en tire un état, avec des règles regex en YAML.

- **`class RulesError(ValueError)`** — Fichier de règles invalide.
- **`class Rule`**
- `def parse_rules(raw: Any) -> tuple[dict[str, Any], list[Rule]]` — Valide le contenu d'un fichier de règles. Retourne (en-tête, règles).
- **`class LogTailAdapter`** — Construit un état à partir des lignes d'un journal texte.
  - `def from_file(cls, rules_path: Path, options: PrivacyOptions | None=None) -> LogTailAdapter`
  - `def detect(self) -> bool`
  - `def read_state(self) -> dict[str, Any]`
  - `def schema(self) -> dict[str, Any]`
  - `def widgets(self) -> list[dict[str, Any]]`
  - `def privacy_filter(self, state: dict[str, Any], mode: str) -> dict[str, Any]`
  - `def context_for_llm(self, state: dict[str, Any]) -> str`

### `modules/gaming_hud/adapters/privacy.py`

Filtre de confidentialité commun aux adaptateurs (mode Showcase / diffusion OBS).

- **`class PrivacyOptions`** — Réglages du mode Showcase.
- `def scrub_text(text: str) -> str` — Retire e-mails, chemins de fichiers et jetons d'une chaîne.
- `def round_amount(value: float, unit: int=1) -> int` — Arrondit à 1 chiffre significatif, dans l'unité donnée (ex. 10 000 cuivres = 1 pièce d'or).
- `def filter_state(state: Any, options: PrivacyOptions, *, money_keys: Iterable[str]=(), money_unit: int=1, name_keys: Iterable[str]=(), names: Iterable[str]=(), private_keys: Iterable[str]=()) -> Any` — Copie filtrée de `state`.
- `def leaks(filtered: Any, canaries: Iterable[str]) -> list[str]` — Canaris retrouvés dans la sortie filtrée (aide de test : la liste doit être vide).

### `modules/gaming_hud/adapters/screen_ocr.py`

Adaptateur EXPÉRIMENTAL : état dérivé d'une capture d'écran par un modèle de vision local.

- `def grab_screen_png(max_edge: int=1280) -> bytes` — Capture l'écran principal (Pillow) et le réduit. Lève `RuntimeError` si la capture est impossible.
- `def ollama_vision(host: str, model: str, prompt: str, image_png: bytes, num_ctx: int=4096, keep_alive: str='30s', timeout_s: float=180.0) -> str` — Question + image au modèle de vision local, réponse au format JSON (API native d'Ollama).
- `def extract_json(text: str) -> dict[str, Any]` — Extrait l'objet JSON d'une réponse de modèle (tolère les balises de code et le texte autour).
- **`class ScreenOcrAdapter`** — Lit des champs à l'écran avec un modèle de vision local.
  - `def prompt(self) -> str`
  - `def detect(self) -> bool`
  - `def read_state(self, force: bool=False) -> dict[str, Any]`
  - `def schema(self) -> dict[str, Any]`
  - `def widgets(self) -> list[dict[str, Any]]`
  - `def privacy_filter(self, state: dict[str, Any], mode: str) -> dict[str, Any]`
  - `def context_for_llm(self, state: dict[str, Any]) -> str`

### `modules/gaming_hud/adapters/wow_retail.py`

Adaptateur World of Warcraft (Retail) : l'implémentation d'origine derrière l'interface `GameAdapter`.

- **`class WowRetailAdapter`** — Lit l'état du personnage depuis les SavedVariables de l'addon HermesAssistant.
  - `def detect(self) -> bool`
  - `def read_state(self) -> dict[str, Any]`
  - `def schema(self) -> dict[str, Any]`
  - `def widgets(self) -> list[dict[str, Any]]`
  - `def privacy_filter(self, state: dict[str, Any], mode: str) -> dict[str, Any]`
  - `def context_for_llm(self, state: dict[str, Any]) -> str` — Même phrase que l'application d'origine (`main.player_context`), construite depuis l'état normalisé.

### `modules/gaming_hud/module.py`

Module du Hub : lit l'état du jeu par un `GameAdapter` et le publie sur le bus.

- `def build_adapter(config: dict[str, Any]) -> GameAdapter` — Construit l'adaptateur demandé par la configuration. Lève `ValueError` si elle est invalide.
- `def compact(state: dict[str, Any], limit: int=MAX_SECTION_BYTES) -> tuple[dict[str, Any], list[str]]` — Sépare les sections publiables des sections trop lourdes pour le bus. Retourne (état, sections omises).
- `def running_process_names() -> set[str]` — Noms des processus en cours (minuscules) ; ensemble vide si `psutil` est absent.
- **`class GamingHudModule(ModuleBase)`** — Publie l'état du jeu ; bascule en mode Showcase quand un logiciel de diffusion est lancé.
  - `def start(self) -> None`
  - `def stop(self) -> None`
  - `def health(self) -> Health`
  - `def handle_event(self, event: Event) -> None`
  - `def set_showcase(self, on: bool) -> None`
  - `def read(self) -> dict[str, Any]` — Lit l'état et rend ce qui a le droit de sortir du module dans le mode courant.
  - `def publish_state(self, force: bool=False) -> bool` — Publie l'état s'il a changé (ou si `force`). Retourne True si un événement est parti.

### `scripts/gen_architecture_map.py`

Génère la partie automatique de ARCHITECTURE_MAP.md (arborescence + signatures publiques) via `ast`.

- `def first_line(doc: str | None) -> str`
- `def signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str`
- `def describe_module(path: Path) -> list[str]`
- `def tree_lines() -> list[str]`
- `def generate() -> str`
- `def render(current: str) -> str`
- `def main(argv: list[str] | None=None) -> int`

### `scripts/relay_orchestrator.py`

Relais Cloud <-> Local : continuer à développer pendant les coupures de quota.

- **`class Clock`** — Horloge réelle. Remplaçable par `VirtualClock` (tests, --dry-run).
  - `def now(self) -> float`
  - `def sleep(self, seconds: float) -> None`
- **`class VirtualClock(Clock)`** — Horloge simulée : `sleep` avance le temps sans attendre.
  - `def now(self) -> float`
  - `def sleep(self, seconds: float) -> None`
- `def fmt_time(ts: float | None) -> str`
- **`class RelayState`** — État du relais, écrit de façon atomique dans `logs/relay_state.json`.
  - `def save(self, path: Path) -> None` — Écriture atomique : fichier temporaire, fsync, puis remplacement.
  - `def load(cls, path: Path) -> RelayState | None` — Charge l'état ; un fichier absent ou illisible donne `None` (le fichier abîmé est mis de côté).
- **`class LockError(RuntimeError)`** — Un autre orchestrateur est déjà actif.
- `def pid_is_alive(pid: int) -> bool` — Vrai si le processus existe. N'envoie jamais de signal sous Windows (os.kill y tuerait le processus).
- **`class SingleInstanceLock`** — Fichier verrou créé de façon exclusive. Un verrou laissé par un processus mort est repris.
  - `def acquire(self) -> None`
  - `def release(self) -> None`
- **`class Status(StrEnum)`**
- **`class CloudResult`**
- `def classify_text(text: str) -> Status | None` — Reconnaît un message de limite d'usage (QUOTA) ou une erreur de débit (TRANSIENT).
- `def parse_retry_after(value: str | None) -> float | None`
- `def resolve_command(cmd: Sequence[str]) -> list[str]` — Résout l'exécutable via le PATH (sous Windows : .cmd/.exe ; un .ps1 passe par PowerShell).
- **`class CloudBackend(Protocol)`**
  - `def run(self, prompt: str) -> CloudResult`
- **`class ClaudeCodeBackend`** — Lance Claude Code en mode non interactif. Le prompt passe par l'entrée standard (jamais par un shell).
  - `def run(self, prompt: str) -> CloudResult`
  - `def classify(returncode: int, stdout: str, stderr: str) -> CloudResult` — Une sortie réussie peut contenir « 429 » dans son texte : on ne cherche les motifs que sur un échec.
- **`class ApiBackend`** — Appel direct de l'API Anthropic via le SDK officiel (paquet `anthropic`, optionnel).
  - `def run(self, prompt: str) -> CloudResult`
- **`class LocalAgent(Protocol)`**
  - `def available(self) -> tuple[bool, str]`
  - `def start(self, prompt: str) -> None`
  - `def is_running(self) -> bool`
  - `def exit_code(self) -> int | None`
  - `def stop(self) -> None`
- `def ollama_base_url(host: str) -> str`
- `def ollama_has_model(host: str, model: str, timeout_s: float=5.0) -> tuple[bool, str]` — Interroge /api/tags du serveur Ollama configuré (machine locale ou réseau local).
- `def router_is_up(router_url: str, timeout_s: float=5.0) -> tuple[bool, str]` — Vérifie que le routeur local (OmniRoute) répond sur /models.
- **`class SubprocessLocalAgent`** — Agent local branché sur Ollama : Claude Code via un routeur local, Aider, ou OpenCode.
  - `def prompt_file(self) -> Path`
  - `def build_env(self) -> dict[str, str]` — Environnement de l'agent local. Aucune vraie clé : le routeur local n'en demande pas.
  - `def build_command(self, prompt: str) -> list[str]`
  - `def available(self) -> tuple[bool, str]`
  - `def start(self, prompt: str) -> None`
  - `def is_running(self) -> bool`
  - `def exit_code(self) -> int | None`
  - `def stop(self) -> None`
- **`class GitRepo`** — Sous-ensemble de Git utile au relais : point de reprise et diff de revue.
  - `def head(self) -> str | None`
  - `def has_changes(self) -> bool`
  - `def wip_commit(self, message: str) -> str | None` — Commit intermédiaire de tout le travail en cours. Retourne le nouveau HEAD, ou None s'il n'y a rien.
  - `def log_since(self, base: str | None, limit: int=40) -> str`
  - `def diff_stat(self, base: str | None) -> str`
  - `def diff(self, base: str | None, max_chars: int) -> str`
- `def build_local_prompt(tasks: str) -> str`
- `def tail_text(path: Path, max_chars: int) -> str`
- `def build_resume_prompt(mission: str, changelog_tail: str, git_log: str, diff_stat: str, diff: str) -> str`
- **`class RelayConfig`**
- **`class RelayOrchestrator`** — Machine à états du relais. Toutes les dépendances sont injectées (tests sans réseau ni processus).
  - `def window_s(self) -> float`
  - `def run(self) -> int` — Codes de sortie : 0 terminé · 2 erreur · 3 autre instance active · 130 interrompu.
- **`class SimulatedCloud`** — Agent cloud factice : quota atteint au premier passage, succès au second. Aucun appel de service.
  - `def run(self, prompt: str) -> CloudResult`
- **`class SimulatedLocal`** — Agent local factice : chaque passage dure `run_s` secondes d'horloge simulée.
  - `def available(self) -> tuple[bool, str]`
  - `def start(self, prompt: str) -> None`
  - `def is_running(self) -> bool`
  - `def exit_code(self) -> int | None`
  - `def stop(self) -> None`
- **`class NullGit`** — Git factice pour la simulation : ne lit ni n'écrit rien.
  - `def head(self) -> str | None`
  - `def wip_commit(self, message: str) -> str | None`
  - `def log_since(self, base: str | None, limit: int=40) -> str`
  - `def diff_stat(self, base: str | None) -> str`
  - `def diff(self, base: str | None, max_chars: int) -> str`
- `def build_parser() -> argparse.ArgumentParser`
- `def setup_logging(log_path: Path) -> None`
- `def read_optional(path: Path) -> str`
- `def main(argv: Sequence[str] | None=None) -> int`
<!-- AUTO:END -->
