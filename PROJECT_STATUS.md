# PROJECT_STATUS — AetherTwin (I&F Core)

Dernière mise à jour : **16/11/2026** (J0–J1) · Clôture du concours : **25/11/2026** · Reste : 9 jours.

Statuts : `FAIT-TESTÉ` (exécuté réellement, tests verts) · `FAIT-NON-TESTÉ` (écrit, pas exécuté en
conditions réelles) · `SIMULÉ` (fonctionne avec des doublures) · `À FAIRE`.

## Où on en est

- Dépôt initialisé : venv Python 3.11, Git, lint, tests, CI, fichiers de suivi. **270 tests** au total :
  268 passent partout, 2 sont des tests réels sur GPU, activés par `AETHERTWIN_REAL_OLLAMA=1`.
- Relais Cloud ⇄ Local écrit et testé **en simulation**.
- **J2 terminé** : moniteur GPU, contrat de module, bus, ordonnanceur, gardiens, démon et API locale.
- **J3 terminé** (17/11) : WoW Assistant porté dans `modules/gaming_hud/`, interface `GameAdapter`, trois
  adaptateurs, module du Hub avec bascule Showcase, routeur LLM. Premier module réel du Hub.
- Essai réel de bout en bout réussi : démon → module → données du jeu → modèle local → réponse correcte.
- **J4 terminé** (17/11) : overlay OBS local avec monitoring des GPU, logo, capture de rendu réelle.
- **J5 terminé** (17/11) : `genesis_lab`, base vectorielle, collecte web polie, ingestion nocturne, sources
  citées par le Professeur.
- **J6 terminé** (17/11) : `scantrad`, traduction locale d'une page de manga, essai réel sur la page de test
  (`docs/captures/scantrad_page_test_fr.png`). Prochaine étape : J7 (`mangastudio`, `if_game`).
- Décisions de Jérémy : Q4_K_M tant que la VRAM est de 32 Go ; contexte local 32 768 ; pas de push pour l'instant.
- **Lancement simple** (17/11) : `Lancer AetherTwin.bat` à la racine (raccourci « AetherTwin » sur le bureau)
  ouvre un tableau de bord local sur `http://127.0.0.1:5750/` : GPU, modules, assistant, Professeur.
