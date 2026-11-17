# AGENT_HANDOFF — guide de passation

Ce guide est écrit pour un autre agent, par exemple un modèle Qwen local avec un contexte limité.
Les phrases sont courtes. Rien n'est implicite.

## Règle de lecture

1. Lis ce fichier en entier.
2. Lis `PROJECT_STATUS.md`.
3. Lis `ARCHITECTURE_MAP.md`.
4. **Ne charge pas tout le dépôt.** Ouvre seulement les fichiers de ta tâche.
5. N'ouvre jamais `_import/` en entier. `ui.py` fait 93 Ko.

## Où on en est (16/11/2026)

1. Le projet s'appelle AetherTwin (I&F Core). C'est un hub d'agents locaux.
2. Il est présenté au concours ASUS Agent Computer Challenge. Clôture : 25/11/2026.
3. Le dépôt Git est initialisé. La branche est `main`.
4. Le venv est `.venv`. Python 3.11.
5. Le relais Cloud ⇄ Local existe : `scripts/relay_orchestrator.py`. Il est testé en simulation.
6. Les jalons J2 et J3 sont faits. `core/` contient : moniteur GPU, contrat de module, bus, lanceur de
   module, ordonnanceur GPU, Inoue, Fuma, daemon, API locale, configuration, routeur LLM.
7. `modules/gaming_hud/` est le premier module réel. Son dossier `app/` est le code d'origine de
   WoW Assistant (imports à plat, ne pas reformater). Le dossier `_import/` n'existe plus.
8. Les tests passent : 268 tests, plus 2 tests réels sur GPU ignorés par défaut. WoW Assistant v9 a reçu des correctifs le 17/11 (`tests/wow_assistant_v9/`).
   Les mêmes fichiers sont dans `D:\Hermes-Agent\wow_assistant_v9`, la copie que Jérémy utilise.
9. Le poste a 2 GPU visibles : RTX 5080 16 Go et RTX 5060 Ti 16 Go. Les modèles restent en Q4_K_M.
10. J4 (overlay OBS), J5 (`genesis_lab`, `core/knowledge/`) et J6 (`modules/scantrad/`) sont faits (17/11).
    Lanceur double-clic : `Lancer AetherTwin.bat` (raccourci « AetherTwin » sur le bureau), tableau de bord
    sur `http://127.0.0.1:5750/`, en onglets. J7 fait aussi (`mangastudio`, `if_game`).
    **Prochaine tâche : J8** : `research/overlord_notes.md` (+ questionnaire), `docs/HARDWARE_FIT.md`,
    `docs/DEMO_SCRIPT.md`, README final, `scripts/setup.ps1` vérifié dans un venv vierge (penser à torch cu128,
    facultatif). Puis J9 : gel, branche `concours`, tag `v0.1.0-concours`, scan des secrets dans l'historique.

## Commandes exactes

Lance-les depuis la racine du dépôt. Utilise `cmd.exe` ou PowerShell. **Pas Git Bash** pour Aider.

| But | Commande |
|---|---|
| Tests | `.venv\Scripts\python.exe -m pytest` |
| Un seul fichier de tests | `.venv\Scripts\python.exe -m pytest tests\test_relay_orchestrator.py` |
| Lint | `.venv\Scripts\python.exe -m ruff check .` |
| Régénérer la carte | `.venv\Scripts\python.exe scripts\gen_architecture_map.py` |
| Relais, simulation | `.venv\Scripts\python.exe scripts\relay_orchestrator.py --dry-run` |
| Relais, état | `.venv\Scripts\python.exe scripts\relay_orchestrator.py --status` |
| Relais, réel | `.venv\Scripts\python.exe scripts\relay_orchestrator.py` |
| Relevé GPU réel | `.venv\Scripts\python.exe -m core.hardware.gpu_monitor` |
| Installer les dépendances | `.venv\Scripts\python.exe -m pip install -r requirements-dev.txt` |

N'utilise jamais `python` seul. Le `python` du PATH est une autre version (3.10).

## Comment lancer chaque module

