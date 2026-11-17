# PROJECT_STATUS — AetherTwin (I&F Core)

Dernière mise à jour : **16/11/2026** (J0–J1) · Clôture du concours : **25/11/2026** · Reste : 9 jours.

Statuts : `FAIT-TESTÉ` (exécuté réellement, tests verts) · `FAIT-NON-TESTÉ` (écrit, pas exécuté en
conditions réelles) · `SIMULÉ` (fonctionne avec des doublures) · `À FAIRE`.

## Où on en est

- Dépôt initialisé : venv Python 3.11, Git, lint, tests, CI, fichiers de suivi. **134 tests** au total.
- Relais Cloud ⇄ Local écrit et testé **en simulation**.
- **J2 terminé** : moniteur GPU, contrat de module, bus, ordonnanceur, gardiens, démon et API locale.
- Aucun module du Hub n'existe encore. `modules/` est vide. Prochain jalon : J3.
- Décisions de Jérémy : Q4_K_M tant que la VRAM est de 32 Go ; contexte local 32 768 ; pas de push pour l'instant.
- Le code de WoW Assistant est dans `_import/wow_assistant_v9/`, intact, non porté.

## Tableau des briques

| Brique | Priorité | Jalon | Statut | Détail |
|---|---|---|---|---|
| Structure, `CLAUDE.md`, suivi, CI | P0 | J0 | `FAIT-TESTÉ` | ruff propre, pytest vert en local. CI GitHub : `FAIT-NON-TESTÉ` (dépôt pas encore poussé) |
| `scripts/gen_architecture_map.py` | P0 | J0 | `FAIT-TESTÉ` | signatures extraites par `ast`, test de fraîcheur |
| Garde-fou anti-secrets (`tests/test_repo_hygiene.py`) | P0 | J0 | `FAIT-TESTÉ` | scanne les fichiers suivis |
| `scripts/relay_orchestrator.py` — logique (états, verrou, reprise, backoff) | P0 | J1 | `SIMULÉ` | horloge virtuelle + doublures ; `--dry-run` exécuté |
| Relais — backend API Anthropic | P0 | J1 | `SIMULÉ` | SDK officiel contre un serveur HTTP factice (429, 529, 400, 200) ; jamais appelé sur le vrai service |
| Relais — backend Claude Code | P0 | J1 | `FAIT-NON-TESTÉ` | sous-processus réel testé avec un faux binaire ; le format exact du message de quota de Claude Code n'a pas été observé |
| Relais — agent local Claude Code via OmniRoute (défaut) | P0 | J1 | `FAIT-NON-TESTÉ` | commande et environnement repris du lanceur de Jérémy ; sous-processus réel testé avec un faux binaire ; jamais lancé contre OmniRoute + Qwen |
| Relais — agent local Aider / OpenCode | P0 | J1 | `FAIT-NON-TESTÉ` | commande construite et testée ; **Aider et OpenCode ne sont pas installés** sur ce poste |
| `core/hardware/gpu_monitor.py` | P0 | J2 | `FAIT-TESTÉ` | lecture réelle des 2 GPU via `pynvml` (nom, VRAM, charge, température, puissance) ; repli `nvidia-smi` puis « inconnu » testés |
| `core/module_api.py` (manifeste, événements, classe de base) | P0 | J2 | `FAIT-TESTÉ` | validation et découverte testées ; aucun vrai module ne l'utilise encore |
| Inoue — budget VRAM, file d'attente, un seul gros LLM | P0 | J2 | `SIMULÉ` | comptabilité testée avec des GPU factices ; **ne pilote pas encore Ollama** (aucun chargement/déchargement réel) |
| Fuma — watchdog, alertes thermiques, mode nocturne | P0 | J2 | `SIMULÉ` | testé avec des modules factices et une horloge injectée ; pas encore branché sur de vrais processus |
| `core/bus.py` — bus entre processus sur 127.0.0.1 | P0 | J2 | `FAIT-TESTÉ` | événement échangé avec un vrai second processus ; clé erronée refusée ; messages JSON |
| `core/scheduler.py` — file d'attente GPU unique | P0 | J2 | `SIMULÉ` | testé avec des tâches factices ; aucune vraie tâche vision/diffusion |
| `core/daemon.py` + `core/module_runner.py` | P0 | J2 | `FAIT-TESTÉ` | module de test lancé dans un vrai processus séparé, arrêté proprement, relancé par Fuma après un plantage ; déclencheur de processus simulé (faux `obs64.exe`). Démon réel lancé le 16/11 : 2 GPU, budget 28,66 Go |
| `core/api.py` — `/health`, `/modules`, `/events`, `/gpu`, `/ask` | P0 | J2 | `FAIT-TESTÉ` | écoute vérifiée sur 127.0.0.1 ; **`/ask` répond 503** tant que le routeur LLM n'existe pas (J5) |
| Détection de fenêtres (`pygetwindow`), interface générée à la volée (`widget_schema`) | P0 | J2→J3 | `À FAIRE` | reporté avec le port de `ui.py` |
| Correctifs de WoW Assistant v9 (17/11) : fermeture, saisie, presse-papier, clic droit, widgets web, mise en page | P0 | avant J3 | `FAIT-TESTÉ` | 24 tests headless ; fermeture vérifiée avec de vraies fenêtres ; fenêtre web vérifiée activable (Python 3.10 et 3.11). **Testé par Jérémy le 17/11** : frappe dans Open WebUI, sessions conservées, fermeture. Connexion YouTube refusée par Google (limite connue). Bouton « × » d'effacement de clé API ajouté |
| Modèles 3D à la place des silhouettes | P2 | — | `À FAIRE` | non entrepris : voir le changelog du 17/11 |
| Port de WoW Assistant → `modules/gaming_hud/` | P0 | J3 | `À FAIRE` | code d'origine lu, non porté |
| `GameAdapter` + `wow_retail` + `log_tail` + `screen_ocr` | P0 | J3 | `À FAIRE` | |
| Mode Showcase OBS, `/obs-hud`, filtre de confidentialité, logo | P0/P1 | J4 | `À FAIRE` | |
| Base vectorielle, scraping légal, routeur LLM | P1 | J5 | `À FAIRE` | |
| `genesis_lab` + Professeur | P1 | J5 | `À FAIRE` | |
| `scantrad` | P1 | J6 | `À FAIRE` | |
| `mangastudio`, `if_game` | P2 | J7 | `À FAIRE` | |
| `research/overlord_notes.md`, `docs/HARDWARE_FIT.md`, README final | P0 | J8 | `À FAIRE` | README actuel = version provisoire |
| Gel, branche `concours`, tag `v0.1.0-concours`, scan de l'historique | P0 | J9 | `À FAIRE` | |

