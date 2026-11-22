# PROJECT_STATUS — AetherTwin (I&F Core)

Dernière mise à jour : **22/11/2026** (J8) · Clôture du concours : **25/11/2026**.

Statuts : `FAIT-TESTÉ` (exécuté réellement, tests verts) · `FAIT-NON-TESTÉ` (écrit, pas exécuté en
conditions réelles) · `SIMULÉ` (fonctionne avec des doublures) · `EN COURS` (entamé, à poursuivre) · `À FAIRE`.

**Après le 25/11 (décision de Jérémy, 22/11)** : relais Claude Code ↔ agent local en réel (usage personnel,
hors concours), topologie 3 GPU (décembre), workflow ComfyUI (à voir ensemble), push GitHub (par Jérémy).
Les documents finaux et le gel J9 attendent sa demande.

## Où on en est

- Dépôt initialisé : venv Python 3.11, Git, lint, tests, CI, fichiers de suivi. **404 tests** au total (22/11) :
  400 passent, 4 sont des tests réels sur GPU, activés par `AETHERTWIN_REAL_OLLAMA=1`.
- Relais Cloud ⇄ Local écrit et testé **en simulation**.
- **J2 terminé** : moniteur GPU, contrat de module, bus, ordonnanceur, gardiens, démon et API locale.
- **J3 terminé** (17/11) : WoW Assistant porté dans `modules/gaming_hud/`, interface `GameAdapter`, trois
  adaptateurs, module du Hub avec bascule Showcase, routeur LLM. Premier module réel du Hub.
- Essai réel de bout en bout réussi : démon → module → données du jeu → modèle local → réponse correcte.
- **J4 terminé** (17/11) : overlay OBS local avec monitoring des GPU, logo, capture de rendu réelle.
- **J5 terminé** (17/11) : `genesis_lab`, base vectorielle, collecte web polie, ingestion nocturne, sources
  citées par le Professeur.
- **J6 terminé** (17/11) : `scantrad`, traduction locale d'une page de manga, essai réel sur la page de test
  (`docs/captures/scantrad_page_test_fr.png`), puis détection refaite pour les vraies pages.
- **J7 terminé** (17/11) : `mangastudio` (HandSegNet et FootSegNet réels sur GPU, nœuds ComfyUI, onglet
  Studio) et `if_game` (onglet Éther).
- **J8 en cours** (17/11, décision de Jérémy : vérifier l'installation et améliorer l'existant avant les
  documents finaux) : installation vérifiée sur un clone vierge (`setup.ps1` 75 s, avec `-Gpu` 169 s, toute la
  suite verte après correction de la carte) ; réponse de l'assistant mot à mot ; jeu d'abord en HD-2D, puis
  (22/11) en vue RPG 16 bits avec Fuma et Inoue en chats et minicarte ; Scantrad en mode manuel ; Inoue tient
  compte de la VRAM mesurée. Licence des modèles de segmentation : poids Apache 2.0, code des dépôts d'origine MIT.