| Module | Commande | État |
|---|---|---|
| WoW Assistant (fenêtre Pygame) | `.venv\Scripts\python.exe -m modules.gaming_hud` | fait, testé en réel |
| `gaming_hud` dans le Hub | daemon lancé, puis `curl -X POST http://127.0.0.1:5750/modules/gaming_hud/activate` | fait, testé en réel |
| Question à l'assistant local | `curl -X POST http://127.0.0.1:5750/ask -H "Content-Type: application/json" -d "{\"prompt\":\"bonjour\",\"model\":\"qwen3-27b:latest\"}"` | fait, testé en réel |
| Daemon + tableau de bord | `Lancer AetherTwin.bat` (ou `.venv\Scripts\python.exe -m core.daemon --open`) | fait, testé en réel |
| Daemon sans API | `.venv\Scripts\python.exe -m core.daemon --no-api` | fait |
| Professeur (`genesis_lab`) | tableau de bord, section Professeur (module à lancer d'abord) | fait, testé en réel |
| Base de connaissances | tableau de bord, « Collecter maintenant » ; `GET /knowledge/search?q=…` | fait, testé en réel (sans vecteurs) |
| `scantrad` | onglet Scantrad du tableau de bord, ou `.venv\Scripts\python.exe -m modules.scantrad PAGE.png --series demo` (Hub lancé) | fait, testé en réel (page de test + une vraie page) |
| WoW Assistant depuis le Hub | onglet Jeu, ou `POST /modules/gaming_hud/app/start` (champ `app` du manifeste) | fait, testé en réel |
| `mangastudio` | onglet Studio (poids dans `models/mangastudio/`, torch cu128 dans `.venv`) | fait, testé en réel (HandSegNet) |
| `if_game` | onglet Éther | fait, testé en réel |

## Recette locale validée par Jérémy (Ollama + Aider)

Cette recette vient du laboratoire Ov3rLoRd. Elle est **déclarée** par Jérémy. Elle n'a pas été
rejouée dans ce dépôt. **Aider n'est plus installé sur ce poste** : l'agent local par défaut du relais
est Claude Code branché sur Ollama via OmniRoute (voir « Réponses de Jérémy »). La recette Aider reste
valable si Aider est réinstallé (`--local-agent aider`).

1. Lance Ollama avec un fichier `.bat`. Le `.bat` définit `GGML_CUDA_NO_PINNED=1` avant `ollama serve`.
   Raison : une variable définie ailleurs n'est pas toujours transmise au serveur.
2. Installe Aider dans un **venv dédié**. Pas dans `.venv` du projet.
3. Modèle : `qwen3-coder:30b-a3b-q4_K_M`.
4. **`num_ctx=32768` est obligatoire.** Sans lui, le contexte par défaut (262 144 jetons) provoque
   une erreur d'allocation au chargement.
5. Lance Aider depuis `cmd.exe`. Sous Git Bash, la sortie d'Aider est peu fiable.
6. Après chaque passage d'Aider, **vérifie** : `git log --oneline -5`, puis lis le contenu des
   fichiers modifiés. Ne fais pas confiance au texte affiché par Aider.

Exemple de `.bat` (à adapter, non versionné) :

```bat
@echo off
set GGML_CUDA_NO_PINNED=1
ollama serve
```

Le relais prépare lui-même Aider : il écrit `logs\aider_model_settings.yml` avec `num_ctx`,
et passe `AGENT_HANDOFF.md`, `PROJECT_STATUS.md`, `ARCHITECTURE_MAP.md` en lecture seule.

## Règles à ne jamais enfreindre

1. Aucune clé API, aucun mot de passe, aucun chemin personnel dans le dépôt.
2. N'écris jamais « fonctionne » pour ce que tu n'as pas exécuté. Utilise les statuts de `PROJECT_STATUS.md`.
3. N'invente aucun chiffre, aucun résultat, aucune date. Écris `[À COMPLÉTER PAR JÉRÉMY : …]`.
4. Écris une entrée dans `logs/CHANGELOG_DEV.md` à chaque modification de code.
5. Ne modifie pas `_import/`. C'est la référence d'origine.
6. Réseau : `127.0.0.1` seulement.
7. `subprocess` : toujours une liste d'arguments. Jamais `shell=True` avec un texte venu d'un LLM.
8. Un seul gros modèle de langage chargé à la fois. Fixe toujours `num_ctx`.
9. Écris « Ov3rLoRd » exactement ainsi.
10. Agent local : tes commits commencent par `wip(local):`.

## Prochaines tâches, dans l'ordre

Fais une tâche à la fois. Après chaque tâche : tests, changelog, commit.

### J2 — `core/` (P0)

**Tâches 1 à 7 : faites le 16/11/2026.** Le tableau reste pour référence. Restes connus du J2 :

- Détection des fenêtres (`pygetwindow`) : non faite. Seuls les processus sont observés.
- Interface générée à la volée depuis `widget_schema()` : non faite. Elle dépend du port de `ui.py` (J3).
- (Fait depuis, le 17/11 : `core/llm_router.py` pilote Ollama pour Inoue, et `/ask` répond.)

Comment écrire un module : un dossier `modules/<nom>/` avec `manifest.json` et une classe qui hérite de
`ModuleBase` (`core/module_api.py`). Exemple court : la constante `DEMO_MODULE` de
`tests/core/test_daemon.py`. Exemple réel : `modules/gaming_hud/module.py`.

Comment ajouter un jeu : écrire une classe qui respecte `GameAdapter`
(`modules/gaming_hud/adapters/base.py`). Pour un jeu qui écrit un journal texte, aucun code n'est
nécessaire : copie `modules/gaming_hud/rules/log_tail.example.yaml` et adapte les règles.

Comment appeler un modèle local : toujours par `core/llm_router.py` (`LlmRouter.chat`). Ne parle jamais
à Ollama directement : le routeur fixe `num_ctx` et décharge l'ancien gros modèle avant d'en charger un autre.

| # | Tâche | Fichiers | Terminé quand |
|---|---|---|---|
| 1 | Moniteur GPU | `core/hardware/gpu_monitor.py`, `tests/core/test_gpu_monitor.py` | `GpuMonitor.snapshot()` rend une liste de GPU (nom, VRAM totale/utilisée, température, puissance). Backend `pynvml`. Sans `pynvml` ou sans GPU : liste vide et `backend == "inconnu"`. Aucune exception |
| 2 | Contrat de module | `core/module_api.py`, `tests/core/test_module_api.py` | Classe de base avec `start()`, `stop()`, `health()`, `handle_event(event)`. Chargement et validation de `manifest.json` (`name`, `version`, `description`, `vram_min_gb`, `vram_comfort_gb`, `python_deps`, `triggers`, `network`) |
| 3 | Bus d'événements | `core/bus.py`, `tests/core/test_bus.py` | Publication / abonnement entre processus, sur `127.0.0.1`. Un test envoie un événement d'un processus à un autre |
| 4 | Inoue | `core/guardians/inoue.py`, `tests/core/test_inoue.py` | Budget = VRAM totale − 10 %. `request(module, gb)` rend `accordé`, `en file` ou `refusé`. Testé avec un moniteur GPU factice |
| 5 | Fuma | `core/guardians/fuma.py`, `tests/core/test_fuma.py` | Watchdog : redémarre un module de test qui plante, avec un nombre maximal d'essais. Mode nocturne : plage horaire configurable, horloge injectée |
| 6 | Ordonnanceur GPU | `core/scheduler.py` | File d'attente unique pour les tâches vision/diffusion |
| 7 | Daemon minimal | `core/daemon.py`, `tests/core/test_daemon.py` | Démarre sans GPU. Charge et décharge un module de test. Détecte le lancement et l'arrêt d'un processus de test. API FastAPI sur `127.0.0.1` : `/health`, `/modules`, `/events`, `/gpu`, `/ask` |

### J7 — à faire (P2) : `mangastudio` puis `if_game`

Lis d'abord les sections 6.4 et 6.6 du prompt maître (fichier privé, hors dépôt) ou leur résumé ci-dessous.
PyTorch et ComfyUI ne sont **pas** installés : tout ce qui en dépend est optionnel et testé par import et
signature seulement. Les poids HandSegNet/FootSegNet ne sont pas sur le poste (chemins dans `config/local.yaml`,
section `mangastudio`) : mode dégradé avec message clair. N'annonce aucun résultat visuel non produit.

| # | Tâche | Fichiers | Terminé quand |
|---|---|---|---|
| A | Squelette `mangastudio` | `modules/mangastudio/{manifest.json,module.py}` | Démarre sans PyTorch ni poids : `health()` dégradé, message clair |
| B | Nœud ComfyUI | `modules/mangastudio/comfyui_nodes/__init__.py` | `NODE_CLASS_MAPPINGS` présent ; test d'import et de signature sans ComfyUI |
| C | Workflow de continuité | `modules/mangastudio/workflows/continuity.json` | JSON valide (ControlNet + IP-Adapter), test de structure |
| D | UI standalone en simulation | `modules/mangastudio/ui.py` | Démarre en mode simulation (`SDL_VIDEODRIVER=dummy` ou page web locale) |
| E | `if_game` | `modules/if_game/` | Monde en JSON validé par le code (le LLM propose, le code applique), graine reproductible, sauvegarde locale ; LLM factice dans les tests |

### J6 — `scantrad` — **fait le 17/11/2026**

Chaîne détection (OpenCV) → OCR (`qwen2.5vl:7b` via le Hub) → effacement (inpainting OpenCV) → traduction
(modèle par défaut, glossaire par série) → réincrustation (Pillow). Page de test générée :
`tests/data/scantrad/`. Mesures et limites : `modules/scantrad/README.md`. Reste : une vraie page scannée.

### J5 — **fait le 17/11/2026**

`core/knowledge/` : base vectorielle (SQLite, embedder injectable), collecte polie, service d'ingestion
(tâche de nuit récurrente de Fuma). Le Professeur cite ses sources via `/knowledge/search`. Aucun modèle
d'embedding installé : la recherche tourne en mode dégradé par mots pondérés tant que
`ollama pull nomic-embed-text` n'est pas fait ; ensuite, `KnowledgeStore.reindex()` (ou une nouvelle collecte).
Non fait : la recherche DuckDuckGo demandée par le prompt maître (section 6.5) ; à évaluer (robots.txt de
DuckDuckGo et conditions d'utilisation) avant de l'ajouter.

| # | Tâche | Fichiers | Terminé quand |
|---|---|---|---|
| A | Base vectorielle locale | `core/knowledge/store.py`, `tests/core/test_knowledge_store.py` | Ajout de documents, recherche par similarité, persistance sur disque. Embeddings par Ollama via une fonction injectable (faux embeddings dans les tests) |
| B | Collecte web polie | `core/knowledge/fetcher.py`, test avec un faux serveur HTTP | Respecte `robots.txt`, limite le débit, `User-Agent` explicite, cache disque, journal des sources. Aucun appel réseau réel dans les tests |
| C | Ingestion nocturne | `core/knowledge/ingest.py` | Les tâches lourdes passent par `Fuma.schedule_night_task` |
| D | Calculs de `genesis_lab` | `modules/genesis_lab/` | FASTA (longueur, GC %, ORF, traduction), orbites, bilans de matière. **Code déterministe**, valeurs de référence dans les tests |
| E | Professeur adaptatif | `modules/genesis_lab/tutor.py` | Session guidée scriptée avec un LLM factice ; progression mémorisée dans un fichier local |

### J4 — Mode Showcase OBS (P0/P1) — **fait le 17/11/2026**

Fichiers : `modules/gaming_hud/obs_server.py`, `modules/gaming_hud/web/`, `assets/logo_if_core*.svg`,
`tests/gaming_hud/test_obs_hud.py`. Reste : l'essai dans OBS réel, par Jérémy. Tableau d'origine :

| # | Tâche | Fichiers | Terminé quand |
|---|---|---|---|
| A | Serveur de l'overlay | `modules/gaming_hud/obs_server.py`, `tests/gaming_hud/test_obs_server.py` | Écoute sur `127.0.0.1:5757` seulement. `GET /obs-hud` rend une page HTML. `GET /obs-hud/events` diffuse l'état en SSE. L'état diffusé passe **toujours** par `privacy_filter(state, "showcase")` |
| B | Page de l'overlay | `modules/gaming_hud/web/obs_hud.html` (+ CSS/JS dans le même dossier) | Fond transparent. Aucune dépendance externe (pas de CDN). Affiche personnage, zone, quêtes, et les GPU (utilisation, VRAM, température, puissance) |
| C | Logo | `assets/logo_if_core.svg`, `assets/logo_if_core_mono.svg` | Yin & Yang géométrique : Inoue claire, Fuma sombre. Variante monochrome pour l'overlay |
| D | Captures de rendu | `tests/gaming_hud/test_obs_hud_render.py` | Playwright ouvre `/obs-hud` et enregistre une capture. Test ignoré si Playwright est absent |
| E | Canaris sur la page | même fichier que A | Aucun canari (`tests/gaming_hud/test_adapters.py`) dans le HTML ni dans le flux SSE |

### J3 — `modules/gaming_hud/` (P0) — **fait le 17/11/2026**

Écarts avec le tableau ci-dessous : le code d'origine est dans `modules/gaming_hud/app/` et garde ses
imports à plat ; `modules/gaming_hud.py` n'existe pas (un paquet du même nom le remplace) ; les tests
sont dans `tests/gaming_hud/`.

| # | Tâche | Fichiers | Terminé quand |
|---|---|---|---|
| 8 | Copier le code d'origine dans le paquet | `modules/gaming_hud/` | `python -m modules.gaming_hud` lance l'ancien WoW Assistant, comportement identique |
| 9 | Interface `GameAdapter` | `modules/gaming_hud/adapters/base.py` | Protocole : `id`, `detect`, `read_state`, `schema`, `widgets`, `privacy_filter`, `context_for_llm` |
| 10 | Adaptateur WoW | `modules/gaming_hud/adapters/wow_retail.py` | Enveloppe `GameConnection` + `lua_parser` + `snapcache` |
| 11 | Adaptateur `log_tail` | `modules/gaming_hud/adapters/log_tail.py` | Suit un fichier texte ; règles regex dans un YAML |
| 12 | Adaptateur `screen_ocr` | `modules/gaming_hud/adapters/screen_ocr.py` | Squelette fonctionnel, marqué expérimental |
| 13 | Tests headless | `tests/gaming_hud/` | `SDL_VIDEODRIVER=dummy`, faux serveurs HTTP, événements scriptés |

## Pièges connus

| Piège | Ce qu'il faut faire |
|---|---|
| `python` nu = Python 3.10 | Toujours `.venv\Scripts\python.exe` |
| `os.kill(pid, 0)` **tue** le processus sous Windows | Utiliser `pid_is_alive` de `scripts/relay_orchestrator.py` |
| PowerShell casse les guillemets de `python -c "..."` | Écrire un fichier `.py` et le lancer |
| Sortie d'Aider peu fiable sous Git Bash | Lancer depuis `cmd.exe`, vérifier avec `git log` |
| Contexte par défaut d'un modèle 30 B = 262 144 jetons | Fixer `num_ctx=32768` |
| Claude Code ne connaît pas `ollama/...` : il suppose 200 000 jetons de contexte | Ollama n'en sert que 32 768 par défaut. Garder les tâches locales courtes. Une tâche = peu de fichiers |
| OmniRoute écoute sur `0.0.0.0` sans clé | Le lancer avec `OMNIROUTE_SERVER_HOST=127.0.0.1` |
| `tests/test_architecture_map.py` échoue après un ajout de fichier | Relancer `scripts\gen_architecture_map.py` |
| `modules/gaming_hud/app/` utilise des imports à plat (`import ui`) | Appeler `modules.gaming_hud.ensure_app_path()` avant d'importer un de ses fichiers. Ne pas convertir en imports de paquet |
| Un fichier de `app/` modifié | Le recopier dans `D:\Hermes-Agent\wow_assistant_v9` : les deux doivent rester identiques |
| Message de commit contenant des guillemets sous PowerShell | Écrire le message dans un fichier, puis `git commit -F fichier` |
| Un gros modèle Qwen dépasse 16 Go de VRAM | Normal : Ollama le répartit sur 2 GPU. Ne charge jamais deux gros modèles : passe par `LlmRouter` |
| Les tests réels sur GPU sont ignorés par défaut | `set AETHERTWIN_REAL_OLLAMA=1` pour les activer |
| La page d'overlay interdit l'évaluation de code (politique de sécurité) | Dans un test Playwright, attendre avec `expect(locator)`, pas avec `wait_for_function("…")` |
| Le port 5757 est déjà pris | Le module continue sans overlay et le dit dans son bilan de santé. Dans les tests : `obs_hud_port: 0` |
| Ne jamais mettre de `innerHTML` dans `web/obs_hud.js` | Écrire les données avec `textContent` (un test le vérifie) |
| Le modèle local invente des calculs intermédiaires faux | Ne lui demande jamais un nombre. Le code calcule ; `foreign_numbers` (`tutor.py`) rejette un texte qui contient un nombre non fourni |
| Une valeur de référence fausse dans un test | Vérifie d'abord le test à la main avant de « corriger » le code (arrivé le 17/11 sur un GC %) |
| `.toc` de l'addon sans `## SavedVariables` | Le jeu n'écrit rien. Ne jamais retirer cette ligne |
| Widgets : clic sur les poignées | Enregistrer le corps **avant** les poignées |
| Cache d'instantané | Une section vide n'écrase jamais une section connue |
| Overlay | C'est une 2ᵉ fenêtre SDL (`pygame._sdl2.video.Window`). Les événements sont routés par `event.window` |
| WoW n'écrit les SavedVariables qu'au `/reload`, à la déconnexion ou via `/ha save` | Ne pas attendre de temps réel |

## Réponses de Jérémy (16/11/2026)

| Sujet | Réponse | Vérifié ? |
|---|---|---|
| Compte GitHub | `https://github.com/Ov3rLoRd-MLEngineer` | le dépôt AetherTwin n'y est pas encore créé |
| Seconde RTX 5060 Ti | pas encore branchée, il manque un riser | oui : 2 GPU, 31,8 Gio vus par Ollama |
| Serveur de modèles | Ollama sur le port 11434, OmniRoute sur le port 20128, sur ce poste | oui (journaux de démarrage) |
| Agent local habituel | **Claude Code** lancé avec `--model ollama/qwen3-27b:latest`, via OmniRoute | commande relevée dans son lanceur |
| Aider | **pas installé**. Tout a été désinstallé depuis le premier projet | oui |
| Modèles Qwen | `qwen3-27b`, `qwen3-35b`, `qwen3-coder:30b` : **tous en Q4_K_M** | oui (`ollama show`) |
| HandSegNet | GitHub `Ov3rLoRd-MLEngineer/handsegnet-anime-sdxl`, HuggingFace du même nom | liens fournis, non ouverts |
| FootSegNet | GitHub `Ov3rLoRd-MLEngineer/footsegnet-anime-sdxl`, HuggingFace du même nom | liens fournis, non ouverts |
| Poids des modèles | rien en local, archivé sur un autre disque. **Tout est à télécharger** | — |
| Dépôt Ov3rLoRd | `https://github.com/Ov3rLoRd-MLEngineer/OVERLORD`, public | oui : **237 commits** sur `main` (239 toutes branches), du 23/06/2026 au 10/08/2026 |

Variables d'environnement de l'agent local Claude Code (le relais les pose lui-même) :

```bat
set ANTHROPIC_BASE_URL=http://127.0.0.1:20128/v1
set ANTHROPIC_AUTH_TOKEN=ollama
set ANTHROPIC_API_KEY=
claude -p --model "ollama/qwen3-27b:latest"
```

`ANTHROPIC_AUTH_TOKEN=ollama` est une valeur factice, pas un secret : le routeur local ne demande pas de clé.

## Décisions de Jérémy (16/11/2026, soir)

1. **Quantification : on reste en Q4_K_M** tant que la machine n'a que 32 Go de VRAM. Le Q8 est trop lourd.
2. **Contexte local : 32 768 jetons.** C'est la limite logique pour ce matériel.
3. **Pas de push GitHub pour l'instant.** Le travail se fait en local. Le dépôt sera poussé plus tard.
4. Le message cosmétique du `.bat` d'Ollama reste en l'état.
5. **Trois GPU sur une seule machine** (17/11) : pas de serveur Ollama séparé pour l'instant.
6. **Clés API saisies dans l'interface** de WoW Assistant (17/11), avec un bouton d'effacement. Pas de variable d'environnement imposée à l'utilisateur.
7. **Modèles 3D** dans WoW Assistant : abandonnés pour l'instant.
8. WoW Assistant se lance en **Python 3.11** avec `Lancer WoW Assistant.bat`.

## Questions encore ouvertes

1. Nom du dépôt GitHub d'AetherTwin (au moment du push).
2. Identité Git des commits : confirmer `Ov3rLoRd-MLEngineer` + adresse noreply avant le premier push.
