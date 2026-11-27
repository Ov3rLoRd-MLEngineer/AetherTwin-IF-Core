# Revue « comme un juge » — AetherTwin (I&F Core)

Revue faite le 26/11/2026 sur la branche `main` (commit `0ddbae4`), poste réel du projet (Windows 10 Pro
10.0.19045, RTX 5080 16 Go + RTX 5060 Ti 16 Go, 32 Go de RAM, Ollama). Catégorie évaluée : Advanced / High-End.
Le tag soumis `v0.1.0-concours` (`395c74b`) n'a pas été touché ; `git diff v0.1.0-concours..main` ne contient que
des documents, la CI et un correctif de nom de fichier (`modules/dev_launcher/launch.py`).

Aucun code ni document existant n'a été modifié pendant cette revue. Les scripts de mesure ont tourné hors du
dépôt ; leur contenu utile est recopié en annexe.

---

## 1. Synthèse

- **Verdict :** projet solide et vérifiable, au-dessus de la moyenne d'un concours, desservi par sa largeur et
  par quelques contradictions de documents.
- **Note totale : 74 / 100** (marge ± 5), proche de l'estimation externe (72 à 74). Le désaccord porte sur la
  répartition des notes, pas sur le total.
- **Plus grande force :** la reproductibilité est réelle. Un clone neuf depuis GitHub, `setup.ps1` puis `pytest`
  donnent 1 120 tests verts en moins de 6 minutes au total, sans aucune intervention.
- **Thèse centrale prouvée pour la première fois :** quand un autre programme tient 12 Gio de VRAM, Ollama seul
  plante (deux erreurs 500 « out of memory » en 3 à 5 s). Avec le Hub, Inoue met la demande en file en 0,16 s,
  avec une raison claire, puis la sert sans erreur une fois la place libérée (§ 3.6).
- **Plus grande faiblesse :** la dispersion. Consoles 8 et 16 bits, émulateurs, studios pixel et audio, chimie :
  tout cela dilue un message qui tient en une phrase. Ces modules portent même des risques propres (noms de
  consoles commerciales dans des noms de fichiers et dans `PROJECT_STATUS.md`).
- **Deuxième faiblesse :** les documents se contredisent sur le relais Cloud ⇄ Local (« simulation » ou « validé
  en réel »), sur le nombre de tests, et `AGENT_HANDOFF.md` est figé au 22/11.
- **Un risque visible :** la CI du tag soumis est rouge sur GitHub. Le workflow du tag lançait Ubuntu et Windows,
  et les deux ont échoué. La CI de `main` est verte.

## 2. Notes par critère

| Critère | Poids | Externe | Revue | Pondéré |
|---|---|---|---|---|
| Pertinence Agentic / Local AI | 30 % | 7,5 à 8 | **7,5** | 22,5 |
| Faisabilité, implémentation, reproductibilité | 30 % | 7 | **7,5** | 22,5 |
| Originalité et potentiel | 20 % | 7,5 | **7,5** | 15 |
| Adéquation hardware et clarté | 20 % | 6,5 | **7** | 14 |
| **Total** | | ≈ 72 à 74 | | **74** |

**Pertinence, 7,5.**
- Le problème est concret, et Inoue fait bien plus qu'un décor.
  - Il compte la VRAM **mesurée** des cartes, en plus de ses propres attributions (`core/guardians/inoue.py:75-84`,
    `available_gb = budget − max(attribué, mesuré)`).
  - Les modules déclarent leur besoin (`vram_min_gb` / `vram_comfort_gb`, `core/module_api.py:42-43`), contrôlé
    au démarrage (`core/daemon.py:170`) et par l'ordonnanceur (`core/scheduler.py:60`).
  - Il impose un seul gros modèle à la fois, avec déchargement réel (`keep_alive: 0`) avant le chargement suivant
    (`core/llm_router.py:207-212`).
  - Il garde 10 % de marge (`SAFETY_MARGIN`, ligne 24).
  - Ce qu'il fait de plus qu'Ollama est maintenant **démontré par une mesure** (§ 3.6).
- *Désaccord avec l'estimation externe :* une note de 8 suppose une thèse lisible du premier coup. Or le README
  met sur le même plan des consoles émulées, un tableur et un labo de chimie.
- *Limite réelle :* Inoue raisonne sur un budget **global** (somme des deux cartes), sans affectation par carte.
  Le placement sur les cartes reste celui d'Ollama. La documentation ne dit pas le contraire, mais un juge qui
  lit « arbitre de VRAM » peut l'attendre.

**Implémentation, 7,5.**
- Les résultats mesurés pendant cette revue :
  - 1 122 tests verts et 4 sautés sur le dépôt ;
  - 1 120 verts et 6 sautés sur une installation propre ;
  - `ruff` propre ;
  - CI Windows verte sur `main` ;
  - `127.0.0.1` partout ;
  - bac à sable Python sérieux (`modules/calc_cas/sandbox.py`, liste blanche, processus séparé et borné) ;
  - aucun secret dans l'historique.