- Le code de WoW Assistant est dans `modules/gaming_hud/app/`.

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
| Port de WoW Assistant → `modules/gaming_hud/app/` | P0 | J3 | `FAIT-TESTÉ` | code déplacé sans modification ; `python -m modules.gaming_hud` lancé en réel : fenêtre ouverte, données du jeu lues, fermeture par la croix, code 0. Imports « à plat » conservés (décision consignée) |
| Interface `GameAdapter` + adaptateur `wow_retail` | P0 | J3 | `FAIT-TESTÉ` | lecture seule vérifiée (aucun fichier du jeu modifié) ; testé sur un faux dossier de jeu **et** sur les SavedVariables réelles |
| Adaptateur `log_tail` (journal texte + règles YAML) | P0 | J3 | `FAIT-TESTÉ` | fichier qui grandit, ligne incomplète, troncature, règles invalides ; **aucun vrai jeu** branché dessus |
| Adaptateur `screen_ocr` (expérimental) | P0 | J3 | `FAIT-TESTÉ` | test réel avec `qwen2.5vl:7b` sur une **image générée** : 3 valeurs lues sur 3. Jamais essayé sur une vraie capture de jeu |
| Filtre de confidentialité Showcase (`adapters/privacy.py`) | P0 | J3/J4 | `FAIT-TESTÉ` | canaris (compte, e-mail, chemin, clé, or exact, noms) absents de la sortie ; vérifié aussi sur les données réelles |
| Module du Hub `GamingHudModule` + bascule Showcase | P0 | J3/J4 | `FAIT-TESTÉ` | bout en bout dans le démon réel ; le logiciel de diffusion est **simulé** par un faux processus (OBS réel non testé) |
| `core/llm_router.py` + `/ask` + API compatible OpenAI | P1 | J5 (avancé) | `FAIT-TESTÉ` | faux Ollama en HTTP, puis **réel** : `qwen3-27b` (16,77 Go) puis `qwen3-coder:30b` (19,69 Go) à `num_ctx` 32 768, un seul en mémoire à la fois. Pas de diffusion mot à mot |
| Assistant de l'appli branché sur le Hub | P0 | J3 | `FAIT-TESTÉ` | le `LLMClient` d'origine, inchangé, interroge le Hub (liste des modèles et réponse réelles). Contexte fourni par `GameAdapter` ; mode `hermes.exe` conservé, non testé |
| Overlay OBS `http://127.0.0.1:5757/obs-hud` (page, SSE, monitoring GPU) | P0/P1 | J4 | `FAIT-TESTÉ` | rendu vérifié dans un vrai navigateur (Edge piloté par Playwright), capture dans `docs/captures/obs_hud.png` ; essai réel sur les données du jeu et les 2 GPU ; écoute sur 127.0.0.1 vérifiée. **Non testé dans OBS lui-même** |
| Logo I&F Core (couleur + monochrome) | P1 | J4 | `FAIT-TESTÉ` | SVG géométrique écrit à la main, remplaçable ; la variante monochrome est affichée dans l'overlay |
| Tableau de bord du Hub (`/`) + lanceur `.bat` + commandes de module (`/modules/{nom}/command/{cmd}`) | P1 | J5 | `FAIT-TESTÉ` | tests (CSP, refus de chemins hors `core/web/`, réponse rattachée par `request_id`) + **essai réel** : GPU réels affichés, exercice du Professeur corrigé avec explication de `qwen3-27b` |
| Base vectorielle `core/knowledge/store.py` | P1 | J5 | `FAIT-TESTÉ` | SQLite, embedder injectable, licence obligatoire, refus de mélanger deux modèles. Vecteurs testés avec un faux embedder seulement : **aucun modèle d'embedding installé** (`ollama pull nomic-embed-text`). En réel : mode dégradé par mots pondérés (idf + titre), pertinent sur les 5 sujets essayés |
| Collecte web polie `core/knowledge/fetcher.py` | P1 | J5 | `FAIT-TESTÉ` | https + liste blanche (`wikipedia.org`), robots.txt, 5 s entre deux requêtes, cache 7 j, journal `logs/web_fetch.jsonl`. **Réel** : 18 pages Wikipédia FR collectées, 377 passages, 0 refus |
| Ingestion nocturne + recherche du Professeur | P1 | J5 | `FAIT-TESTÉ` | tâche récurrente de Fuma (chaque nuit), bouton « Collecter maintenant », `/knowledge/search` ; **réel** : correction du Professeur avec sources Wikipédia citées |
| `genesis_lab` : calculs bio, astro, chimie | P1 | J5 | `FAIT-TESTÉ` | code déterministe, comparé à des valeurs de référence (année sidérale, ISS, Sirius, Proxima, masses molaires, volume molaire, pH de l'acide acétique…). Biopython non requis, comparaison croisée non faite |
| `genesis_lab` : Professeur adaptatif | P1 | J5 | `FAIT-TESTÉ` | session guidée scriptée (LLM factice) + **essai réel** avec `qwen3-27b` à deux niveaux : le vocabulaire s'adapte, la valeur calculée par le code est conservée. L'essai a montré que le modèle invente des calculs intermédiaires faux : un garde-fou rejette désormais tout nombre non fourni par le code. Essai réel limité à un exercice. Sources : branchement prévu, base vectorielle non faite |
| `genesis_lab` : module du Hub | P1 | J5 | `FAIT-TESTÉ` | calcul demandé sur le bus et rendu par le module dans son processus (démon réel) ; liste blanche d'outils |
| `scantrad` : chaîne complète | P1 | J6 | `FAIT-TESTÉ` | tests (vraie page de test + modèles factices) et **essai réel** : 5 bulles détectées dans l'ordre manga, OCR exact par `qwen2.5vl:7b`, traduction `qwen3-27b`, 23,6 s, VRAM au plus haut 26 153 MiB. Une seule page, synthétique : vraie page scannée non essayée |
| `scantrad` : module du Hub + entrée du lanceur | P1 | J6 | `FAIT-TESTÉ` / `FAIT-NON-TESTÉ` | module piloté par le démon (test réel de processus, sans modèle) ; l'entrée 4 du lanceur n'a pas été jouée de bout en bout |
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
| VRAM `qwen3-27b` Q4_K_M, `num_ctx` 32 768 | **16,77 Gio** ; première réponse en 10,9 s | `/api/ps` d'Ollama, 17/11 |
| VRAM `qwen3-coder:30b` Q4_K_M, `num_ctx` 32 768 | **19,69 Gio** ; première réponse en 14,0 s | `/api/ps` d'Ollama, 17/11 |
| VRAM `qwen2.5vl:7b`, `num_ctx` 4 096 | 6 464 MiB sur la RTX 5060 Ti ; lecture d'image en 16,7 s à froid | `nvidia-smi`, 17/11 |

Constat utile pour `docs/HARDWARE_FIT.md` : les deux gros modèles dépassent déjà, en Q4 et à 32 768 de
contexte, la VRAM d'une seule carte de 16 Go. Ollama les répartit donc sur les deux GPU.

**Écarts avec le cahier des charges :**

- Deux GPU visibles (≈ 32 Go), pas trois (48 Go) : la seconde RTX 5060 Ti attend un riser.
  `config/hardware_profiles.yaml` contient les deux profils.
- **Aucun modèle Q8_0 n'est installé.** Les trois Qwen sont en Q4_K_M. Le profil « qualité » reste à définir.
- La VRAM occupée par chaque modèle une fois chargé n'a **pas** encore été mesurée.
- L'agent local réel de Jérémy est Claude Code via OmniRoute, pas Aider.

## Reste à faire, par priorité

1. **Restes du J2** : détection de fenêtres, interface générée à la volée depuis `widget_schema()`.
2. **Reste du J4** : essai dans OBS réel (test n° 11 ci-dessous), à faire par Jérémy.
3. **Restes du J3** : essayer `log_tail` et `screen_ocr` sur un vrai jeu ; diffusion mot à mot dans l'API.
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
| 7 | Hub complet | raccourci **AetherTwin** du bureau, choix 2 ; le tableau de bord s'ouvre sur `http://127.0.0.1:5750/` | GPU, modules `gaming_hud` et `genesis_lab` « actif » ; lien « Derniers événements » : un `module.gaming_hud.state` avec ton personnage |
| 8 | Bascule Showcase avec OBS réel | Hub lancé (choix 2), démarrer OBS, rouvrir « Derniers événements » | `module.gaming_hud.showcase` `{"on": true}`, puis un état sans chemin ni compte, or arrondi |
| 13 | Scantrad sur une de tes pages | Hub lancé ; raccourci **AetherTwin**, choix 4, glisser l'image dans la fenêtre | image `_fr.png` à côté de l'original ; note les bulles ratées (vraie page scannée jamais essayée) |
| 14 | Recherche par vecteurs | `ollama pull nomic-embed-text`, relancer le Hub, « Collecter maintenant » | ligne Connaissances : « avec vecteurs (nomic-embed-text) » |
| 12 | Professeur | tableau de bord, section Professeur : « Nouvel exercice », répondre, « Corriger » | correction, explication rédigée par le modèle local (10 à 40 s au premier appel), niveau qui évolue |
| 9 | Assistant de l'appli via le Hub | dans WoW Assistant : Paramètres > Assistant IA, Endpoint `http://127.0.0.1:5750`, puis « Charger la liste des modèles » | la liste des modèles d'Ollama s'affiche ; les réponses passent par le Hub |
| 11 | Overlay dans OBS | Hub lancé et `gaming_hud` actif ; dans OBS : Sources > + > Navigateur, URL `http://127.0.0.1:5757/obs-hud`, largeur 420, hauteur 600 | l'overlay apparaît sur fond transparent, les jauges GPU bougent, aucun chemin ni nom de compte visible |
| 10 | Tests réels sur GPU | `set AETHERTWIN_REAL_OLLAMA=1` puis `.venv\Scripts\python.exe -m pytest -k real -s` | 2 tests réussis, VRAM affichée |
| 6 | Topologie 3 GPU, une fois le riser installé | `.venv\Scripts\python.exe -m core.hardware.gpu_monitor` | `gpu_count: 3`, environ 48 900 MiB |

## Points attendus de Jérémy

Voir la section « Questions ouvertes » de `AGENT_HANDOFF.md`.