## Mesures réelles du poste (16/11/2026)

| Élément | Valeur mesurée | Commande |
|---|---|---|
| OS | Windows 10 Professionnel 10.0.19045 | `Get-CimInstance Win32_OperatingSystem` |
| Python | 3.11.0 (venv). 3.10 aussi présent. Pas de 3.12 | `py -0p` |
| GPU 0 | NVIDIA GeForce RTX 5080, 16 303 MiB | `nvidia-smi` |
| GPU 1 | NVIDIA GeForce RTX 5060 Ti, 16 311 MiB | `nvidia-smi` |
| Ollama | 0.40.16, 17 modèles installés | `ollama list` |
| `qwen3-coder:30b-a3b-q4_K_M` | 30,5 B, Q4_K_M, contexte max 262 144, 18 Go sur disque | `ollama show` |
| `qwen3-27b:latest` | 27,3 B, Q4_K_M, contexte max 262 144, 16 Go sur disque | `ollama show` |
| `qwen3-35b:latest` | 34,7 B, Q4_K_M, contexte max 262 144, 21 Go sur disque | `ollama show` |
| VRAM vue par Ollama | 31,8 Gio au total ; contexte par défaut 32 768 | journal de démarrage d'Ollama |
| Dépôt Ov3rLoRd | 237 commits sur `main`, 239 toutes branches, 23/06/2026 → 10/08/2026 | `git rev-list --count` sur le dépôt public |