- *Désaccord avec l'estimation externe :* elle dit « reproductibilité non démontrée ». Elle l'est maintenant,
  depuis GitHub, sur ce poste (§ 3.2). Elle ne l'est pas encore sur une machine vierge sous Windows 11 (§ 7).
- Ce qui retient la note :
  - CI du tag rouge ;
  - suite fragile quand la mémoire vive sature (§ 3.1) ;
  - profondeur inégale : `gaming_hud` fait 17 000 lignes, `circuit_lab` 198 lignes de Python pour plus de 5 000
    de JavaScript ;
  - documents en partie périmés.

**Originalité, 7,5.** Je confirme l'estimation externe.
- Fuma est un vrai composant (`core/guardians/fuma.py`) : watchdog avec délai croissant et mise au repos,
  alertes thermiques, file de tâches de nuit, horloge injectée pour les tests.
- La recherche web (§ 3.10) trouve des outils de libération de VRAM **à l'intérieur** de ComfyUI et des scripts
  maison. Elle ne trouve pas de hub qui arbitre la VRAM entre modules hétérogènes. Cette recherche repose sur des
  extraits de résultats, donc reste « partiellement vérifié ».
- Le relais de développement Cloud ⇄ Local et la vidéo produite par un agent via MCP sont des arguments originaux,
  mais le README ne les met pas en valeur.

**Hardware et clarté, 7.**
- *Désaccord avec l'estimation externe :* le tableau de mesures existe déjà (`docs/HARDWARE_FIT.md` § 2, dates et
  sources). Il lui manque les jetons/s des modèles principaux, mesurés ici (§ 3.7).
- 32 Go = 16 + 16 : le README, `HARDWARE_FIT.md`, la candidature et la voix off de la vidéo concordent.
- Ce qui retient la note :
  - un README de 277 lignes ;
  - une « Démo en cinq minutes » placée **après** l'installation ;
  - aucun lien vers la vidéo dans le README ;
  - le fait que la vidéo ait été tournée et montée par un agent via MCP n'est dit que dans `docs/DEMO_SCRIPT.md`
    et `PROJECT_STATUS.md`.

## 3. Résultats des vérifications

### 3.1 Tests et lint

| Exécution | Résultat | Durée |
|---|---|---|
| `pytest` sur `main`, poste seul | **1 122 réussis, 4 sautés, 0 échec**, code 0 | 3 min 57 |
| `pytest` sur l'installation propre (§ 3.2) | **1 120 réussis, 6 sautés, 0 échec**, code 0 | 3 min 46 |
| `ruff check .` | « All checks passed! », code 0 | — |
| CI GitHub, `main` (`f961442`) | réussie (Windows) | — |
| CI GitHub, tag `395c74b` | **échec** (workflow d'alors : Ubuntu + Windows) | — |

Écarts avec les chiffres annoncés :
- README ligne 242 : « 1 102 réussis, 5 sautés » au 25/11.
- `PROJECT_STATUS.md` ligne 14 : « 1 118 tests ».
- `AGENT_HANDOFF.md` lignes 17 et 36 : « 404 » puis « 268 ».
- Le total réel est de 1 126 sur `main`.

**Fragilité observée.** Un premier passage lancé en même temps qu'un second `pytest` et que des chargements de
modèles de 17 à 20 Go a saturé les 32 Go de RAM.
- Sur `main`, 4 échecs : `scantrad/test_manual`, `scantrad/test_scantrad_module`, et deux dans
  `voice/test_convert`.
- Les erreurs : « fichier de pagination insuffisant » au chargement de `cublas64_12.dll`, allocations OpenBLAS et
  ONNX Runtime refusées.
- Sur l'installation propre, un plantage « access violation » dans
  `tests/core/test_translate.py::test_image_is_read_by_the_vision_model_after_shrinking`.
- Relancées seules, les deux suites sont vertes. Ce n'est pas un bug fonctionnel, mais un juge qui lance les
  tests avec Ollama chargé sur une machine à 32 Go peut tomber dessus.

### 3.2 Installation depuis le README seul

Procédure suivie : « Depuis le dépôt », dans un dossier temporaire neuf, sans l'option `-Shortcut` (pour ne pas
toucher au bureau).

| Étape | Résultat |
|---|---|
| `git clone https://github.com/Ov3rLoRd-MLEngineer/AetherTwin-IF-Core` | 1,4 s |
| `scripts\setup.ps1` (venv Python 3.11, dépendances, config) | code 0, 1 min 53 |
| `pytest` | 1 120 réussis, 6 sautés |
| `ollama pull …` | non refait : modèles déjà présents sur le poste |
| `python -m core.daemon --open` | non refait sur la copie : le Hub tourne déjà sur ce poste |

- Aucune connaissance non documentée n'a été nécessaire.
- Limites de l'essai : même machine (Python 3.11, Git et pilotes déjà installés), Windows 10, et options `-Gpu`,
  `-Weights` et `-Voice` non essayées.
- Les deux tests sautés en plus de ceux du dépôt correspondent à l'absence de PyTorch dans l'installation
  minimale.
- **Machine vierge sous Windows 11 : non vérifié** (§ 7).

### 3.3 Statuts déclarés contre réalité

