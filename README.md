# AetherTwin (I&F Core)

> **Version provisoire du README (J1, 16/11/2026).** Le projet est en cours de construction.
> L'état réel de chaque brique est dans [`PROJECT_STATUS.md`](PROJECT_STATUS.md).

AetherTwin est un **hub d'agents locaux** : un démon central observe ce que fait la machine
(jeu, lecteur, outil de création), active le module adapté et répartit la VRAM entre les modèles.
Tout s'exécute en local, sous Ollama, sur du matériel NVIDIA grand public.

*À Inoue et Fuma.*

## État actuel

| Élément | État |
|---|---|
| Structure du dépôt, conventions, CI, garde-fou anti-secrets | fait, testé |
| Relais de développement Cloud ⇄ Local (`scripts/relay_orchestrator.py`) | testé en simulation |
| Hub (`core/`) et modules (`modules/`) | à faire |
| Code d'origine du premier module (WoW Assistant) | présent dans `_import/`, à porter |

## Installation

Windows 10 ou 11, Python 3.11.

```powershell
git clone <URL-du-dépôt> AetherTwin-IF-Core
cd AetherTwin-IF-Core
.\scripts\setup.ps1
.\.venv\Scripts\python.exe -m pytest
```

Sans le script :

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

## Développement 24 h/24 : le relais Cloud ⇄ Local

Le projet est développé par deux agents qui se relaient, avec une passation documentée :

- un agent **cloud** (Claude Code), limité par une fenêtre de quota ;
- un agent **local** (Qwen sous Ollama, piloté par Aider ou OpenCode), qui prend le relais pendant la coupure.

```mermaid
stateDiagram-v2
    [*] --> Cloud: lancement, T0 enregistré
    Cloud --> Cloud: 429 transitoire (backoff court)
    Cloud --> Local: limite d'usage, ou 429 persistant
    Local --> Cloud: T0 + fenêtre — arrêt propre, commit wip(local), résumé et diff pour revue
    Cloud --> [*]: mission terminée
```

L'agent local reçoit `AGENT_HANDOFF.md`, `PROJECT_STATUS.md`, `ARCHITECTURE_MAP.md` et la liste de
tâches courante. Il consigne son travail dans `logs/CHANGELOG_DEV.md`. À la reprise, l'agent cloud
relit **le diff seulement**.

```powershell
# simulation complète, sans appeler aucun service
.\.venv\Scripts\python.exe scripts\relay_orchestrator.py --dry-run

# relais réel
.\.venv\Scripts\python.exe scripts\relay_orchestrator.py --backend claude-code --local-agent aider

# état enregistré
.\.venv\Scripts\python.exe scripts\relay_orchestrator.py --status
```

Options principales : `--window-minutes` (défaut 302, soit 5 h + 2 min), `--local-model`
(défaut `qwen3-coder:30b-a3b-q4_K_M`), `--num-ctx` (défaut 32768), `--ollama-host`, `--max-cycles`.

Robustesse : une seule instance (fichier verrou), état écrit de façon atomique dans
`logs/relay_state.json` et relu après un redémarrage, journal `logs/relay.log`, arrêt propre sur
Ctrl+C. Aucune clé dans le dépôt : les identifiants viennent de l'environnement.

## Ce que j'ai vérifié / ce que je n'ai pas pu vérifier

**Vérifié (exécuté le 16/11/2026, Windows 10, Python 3.11) :**

- `pytest` : 42 tests réussis ; `ruff check .` propre.
- Relais : tous les scénarios en simulation (horloge virtuelle, serveur HTTP factice renvoyant des 429).
- `relay_orchestrator.py --dry-run` : un cycle complet, code de sortie 0.

**Non vérifié :**

- Le relais face à une vraie limite de quota de Claude Code.
- Le lancement réel d'Aider ou d'OpenCode (non installés sur le poste de développement).
- Le backend API face au vrai service Anthropic.
- La CI GitHub (le dépôt n'est pas encore poussé).

## Feuille de route

Voir [`PROJECT_STATUS.md`](PROJECT_STATUS.md) : hub et gardiens (J2), HUD de jeu (J3), mode Showcase
OBS (J4), base vectorielle et laboratoire scientifique (J5), traduction de manga (J6), studio de
retouche et mini-jeu (J7), documentation finale (J8).

## Licence

Apache 2.0 — voir [`LICENSE`](LICENSE) et [`THIRD_PARTY.md`](THIRD_PARTY.md).
