# PROJECT_STATUS — AetherTwin (I&F Core)

Dernière mise à jour : **16/11/2026** (J0–J1) · Clôture du concours : **25/11/2026** · Reste : 9 jours.

Statuts : `FAIT-TESTÉ` (exécuté réellement, tests verts) · `FAIT-NON-TESTÉ` (écrit, pas exécuté en
conditions réelles) · `SIMULÉ` (fonctionne avec des doublures) · `À FAIRE`.

## Où on en est

- Dépôt initialisé : venv Python 3.11, Git, lint, tests, CI, fichiers de suivi.
- Relais Cloud ⇄ Local écrit et testé **en simulation** (42 tests).
- Aucun module du Hub n'existe encore. `core/` et `modules/` sont vides.
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
| Relais — agent local Aider / OpenCode | P0 | J1 | `FAIT-NON-TESTÉ` | commande construite et testée ; **Aider et OpenCode absents du PATH** sur ce poste, jamais lancés |
| `core/` : contrat de module, bus, daemon | P0 | J2 | `À FAIRE` | |
| Gardiens Inoue (VRAM) et Fuma (stabilité) | P0 | J2 | `À FAIRE` | |
| `core/hardware/gpu_monitor.py` | P0 | J2 | `À FAIRE` | |
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
| `qwen3-coder:30b-a3b-q4_K_M` | installé, 18 Go sur disque | `ollama list` |
| `qwen3-27b:latest` / `qwen3-35b:latest` | 16 Go / 21 Go sur disque, quantification non vérifiée | `ollama list` |

**Écart avec le cahier des charges :** deux GPU visibles (≈ 32 Go), pas trois (48 Go). La seconde
RTX 5060 Ti n'est pas dans cette machine. `config/hardware_profiles.yaml` contient les deux profils.
La VRAM occupée par chaque modèle une fois chargé n'a **pas** encore été mesurée.

## Reste à faire, par priorité

1. **P0 — J2** : `core/module_api.py`, bus, `daemon.py` minimal, Inoue, Fuma, `gpu_monitor.py`.
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
| 3 | Installer Aider dans un venv dédié, puis vérifier | `aider --version` | version affichée |
| 4 | Relais réel, fenêtre courte | `.venv\Scripts\python.exe scripts\relay_orchestrator.py --window-minutes 10 --max-cycles 1` (depuis `cmd.exe`) | à la limite de quota : bascule sur Aider, puis retour ; vérifier `logs\relay.log` et `git log` |
| 5 | Relever le message exact de limite de Claude Code | copier la ligne de `logs\relay.log` | permet d'ajuster `QUOTA_PATTERNS` si besoin |
| 6 | Topologie 3 GPU | `nvidia-smi -L` sur la machine qui porte les 3 cartes | 3 lignes |

## Points attendus de Jérémy

Voir la section « Questions ouvertes » de `AGENT_HANDOFF.md`.