- **Décompte des statuts dans `PROJECT_STATUS.md` :** 118 `FAIT-TESTÉ`, 12 `FAIT-NON-TESTÉ`, 4 `SIMULÉ`,
  11 `EN COURS`, 3 `À FAIRE`.
- **Contrôle par sondage :** chaque module a du code et des tests. Les « essais réels » cités pour Inoue, le
  routeur et `calc_cas` sont cohérents avec le code lu.

Taille et tests par module (lignes de Python, fichiers et tests) :

| Module | Python | Tests | Remarque |
|---|---|---|---|
| `gaming_hud` | 16 981 | 185 | application WoW Assistant reprise, la plus grosse brique |
| `calc_cas` | 3 971 | 121 | outils exacts, MCP, bac à sable : cœur de la thèse « outils » |
| `voice` | 3 454 | 18 | peu de tests pour la taille |
| `genesis_lab` | 2 504 | 54 | Professeur |
| `scantrad` | 1 750 | 38 | relais vision → langue dans la VRAM |
| `data_lab` | 1 570 | 16 | peu de tests pour la taille |
| `dev_launcher` | 1 485 | 26 | relais, Claude Code local |
| `pixel_studio` | 933 | 15 | + 1 532 lignes de JS |
| `chem_lab` | 855 | 14 | |
| `mangastudio` | 486 | 10 | |
| `if_game` | 483 | 15 | + 1 404 lignes de JS (`ether_scene.js`) |
| `artcraft` | 396 | 13 | intégration d'une suite externe |
| `circuit_lab` | 198 | 4 | logique en JS (~5 000 lignes : `c16_*`, `nes_*`, `mcu_*`), testée par Node via pytest |
| `core` | — | 147 | démon, gardiens, routeur, API |

Écarts trouvés :
1. **Relais Cloud ⇄ Local : sous-déclaration et sur-déclaration dans le même fichier.**
   - Ce qui dit « simulation » ou « non testé » :
     - `PROJECT_STATUS.md` l.19 : « testé **en simulation** » ;
     - l.55-56 : `SIMULÉ` ;
     - l.58 : « le format exact du message de quota de Claude Code n'a pas été observé » ;
     - README l.255 : « testé en simulation seulement » ;
     - voix off de la vidéo : « Ce relais est testé en simulation ».
   - Ce qui dit « validé en réel » : l.338-339, « Relais réel, fenêtre courte… bascule sur l'agent local, puis
     retour » et « Relever le message exact… », tous deux « ✅ validé (Jérémy, 25/11) ».
   - **Tranché le 26/11 (§ 8) :** la bascule a eu lieu en réel le 25/11. Le README l.30-31 est donc exact ; ce
     sont les mentions « simulation » qui étaient en retard (corrigées sur `main` le 26/11).
2. **`AGENT_HANDOFF.md` est périmé** (« mis à jour le 22/11 », 404 tests). Or il est censé être le premier fichier
   lu par un agent local.
3. **README l.256 :** « La CI GitHub sous Ubuntu : 10 tests propres à Windows… » est exact pour le portage, mais
   ne dit pas que la CI de `main` tourne désormais sous Windows seulement et qu'elle est verte.

### 3.4 Cohérence des documents

- **Liens relatifs :** README, `PROJECT_STATUS.md`, `docs/CANDIDATURE.md`, `docs/RELEASE.md` et
  `AGENT_HANDOFF.md`, tous vérifiés. Aucun lien mort.
- **Licences :** `LICENSE` (Apache 2.0), `NOTICE` et `THIRD_PARTY.md` sont présents.
- **Chiffres périmés :** voir § 3.1 et § 3.3.
- **« Windows 10 » dans l'en-tête du Hub :** l'affichage est **exact pour ce poste**. Le poste est un vrai
  Windows 10 :
  - `platform.release()` → `10` ;
  - `platform.version()` → `10.0.19045` ;
  - `sys.getwindowsversion().build` → `19045` ;
  - même valeur dans `docs/HARDWARE_FIT.md` l.11.
- **Le code a pourtant un défaut latent** : `core/daemon.py:115` construit le nom avec
  `f"{platform.system()} {platform.release()}"`. Sous Python 3.11, `platform.release()` renvoie « 10 » aussi sous
  Windows 11, ce qui est connu et corrigé dans les versions récentes de Python ; **non vérifié ici**, faute de
  machine Windows 11. Il faudrait se fonder sur le numéro de build (≥ 22000 → Windows 11), comme le fait déjà
  `setup.ps1` avec `Win32_OperatingSystem.Caption`.
- **Contradiction sur Windows 11 :** le projet ne contient **aucune trace** d'un essai sous Windows 11.
  `PROJECT_STATUS.md` l.143 parle d'« une autre partition Windows » sans version, et le README l.240 dit
  « Vérifié (Windows 10, Python 3.11) ». Pour l'instant, la mention « vérifié sous Windows 11 » n'est pas étayée.
- **Vidéo :** le README ne donne ni lien ni mention du fait qu'elle a été produite par un agent. `DEMO_SCRIPT.md`
  § « Montage réalisé » le dit.

### 3.5 Sécurité et secrets