- Décisions de Jérémy : Q4_K_M tant que la VRAM est de 32 Go ; contexte local 32 768 ; pas de push pour l'instant.
- **Lancement simple** (17/11) : `Lancer AetherTwin.bat` à la racine (raccourci « AetherTwin » sur le bureau)
  démarre le Hub et ouvre le tableau de bord sur `http://127.0.0.1:5750/`, en onglets : Accueil (GPU,
  modules, budget VRAM, modèles chargés), Jeu (WoW Assistant, état du jeu, Showcase, overlay OBS), Assistant,
  Professeur, Connaissances, Scantrad (automatique, manuel, glossaire), Studio, Éther, Journal. Bouton
  « Arrêter le Hub ».
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
| `core/module_api.py` (manifeste, événements, classe de base) | P0 | J2 | `FAIT-TESTÉ` | validation et découverte testées ; utilisé par les 5 modules du Hub |
| Inoue — budget VRAM, file d'attente, un seul gros LLM | P0 | J2→J8 | `FAIT-TESTÉ` | branchée sur le routeur LLM (déchargement réel du gros modèle précédent). **22/11** : la place libre tient compte de la VRAM **mesurée** (Jérémy avait 29,8 Go mesurés pour 28,7 de budget) ; alerte « au-dessus du budget » sur l'Accueil. Réel : `qwen3-27b` chargé, 9,6 Go libres annoncés pour 19,0 mesurés |
| Fuma — watchdog, alertes thermiques, mode nocturne | P0 | J2→J5 | `FAIT-TESTÉ` | branché dans le démon : relance un vrai module planté (test de processus), contrôle les températures mesurées des GPU, programme la collecte nocturne de la base de connaissances. **Non observés en réel** : une alerte thermique (cartes restées sous les seuils), une collecte lancée de nuit (« Collecter maintenant » vérifié) |
| `core/bus.py` — bus entre processus sur 127.0.0.1 | P0 | J2 | `FAIT-TESTÉ` | événement échangé avec un vrai second processus ; clé erronée refusée ; messages JSON |
| `core/scheduler.py` — file d'attente GPU unique | P0 | J2 | `SIMULÉ` | testé avec des tâches factices ; créé par le démon mais **aucun module ne lui soumet de tâche** : les modèles passent par le routeur LLM et Inoue |
| `core/daemon.py` + `core/module_runner.py` | P0 | J2 | `FAIT-TESTÉ` | module de test lancé dans un vrai processus séparé, arrêté proprement, relancé par Fuma après un plantage ; déclencheur de processus simulé (faux `obs64.exe`). Démon réel lancé le 16/11 : 2 GPU, budget 28,66 Go |
| `core/api.py` — `/health`, `/modules`, `/events`, `/gpu`, `/ask` | P0 | J2→J8 | `FAIT-TESTÉ` | écoute vérifiée sur 127.0.0.1 ; `/ask` branché sur le routeur LLM depuis J5 ; contrôle de l'hôte et de l'origine (J8) |
| Détection de fenêtres (`pygetwindow`), interface générée à la volée (`widget_schema`) | P0 | J2→J3 | `EN COURS` | en cours, à reprendre avec le port de `ui.py` |
| Correctifs de WoW Assistant v9 (17/11) : fermeture, saisie, presse-papier, clic droit, widgets web, mise en page | P0 | avant J3 | `FAIT-TESTÉ` | 24 tests headless ; fermeture vérifiée avec de vraies fenêtres ; fenêtre web vérifiée activable (Python 3.10 et 3.11). **Testé par Jérémy le 17/11** : frappe dans Open WebUI, sessions conservées, fermeture. Connexion YouTube refusée par Google (limite connue). Bouton « × » d'effacement de clé API ajouté |
| Modèles 3D à la place des silhouettes | P2 | — | `EN COURS` | en cours : voir le changelog du 17/11 |
| Port de WoW Assistant → `modules/gaming_hud/app/` | P0 | J3 | `FAIT-TESTÉ` | code déplacé sans modification ; `python -m modules.gaming_hud` lancé en réel : fenêtre ouverte, données du jeu lues, fermeture par la croix, code 0. Imports « à plat » conservés (décision consignée) |
| Interface `GameAdapter` + adaptateur `wow_retail` | P0 | J3 | `FAIT-TESTÉ` | lecture seule vérifiée (aucun fichier du jeu modifié) ; testé sur un faux dossier de jeu **et** sur les SavedVariables réelles |
| Adaptateur `log_tail` (journal texte + règles YAML) | P0 | J3 | `FAIT-TESTÉ` | fichier qui grandit, ligne incomplète, troncature, règles invalides ; **aucun vrai jeu** branché dessus |
| Adaptateur `screen_ocr` (expérimental) | P0 | J3 | `FAIT-TESTÉ` | test réel avec `qwen2.5vl:7b` sur une **image générée** : 3 valeurs lues sur 3. Jamais essayé sur une vraie capture de jeu |
| Filtre de confidentialité Showcase (`adapters/privacy.py`) | P0 | J3/J4 | `FAIT-TESTÉ` | canaris (compte, e-mail, chemin, clé, or exact, noms) absents de la sortie ; vérifié aussi sur les données réelles |
| Module du Hub `GamingHudModule` + bascule Showcase | P0 | J3/J4 | `FAIT-TESTÉ` | bout en bout dans le démon réel ; **OBS réel testé par Jérémy (17/11)** : ouverture, fermeture, forçage |
| `core/llm_router.py` + `/ask` + API compatible OpenAI | P1 | J5 (avancé) | `FAIT-TESTÉ` | faux Ollama en HTTP, puis **réel** : `qwen3-27b` (16,77 Go) puis `qwen3-coder:30b` (19,69 Go) à `num_ctx` 32 768, un seul en mémoire à la fois. Diffusion mot à mot ajoutée au J8 (voir plus bas) |
| Assistant de l'appli branché sur le Hub | P0 | J3 | `FAIT-TESTÉ` | le `LLMClient` d'origine, inchangé, interroge le Hub (liste des modèles et réponse réelles). Contexte fourni par `GameAdapter` ; mode `hermes.exe` conservé, non testé |
| Overlay OBS `http://127.0.0.1:5757/obs-hud` (page, SSE, monitoring GPU) | P0/P1 | J4 | `FAIT-TESTÉ` | rendu vérifié dans un vrai navigateur (Edge piloté par Playwright), capture dans `docs/captures/obs_hud.png` ; essai réel sur les données du jeu et les 2 GPU ; écoute sur 127.0.0.1 vérifiée. **Vu dans OBS par Jérémy (test 11, 17/11)** |
| Logo I&F Core (couleur + monochrome) | P1 | J4 | `FAIT-TESTÉ` | SVG géométrique écrit à la main, remplaçable ; la variante monochrome est affichée dans l'overlay |
| Tableau de bord du Hub (`/`) + lanceur `.bat` + commandes de module (`/modules/{nom}/command/{cmd}`) | P1 | J5 | `FAIT-TESTÉ` | tests (CSP, refus de chemins hors `core/web/`, réponse rattachée par `request_id`) + **essai réel** : GPU réels affichés, exercice du Professeur corrigé avec explication de `qwen3-27b` |
| Base vectorielle `core/knowledge/store.py` | P1 | J5 | `FAIT-TESTÉ` | SQLite, embedder injectable, licence obligatoire, refus de mélanger deux modèles. `nomic-embed-text` installé par Jérémy : **377 passages vectorisés (test 14, 17/11)** ; sans modèle d'embedding, repli par mots pondérés (idf + titre) |
| Collecte web polie `core/knowledge/fetcher.py` | P1 | J5 | `FAIT-TESTÉ` | https + liste blanche (`wikipedia.org`), robots.txt, 5 s entre deux requêtes, cache 7 j, journal `logs/web_fetch.jsonl`. **Réel** : 18 pages Wikipédia FR collectées, 377 passages, 0 refus |
| Ingestion nocturne + recherche du Professeur | P1 | J5 | `FAIT-TESTÉ` | tâche récurrente de Fuma (chaque nuit), bouton « Collecter maintenant », `/knowledge/search` ; **réel** : correction du Professeur avec sources Wikipédia citées |
| `genesis_lab` : calculs bio, astro, chimie | P1 | J5 | `FAIT-TESTÉ` | code déterministe, comparé à des valeurs de référence (année sidérale, ISS, Sirius, Proxima, masses molaires, volume molaire, pH de l'acide acétique…). Biopython non requis, comparaison croisée non faite |
| `genesis_lab` : Professeur adaptatif | P1 | J5 | `FAIT-TESTÉ` | session guidée scriptée (LLM factice) + **essai réel** avec `qwen3-27b` à deux niveaux : le vocabulaire s'adapte, la valeur calculée par le code est conservée. L'essai a montré que le modèle invente des calculs intermédiaires faux : un garde-fou rejette désormais tout nombre non fourni par le code. Sources Wikipédia citées depuis J5 ; « Bravo » à une mauvaise réponse corrigé (test 12) ; validé par Jérémy (17/11) |
| `genesis_lab` : module du Hub | P1 | J5 | `FAIT-TESTÉ` | calcul demandé sur le bus et rendu par le module dans son processus (démon réel) ; liste blanche d'outils |
| `scantrad` : chaîne complète | P1 | J6 | `FAIT-TESTÉ` | tests (vraie page de test + modèles factices) et **essai réel** : 5 bulles détectées dans l'ordre manga, OCR exact par `qwen2.5vl:7b`, traduction `qwen3-27b`, 23,6 s, VRAM au plus haut 26 153 MiB. Depuis : vraies pages de Jérémy (dont une double page de One-Punch Man, 22/11 : 8 bulles sur 8 dans l'ordre, après correction de l'ordre et de la lecture par colonnes) |
| `scantrad` : module du Hub | P1 | J6 | `FAIT-TESTÉ` | module piloté par le démon (test réel de processus) ; utilisé par Jérémy depuis l'onglet Scantrad. (L'ancien menu du lanceur, avec son « entrée 4 », a été remplacé le 17/11 par le lancement direct du tableau de bord) |
| `mangastudio` : segmentation main/pied | P2 | J7 | `FAIT-TESTÉ` | **réel** : HandSegNet sur RTX 5080, 0,17 s par masque une fois chargé (21,8 s au premier appel), 2,8 Go de VRAM ; simulation GrabCut signalée sans torch ni poids. FootSegNet : chargement vérifié, pas de masque réel essayé |
| `mangastudio` : nœuds ComfyUI | P2 | J7 | `FAIT-TESTÉ` (hors ComfyUI) | chargés seuls et exécutés avec le vrai modèle ; **jamais chargés dans un vrai ComfyUI** |
| `mangastudio` : workflow de continuité | P2 | J7 | `FAIT-NON-TESTÉ` | IP-Adapter + ControlNet + masque des mains ; structure vérifiée, aucune image générée |
| `mangastudio` : onglet Studio | P2 | J7 | `FAIT-TESTÉ` / `FAIT-NON-TESTÉ` | envoi et segmentation réels par l'API ; tracé des boîtes à la souris non essayé |
| Installation (`scripts/setup.ps1`, `-Gpu`, `-Weights`, `-Shortcut`) | P0 | J8 | `FAIT-TESTÉ` | clone vierge : 75 s sans GPU, 169 s avec PyTorch (cache pip chaud) ; suite complète verte ; `-Weights` et `-Shortcut` non rejoués sur le clone |
| Assistant : réponse mot à mot (`/ask/stream`) | P1 | J8 | `FAIT-TESTÉ` | **réel** : premier mot à 16 s chargement compris, ~30 morceaux/s ; l'API compatible OpenAI diffuse aussi (`stream: true`, ligne plus bas). **Vu par Jérémy (test 16)** |
| `scantrad` : correction à la main et réincrustation | P1 | J8 | `FAIT-TESTÉ` | page nettoyée et bulles gardées à côté de la traduction ; tests par l'API ; **essayé par Jérémy (test 17)** |
| `mangastudio` : détection automatique des mains/pieds | P2 | J8 | `FAIT-TESTÉ` | **réel** : `qwen2.5vl:7b` propose 5 boîtes en 2,6 s, HandSegNet en fait 5 masques ; 2 débordent (manteau, cape). Page de manga N&B = hors domaine : les deux modèles n'ont vu que des images SDXL (précision de Jérémy). **Jérémy, 22/11 : marche aussi sur photos, masque parfois trop large — « en cours », à ajuster** |
| Assistant : conversation (historique, Markdown) | P1 | J8 | `FAIT-TESTÉ` | **réel** : la 2e question retrouve le nom et la classe donnés à la 1re (1,8 s) ; listes et gras rendus sans HTML injecté |
| Assistant appuyé sur la base (sources citées) | P1 | J8 | `FAIT-TESTÉ` | **réel** : « un parsec vaut environ 3,26 années-lumière [1] » ; question hors sujet : aucune source jointe. Seuil 0,65 mesuré (couvert 0,70-0,81, hors sujet 0,55-0,61) ; préfixes nomic essayés, sans gain |
| Accueil : décharger un modèle | P1 | J8 | `FAIT-TESTÉ` | bouton par modèle chargé ; **essayé par Jérémy le 22/11** |
| Sécurité de l'API : origine et hôte vérifiés | P0 | J8 | `FAIT-TESTÉ` | une écriture venue d'un autre site (formulaire, `Sec-Fetch-Site: cross-site`, `Origin: null`) ou un hôte non local (DNS rebinding) reçoit 403 ; le tableau de bord continue de fonctionner (vérifié en réel) |
| `scantrad` : chapitre entier | P1 | J8 | `FAIT-TESTÉ` | **réel** dans le navigateur : 2 pages en 42 s, ordre des noms, galerie, correction par page ; a révélé un bogue (envoi sans clic) corrigé |
| `scantrad` : fin de ligne espacée, marge d'OCR blanchie | P1 | J8 | `FAIT-TESTÉ` | « だよ » de la page de test n'était pas effacé ; une première correction a fait lire au modèle le texte d'une bulle voisine sur le dessin (« Ce monde », « Mariage » posés sur l'image) : corrigé, vraie page revenue à 4 bulles justes et 7 faux positifs écartés |
| API compatible OpenAI : `stream: true` (SSE) | P1 | J8 | `FAIT-TESTÉ` | format `chat.completion.chunk` puis `[DONE]` ; **réel** avec `qwen3-27b` par `curl` ; non essayé depuis un client tiers (Open WebUI, WoW Assistant) |
| Professeur : laboratoire FASTA dans le navigateur | P1 | J5/J8 | `FAIT-TESTÉ` | **réel** : exemple GFP, 178 bases, GC 40,449 %, 1 ORF de 53 acides aminés (MASKGEELFTGVV…) |
| Fermeture douce de WoW Assistant | P1 | J8 | `FAIT-TESTÉ` | **réel** : fermée par demande de fenêtre en 2 s, sans forcer ; repli forcé au bout de 6 s |
| Journal du Hub (`logs/hub.log`) | P1 | J8 | `FAIT-TESTÉ` | démarrages, arrêts, erreurs, alertes, applications ; jamais les états du jeu ; 1 Mo × 3 |
| Jeu : ambiance sonore générée | P2 | J8 | `FAIT-NON-TESTÉ` | v1 écoutée par Jérémy le 22/11 (ambiances trop proches, pas de volume). **v2 (22/11 soir)** : 11 ambiances distinctes (vent et oiseaux au jardin, grillons la nuit, ressac à la plage, ruisseau au pont, horloge à la bibliothèque, gouttes et écho dans la grotte…), timbre et motif propres à chacune, curseur de volume retenu par le navigateur. Activée sans erreur sur 7 ambiances ; **pas écoutée** |
| Accueil : budget VRAM d'Inoue | P1 | J8 | `FAIT-TESTÉ` | vérifié sur le Hub de Jérémy (6,39 Go réservés sur 28,66) |
| `if_game` : rendu HD-2D | P2 | J8 | remplacé | remplacé le 22/11 par la vue RPG 16 bits (ligne suivante) |
| `if_game` : vue RPG 16 bits, Fuma et Inoue en chats, minicarte | P2 | J8 | `FAIT-TESTÉ` | demande de Jérémy (style FF6 / Chrono Trigger / Seiken Densetsu, inspiration seulement). Vue de dessus en tuiles, 11 décors (jardin, forêt, verger, lac, plage et phare, pont, bibliothèque, observatoire, grotte, serre, sanctuaire), jour / crépuscule / nuit avec lumières ; Fuma au clavier ou à la souris, Inoue le suit ; sorties de bord, escaliers, objets à ramasser en marchant, stèle d'énigme. **Monde en grille** : nord puis sud ramène au même lieu, minicarte cohérente ; anciennes sauvegardes converties. Vérifié dans le navigateur : 7 décors vus, déplacement, passage vers un lieu inventé par le modèle, puis partie de Jérémy restaurée à l'identique |
| `if_game` : Fuma & Inoue, onglet Éther | P2 | J7 | `FAIT-TESTÉ` | graine reproductible, propositions du modèle validées (ton calme, formes), sauvegarde ; **réel** : lieu inventé par `qwen3-27b` et réplique de Fuma acceptés |
| `scantrad` : mode manuel (zones à la souris, gomme, réincrustation) | P1 | J8 | `FAIT-TESTÉ` | demande de Jérémy (test 17). **Réel** sur sa page dans le navigateur : 2 zones tracées dans l'ordre de lecture, lues par `qwen2.5vl:7b` (96 s à froid, 1 s ensuite), traduites, gomme et annulation, page propre. Un bloc horizontal de 3 lignes était lu « AUCUN » : consigne d'OCR propre au mode manuel. Effacement par la couleur du papier (l'inpainting laissait un fantôme gris) |
| `scantrad` : lecture par colonnes, ordre des doubles pages, mesure par les zones manuelles, enregistrement | P1 | J8 | `FAIT-TESTÉ` | 22/11. Texte vertical découpé en colonnes lues une à une (manuel et automatique) ; double page lue page de droite d'abord, rangées par recouvrement réel ; fusion de bulles bornée. Chaque page faite en manuel sert de vérité de terrain : `python -m modules.scantrad --evaluate` mesure la détection automatique. **Réel** sur la double page de Jérémy : ordre 4/7 → 7/7, 8 bulles sur 8 lues justes en automatique ; le texte automatique peut encore déborder sur le dessin. Boutons « Enregistrer » (page, chapitre, manuel) non cliqués dans un vrai navigateur |
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

- Deux GPU visibles (≈ 32 Go), pas trois (48 Go) : la troisième carte (une seconde RTX 5060 Ti) attend un
  riser, prévue en décembre. `config/hardware_profiles.yaml` contient les deux profils.
- **Aucun modèle Q8_0 n'est installé.** Les trois Qwen sont en Q4_K_M (décision de Jérémy tant que la VRAM est
  de 32 Go).
