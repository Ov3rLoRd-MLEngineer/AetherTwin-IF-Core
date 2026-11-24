# Rapport — calculatrice `calc_cas` et studio pixel `pixel_studio` (session « calculatrice », 23–24/11/2026)

Pour la session Claude Code qui travaille sur `main` dans `D:\AetherTwin\AetherTwin-IF-Core`. Tout est
**fusionné dans `main`** (avance rapide, rien poussé) : commits `6c8196b` (travail) et `781a9b5` (fusion de ton
commit `76f03f7` dans la branche). La branche `feature/calc-cas` et le worktree `D:\AetherTwin\AetherTwin-calc` sont
supprimés.

## Ce qui a changé et qui te concerne directement

1. **Onglet « Outils » du tableau de bord** (`core/web/dashboard.html`, `calc_cas.js`, `calc_cas.css`) : décision de
   Jérémy (24/11), l'onglet montre **la calculatrice elle-même** (la fenêtre `/static/calc_app.html` dans une
   `iframe` centrée), le bouton « Ouvrir la calculatrice » et une ligne d'état Hermes. Les anciens panneaux
   (saisie, graphes, tableur, agent) sont retirés : les modèles passent par le MCP.
   - **Conflit avec tes sous-onglets** : j'ai gardé `data-subtabs` sur le panneau et une seule section
     `<section data-sub="Calculatrice" class="calc-tool">` ; `setupSubtabs` n'affiche pas de barre sous 2 sections.
     D'autres outils pourront s'ajouter en sous-onglets.
   - **Test modifié** : `tests/core/test_dashboard.py::test_panels_use_subtabs_and_system_assets` exige désormais
     au moins **1** sous-onglet pour `outils` (3 pour les autres panneaux), avec un commentaire.
   - L'`iframe` est chargée au premier affichage de l'onglet (`#outils` ou clic) ; la CSP du Hub l'autorise déjà
     (`frame-src 'self'`).
2. **`modules/dev_launcher/hermes_link.py`** : nouvelle fonction `register_server(exe, name, args, runner)`
   (nom validé `[a-z][a-z0-9_]{1,40}`, `config.yaml` sauvegardé avant) ; `register()` l'appelle pour
   `aethertwin_dev`, comportement inchangé. Nouveau test `test_other_mcp_servers_can_be_registered`.
3. **`tests/gaming_hud/test_profit.py`** : erreur ruff I001 préexistante corrigée (une ligne vide).
4. **Dépendance ajoutée** : `matplotlib==3.10.7` dans `requirements.txt` (déjà installée dans le venv) ;
   `THIRD_PARTY.md` complété (matplotlib et ses dépendances : contourpy, cycler, kiwisolver, fonttools, pyparsing,
   python-dateutil, packaging). `pygame` (déjà présent) sert aussi au mode jeu.
5. **Hermes** : serveur MCP **`aethertwin_calc`** déclaré dans `%LOCALAPPDATA%\hermes\config.yaml`
   (sauvegarde `.bak` horodatée à côté) : commande `D:\AetherTwin\AetherTwin-IF-Core\.venv\Scripts\python.exe`,
   arguments `-I D:\AetherTwin\AetherTwin-IF-Core\modules\calc_cas\mcp_server.py`. `mcp_server.py` se lance
   désormais comme script depuis n'importe quel dossier (la racine du dépôt remplace le dossier du script dans
   `sys.path`). Bouton « Brancher sur Hermes » dans l'onglet Outils (commande `hermes_register`).

## Nouveautés de la calculatrice (`modules/calc_cas/`, `core/web/calc_app.*`, `calc_geo.js`)

- **Résultats en image** (`render.py`) : `sympy.latex()` dessiné par matplotlib mathtext, PNG transparent à
  200 ppp affiché à mi-taille, encre noire inversée en écran sombre ; matrices mises en page cellule par cellule ;
  repli `sympy.pretty(use_unicode=True)` (nouvelle clé `pretty` de `present()`) si mathtext échoue (`cases`…).
  Commande `render` (liste de LaTeX, 50 au plus) ; les images ne sont pas gardées dans `session.json`.