**Historique Git complet** (`git log --all -p`, 8,5 Mo), aucune correspondance pour :
- les clés Anthropic, GitHub (`ghp_`, `github_pat_`), AWS, Hugging Face, Slack et Google ;
- les clés privées PEM ;
- les mots de passe en clair ;
- l'adresse e-mail de Jérémy.

**Un chemin personnel** (`C:\Users\<nom Windows>\AppData\Local\hermes\config.yaml`) apparaît dans **l'historique**
d'un document, mais plus dans `HEAD`.
- Gravité faible : c'est un nom d'utilisateur, pas un secret.
- Le supprimer imposerait de réécrire l'historique, ce qui est déconseillé maintenant que le tag est soumis.

**Écoute réseau :** uniquement sur la boucle locale.
- Uvicorn est sur `127.0.0.1` (`core/daemon.py:551`).
- Le bus sur `127.0.0.1` (`core/bus.py:58`).
- Le serveur de l'overlay OBS refuse toute autre adresse (`modules/gaming_hud/obs_server.py:26`).
- Le client OBS également (`modules/gaming_hud/obs_control.py:83`).
- Strata est refusé s'il n'écoute pas en local (`core/strata.py:156`).
- L'API vérifie l'hôte (`TRUSTED_HOSTS`, `core/api.py:112`) contre le DNS rebinding et pose une CSP.

**Texte de LLM vers un shell :**
- Aucun `shell=True`, `os.system` ni `os.popen` dans `core`, `modules` ou `scripts`.
- Les deux `exec` sont dans des bacs à sable :
  - `modules/calc_cas/sandbox.py:291` : analyse de l'arbre syntaxique, imports en liste blanche, fonctions natives
    filtrées, processus séparé tué au délai, mémoire bornée ;
  - `games.py:288` : même schéma.
- Le lanceur d'émulateurs construit sa commande sans shell (d'après ses tests).
- Les tâches confiées à Claude Code local sont confinées à un dossier, sans Bash ni web
  (`PROJECT_STATUS.md` l.108). **Non revérifié en réel ici.**

**Appels réseau sortants à noter :**
- `gaming_hud` télécharge des images du jeu (Battle.net) et, en option, la visionneuse 3D de Wowhead.
- Ce ne sont pas des appels de génération, mais un juge pointilleux sur « aucun appel au cloud » pourrait le
  relever. Il faudrait le dire dans la phrase d'accroche.

### 3.6 Inoue, Fuma, routeur : scénario de contention mesuré

**Code lu :**
- `core/guardians/inoue.py` (181 lignes) ;
- `core/guardians/fuma.py` (167 lignes) ;
- `core/llm_router.py` (416 lignes) ;
- `core/scheduler.py` (91 lignes).

Les deux gardiens sont de vrais composants, reliés au démon et testés (147 tests dans `tests/core`).

**Scénario.**
- Un autre programme (PyTorch, comme le ferait ComfyUI) réserve 12 Gio sur la RTX 5060 Ti.
- Ensuite, deux gros modèles sont demandés.
- Réglages : contexte de 32 768 jetons, cache KV q8_0, flash attention.

| Étape | Sans le Hub (Ollama seul) | Avec le Hub (routeur + Inoue) |
|---|---|---|
| VRAM au départ (carte 0 / carte 1) | 1,6 Go / 12,1 Go (occupant) | idem |
| `qwen3-27b` demandé | **erreur 500 en 2,6 s** : `cudaMalloc failed: out of memory`, tampon CUDA1 de 8,2 Go | **mis en file en 0,16 s** : « VRAM occupée par d'autres modules » (budget 28,66 Go, mesuré 14,16 Go, libre 14,51 Go, besoin estimé 18,0 Go) |
| `qwen3-coder:30b-a3b` demandé en même temps | **erreur 500 en 4,6 s** : out of memory, tampon CUDA0 de 9,4 Go | (une génération à la fois : verrou du routeur) |
| Occupant libéré | — | `qwen3-27b` accordé et chargé, réponse en **17,3 s** ; VRAM 10,0 / 8,9 Go |
| Second gros modèle | — | le premier est déchargé **avant** ; `qwen3-coder` chargé en 16,2 s, puis retour à `qwen3-27b` en 12,5 s (essai répété, sans erreur) |

Ce que ça montre :
1. Ollama ne refuse pas proprement une demande qui ne tient pas à cause d'un autre programme : il essaie, échoue
   et renvoie une erreur brute.
2. Inoue, qui lit la VRAM réelle, met en attente avec une raison lisible et ne déclenche aucun chargement voué à
   l'échec.
3. Le routeur enchaîne bien deux gros modèles sans jamais les avoir ensemble en mémoire.

Incident observé une fois :
- Juste après les plantages d'Ollama, le passage de `qwen3-27b` à `qwen3-coder` par le routeur a reçu une
  erreur 500 « connexion fermée » de `llama-server`.
- Relancé sur un Ollama sain, le même enchaînement a réussi trois fois de suite.
- Cause non établie. Piste : le routeur charge le modèle suivant juste après la requête `keep_alive: 0`, sans
  attendre que la VRAM soit réellement rendue. Il faudrait sonder `/api/ps` ou `nvidia-smi` avant de charger.