- VRAM mesurée par modèle chargé : voir le tableau ci-dessus (17/11).
- L'agent local réel de Jérémy est Claude Code via OmniRoute, pas Aider.

## Reste à faire (mis à jour le 22/11)

1. **Sur demande de Jérémy seulement** : documents finaux (README final, `docs/HARDWARE_FIT.md`,
   `docs/DEMO_SCRIPT.md`, `research/overlord_notes.md`), puis gel J9 (branche `concours`, tag, scan de l'historique).
2. **Essais restants côté Jérémy** : tests 9, 10, et ceux de la section suivante encore sans résultat.
3. **En cours, non bloquant** : détection de fenêtres et interface générée depuis `widget_schema()` ; modèles 3D du
   HUD ; `log_tail` et `screen_ocr` sur un vrai jeu ; Studio (masques trop larges) ; jeu Éther (à développer après
   l'analyse de Jérémy).
4. **Après le 25/11** : voir l'encadré en tête de ce fichier.

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
| 7 | Hub complet — **OK (Jérémy, 17/11)** ; à refaire avec les onglets | raccourci **AetherTwin** ; onglet **Jeu** : « Lancer WoW Assistant », puis « Fermer » | la fenêtre de WoW Assistant s'ouvre et se ferme depuis le navigateur ; « Ce que l'assistant sait de ton jeu » affiche ton personnage |
| 8 | Bascule Showcase avec OBS réel — **OK (Jérémy, 17/11)** : ouverture, fermeture, forçage | — | — |
| 15 | Jeu, premier rendu HD-2D (remplacé depuis) — **OK (Jérémy, 22/11)** : pas de saccade ; joué au texte surtout | — | — |
| 16 | Assistant mot à mot — **OK (Jérémy, 22/11)** | — | — |
| 17 | Corriger une traduction — **fonctionne, détection limitée (Jérémy, 22/11)** | — | demande : mode manuel (zones posées à la souris dans l'ordre de lecture, gomme blanche, réincrustation) |
| 18 | Mains automatiques — **en cours d'ajustement (Jérémy, 22/11)** : marche aussi sur photos et images variées, masque parfois trop large | — | à étudier |
| 19 | Ambiance sonore — **entendue (Jérémy, 22/11)** : style original | — | demandes : ambiance propre à chaque type de lieu (plage, forêt, grotte), réglage du volume |
| — | Décharger un modèle — **OK (Jérémy, 22/11)** | — | — |
| 20 | Scantrad, mode manuel — **OK (Jérémy, 22/11)** ; traduction à prendre comme indicative | — | vu sur sa capture : texte minuscule dans les zones étroites, une bulle en colonnes lue dans le désordre → corrigés le 22/11 |
| 21 | Jeu, nouvelle vue — **OK (Jérémy, 22/11)** : déplacement, ramassage, carte | — | Espace ne faisait pas parler Inoue (impossible de lui faire face) → elle suit désormais à distance |
| 22 | Sons par lieu et volume — **OK (Jérémy, 22/11)** | — | — |
| 23 | Alerte VRAM d'Inoue — **OK (Jérémy, 22/11)** : « hors réservations » affiché ; charge répartie sur les deux GPU | — | — |
| 13 | Scantrad sur une de tes pages — 1er essai : bulles ratées, texte non effacé (corrigé le 17/11) ; repris par les tests 17, 20 et 24 | — | — |
| 24 | Scantrad, mode automatique sur une double page + enregistrement | onglet **Scantrad** : ta double page OPM en automatique, puis « Enregistrer cette page traduite » ; en manuel, « Enregistrer l'image » | bulles dans l'ordre (page de droite d'abord), les deux bulles du bas séparées ; l'image arrive dans tes téléchargements sous `<nom>_fr.png`. Le texte peut encore déborder sur le dessin en automatique : c'est là que le mode manuel sert |
| 14 | Recherche par vecteurs — **OK (Jérémy, 17/11)** : 377 passages avec vecteurs | — | — |
| 12 | Professeur — **OK (Jérémy, 17/11)** | — | — |
| 9 | Assistant de l'appli via le Hub | dans WoW Assistant : Paramètres > Assistant IA, Endpoint `http://127.0.0.1:5750`, puis « Charger la liste des modèles » | la liste des modèles d'Ollama s'affiche ; les réponses passent par le Hub |
| 11 | Overlay dans OBS — **OK (Jérémy, 17/11, capture)** | — | — |
| 10 | Tests réels sur GPU — **fait par Claude le 22/11** : tous verts (`qwen3-27b` 16,77 Go en 9,4 s, `qwen3-coder:30b` 19,69 Go en 14,8 s, un seul gros modèle à la fois ; vecteurs `nomic-embed-text` ; `screen_ocr` ; masque HandSegNet) | — | — |
| 6 | Topologie 3 GPU, une fois le riser installé | `.venv\Scripts\python.exe -m core.hardware.gpu_monitor` | `gpu_count: 3`, environ 48 900 MiB |

## Points attendus de Jérémy

Voir la section « Questions ouvertes » de `AGENT_HANDOFF.md`.