**Écarts avec le cahier des charges :**

- Deux GPU visibles (≈ 32 Go), pas trois (48 Go) : la seconde RTX 5060 Ti attend un riser.
  `config/hardware_profiles.yaml` contient les deux profils.
- **Aucun modèle Q8_0 n'est installé.** Les trois Qwen sont en Q4_K_M. Le profil « qualité » reste à définir.
- La VRAM occupée par chaque modèle une fois chargé n'a **pas** encore été mesurée.
- L'agent local réel de Jérémy est Claude Code via OmniRoute, pas Aider.

## Reste à faire, par priorité

1. **Restes du J2** (à traiter avec J3 et J5) : détection de fenêtres, interface générée à la volée, pilotage d'Ollama par Inoue (`keep_alive`).
2. **P0 — J3** : port de WoW Assistant, `GameAdapter`, adaptateur `log_tail`.
3. **P0/P1 — J4** : Showcase OBS, `/obs-hud`, filtre de confidentialité avec canaris, logo SVG.
4. **P1 — J5/J6** : base vectorielle, routeur LLM, `genesis_lab`, `scantrad`.
5. **P2 — J7** : `mangastudio`, `if_game` (squelettes honnêtes si le temps manque).
6. **P0 — J8/J9** : documents finaux, installation en venv vierge, gel, soumission.

## Problèmes rencontrés et solutions

| Problème | Solution |
|---|---|
| Identité Git globale absente | Identité **locale au dépôt** : `Ov3rLoRd-MLEngineer` + adresse `users.noreply.github.com`. À confirmer par Jérémy avant le premier `push` |
| `gh` (GitHub CLI) absent | La création du dépôt GitHub reste à faire par Jérémy |
| `os.kill(pid, 0)` termine le processus sous Windows | `pid_is_alive` passe par `OpenProcess` / `GetExitCodeProcess` |
| Une réponse réussie de Claude peut contenir « 429 » dans son texte | Les motifs de quota ne sont cherchés que si la commande a échoué (`is_error` ou code de sortie ≠ 0) |
| `claude` résolu en `.ps1` sous PowerShell | `resolve_command` passe par `shutil.which` (`.cmd`) et enveloppe un `.ps1` dans PowerShell |
| Scripts Python en ligne avec guillemets cassés par PowerShell | Passer par des fichiers, pas par `python -c` |

## Tests à faire par Jérémy sur sa machine

| # | Test | Commande | Résultat attendu |
|---|---|---|---|
| 1 | Suite de tests | `.venv\Scripts\python.exe -m pytest` | tout vert |
| 2 | Relais en simulation | `.venv\Scripts\python.exe scripts\relay_orchestrator.py --dry-run` | un cycle cloud → local → cloud, code 0 |
| 3 | Agent local seul : Ollama et OmniRoute lancés | `set ANTHROPIC_BASE_URL=http://127.0.0.1:20128/v1` · `set ANTHROPIC_AUTH_TOKEN=ollama` · `set ANTHROPIC_API_KEY=` puis `echo Lis AGENT_HANDOFF.md et resume-le en 3 lignes \| claude -p --model "ollama/qwen3-27b:latest"` | une réponse du modèle local, sans erreur de contexte |
| 4 | Relais réel, fenêtre courte | `.venv\Scripts\python.exe scripts\relay_orchestrator.py --window-minutes 10 --max-cycles 1 --local-model qwen3-27b:latest` (depuis `cmd.exe`) | à la limite de quota : bascule sur l'agent local, puis retour ; vérifier `logs\relay.log` et `git log` |
| 5 | Relever le message exact de limite de Claude Code | copier la ligne de `logs\relay.log` | permet d'ajuster `QUOTA_PATTERNS` si besoin |
| 6 | Topologie 3 GPU, une fois le riser installé | `.venv\Scripts\python.exe -m core.hardware.gpu_monitor` | `gpu_count: 3`, environ 48 900 MiB |

## Points attendus de Jérémy

Voir la section « Questions ouvertes » de `AGENT_HANDOFF.md`.