**Autre constat.** La variante `qwen3-coder:30b-a3b-64k`, choisie dans l'onglet Développement pour Claude Code
local, **plante seule** sur ce poste :
- avec son contexte de 64 k : out of memory sur CUDA1 à l'allocation du cache KV (1,6 Go), alors que la carte 1
  était vide ;
- à 32 k : `llama-server` qui se ferme.
- La variante `30b-a3b-q4_K_M` marche, elle.
- À vérifier par Jérémy : la mise à jour d'Ollama, ou un réglage `num_gpu` ou de répartition (§ 7).

Le script est en annexe A. Il peut être versé dans `scripts/` et cité dans la vidéo ou dans le README.

### 3.7 Mesures hardware (26/11/2026, Ollama, `num_ctx` 32 768, KV q8_0, flash attention)

| Modèle | Quantification | Taille (`/api/ps`) | VRAM carte 0 / carte 1 pendant (Mio) | Chargement à froid | Débit |
|---|---|---|---|---|---|
| `qwen3-27b` | Q4_K_M | 16,77 Gio | 10 177 / 8 970 | 11,6 s | **29,6 jetons/s** |
| `qwen3-coder:30b-a3b` | Q4_K_M | 19,69 Gio | 12 174 / 9 972 | 12,3 s | **132,9 jetons/s** |
| `qwen2.5vl:7b` (texte seul) | Q4_K_M | 5,89 Gio | 1 567 / 7 402 | 7,1 s | **82,1 jetons/s** |

- La VRAM de la carte 0 comprend environ 1,6 Go pris par le bureau Windows et les applications.
- Les tailles concordent avec `docs/HARDWARE_FIT.md` (16,77 et 19,69 Gio) ; les débits y manquaient.
- Le premier relevé de `qwen3-27b` (30,5 jetons/s, chargement en 14,3 s) a été fait pendant une autre charge ;
  le tableau garde la mesure faite sur un poste au repos.
- **Non mesuré :** `qwen2.5vl` sur une image, HandSegNet et FootSegNet (déjà dans `HARDWARE_FIT.md`), Strata,
  et la consommation électrique.

### 3.8 Chemin d'un évaluateur pressé (10 minutes)

Ce qu'il voit, dans l'ordre :
1. Le titre et l'accroche : bons.
2. La dédicace.
3. Le lien de démo, ajouté le 25/11.
4. Le bandeau sur le tag.
5. Trois captures.
6. « En bref » : quatre puces, la première est la bonne.
7. Un schéma Mermaid à dix-huit boîtes.
8. L'installation.
9. Ensuite seulement, la « Démo en cinq minutes » (l.138).

Problèmes :
- La thèse (« contention de VRAM résolue ») n'est jamais **montrée** : aucun chiffre avant/après, aucun lien
  vers la vidéo.
- Le tableau des modules mélange le cœur et les à-côtés.
- Pour lancer quelque chose, il faut Python 3.11, Ollama et 17 Go de modèles. C'est raisonnable en High-End,
  mais il faudrait le dire en une ligne en haut.

Section proposée, juste sous l'accroche :

> **Visite en 5 minutes**
> 1. *La vidéo (1 min 48)* : [lien YouTube].
> 2. *La preuve* : un programme tient 12 Gio de VRAM ; Ollama seul plante en 3 s (« out of memory ») ;
>    avec AetherTwin, Inoue met la demande en file en 0,16 s puis la sert dès que la place se libère
>    (`scripts/contention_demo.py`, résultats datés dans `docs/HARDWARE_FIT.md`).
> 3. *Le code du cœur* : `core/guardians/inoue.py` (180 lignes), `core/llm_router.py`, `core/guardians/fuma.py`.
> 4. *Essayer* : télécharger la Release, `Installer AetherTwin.bat`, `Lancer AetherTwin.bat` ; Ollama
>    et `qwen3-27b` conseillés, sinon mode dégradé.
> 5. *L'état honnête* : `PROJECT_STATUS.md` (statuts FAIT-TESTÉ / SIMULÉ / EN COURS).

### 3.9 Les angles faibles d'un dépôt trop large

- **Portent la thèse :**
  - `core/guardians` et `core/llm_router.py` ;
  - `core/daemon.py`, `core/scheduler.py` ;
  - `scantrad`, qui fait se relayer deux modèles dans la VRAM ;
  - `calc_cas`, pour les outils exacts et le MCP ;
  - `gaming_hud` en lecture seule, avec l'overlay filtré ;
  - `dev_launcher`, pour le relais.
- **Crédibles mais secondaires :** `genesis_lab` (Professeur), `voice`, `data_lab`.
- **Leur absence ne changerait rien à la note, et ils coûtent en clarté :**
  - `circuit_lab` : consoles 8 et 16 bits, microcontrôleurs ;
  - le lanceur d'émulateurs de `calc_cas` ;
  - `pixel_studio`, le studio audio ;
  - `chem_lab` ;
  - l'intégration `artcraft` ;
  - le mode jeu de la calculatrice (snake, pong, tetris).
  - Ce sont des démonstrations d'agent outillé réussies, mais hors du sujet « arbitrage de ressources locales ».
