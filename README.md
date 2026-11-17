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
| Moniteur GPU, contrat de module | fait, testé |
| Bus d'événements entre processus, démon, API locale (`127.0.0.1`) | fait, testé |
| Gardiens Inoue (budget VRAM) et Fuma (watchdog, mode nocturne) | testés en simulation, branchés dans le démon |
| Routeur LLM : un seul gros modèle chargé à la fois, `num_ctx` fixé | fait, testé en réel sur 2 GPU |
| Module `gaming_hud` : état du jeu en lecture seule, mode Showcase | fait, testé en réel (OBS simulé) |
| Adaptateurs de jeu : WoW, journal texte, capture d'écran (expérimental) | faits, testés |
| Page d'overlay OBS, base vectorielle, autres modules | à faire |
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

## Lancer le démon

```powershell
.\.venv\Scripts\python.exe -m core.daemon
```

Puis, dans un navigateur : `http://127.0.0.1:5750/health` (état du Hub et des deux gardiens),
`/gpu` (mesure des cartes), `/modules`, `/events`. Le démon démarre aussi sans GPU, en mode dégradé.

Activer le HUD de jeu et poser une question au modèle local, avec le contexte du jeu :

```powershell
curl.exe -X POST http://127.0.0.1:5750/modules/gaming_hud/activate
curl.exe -X POST http://127.0.0.1:5750/ask -H "Content-Type: application/json" -d '{\"prompt\":\"Où est mon personnage ?\",\"model\":\"qwen3-27b:latest\"}'
```

L'application de jeu d'origine (fenêtre, overlay, voix) se lance seule : `python -m modules.gaming_hud`.

### Mesures réelles (17/11/2026, RTX 5080 16 Go + RTX 5060 Ti 16 Go, Ollama 0.40.16)

| Modèle | Quantification | `num_ctx` | VRAM occupée | Première réponse |
|---|---|---|---|---|
| `qwen3-27b` | Q4_K_M | 32 768 | 16,77 Gio | 10,9 s |
| `qwen3-coder:30b` | Q4_K_M | 32 768 | 19,69 Gio | 14,0 s |
| `qwen2.5vl:7b` (vision) | — | 4 096 | 6,3 Gio | 16,7 s |

Les deux gros modèles dépassent la VRAM d'une seule carte de 16 Go : Ollama les répartit sur les deux
GPU, et le Hub n'en garde jamais deux en mémoire. Débit en jetons par seconde : non mesuré.

## Développement 24 h/24 : le relais Cloud ⇄ Local

Le projet est développé par deux agents qui se relaient, avec une passation documentée :

- un agent **cloud** (Claude Code), limité par une fenêtre de quota ;
- un agent **local** (Qwen sous Ollama), qui prend le relais pendant la coupure. Par défaut c'est
  Claude Code lui-même, branché sur Ollama par un routeur local (OmniRoute) ; Aider et OpenCode sont
  aussi pris en charge.

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
.\.venv\Scripts\python.exe scripts\relay_orchestrator.py --backend claude-code --local-agent claude-code

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

- `pytest` : 200 tests réussis, 2 tests réels sur GPU ignorés par défaut ; `ruff check .` propre.
- Bout en bout réel (17/11) : démon → module `gaming_hud` → données du jeu → modèle local → réponse correcte.
- Routeur LLM : deux gros modèles chargés l'un après l'autre, un seul en mémoire à chaque instant.
- Filtre de confidentialité : aucune donnée privée de test, ni des données réelles, dans la sortie Showcase.
- Moniteur GPU : lecture réelle de deux GPU NVIDIA (RTX 5080, RTX 5060 Ti) via `pynvml`.
- Démon : lancé pour de vrai, API joignable sur `127.0.0.1:5750` uniquement ; un module de test tourne
  dans un processus séparé, s'arrête proprement, et est relancé par Fuma après un plantage.
- Relais : tous les scénarios en simulation (horloge virtuelle, serveur HTTP factice renvoyant des 429).
- `relay_orchestrator.py --dry-run` : un cycle complet, code de sortie 0.

**Non vérifié :**

- Le relais face à une vraie limite de quota de Claude Code.
- Le lancement réel de l'agent local (Claude Code via OmniRoute ; Aider et OpenCode ne sont pas installés).
- Le backend API face au vrai service Anthropic.
- La CI GitHub (le dépôt n'est pas encore poussé).
- La bascule Showcase avec OBS réel (le logiciel de diffusion est simulé par un faux processus).
- Les adaptateurs `log_tail` et `screen_ocr` sur un vrai jeu (testés sur un journal et une image de test).

## Feuille de route

Voir [`PROJECT_STATUS.md`](PROJECT_STATUS.md) : hub et gardiens (J2), HUD de jeu (J3), mode Showcase
OBS (J4), base vectorielle et laboratoire scientifique (J5), traduction de manga (J6), studio de
retouche et mini-jeu (J7), documentation finale (J8).

## Licence

Apache 2.0 — voir [`LICENSE`](LICENSE) et [`THIRD_PARTY.md`](THIRD_PARTY.md).