- **Mode jeu** (`games.py`, `games_examples.py`) : `import jeu` → fenêtre pygame dans un processus séparé
  (`python -I games.py <fichier>`, mémoire 768 Mo, même contrôle AST que la console, aucun objet pygame exposé).
  Commandes `game_run`, `game_stop`, `game_status`. Jeux : snake, pong, tetris, labyrinthe_3d (lancer de rayons).
  Correctif du bac à sable au passage : `from module import _x` est maintenant refusé (le nom importé est vérifié,
  pas seulement l'alias).
- **Import / export des programmes** : `.py`, et `.aether` = JSON
  `{format: "aether-programme", version: 1, nom, cree, application, jeu, code}`.
- **Émulateurs externes** (`emulators.py`) : détection d'émulateurs open source installés (mGBA, Mesen, Snes9x,
  BlastEm, simple64, melonDS, DuckStation, PPSSPP, Flycast, Dolphin, Azahar/Lime3DS, PCSX2, RetroArch) ; systèmes
  de la Game Boy à la PS2 (prévu au-delà d'un téléphone type Galaxy S10+) ; ROM prises uniquement dans
  `data/calc_cas/roms` ; `Popen` en liste, processus détaché. **Aucune ROM, aucun BIOS, aucun émulateur fourni.**
  Commandes `emulators`, `emulator_launch`, `roms_open` ; configuration `calc_cas.roms_dir`, `calc_cas.emulators`.
- **Géométrie** : la construction entière est refaite en exact côté moteur (`geometry.figure_measure`, même ordre
  d'intersection que la page) → vraies valeurs irrationnelles des points construits ; transformations (symétries
  centrale et axiale, rotation en degrés, translation) ; point sur objet ; lieu géométrique tracé, et son équation
  exacte par élimination (Gröbner), racines carrées comprises (chaque racine devient une inconnue w, w² = radicande ;
  ajouté le 24/11 après le premier rapport : milieu d'une corde par C → cercle de diamètre [AC]).

## Tests et vérifications

- `ruff check .` : propre. **Suite complète sur `main` : 945 réussis, 4 ignorés** (tests réels sur GPU),
  215 s.
- Nouveaux fichiers de tests : `tests/calc_cas/test_render.py`, `test_games.py`, `test_emulators.py` ; ajouts dans
  `test_geometry.py`, `test_module.py`, `test_app.py`, `tests/dev_launcher/test_dev_launcher.py`.
- Essais réels (Hub de test sur le port 5760, celui de Jérémy sur 5750 non touché) : onglet Outils (cadre,
  « Hermes : branché ») ; Calculs en image (intégrale, matrice inverse, solutions ; morceaux → texte ; écran sombre) ;
  géométrie (lieu → `2x² − 2x + 2y² − 6y + 3 = 0`, rotation, point sur objet glissé) ; Pong ouvert dans sa fenêtre
  puis arrêté ; dialogue des émulateurs (ROM homebrew factice listée) ; import / export.
- **Hermes réel** : `hermes mcp test aethertwin_calc` → connecté, 3 outils ; `hermes chat --oneshot -q …` → appel de
  `mcp__aethertwin_calc__cas_compute`, réponse « e − 2 » pour ∫₀¹ x²eˣ dx, en 31 s.

## Émulateur : lancement réel (24/11, après le premier rapport)

- mGBA 0.10.5 (GPL, archive portable officielle) et µCity (jeu Game Boy Color libre, GPL-3) téléchargés hors du
  dépôt avec l'accord de Jérémy ; `emulator_launch {emulator: mgba, rom: homebrew/ucity.gbc}` → fenêtre
  « mGBA - MICROCITY (60 fps) », puis fermée. Rien de téléchargé n'est dans le dépôt. Plus rien n'est en cours
  sur `calc_cas`.

## Studio pixel art `pixel_studio` (24/11, commit `ad61b2e`, fusionné dans `main`)

Proposé à Jérémy avec d'autres outils ; il a retenu le studio pixel (jeu façon RPG 16 bits). Branche
`feature/pixel-studio` et worktree `D:\AetherTwin\AetherTwin-pixel` supprimés après la fusion.

1. **Nouveau module** `modules/pixel_studio/` (README détaillé) : projets `.aether-pixel` dans
   `data/pixel_studio/projects`, exports dans `data/pixel_studio/exports`, sprites pour les jeux dans
   `data/pixel_studio/sprites` ; configuration facultative `pixel_studio.data_dir`. Fenêtre de bureau « Studio
   pixel Æther » (bouton « Lancer » / « Ouvrir le studio »).
2. **Tableau de bord, onglet Outils** : deux sous-onglets désormais, « Calculatrice » et « Studio pixel »
   (`core/web/pixel_tool.js` et `.css`, chargés dans `dashboard.html`). **Test modifié** :
   `tests/core/test_dashboard.py` exige au moins **2** sous-onglets pour `outils`.
3. **Fichiers partagés touchés** : `modules/calc_cas/app.py` (`browser_args` prend une taille de fenêtre, défaut
   inchangé), `modules/calc_cas/games.py` (`jeu.sprite`, `jeu.carte`, `jeu.bloque` ; argument facultatif « dossier
   des sprites »), `modules/calc_cas/module.py` (`pixel_sprites_dir()` passé au processus du jeu),
   `requirements.txt` et `THIRD_PARTY.md` (commentaire de Pillow seulement, aucune dépendance nouvelle).
4. **Hermes** : serveur MCP **`aethertwin_pixel`** déclaré (sauvegarde `.bak` horodatée), 6 outils ; essai réel :
   Hermes a créé un sprite 5×5 correct en 66 s.
5. Tests : `tests/pixel_studio/` (15) ; suite complète **959 réussis, 5 ignorés** ; ruff propre.

## Voix locale et studio audio `voice` (24/11, fusionné dans `main`)

Demandé par Jérémy. Il veut :
- un synthé et séquenceur avec un modulateur vocal en direct ;
- des réponses parlées et le micro dans le Hub, WoW Assistant et ses outils IA, avec des voix modifiables ;
- MCP ;
- VB-Cable, avec seulement le lien officiel et une vérification.

La branche `feature/voice` et le worktree `D:\AetherTwin\AetherTwin-voice` ont été supprimés après la fusion.

1. **Nouveau module** `modules/voice/` (README détaillé) :
   - Whisper local, Piper, voix de Windows en secours ;
   - profils dans `data/voice/profiles.json` ; Piper et ses voix dans `data/voice/piper` (bouton « Installer ») ;
   - fenêtre « Studio audio Æther » ;
   - serveur MCP **`aethertwin_voice`** (5 outils), déclaré chez Hermes (sauvegarde `.bak`) ; essai réel : Hermes a
     parlé avec le profil « narrateur ».
2. **API du Hub** (`core/api.py`) :
   - `/v1/audio/speech` et `/v1/audio/transcriptions`, compatibles OpenAI ; le module est lancé à la demande ;
   - `/voice/settings` et `/voice/profiles`.
3. **Tableau de bord** :
   - onglet Assistant : bouton 🎙, case « lire les réponses à voix haute », voix, volume, Silence (`voice.js`,
     `voice.css`) ;
   - `dashboard.js` émet les événements `aether-ask` et `aether-reply` ;
   - onglet Outils : troisième sous-onglet « Studio audio » (`audio_tool.js` ; page `audio_app.*` et
     `audio_worklet.js`).
4. **WoW Assistant** (`modules/gaming_hud/app/`) :
   - voix « Voix du Hub » (`voice.tts.hub_url`, `voice.tts.hub_voice`), dans `voice.py`, `settings.py` et `ui.py` ;
   - 5 chaînes anglaises dans `i18n_en.json`.
5. **À savoir :** `tests/gaming_hud/test_routine.py::test_store_keeps_alts_tasks_and_unchecks_them_at_reset` échoue
   aussi sans ces changements. Il dépend du jour (mardi, jour de remise à zéro) et est à corriger à part.
6. Tests : `tests/voice/` (12) ; suite complète **969 réussis, 5 ignorés** (le test daté ci-dessus mis de côté) ;
   ruff propre.

## Rappels

- Rien n'a été poussé. Les documents finaux gelés (README final, HARDWARE_FIT, DEMO_SCRIPT, overlord_notes) n'ont
  pas été touchés.
- `ARCHITECTURE_MAP.md` régénéré après la fusion ; `PROJECT_STATUS.md` (lignes `calc_cas`) et
  `logs/CHANGELOG_DEV.md` (entrée du 24/11) à jour.