- **Risque de nommage.** Le projet s'interdit d'utiliser un nom de console commerciale pour ses machines
  simulées. Pourtant :
  - des fichiers s'appellent `core/web/nes_cpu.js`, `nes_machine.js` et `nes_ppu.js` ;
  - `PROJECT_STATUS.md` l.158 cite « Game Boy → PS2 » pour le lanceur d'émulateurs ;
  - le format « iNES » est un nom de format de fichier, ce qui se défend.
  - Gravité faible, mais facile à corriger sur `main`.

### 3.10 Comparaison avec l'existant

Ce qu'**Ollama** fait déjà seul :
- il charge à la demande ;
- il garde un modèle en mémoire 5 minutes (`keep_alive`) ;
- il limite le nombre de modèles chargés (`OLLAMA_MAX_LOADED_MODELS`) ;
- il met en file les requêtes parallèles ;
- il évince un modèle inactif pour faire de la place ;
- il répartit un modèle entre plusieurs cartes.

Ce qu'il ne fait pas, d'après la mesure du § 3.6 :
- tenir compte d'un **autre programme** qui occupe la VRAM, au-delà de ce qu'il lit au moment du chargement ;
- **réserver** de la place pour un module qui n'est pas un modèle Ollama (PyTorch, ONNX, OBS) ;
- garder une marge de sécurité ;
- refuser ou mettre en file avec une raison lisible au lieu de planter.

C'est exactement ce qu'Inoue ajoute.

Ce qu'AetherTwin ne fait **pas** non plus : affecter un modèle à une carte précise, ou agir sur ComfyUI ou un
jeu (il les compte, il ne les pilote pas).

Côté existant, la recherche trouve des outils à l'intérieur de ComfyUI (ComfyUI-VRAM-Manager, LLMVRAMManager)
et des scripts maison qui évincent ComfyUI quand il est inactif. Aucun hub généraliste ne fait cet arbitrage.
Cette conclusion repose sur des extraits de résultats : « partiellement vérifié ».

## 4. Écarts et contradictions trouvés

| # | Document | Dit | Réalité vérifiée |
|---|---|---|---|
| 1 | README l.30-31 | un agent local « reprend » quand le quota tombe | exact : bascule réelle le 25/11 (Jérémy, § 8) |
| 2 | `PROJECT_STATUS.md` l.19, 55-59 ; README l.255 ; voix off | relais « en simulation » ; message de quota « pas observé » | l.338-339 du même fichier : relais réel et message relevé, « validés le 25/11 » |
| 3 | README l.242 / `PROJECT_STATUS.md` l.14 / `AGENT_HANDOFF.md` l.17, 36 | 1 102 + 5 / 1 118 / 404 / 268 tests | 1 126 (1 122 réussis + 4 sautés) |
| 4 | `AGENT_HANDOFF.md` | « mis à jour le 22/11 » | trois jours de travail manquent (OBS MCP, Release, vidéo, CI) |
| 5 | README l.256 | CI sous Ubuntu, portage en cours | CI de `main` : Windows seulement, verte ; CI du tag : rouge |
| 6 | Affirmation orale « vérifié sous Windows 11 » | — | aucune trace dans le dépôt ; poste de développement en Windows 10 |
| 7 | Règle « pas de nom de console commerciale » | — | `nes_*.js`, « Game Boy → PS2 » (`PROJECT_STATUS.md` l.158) |
| 8 | Accroche « aucune requête de génération ne part vers un cloud » | exacte | mais `gaming_hud` contacte Battle.net (et Wowhead en option) pour des images ; à préciser |
| 9 | Onglet Développement | `qwen3-coder:30b-a3b-64k` proposé pour Claude Code local | cette variante plante seule sur le poste le 26/11 (§ 3.6) |

## 5. Risques de mauvaise note, par gravité

1. **Élevé — la thèse n'est pas montrée.**
   - Le juge voit un hub immense et doit croire sur parole qu'Inoue sert à quelque chose.
   - La preuve du § 3.6 n'est ni dans le dépôt, ni dans la vidéo.
2. **Élevé — la dispersion.**
   - Les consoles émulées, les émulateurs et le studio audio peuvent faire passer le projet pour un « fourre-tout »
     plutôt que pour un agent système.
3. **Moyen — la CI rouge sur le tag soumis.**
   - C'est visible sur la page du commit et de la Release.
   - Elle ne se corrige pas sans toucher au tag. Il faut l'expliquer en une ligne dans la Release ou le README.
4. **Moyen — les contradictions sur le relais.**
   - Un juge qui croise le README et `PROJECT_STATUS.md` peut douter de l'honnêteté des statuts, qui est
     justement un point fort revendiqué.
5. **Moyen — la reproductibilité hors du poste de l'auteur n'est pas tracée.**
   - Il n'y a ni journal d'installation sur Windows 11, ni sur une machine sans Python préinstallé.
6. **Faible — la suite de tests fragile quand la RAM sature.**
7. **Faible — les noms de consoles commerciales.**
8. **Faible — le chemin personnel dans l'historique.**
9. **Faible — les appels Battle.net et Wowhead** face à « aucun appel au cloud ».

## 6. Plan d'amélioration priorisé (pour `main`, pas pour le tag)

### (a) Moins d'une heure

| Action | Gain estimé | Fichiers |
|---|---|---|
| Verser le script de contention dans le dépôt et ajouter ses résultats datés à `HARDWARE_FIT.md` (avec les débits du § 3.7) | +2 à +3 points (pertinence, hardware) | `scripts/contention_demo.py` (annexe A), `docs/HARDWARE_FIT.md` |
| Ajouter la « Visite en 5 minutes » en haut du README, avec le lien de la vidéo et la phrase « tournée et montée par un agent via les MCP OBS et EffectCraft » | +1 à +2 (clarté) | `README.md` |
| Aligner le relais partout : bascule réelle observée le 25/11 (fait le 26/11 pour le README et `PROJECT_STATUS.md` l.19 ; reste la voix off et les lignes `SIMULÉ` du relais) | +1 (implémentation : honnêteté des statuts) | `README.md` l.30-31, 255 ; `PROJECT_STATUS.md` l.19, 55-59 |
| Aligner le nombre de tests (1 126) et dater ; remettre `AGENT_HANDOFF.md` à jour | +0,5 | `README.md`, `PROJECT_STATUS.md`, `AGENT_HANDOFF.md` |
| Expliquer la CI rouge du tag : « workflow d'alors Ubuntu + Windows ; corrigé sur `main` » | +0,5 | notes de la Release, `README.md` l.256 |
| Préciser l'accroche : « aucune requête de génération vers un cloud ; WoW Assistant télécharge seulement des images du jeu » | +0,5 | `README.md` l.3-6 |

### (b) Une demi-journée

| Action | Gain estimé | Fichiers |
|---|---|---|
| Afficher la contention dans le Hub : quand Inoue met en file, l'Accueil montre « en file : 18,0 Go demandés, 14,5 libres, occupé hors Hub : 12,1 Go ». C'est la scène manquante pour une vidéo de 20 s | +1 à +2 | `core/web/dashboard.js`, `core/api.py` |
| Faire attendre le routeur après `keep_alive: 0` que `/api/ps` ou la mesure confirme la libération (incident du § 3.6) | +0,5 (robustesse) | `core/llm_router.py:210-212` + test |
| Corriger la détection de Windows 11 (build ≥ 22000) | +0,5 | `core/daemon.py:115` + test |
| Renommer `nes_*.js` et retirer « Game Boy → PS2 » de `PROJECT_STATUS.md` | +0,5 (risque) | `core/web/`, `PROJECT_STATUS.md` |
| Remplacer la variante `qwen3-coder:30b-a3b-64k` par défaut, ou documenter son plantage | +0,5 | `modules/dev_launcher`, `docs/HARDWARE_FIT.md` |
| Tracer une installation sur une machine vierge sous Windows 11 : journal de `setup.ps1` + `pytest` + capture, versé dans `docs/RELEASE.md` | +1 (reproductibilité) | `docs/RELEASE.md` |

### (c) Plus long

| Action | Gain estimé | Fichiers |
|---|---|---|
| Affectation **par carte** dans Inoue : budget par GPU, choix de la carte pour un module PyTorch ou ONNX (`CUDA_VISIBLE_DEVICES`) | +1 à +2 (thèse plus forte) | `core/guardians/inoue.py`, `core/daemon.py` |
| Suite de tests résistante à la saturation de RAM : marquer les tests lourds (PyTorch, ONNX, vision) et les lancer à part | +0,5 | `pyproject.toml`, `tests/` |
| Portage Ubuntu de la CI (10 tests propres à Windows) | +0,5 | `.github/workflows/tests.yml`, tests concernés |

**À mettre en pause sur `main`, pour concentrer la profondeur sur le cœur :**
- `circuit_lab` (consoles 8 et 16 bits, microcontrôleurs) ;
- le lanceur d'émulateurs et le mode jeu de `calc_cas` ;
- le studio audio ;
- `pixel_studio` ;
- l'intégration `artcraft`.

Les garder, mais les sortir du tableau principal du README, sous un titre « Démonstrations annexes d'agents
outillés ».

## 7. Questions pour Jérémy

1. **Relais :** confirmes-tu la formulation exacte, à savoir « relais réel côté Claude Code ; bascule vers
   l'agent local écrite mais volontairement non activée » ?
   - Qu'ont réellement validé les lignes 338-339 de `PROJECT_STATUS.md` le 25/11 : la bascule ou seulement la
     détection ?
2. **Windows 11 :** sur quelle machine as-tu installé l'archive le 25/11 (version de Windows, Python déjà
   présent ou non, GPU) ? As-tu une capture ou un journal à verser au dépôt ?
3. **`qwen3-coder:30b-a3b-64k` :** marchait-il chez toi avant le 26/11 ? Quelle version d'Ollama as-tu ?
4. **Ce qui fait foi pour le jury :** veux-tu que le README de `main` cite les résultats de contention, sachant
   qu'ils sont postérieurs au tag ?
5. **Le lien YouTube de la vidéo :** peut-il figurer dans le README ?
6. **Modules annexes :** acceptes-tu de les sortir du tableau principal du README ? Le code, lui, ne bouge pas.

---

## 8. Réponses de Jérémy (26/11/2026) et suites données

Ces réponses sont des témoignages, sans capture ni journal versés au dépôt.

1. **Relais :** à une vraie fin de quota, la bascule s'est faite. L'agent local a demandé s'il fallait poursuivre
   ou attendre le retour du quota, ce qui était la consigne du test. Ce comportement correspond à celui décrit
   pour `dev_launcher/quota_watch.py`.
   - Suite : README et `PROJECT_STATUS.md` alignés (relais réel, sans capture) ; l'écart n° 1 est levé.
   - Reste : la voix off de la vidéo dit « testé en simulation » (la vidéo est rendue, elle ne change pas), et
     les lignes du relais par `scripts/relay_orchestrator.py` gardent leurs statuts d'origine.
2. **Windows 11 :** installation de l'archive sur une autre partition du même poste, où seuls Ollama et
   World of Warcraft étaient installés (donc sans Python préalable). Pas de capture.
   - Le risque n° 5 baisse, sans disparaître : même matériel, et aucune trace dans le dépôt.
3. **`qwen3-coder:30b-a3b-64k` :** fonctionnait avant le 26/11. La variante est toujours présente
   (`ollama list`). Ollama est en 0.40.18 le 26/11, contre 0.40.16 lors des mesures du 17/11.
   - Hypothèse **non vérifiée** : régression liée à la mise à jour d'Ollama.
4. **Résultats de contention dans le README :** non, ils sont postérieurs au tag. Ils restent dans ce rapport.
5. **Lien YouTube dans le README :** non, le jury l'a déjà.
6. **Modules annexes :** oui. `pixel_studio`, `circuit_lab` et `artcraft` sont sortis du tableau principal du
   README, sous « Démonstrations annexes d'agents outillés ». Le code ne bouge pas.

## 9. Suites données le 27/11/2026 (sur `main`)

| Action du § 6 | État |
|---|---|
| Script de contention dans le dépôt, résultats dans `HARDWARE_FIT.md` | fait (`scripts/contention_demo.py`, relancé le 27/11) |
| Visite en 5 minutes en haut du README | faite (sans lien vidéo ni chiffres de contention, à la demande de Jérémy) |
| Relais aligné, nombre de tests, `AGENT_HANDOFF.md` | faits |
| CI rouge du tag expliquée | faite dans le README |
| Accroche précisée (Battle.net, Wowhead) | faite |
| Contention visible dans le Hub | faite : panneau « État de charge » de l'Accueil |
| Routeur : attendre la libération après `keep_alive: 0` | fait, avec une nouvelle tentative si Ollama plante au chargement |
| Détection de Windows 11 | faite |
| Noms de consoles commerciales | retirés (`c8_*.js`, `PROJECT_STATUS.md`) |
| Affectation **par carte** dans Inoue | faite (`single_card`), plus un budget de **RAM** |
| Variante `qwen3-coder:30b-a3b-64k` | non tranchée : Ollama 0.40.18 plante aussi sur `qwen3-27b` le 27/11 |
| Suite de tests résistante à la saturation de RAM | sans objet : les tests lourds sont déjà opt-in ; la saturation venait de deux suites lancées en parallèle |
| Portage Ubuntu de la CI | non fait (pas de Linux ni d'accès aux journaux de la CI sur ce poste) |
| Installation tracée sur Windows 11 | témoignage de Jérémy versé au README, sans capture |

## Annexe A — script de contention (lancé le 26/11/2026, hors du dépôt)

Le script complet a servi aux mesures des § 3.6 et 3.7. Voici le cœur de la partie « avec le Hub », à lancer
depuis la racine du dépôt :

```python
import torch
from core.guardians.inoue import Inoue
from core.hardware.gpu_monitor import GpuMonitor
from core.llm_router import LlmConfig, LlmRefused, LlmRouter

hog = torch.empty(12 * 2**30, dtype=torch.uint8, device="cuda:1")  # « un autre programme » : 12 Gio
router = LlmRouter(inoue=Inoue(GpuMonitor()), config=LlmConfig(num_ctx=32768))
msg = [{"role": "user", "content": "Explique en cinq phrases ce qu'est la mémoire vidéo."}]
try:
    router.chat(msg, model="qwen3-27b:latest", think=False, options={"num_predict": 200})
except LlmRefused as exc:
    print("Inoue :", exc)               # « en file — VRAM occupée par d'autres modules », en 0,16 s
del hog; torch.cuda.empty_cache()
router.chat(msg, model="qwen3-27b:latest", think=False, options={"num_predict": 200})   # accordé
```

La partie « sans le Hub » envoie les mêmes demandes directement à `POST /api/generate` d'Ollama, dans deux
fils en parallèle, et relève les erreurs. Les relevés de VRAM viennent de
`nvidia-smi --query-gpu=index,memory.used` et de `/api/ps`.
