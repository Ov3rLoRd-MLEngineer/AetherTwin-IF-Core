# CHANGELOG_DEV — journal chronologique obligatoire

Chaque entrée : date et heure, agent (**Cloud** = Claude Code · **Local** = Qwen via Aider/OpenCode),
fichiers modifiés, raison, résultat des tests, décisions. La plus récente en bas.
Un agent qui modifie le code sans écrire ici est en faute.

---

## 2026-11-16 — J0 : initialisation du dépôt

- **Agent :** Cloud
- **Fichiers :** `CLAUDE.md`, `AGENT_HANDOFF.md`, `PROJECT_STATUS.md`, `ARCHITECTURE_MAP.md`,
  `README.md`, `LICENSE`, `NOTICE`, `THIRD_PARTY.md`, `pyproject.toml`, `requirements*.txt`,
  `.gitignore`, `.gitattributes`, `.github/workflows/tests.yml`, `config/*.yaml`,
  `scripts/gen_architecture_map.py`, `scripts/setup.ps1`, `tests/test_repo_hygiene.py`,
  `tests/test_architecture_map.py`, paquets vides `core/`, `modules/`.
- **Raison :** jalon J0 du plan (structure, conventions, suivi, CI).
- **Lu avant d'écrire :** `_import/wow_assistant_v9/` — `README.md`, `main.py`, `llm.py`,
  `game_connection.py`, `overlay.py`, `requirements.txt` en entier ; `ui.py` et
  `HermesAssistant.lua` par leur table des symboles.
- **Tests :** `ruff check .` propre ; `pytest` vert (voir l'entrée J1 pour le total).

### Relevés du poste

- `py -0p` : Python 3.11 (défaut) et 3.10. Pas de 3.12.
- OS : Windows 10 Professionnel 10.0.19045 (le cahier des charges disait Windows 11).
- `nvidia-smi -L` : **2 GPU** — RTX 5080 (16 303 MiB) et RTX 5060 Ti (16 311 MiB). Pas 3.
- `ollama --version` : 0.40.16. `qwen3-coder:30b-a3b-q4_K_M` installé.
- Absents du PATH : `aider`, `opencode`, `gh`. Présent : `claude` (`.cmd` et `.ps1`).
- `D:\OVERLORD\` : introuvable ou vide.

### Décisions

1. **Python 3.11** pour le venv : c'est la version de WoW Assistant, et 3.12 n'est pas installé.
2. **`_import/` est versionné tel quel** (`-text` dans `.gitattributes`) : c'est la preuve de l'origine
   du port et la référence de non-régression. Vérifié : aucun secret, aucun chemin de dossier
   utilisateur. Il contient des chemins d'installation de jeu par défaut (`E:/World of Warcraft/…`).
3. **`PROMPT_MAITRE_AetherTwin.md` est ignoré par Git** : document de travail privé, il n'a pas sa
   place dans le dépôt public.
4. **Identité Git locale au dépôt** (aucune identité globale n'existait) : `Ov3rLoRd-MLEngineer`,
   adresse `users.noreply.github.com`, pour ne pas publier d'adresse personnelle. À confirmer.
5. **Longueur de ligne 120** (ruff). Règles : E, F, W, I, B, UP, S.
6. **Deux profils matériels** dans `config/hardware_profiles.yaml` : `tri_gpu_48gb_nvidia` (déclaré)
   et `dual_gpu_32gb_nvidia` (mesuré). La topologie réelle sera mesurée au lancement.
7. **Texte de la licence Apache 2.0** copié depuis une distribution Python installée (texte standard).

---

## 2026-11-16 — J1 : relais Cloud ⇄ Local

- **Agent :** Cloud
- **Fichiers :** `scripts/relay_orchestrator.py`, `tests/test_relay_orchestrator.py`.
- **Raison :** jalon J1. Le relais protège la suite du développement pendant les coupures de quota.
- **Tests :** `pytest` → **42 réussis** (dont 34 pour le relais). `--dry-run` exécuté : code 0.
  Scénarios couverts : 429 transitoire, 429 persistant → bascule, message de limite → bascule
  immédiate, retour à T0 + fenêtre, redémarrage en phase locale (avant et après l'heure de retour),
  redémarrage en phase cloud, deux instances simultanées, verrou orphelin, Ctrl+C en phase cloud et
  en phase locale, agent local indisponible, état illisible.
- **Non testé en conditions réelles :** quota réel de Claude Code, Aider, OpenCode, API Anthropic réelle.

### Règle de quota consignée (lue le 16/11/2026)

Centre d'aide Claude, « How do usage and length limits work? »
(<https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work>) :
la période de cinq heures commence au premier message envoyé et la limite se réinitialise
entièrement cinq heures plus tard. Les offres Pro et Max ont en plus une limite hebdomadaire.
L'usage est partagé entre claude.ai, Claude Code et Claude Desktop. La documentation de Claude Code
décrit pour les offres Team/Enterprise une fenêtre « glissante » : les deux formulations ne sont pas
réconciliées. La durée reste donc un paramètre : `--window-minutes` (défaut 302 = 5 h + 2 min).

### Décisions

1. **Bibliothèque standard uniquement** pour le relais, sauf le backend `--backend api` qui utilise le
   **SDK officiel `anthropic`** (optionnel, importé à l'usage). Modèle par défaut `claude-opus-5-5`,
   modifiable par `--api-model` ou `ANTHROPIC_MODEL`. Le paramètre `fallbacks` (bêta) n'est pas activé.
2. **Limite assumée du backend API :** un appel d'API ne modifie aucun fichier. La réponse est écrite
   dans `logs/relay_api_last_response.md`. Pour un agent qui édite le dépôt : `--backend claude-code`.
3. **Deux niveaux d'erreur.** `QUOTA` (motifs « usage limit », « limit reached », ou `retry-after`
   > 300 s) : bascule immédiate. `TRANSIENT` (429, 529, surcharge) : backoff 5/10/20/40 s, puis bascule
   au 5ᵉ échec.
4. **Heure de retour** = `T0 + fenêtre`. Si le serveur annonce un `retry-after` plus tardif, il prime.
   Si `T0 + fenêtre` est déjà passé, attente de 15 minutes.
5. **Limite hebdomadaire :** non distinguée de la limite de 5 h. Si le quota est encore atteint au
   retour, le relais repart simplement pour un cycle local.
6. **Motifs cherchés seulement en cas d'échec** de Claude Code, car une réponse réussie peut parler de
   « 429 ». Claude Code est lancé avec `-p --output-format json`.
7. **Agent local relancé en boucle** jusqu'à l'heure de retour (20 passages au plus ; mise en pause
   après 3 échecs en moins de 60 s).
8. **`git add -A`** pour le commit `wip(local)` : acceptable parce que `.gitignore` exclut les secrets
   et l'état d'exécution, et que `tests/test_repo_hygiene.py` vérifie les fichiers suivis.

---

## 2026-11-16 (soir) — réponses de Jérémy, agent local Claude Code via OmniRoute

- **Agent :** Cloud
- **Fichiers :** `scripts/relay_orchestrator.py`, `tests/test_relay_orchestrator.py`,
  `config/hardware_profiles.yaml`, `config/local.example.yaml`, `AGENT_HANDOFF.md`,
  `PROJECT_STATUS.md`, `README.md`.
- **Raison :** Jérémy a précisé son installation réelle. Aider n'est pas installé ; son agent local est
  Claude Code lancé avec `--model ollama/<modèle>` à travers OmniRoute (port 20128).
- **Tests :** `pytest` → 46 réussis ; `ruff check .` propre.

### Relevés

- `ollama show` : `qwen3-27b` (27,3 B), `qwen3-35b` (34,7 B), `qwen3-coder:30b` (30,5 B) sont **tous
  en Q4_K_M**, contexte maximal 262 144. Aucun Q8_0 installé.
- Journal d'Ollama : 2 GPU, 31,8 Gio au total, contexte par défaut 32 768, cache KV `q8_0`,
  flash attention activée, `keep_alive` 5 min, écoute sur `0.0.0.0:11434`.
- OmniRoute 3.8.52 : écoute sur `0.0.0.0:20128` **sans clé** (avertissement affiché par OmniRoute).
- Dépôt Ov3rLoRd (public) : **237 commits sur `main`** — le chiffre déclaré est confirmé ; 239 toutes
  branches ; premier commit le 23/06/2026, dernier le 10/08/2026 ; 26 branches.
- Recherche de motifs de clés dans l'état courant (`HEAD`) du dépôt Ov3rLoRd : aucun résultat.
  **L'historique n'a pas été scanné.**

### Décisions

1. **Agent local par défaut : `claude-code`** (au lieu d'`aider`). Le relais pose
   `ANTHROPIC_BASE_URL`, une valeur factice pour `ANTHROPIC_AUTH_TOKEN`, et **vide
   `ANTHROPIC_API_KEY`** pour qu'une vraie clé ne parte jamais vers le routeur local.
2. **`--permission-mode acceptEdits` par défaut** pour Claude Code, côté cloud et côté local : sans
   cela un agent non interactif n'écrit aucun fichier. Modifiable par `--claude-arg` / `--local-arg`.
   Non vérifié : les commandes (tests, commit) peuvent encore demander une autorisation.
3. **`ANTHROPIC_CONTEXT_LENGTH` aligné sur `num_ctx`** (32 768) et non sur 150 000 comme dans le
   lanceur. Effet réel non vérifié : Claude Code affiche « context assumed to be 200k tokens » pour un
   modèle `ollama/...`, ce qui laisse penser que la variable est ignorée.
4. **Modèle local par défaut inchangé** (`qwen3-coder:30b-a3b-q4_K_M`) ; `--local-model qwen3-27b:latest`
   pour utiliser celui du lanceur.

---

## 2026-11-16 (nuit) — J2, première moitié : moniteur GPU, contrat de module, gardiens

- **Agent :** Cloud
- **Fichiers :** `core/hardware/gpu_monitor.py`, `core/module_api.py`, `core/guardians/inoue.py`,
  `core/guardians/fuma.py`, `tests/core/test_gpu_monitor.py`, `tests/core/test_module_api.py`,
  `tests/core/test_guardians.py`, `requirements.txt`, `THIRD_PARTY.md`, fichiers de suivi.
- **Raison :** jalon J2 (tâches 1, 2, 4 et 5 de `AGENT_HANDOFF.md`).
- **Tests :** `pytest` → **89 réussis** ; `ruff check .` propre.
- **Exécution réelle :** `python -m core.hardware.gpu_monitor` → backend `pynvml`, 2 GPU,
  32 614 MiB au total (RTX 5080 : 16 303 MiB ; RTX 5060 Ti : 16 311 MiB), températures et puissances lues.
- **Reste du J2 :** bus, ordonnanceur GPU, daemon, API HTTP locale.

### Décisions

1. **Trois backends GPU** : `pynvml`, puis `nvidia-smi` en sous-processus (aucune dépendance), puis
   « inconnu ». Le cahier des charges demandait `pynvml` + repli ; `nvidia-smi` ajoute un repli utile
   sans coût. Toujours aucun backend AMD.
2. **Une mesure indisponible vaut `None`**, jamais 0 : pas d'alerte ni de chiffre inventé.
3. **Inoue est une comptabilité**, pas un pilote : elle décide (accordé / en file / refusé) et dit
   quels modèles décharger ; le déchargement réel (`keep_alive=0` d'Ollama) sera fait par le routeur
   LLM. Elle expose la VRAM mesurée à côté de la VRAM attribuée, pour comparer.
4. **Sans GPU, budget = 0** : seuls les modules sans besoin VRAM démarrent (mode dégradé explicite).
5. **Fuma met au repos** un module après 3 redémarrages ratés (délais 5, 10, 20 s), et lui rend ses
   essais après 5 minutes de bonne santé. Plage de nuit par défaut : 23 h → 7 h.

---

## 2026-11-16 (nuit) — J2, seconde moitié : bus, ordonnanceur, démon, API locale

- **Agent :** Cloud (session interrompue par la limite d'usage juste après ce commit)
- **Fichiers :** `core/bus.py`, `core/module_runner.py`, `core/scheduler.py`, `core/daemon.py`,
  `core/api.py`, `tests/core/test_bus_scheduler.py`, `tests/core/test_daemon.py`, `requirements*.txt`.
- **Tests :** `pytest tests/core` → 64 réussis, rejoués 3 fois sans échec ; `ruff check .` propre.
- **Exécution réelle :** `python -m core.daemon` → API sur 127.0.0.1:5750 ; `/health` : Windows 10,
  `pynvml`, total 31,85 Go, budget 28,66 Go ; `/gpu` : les 2 cartes ; `/events` : `hub.started`.
- **Décisions de Jérémy :** rester en Q4_K_M tant qu'il n'y a que 32 Go ; contexte local limité à
  32 768 ; pas de push GitHub pour l'instant, travail en local.
- **Décisions techniques :** bus en `multiprocessing.connection` avec clé aléatoire par lancement et
  messages JSON (jamais `pickle`) ; un module par processus via `core.module_runner` ; `/ask` rend 503
  tant que `core/llm_router.py` n'existe pas.
- **Non fait :** détection de fenêtres, interface générée à la volée, pilotage d'Ollama par Inoue ;
  `AGENT_HANDOFF.md`, `README.md`, `THIRD_PARTY.md` et `logs/relay_tasks.md` ne reflètent pas encore
  cette seconde moitié (compte de tests, licences de fastapi/uvicorn/psutil/httpx).
  → Rattrapé dans le commit `docs:` suivant.

---

## 2026-11-17 — correctifs de WoW Assistant v9 (demande de Jérémy, avant J3)

- **Agent :** Cloud
- **Fichiers :** `_import/wow_assistant_v9/` : `ui.py`, `webhost.py`, `clipboard.py` (nouveau), `README.md` ;
  `tests/wow_assistant_v9/conftest.py`, `tests/wow_assistant_v9/test_ui_fixes.py` ; `CLAUDE.md`,
  `requirements.txt`, `THIRD_PARTY.md`, fichiers de suivi.
  Copie des fichiers corrigés (plus `main.py` et `widgets_builtin.py`) dans
  `D:\Hermes-Agent\wow_assistant_v9`, avec sauvegarde des originaux dans
  `_sauvegarde_avant_correctifs_2026-11-17/`.
- **Constat préalable :** la copie d'usage de Jérémy (`D:\Hermes-Agent`, 16/11 20 h 01) était plus ancienne
  que `_import/` (16/11 20 h 49). `_import/` contenait déjà la barre d'outils élargie et les textes d'aide
  replacés ; une partie des défauts signalés venait donc de la version utilisée.
- **Tests :** `pytest` → 132 réussis (dont 22 nouveaux, headless) ; `ruff check .` propre.
- **Vérifications réelles :**
  - Fermeture : vraies fenêtres SDL, overlay ouvert puis fermé, `WM_CLOSE` envoyé à la fenêtre principale.
    Ancienne version : l'appli reste ouverte. Nouvelle : elle se ferme. Refait sur le dossier Hermes-Agent.
  - Widgets web : `webhost.py` lancé avec pywebview 6.2.1 (Python 3.10) sur une page locale. Ancienne
    version : `WS_EX_NOACTIVATE` présent. Nouvelle : absent.
  - Rendu : captures des 8 pages de Paramètres, du menu contextuel et de l'overlay, relues à l'œil.
- **Non vérifié :** la frappe réelle dans Open WebUI et YouTube, la conservation des sessions entre deux
  lancements, le comportement avec le jeu ouvert.

### Causes et corrections

1. **Fermeture impossible après l'overlay.** Avec deux fenêtres SDL (l'overlay reste créé, seulement
   masqué), la croix envoie `WINDOWCLOSE` et non `QUIT`. Le code ignorait `WINDOWCLOSE` pour toutes les
   fenêtres. Désormais : fenêtre principale → quitter ; fenêtre overlay → fermer l'overlay.
2. **Pas de clavier dans les widgets web.** `focus=False` fait poser `WS_EX_NOACTIVATE` par pywebview.
   Passé à `focus=True`. Contrepartie : le widget prend la saisie à son ouverture.
3. **Saisie.** `pygame.key.set_repeat(400, 35)` ; curseur (flèches, Début, Fin, Suppr, clic) ; Ctrl+A/C/X/V,
   Maj+Inser ; menu du clic droit ; défilement du texte long. La répétition est ignorée hors d'un champ et
   pour Échap/Entrée (sinon Échap maintenu fermerait la modale puis l'appli). AltGr (Ctrl+Alt) n'est pas
   pris pour un raccourci, pour que « @ » reste saisissable en AZERTY.

### Décisions

1. **Sélection « tout ou rien »** (Ctrl+A), pas de sélection partielle : suffisant pour copier une adresse
   ou une clé, et bien plus simple.
2. **Un champ masqué n'est jamais copié ni coupé** (clé API) ; y coller reste possible.
3. **`_import/` n'est plus figé** : il suit les correctifs demandés, reportés dans `D:\Hermes-Agent`.
4. **Modèles 3D : non entrepris.** Le jeu ne fournit pas de rendu du personnage à un addon, et afficher
   les modèles demande soit d'extraire et de rendre les fichiers du jeu (moteur 3D complet), soit une page
   web tierce. Piste réaliste : un widget web pointant vers une visionneuse en ligne, à étudier après J3.

---

## 2026-11-17 — WoW Assistant : effacement de clé API, lancement en Python 3.11

- **Agent :** Cloud
- **Fichiers :** `_import/wow_assistant_v9/` : `ui.py`, `README.md`, `Lancer WoW Assistant.bat` (nouveau) ;
  `tests/wow_assistant_v9/test_ui_fixes.py`. Mêmes fichiers copiés dans `D:\Hermes-Agent\wow_assistant_v9`.
  Hors dépôt : `Lancer OmniRoute.bat` créé sur le bureau de Jérémy (force `OMNIROUTE_SERVER_HOST=127.0.0.1`).
- **Tests :** `pytest` → 134 réussis ; `ruff check .` propre.
- **Retour de Jérémy (test réel) :** frappe au clavier dans Open WebUI : OK ; Open WebUI conserve la
  connexion entre deux lancements ; YouTube s'affiche mais la connexion au compte est refusée (attendu :
  Google bloque les fenêtres web intégrées) ; fermeture de l'appli : OK.
- **Python 3.11 :** l'appli ne tournait qu'en 3.10 parce que `pywebview` n'était installé que là.
  `py -3.11 -m pip install pywebview` fait (pywebview 6.2.1, pythonnet 3.2.1). Vérifié : fenêtre web créée
  et activable sous 3.11, tous les modules de l'appli s'importent.
- **Réseau :** Ollama écoute sur `127.0.0.1:11434` (journal du 17/11), OmniRoute sans avertissement.

### Décisions

1. **Clé API : saisie dans l'interface conservée** (choix de Jérémy : plus simple pour un utilisateur).
   Ajout d'un bouton « × » qui efface la clé du champ et de `settings.json` immédiatement.
2. **Trois GPU sur une seule machine** (choix de Jérémy) : pas de serveur Ollama séparé pour l'instant.
   L'adresse d'Ollama reste configurable.
3. **Modèles 3D : abandonnés pour l'instant** (accord de Jérémy).

### À signaler

- La variable utilisateur `OLLAMA_NUM_CTX=65536` n'apparaît pas dans la configuration lue par Ollama
  (le journal liste `OLLAMA_CONTEXT_LENGTH:0` et calcule `default_num_ctx=32768`). Elle semble sans effet.
- OmniRoute signale `STORAGE_ENCRYPTION_KEY` non définie alors qu'une base existe : à traiter par Jérémy.

---

## 2026-11-17 — WoW Assistant : écran Voix ; diagnostic de l'avertissement d'OmniRoute

- **Agent :** Cloud
- **Fichiers :** `_import/wow_assistant_v9/` : `ui.py`, `voice.py`, `settings.py`, `README.md` ;
  `tests/wow_assistant_v9/` (3 tests ajoutés). Mêmes fichiers copiés dans `D:\Hermes-Agent\wow_assistant_v9`.
- **Tests :** `pytest` → 137 réussis ; `ruff check .` propre.
- **Défauts vus sur une capture de Jérémy :**
  1. Avec le moteur faster-whisper, le champ « modèle » était partagé avec l'API et valait `whisper-1`,
     que faster-whisper refuse. Nouveau réglage `voice.stt.fw_model` (défaut `small`), choisi par boutons.
  2. Le message d'état en bas de la fenêtre chevauchait la mention de droite : il est maintenant abrégé.
- **Non vérifié :** une transcription réelle avec faster-whisper (pas de micro ni de modèle téléchargé ici).

### Diagnostic OmniRoute (lecture seule, aucune valeur secrète affichée)

- L'avertissement vient de `bin/omniroute.mjs` : si `STORAGE_ENCRYPTION_KEY` est vide **et** qu'une base
  existe, OmniRoute refuse de créer une clé, par prudence. Il ne vérifie pas si la base est chiffrée.
- La base de Jérémy ne contient **aucun** identifiant chiffré (0 valeur au format `enc:v1:`) : 5 connexions
  de fournisseurs, dont 2 avec jetons et clés **en clair**. Aucune clé n'a donc été perdue.
- D'après `src/lib/db/encryption.ts` : sans clé, stockage en clair ; avec une clé, les valeurs en clair
  restent lisibles et les nouvelles écritures sont chiffrées.
- Rien n'a été modifié chez OmniRoute. La décision (laisser tel quel, ou activer le chiffrement en créant
  `.env` dans le dossier `.omniroute`) revient à Jérémy.

---

## 2026-11-17 — WoW Assistant : faster-whisper « non installé » alors qu'il l'est

- **Agent :** Cloud
- **Fichiers :** `_import/wow_assistant_v9/voice.py`, `webwidget.py` ; un test ajouté. Copiés dans
  `D:\Hermes-Agent\wow_assistant_v9`.
- **Cause :** le `pip` nu de Jérémy appartient à Python 3.10 ; l'appli tourne en 3.11 depuis le lanceur.
  `pip install faster-whisper` l'avait donc installé dans le mauvais Python.
- **Fait :** `py -3.11 -m pip install faster-whisper` (1.2.1 ; CTranslate2 voit 2 périphériques CUDA).
  L'installation avait monté `certifi`, que le paquet `hermes-agent` de Jérémy fixe à 2026.5.20 :
  version remise, `pip check` ne signale plus ce conflit. Les autres avertissements de `pip check`
  (aiohttp, annotated-doc, botocore) existaient avant et n'ont pas été touchés.
- **Messages d'erreur :** ils donnent maintenant la commande exacte pour le Python qui fait tourner
  l'appli (`py -3.11 -m pip install …`), pour faster-whisper et pour pywebview.
- **Tests :** `pytest` → 138 réussis ; `ruff check .` propre.
- **Non vérifié :** une transcription réelle (le modèle n'a pas été téléchargé).

### OmniRoute : état constaté, aucune action

`storage.sqlite` n'est plus dans le dossier `.omniroute` : il est dans la corbeille de Windows, et une
copie est dans `storage.sqlite.rar`. Les fichiers `-wal` (4 Mo) et `-shm` sont restés. Un `.env` vide a
été créé. OmniRoute est arrêté. Rien n'a été touché : la suite dépend de ce que Jérémy voulait faire.

---

## 2026-11-17 — OmniRoute : chiffrement activé (hors dépôt, à la demande de Jérémy)

- **Agent :** Cloud. Aucun fichier du dépôt n'est concerné, hors ce journal.
- Jérémy a restauré `storage.sqlite` depuis la corbeille. Relue en lecture seule : mêmes 5 connexions
  qu'avant, toujours en clair. OmniRoute arrêté (port 20128 libre, aucun processus).
- Sauvegarde de `storage.sqlite`, `-wal`, `-shm` et `.env` dans
  `sauvegarde_avant_chiffrement_2026-11-17_023453` (dossier `.omniroute`).
- Clé aléatoire de 32 octets écrite dans `.env` (`STORAGE_ENCRYPTION_KEY`), jamais affichée ni consignée.
- **Non vérifié :** le redémarrage d'OmniRoute avec cette clé, et le fait que les fournisseurs répondent
  toujours. À faire par Jérémy.
- **Retour arrière :** OmniRoute arrêté, remettre les quatre fichiers de la sauvegarde à leur place.
- **Retour de Jérémy :** OmniRoute redémarre, la clé est chargée, la topologie des fournisseurs est correcte
  (un fournisseur, « Gemini Web (Free) », est en erreur : non investigué).

---

## 2026-11-17 — J3 : gaming_hud, GameAdapter, routeur LLM

- **Agent :** Cloud
- **Fichiers :**
  - déplacés : `_import/wow_assistant_v9/` → `modules/gaming_hud/app/` (sans modification) ; addon Lua →
    `modules/gaming_hud/addon/HermesAssistant/` ; `tests/wow_assistant_v9/` → `tests/gaming_hud/` ;
  - nouveaux : `modules/gaming_hud/__init__.py`, `__main__.py`, `module.py`, `manifest.json`,
    `adapters/{base,privacy,wow_retail,log_tail,screen_ocr}.py`, `rules/log_tail.example.yaml`,
    `core/config.py`, `core/llm_router.py`, `tests/gaming_hud/test_adapters.py`, `test_module.py`,
    `tests/core/test_llm_router.py` ;
  - modifiés : `core/api.py`, `core/daemon.py`, `core/module_runner.py`, `modules/gaming_hud/app/main.py`
    (contexte de l'assistant fourni par l'adaptateur), `config/*.yaml`, fichiers de suivi.
    `main.py` recopié dans `D:\Hermes-Agent\wow_assistant_v9`.
- **Tests :** `pytest` → 200 réussis, 2 ignorés (tests réels sur GPU, lancés à la main et réussis) ;
  `ruff check .` propre.
- **Vérifications réelles :**
  1. `python -m modules.gaming_hud` : fenêtre ouverte, SavedVariables du jeu lues, fermeture par la croix, code 0.
  2. Adaptateur WoW sur les données réelles : état lu ; aucun nom, compte ni chemin dans la sortie Showcase.
  3. `screen_ocr` avec `qwen2.5vl:7b` sur une image générée : 3 valeurs lues sur 3 ; 16,7 s à froid ;
     6 464 MiB sur la RTX 5060 Ti.
  4. Routeur LLM : `qwen3-27b` (16,77 Gio, 10,9 s) puis `qwen3-coder:30b` (19,69 Gio, 14,0 s), `num_ctx`
     32 768 ; un seul gros modèle en mémoire à chaque instant ; VRAM rendue après déchargement.
  5. Bout en bout : démon réel → `gaming_hud` activé par l'API → état du jeu publié → `/ask` au modèle
     local avec le contexte du jeu → réponse correcte (zone et niveau). Puis le `LLMClient` de l'appli,
     inchangé, pointé sur le Hub : 17 modèles listés, réponse reçue.
- **Non vérifié :** OBS réel (simulé par un faux processus) ; `log_tail` et `screen_ocr` sur un vrai jeu ;
  le mode `hermes.exe` ; l'appli lancée avec le jeu ouvert après le déplacement.

### Décisions

1. **Imports à plat conservés dans `app/`.** Convertir 30 fichiers en imports de paquet aurait été un
   remaniement risqué, sans bénéfice à 8 jours de la clôture, et aurait cassé la copie autonome de
   Jérémy. Le dossier est ajouté au chemin d'import par `ensure_app_path()`, uniquement dans le processus
   qui en a besoin. Conséquence assumée : `app/` est exclu du lint et de la liste des signatures.
2. **`modules/gaming_hud.py` n'existe pas** : Python ne permet pas un fichier et un paquet de même nom.
   Le « point d'entrée mince » demandé est `modules/gaming_hud/__init__.py` + `__main__.py`.
3. **Le module du Hub est un service de données sans fenêtre.** L'application Pygame reste indépendante
   (`python -m modules.gaming_hud`). Le module lit l'état par un adaptateur et le publie sur le bus.
4. **Le filtre de confidentialité ne fait pas confiance à la forme des données** : il supprime toute clé
   au nom sensible et nettoie toute chaîne (e-mails, chemins, jetons), à n'importe quelle profondeur.
   Par défaut le nom du personnage reste affiché et l'or est arrondi à un chiffre significatif.
5. **En Showcase, le contexte destiné à l'assistant est bâti sur l'état filtré**, pas sur l'état brut.
6. **Les sections de plus de 20 Ko ne sont pas publiées sur le bus** (collections, hauts faits…) : elles
   sont listées dans `omitted`.
7. **L'assistant de l'appli passe par le Hub sans modification de son code** : le Hub expose
   `/v1/models` et `/v1/chat/completions` ; il suffit de régler l'adresse du serveur sur
   `http://127.0.0.1:5750`. Le mode `hermes.exe` est donc conservé tel quel.
8. **Routeur LLM avancé de J5 à J3**, car le branchement de l'assistant en dépend. « Gros modèle » =
   plus de 8 Go : un seul chargé à la fois. Les petits modèles (vision 7 B) cohabitent.
   L'estimation avant chargement vaut la taille des poids × 1,15 ; elle est remplacée par la mesure
   réelle dès la première réponse.
9. **`screen_ocr` reste marqué expérimental** : un modèle de vision peut se tromper. Les valeurs sont
   validées par type ; une valeur illisible reste absente.

---

## 2026-11-17 — J4 : overlay OBS, monitoring GPU, logo

- **Agent :** Cloud
- **Fichiers :** `modules/gaming_hud/obs_server.py`, `modules/gaming_hud/web/obs_hud.{html,css,js}`,
  `assets/logo_if_core.svg`, `assets/logo_if_core_mono.svg`, `tests/gaming_hud/test_obs_hud.py`,
  `docs/captures/obs_hud.png` ; modifiés : `modules/gaming_hud/module.py`, `pyproject.toml`,
  `requirements-dev.txt`, `THIRD_PARTY.md`, fichiers de suivi.
- **Tests :** `pytest` → 218 réussis, 2 ignorés (tests réels sur GPU) ; `ruff check .` propre.
- **Vérifications réelles :**
  1. Rendu dans Edge piloté par Playwright : textes, jauges, logo chargé, **fond transparent**, aucune
     erreur en console ; un nom contenant du HTML hostile est affiché tel quel, jamais interprété.
  2. Hub lancé, `gaming_hud` activé : `http://127.0.0.1:5757/obs-hud/state` rend le personnage réel et
     les deux GPU réels (charge, VRAM, température, puissance) ; écoute sur 127.0.0.1 ; aucun chemin,
     aucun dossier de compte, aucune clé `source_file` dans la réponse ; port libéré à l'arrêt.
- **Non vérifié :** l'affichage dans OBS lui-même ; la bascule déclenchée par le vrai `obs64.exe`.

### Décisions

1. **Serveur de l'overlay en bibliothèque standard**, dans le processus du module : pas de FastAPI ici,
   pour que le module reste léger et isolé du démon.
2. **La page est toujours filtrée en mode Showcase**, même si le module n'y est pas : elle est faite pour
   être diffusée. Le serveur ne lit qu'une fonction `snapshot()` fournie par le module.
3. **Liste fermée de fichiers servis** (pas de service de dossier) : aucune traversée de chemin possible.
4. **Politique de sécurité de page stricte** (`default-src 'none'`, scripts et styles de même origine
   seulement) et données écrites avec `textContent`.
5. **SSE plutôt que WebSocket** : unidirectionnel, sans dépendance, reconnexion gérée par le navigateur.
6. **Playwright pilote le navigateur déjà installé** (Edge ou Chrome) : pas de téléchargement de
   Chromium. Le test est ignoré si aucun navigateur n'est pilotable.
7. **Logo** : Yin & Yang géométrique, Inoue claire avec taches calico, Fuma sombre avec rayures
   argentées. Écrit à la main en SVG, remplaçable par un dessin définitif.

---

## 2026-11-17 — J5 (première partie) : genesis_lab

- **Agent :** Cloud
- **Fichiers :** `modules/genesis_lab/{__init__,bio,astro,chem,tutor,module}.py`, `manifest.json`,
  `tests/genesis_lab/test_calculs.py`, `test_tutor_module.py`, fichiers de suivi.
- **Tests :** `pytest` → 266 réussis, 2 ignorés ; `ruff check .` propre.
- **Vérifié :** chaque calcul contre une valeur de référence connue — année sidérale (365,2569 j), période
  de Mars, orbite géostationnaire (42 164 km), vitesse et période de l'ISS, vitesse de libération
  terrestre, rayon de Schwarzschild du Soleil, magnitudes absolues du Soleil et de Sirius, distance de
  Proxima ; masses molaires (H2O, CO2, glucose, Ca(OH)2, Al2(SO4)3…), volume molaire (22,414 L), pH de
  l'acide acétique 0,1 mol/L (2,875), K pour ΔG° = −RT ln 10 ; code génétique (64 codons, 3 stops),
  distance de Hamming et alignement de Needleman-Wunsch sur des exemples classiques.
  Module lancé dans le démon réel : calcul demandé sur le bus, résultat rendu.
- **Non vérifié :** le Professeur avec le modèle local réel (LLM factice dans les tests) ; la comparaison
  croisée avec Biopython ; la recherche de sources (aucune base vectorielle encore).
- **Erreur de test corrigée en route :** une valeur de référence de GC % était fausse dans mon test
  (9 bases G/C comptées au lieu de 10). Le code était juste ; le test a été corrigé, pas le code.

### Décisions

1. **Le code calcule, le LLM explique.** Les énoncés, les réponses et la correction viennent des fonctions
   déterministes. Le LLM reçoit la réponse déjà calculée, avec la consigne de ne pas la recalculer ; un
   garde-fou réinsère la valeur calculée si le texte du modèle l'omet.
2. **Aucune dépendance** pour les calculs (Biopython reste optionnel et n'est pas utilisé).
3. **Liste blanche d'outils** dans le module (`TOOLS`) : un nom d'outil venu d'un LLM ne peut désigner
   aucune autre fonction. Pas de `getattr` sur un nom reçu.
4. **L'énoncé d'un exercice est envoyé sans sa réponse** ; l'exercice est reconstruit côté module à partir
   de (domaine, niveau, graine) pour corriger.
5. **Adaptation simple et lisible** : deux réussites d'affilée font monter d'un niveau, deux échecs font
   descendre ; trois niveaux (débutant, intermédiaire, avancé) règlent le vocabulaire demandé au LLM.
6. **Unités dans les noms de fonctions** (`_m`, `_s`, `_kg`, `_pa`, `_k`, `_mol`) et refus des valeurs non
   physiques (négatives, nulles, non finies).

---

## 2026-11-17 — Professeur : essai réel et garde-fou sur les nombres

- **Agent :** Cloud
- **Fichiers :** `modules/genesis_lab/tutor.py`, `tests/genesis_lab/test_tutor_module.py`, suivi.
- **Essai réel** (`qwen3-27b:latest`, `num_ctx` 32 768, réponse fausse à un exercice de Kepler, niveaux
  débutant et avancé) : le vocabulaire s'adapte au niveau ; la valeur calculée par le code (89,0 jours) est
  conservée ; réponses en 5 à 11 s.
- **Défaut constaté pendant l'essai :** au niveau avancé, le modèle a écrit un calcul intermédiaire de son
  cru et faux (« racine cube de 0.059319 … 0.39 ans »), malgré la consigne de ne donner aucun autre nombre.
- **Correction :** `foreign_numbers` compare les nombres du texte à ceux fournis par le code (énoncé,
  réponse, démarche, réponse de l'élève). Un nombre étranger → le reproche précis est renvoyé au modèle
  une fois ; s'il recommence, son texte est écarté et l'explication type est donnée. Les petits entiers
  (exposants, « 3ᵉ loi ») sont admis ; « 89,0 » vaut « 89.0 ».
- **Après correction, même essai réel :** aucune explication ne contient de nombre étranger.
- **Limite connue :** le garde-fou contrôle les nombres, pas le sens des phrases. Une phrase fausse sans
  nombre nouveau passerait. Essai réel limité à un exercice et deux niveaux.
- **Tests :** `pytest` → 268 réussis, 2 ignorés ; `ruff check .` propre.

## 2026-11-17 — Lancement simple : lanceur .bat et tableau de bord

- **Agent :** Cloud
- **Fichiers :** `Lancer AetherTwin.bat`, `core/web/{dashboard.html,dashboard.css,dashboard.js,logo.svg}`,
  `core/api.py`, `core/daemon.py`, `config/local.example.yaml`, `tests/core/test_dashboard.py`,
  `tests/core/test_daemon.py`, `PROJECT_STATUS.md`. Hors dépôt : raccourci `AetherTwin.lnk` sur le bureau.
- **Raison :** Jérémy lançait `python -m core.daemon` depuis `.venv\Scripts` et `modules\gaming_hud\app` :
  `ModuleNotFoundError`, car `-m` exige la racine du projet. Le lanceur se place lui-même à la racine et
  utilise le Python du `.venv` ; il crée `config/local.yaml` depuis l'exemple s'il manque.
- **Ajouts :** page `/` (GPU, modules avec Lancer/Arrêter, assistant, Professeur, liens), CSP stricte, fichiers
  servis seulement depuis `core/web/` ; `Daemon.command()` et `POST /modules/{nom}/command/{cmd}` (attend la
  réponse `module.<nom>.result` portant le même `request_id`) ; options `--open` et `--activate` du démon ;
  si le port est déjà pris, le lanceur ouvre simplement le tableau de bord. Section `genesis_lab` dans
  l'exemple de configuration (explications par le modèle local via le Hub).
- **Tests :** ruff propre ; pytest vert. **Essai réel** : Hub lancé avec `gaming_hud` et `genesis_lab`,
  tableau de bord affichant les deux GPU réels, exercice de GC % corrigé, explication rédigée par
  `qwen3-27b` (~30 s, chargement compris).

## 2026-11-17 — J5 (2/2) : base vectorielle, collecte web polie, ingestion nocturne

- **Agent :** Cloud
- **Fichiers :** `core/knowledge/{__init__,store,fetcher,service}.py`, `config/knowledge_sources.yaml`,
  `config/allowlist.yaml` (`web_domains: wikipedia.org`), `config/local.example.yaml` (section `knowledge`),
  `core/guardians/fuma.py` (tâches de nuit récurrentes), `core/daemon.py`, `core/api.py` (`/knowledge`,
  `/knowledge/search`, `/knowledge/ingest`), `core/web/dashboard.*` (encadré Connaissances),
  `modules/genesis_lab/{module,tutor}.py` (`hub_search`, sources dédoublonnées), `.gitignore`, tests.
- **Choix :** SQLite et bibliothèque standard (pas de numpy ni de base externe) ; embedding par Ollama local,
  injectable ; un texte ajouté sans embedding est gardé sans vecteur et `reindex()` rattrape ; ingestion dans un
  fil séparé pour ne jamais bloquer le tour du démon.
- **Problèmes :** 1) l'extraction gardait les bandeaux de Wikipédia → filtre par classes ; 2) ce filtre, en
  sous-chaîne, masquait toute la page (`vector-toc-available`) → comparaison jeton par jeton, test ajouté ;
  3) en mode dégradé, « Code génétique » sortait pour « pH acide faible » → pondération idf, mots de 2 lettres,
  mots vides, bonus de titre ; 4) une même page citée deux fois → dédoublonnage.
- **Tests :** ruff propre ; pytest vert. **Réel** : 18 pages Wikipédia FR collectées depuis le tableau de bord
  (robots.txt respecté, 5 s d'écart), 377 passages ; recherche pertinente sur 5 sujets ; Professeur avec
  sources citées et explication de `qwen3-27b`. **Non vérifié** : vecteurs réels (aucun modèle d'embedding).

## 2026-11-17 — J6 : scantrad, traduction locale de manga

- **Agent :** Cloud
- **Fichiers :** `modules/scantrad/{__init__,__main__,cli,detect,hub_stages,module,pipeline,testpage,typeset}.py`,
  `modules/scantrad/{manifest.json,README.md}`, `tests/scantrad/`, `tests/data/scantrad/page_test.{png,json}`,
  `docs/captures/scantrad_page_test_fr.png`, `core/api.py` (`num_ctx`, `think`, `temperature` sur
  `/v1/chat/completions`), `requirements.txt` (opencv-python-headless 5.0.0.93, numpy 2.4.6),
  `Lancer AetherTwin.bat` (entrée 4), `.gitignore`, `core/knowledge/service.py`, suivi.
- **Choix :** OCR par le modèle de vision local via le Hub plutôt que manga-ocr (pas de PyTorch) ; détection et
  effacement OpenCV (repli prévu par le prompt maître) ; un appel de traduction par page avec glossaire filtré ;
  chaque étape est un objet remplaçable de `Scantrad`.
- **Problèmes :** 1) `data/` dans `.gitignore` excluait aussi `tests/data/` → règles ancrées `/data/`, `/cache/` ;
  2) cela rendait visible le cache de WoW Assistant (instantané du personnage) → `modules/**/cache/` exclu,
  vérifié par `git check-ignore` ; 3) un commentaire en fin de ligne de `.gitignore` fait partie du motif →
  commentaire sur sa propre ligne ; 4) une collecte après l'installation du modèle d'embedding n'aurait jamais
  calculé les vecteurs des pages inchangées → rattrapage automatique, testé.
- **Tests :** ruff propre ; pytest vert. **Réel** : page de test, 5 bulles dans l'ordre manga, OCR exact,
  traduction naturelle, 23,6 s, VRAM au plus haut 26 153 MiB. Sans Hub : message clair, code 2.
  **Non vérifié** : vraie page scannée ; entrée 4 du lanceur jouée de bout en bout.

## 2026-11-17 — scantrad sur une vraie page : détection par le texte

- **Agent :** Cloud
- **Constat de Jérémy (test 13) :** sur une vraie page, peu de bulles prises et texte d'origine non effacé.
- **Cause :** l'heuristique cherchait des bulles **fermées** sur fond **blanc** ; sur un scan, le papier est gris
  (95e centile à 221), les bulles sont ouvertes et le texte est vertical : une seule bulle trouvée, et deux
  faux positifs (jambe, cheveux) sur lesquels la traduction a été posée.
- **Fichiers :** `modules/scantrad/{detect,pipeline,hub_stages,typeset,cli}.py`, `README.md`, tests.
- **Changements :** `detect_text_blocks` (encre de taille « caractère » sur papier clair, densité d'encre,
  regroupement, fusion des colonnes d'une même bulle), agrandissement des petites pages, l'OCR écarte les faux
  positifs (« AUCUN », pas de japonais) avec une seconde lecture plus large, effacement de l'encre fine
  seulement (masque élargi d'un demi-caractère pour la ponctuation), zone d'écriture = plage claire de la
  bulle, ponctuation française insécable. Une tentative d'élargir les boîtes elles-mêmes a fusionné des
  bulles voisines et effacé du dessin : annulée, seul le masque d'effacement est élargi.
- **Tests :** ruff propre ; pytest vert. **Réel** (page de Jérémy, non versionnée) : 4 bulles traduites,
  7 faux positifs écartés, dessin intact ; ratés : texte manuscrit et texte rogné au bord.

## 2026-11-17 — Hub tout-en-un dans le navigateur (onglets)

- **Agent :** Cloud
- **Demande de Jérémy :** tout faire depuis le navigateur, en onglets, et lancer WoW Assistant depuis le Hub.
- **Fichiers :** `core/web/dashboard.{html,css,js}`, `core/api.py`, `core/daemon.py`, `core/module_api.py`
  (champ `app` du manifeste), `modules/gaming_hud/manifest.json`, `Lancer AetherTwin.bat` (plus de menu),
  `tests/core/{test_dashboard,test_module_api,sleeper}.py`, `tests/scantrad/test_scantrad_module.py`, suivi.
- **Ajouts :** onglets Accueil, Jeu, Assistant, Professeur, Connaissances, Scantrad, Journal ; application de
  bureau d'un module (`app` : un module Python validé, jamais une commande libre ; une seule instance ; fermée
  avec le Hub) ; dernier état publié par module (`/modules/{nom}/state`) ; commande sans réponse
  (`/notify`, bascule Showcase) ; envoi d'image à scantrad (`/scantrad/translate`, 25 Mo max, PNG/JPEG/WebP,
  fichiers servis seulement depuis `data/scantrad/{entrees,sorties}`) ; glossaire éditable ; arrêt du Hub
  (`/shutdown`) ; le Professeur lance son module à la demande ; le démon attend qu'un module fraîchement lancé
  écoute le bus avant de lui envoyer une commande.
- **Problème :** `display: grid` des panneaux annulait l'attribut `hidden` → règle `[hidden]` explicite.
- **Tests :** ruff propre ; pytest vert. **Réel** : onglets affichés, état du personnage et Showcase actif
  (OBS ouvert), WoW Assistant ouvert puis fermé depuis l'onglet Jeu (fenêtre vérifiée), page traduite par
  envoi HTTP (4 bulles, 34,7 s), arrêt du Hub par le bouton sans processus restant. **Non vérifié** : envoi
  d'image depuis le sélecteur de fichier du navigateur (testé par l'API seulement) ; WoW Assistant est fermé
  brutalement (`terminate`), un réglage non enregistré serait perdu.

## 2026-11-17 — J7 (1/2) : mangastudio, HandSegNet et FootSegNet réels

- **Agent :** Cloud
- **Fichiers :** `modules/mangastudio/{__init__,segment,module}.py`, `manifest.json`, `README.md`,
  `comfyui_nodes/__init__.py`, `workflows/continuity.json`, `core/api.py` (`/mangastudio/*`, helpers d'envoi
  et de service d'images partagés avec scantrad), `core/web/dashboard.*` (onglet Studio), `.gitignore`
  (`/models/`), `tests/mangastudio/`, `tests/core/test_dashboard.py`.
  Aussi : `modules/genesis_lab/tutor.py` (le Professeur ne félicite plus une réponse fausse, constat du test 12).
- **Fiches des modèles lues** (Hugging Face et GitHub de Jérémy) : SAM ViT-B, décodeur de masque affiné,
  une boîte par appel, masque binaire, Apache 2.0 (le GitHub de HandSegNet affiche MIT dans sa barre latérale :
  à vérifier par Jérémy). Aucun nœud ComfyUI n'existait dans ces dépôts.
- **Installé dans `.venv`** (à la demande de Jérémy : « tout récupérer ») : torch 2.11.0+cu128,
  torchvision 0.26.0+cu128, segment-anything 1.0, safetensors 0.8.0 ; numpy et pillow inchangés.
  **Téléchargé** dans `models/mangastudio/` (ignoré par Git) : `handsegnet_vit_b_best.safetensors` et
  `footsegnet_vit_b_best.safetensors`, 374 979 240 octets chacun.
- **Tests :** ruff propre ; pytest vert. **Réel** : HandSegNet sur RTX 5080, 21,8 s au premier appel
  (chargement et initialisation CUDA), 0,17 s ensuite, 2 772 MiB alloués ; nœud ComfyUI exécuté hors ComfyUI
  avec le vrai modèle ; Studio par le Hub (envoi + segmentation, score 0,71, 9,1 s modèle compris).
  **Non vérifié** : tracé des boîtes à la souris dans le navigateur ; workflow de continuité dans un vrai
  ComfyUI (structure seulement) ; FootSegNet sur une image réelle (chargement vérifié par l'état seulement).

## 2026-11-17 — J7 (2/2) : if_game, « Fuma & Inoue : Les Gardiens de l'Éther »

- **Agent :** Cloud
- **Fichiers :** `modules/if_game/{__init__,world,module}.py`, `manifest.json`, `core/web/dashboard.*`
  (onglet Éther), `tests/if_game/`, suivi.
- **Principe :** le monde est un JSON (`World`) que seul le code modifie ; les actions sont analysées par le
  code ; un lieu ou une réplique proposés par le modèle sont validés (forme, longueurs, mots durs refusés) et,
  refusés, remplacés par le générateur procédural déterministe (graine). Pas de combat ni d'échec punitif :
  énergie qui baisse en marchant, repos proposé par Fuma, indice si l'énigme est ratée. Sauvegarde atomique
  après chaque action (`data/if_game/partie.json`), sauvegarde incohérente refusée.
- **Tests :** ruff propre ; pytest : 364 réussis, 4 réels ignorés par défaut. **Réel** : onglet Éther, lieu
  « Jardin des Brumes Douces » inventé par `qwen3-27b` et accepté, réplique de Fuma par le modèle (le nom du
  gardien est désormais ajouté devant). Une fausse manœuvre de ma part a relancé une partie pendant l'essai.

## 2026-11-17 — J8 (1) : installation vérifiée sur un clone vierge, rendu HD-2D du jeu

- **Agent :** Cloud
- **Installation vierge :** clone du dépôt dans un dossier temporaire, `scripts\setup.ps1` (75 s), puis toute la
  suite : tout passe sauf la carte d'architecture, qui listait des fichiers **ignorés par Git** présents
  seulement sur le poste de Jérémy (`settings.json`, `history.json`, `activity.json` de WoW Assistant,
  `config/local.yaml`). Correction : `scripts/gen_architecture_map.py` filtre par `git check-ignore -z`
  (une première version sans `-z` recevait des chemins entre guillemets et ne filtrait rien).
- **Licence HandSegNet/FootSegNet :** poids sous Apache 2.0 (Hugging Face), code d'inférence des dépôts
  GitHub sous MIT ; le README GitHub de FootSegNet dit Apache 2.0 pour l'ensemble. Noté dans le README du
  module.
- **Rendu HD-2D** (`core/web/ether_scene.js`, onglet Éther) : Canvas 2D sans bibliothèque ; monde en pixel art
  320×180 avec sol en perspective (« mode 7 »), décors en panneaux, ombres, collines en parallaxe, gardiens
  au premier plan ; effets HD par-dessus : flou de profondeur (maquette), halo, lumières additives
  (lanternes, cristaux, portails, lucioles, lumière d'Inoue qui suit son énergie), vignettage. Six ambiances
  choisies par les mots du lieu (lac, bibliothèque, observatoire, grotte, jardin, sanctuaire), disposition
  reproductible (graine + lieu). Les sorties sont des portails cliquables. `view()` transmet `place_id` et
  `description`. Captures : `docs/captures/ether_hd2d_{jardin,lac}.png`.
- **Problèmes du rendu corrigés à l'œil :** gardiens hors champ (trop près), décors minuscules, mur de brume
  à l'horizon, halo d'Inoue qui l'effaçait, étiquette « sud » sur Inoue.
- **Tests :** ruff propre ; pytest vert. Rendu vérifié dans le navigateur (jardin, grotte, bibliothèque, lac).
  **Non vérifié** : fluidité sur une autre machine ; navigation au clic sur un portail (testée par les
  boutons, pas par le clic dans la scène).

## 2026-11-17 — J8 (2) : réponse mot à mot, installation enrichie, jeu au clic

- **Agent :** Cloud
- **Fichiers :** `core/llm_router.py` (`http_stream`, `chat_stream`), `core/daemon.py` (`ask_messages`),
  `core/api.py` (`POST /ask/stream`, NDJSON), `core/web/dashboard.js` (lecture du flux),
  `core/web/ether_scene.js` (fondu d'arrivée, `portals()`), `scripts/setup.ps1` (`-Gpu`, `-Weights`,
  `-Shortcut`, vérification d'Ollama et des modèles, enregistré avec BOM pour PowerShell 5.1),
  `requirements-gpu.txt`, tests.
- **Diffusion mot à mot :** même réservation VRAM et même verrou que `chat` ; la génération tourne dans un fil
  dédié qui remplit une file (le verrou est pris et rendu par le même fil). **Réel** (Hub d'essai sur le port
  5751 pour ne pas toucher celui de Jérémy) : premier mot à 16,0 s (chargement de `qwen3-27b` compris), fin à
  18,4 s, environ 30 morceaux par seconde.
- **Jeu :** clic réel sur le portail « est » dans la scène : nouveau lieu inventé par le modèle et affiché.
- **Accents de `setup.ps1` :** PowerShell 5.1 lit un `.ps1` sans BOM en ANSI (« SystÃ¨me » dans le journal de
  l'installation vierge) : fichier réenregistré en UTF-8 avec BOM.
- **Tests :** ruff propre ; pytest vert.

## 2026-11-17 — J8 (3) : vérifications

- **Agent :** Cloud
- **Professeur, réel** (Hub d'essai, port 5751) : deux réponses fausses (8,33 au lieu de 33,33 et de 50,0) ;
  les explications ne félicitent plus et montrent l'erreur probable. Correctif du 17/11 confirmé.
- **Carte d'architecture sur clone neuf** du dernier commit : à jour (l'échec précédent venait d'un commit
  fait avant régénération). Dossiers de vérification supprimés (environ 3 Go).
- **Suivi :** `PROJECT_STATUS.md` (J8 en cours, tests 8, 15, 16).

## 2026-11-17 — J8 (4) : corrections de scantrad, mains automatiques, budget VRAM visible

- **Agent :** Cloud
- **Fichiers :** `modules/scantrad/{pipeline,module}.py` (page nettoyée et `_travail.json` gardés, commande
  `retypeset`), `modules/mangastudio/grounding.py` (nouveau), `core/api.py` (`/scantrad/retypeset`,
  `/mangastudio/detect`), `core/web/dashboard.*` (bulles éditables, bouton « Détecter automatiquement »,
  encadré Budget VRAM), tests, suivi.
- **Mains automatiques :** Qwen2.5-VL répond dans l'espace de l'image qu'il reçoit ; Ollama la redimensionne
  vers environ 1 Mpx (premier essai : coordonnées hors de l'image, 663 pour une largeur de 443). L'image est
  désormais envoyée déjà à cette taille (980×1008 pour 443×451) et les boîtes sont ramenées à l'original,
  élargies de 12 %. **Réel** : 5 boîtes en 2,6 s, 5 masques HandSegNet en 10,5 s modèle compris ; deux
  masques débordent sur un manteau et une cape.
- **Tests :** ruff propre ; pytest : 369 réussis, 4 réels ignorés par défaut. Budget VRAM vérifié sur le Hub
  de Jérémy. **Non vérifié** par Jérémy : correction des traductions, détection automatique.

## 2026-11-17 — J8 (5) : conversation, fermeture douce, journal du Hub, son du jeu

- **Agent :** Cloud
- **Fichiers :** `core/daemon.py` (`stop_app` doux puis forcé, `ask_messages(history)`, `setup_journal`),
  `core/api.py` (`history` dans `/ask/stream`, `closed` à l'arrêt d'une application),
  `core/web/dashboard.*` (conversation, rendu Markdown sans innerHTML, bouton Son),
  `core/web/ether_scene.js` (`createAudio`), `.gitignore` (`logs/hub.log*`), tests, suivi.
- **Réel :** WoW Assistant fermé « doucement » en 1,98 s (`taskkill` sans `/F`) ; conversation à deux tours
  correcte ; journal écrit au démarrage et à l'arrêt par le bouton. Son : activé et coupé sans erreur dans la
  console, mais pas écouté.
- **Tests :** ruff propre ; pytest : 370 réussis, 4 réels ignorés par défaut.

## 2026-11-17 — J8 (6) : flux OpenAI, laboratoire FASTA

- **Agent :** Cloud
- **Fichiers :** `core/api.py` (`stream_pieces` partagé, `/v1/chat/completions` avec `stream: true` en SSE),
  `core/web/dashboard.*` (laboratoire FASTA dans l'onglet Professeur), `tests/core/test_llm_router.py`, suivi.
- **Réel :** flux SSE de `qwen3-27b` reçu par `curl` (rôle, contenu, fin, `[DONE]`) ; analyse FASTA de
  l'exemple (début du gène de la GFP, séquence publique) : 1 ORF de 53 acides aminés, protéine correcte.
  L'exemple avait d'abord été décrit à tort comme « écrit pour le projet » : commentaire corrigé.

## 2026-11-17 — J8 (7) : sécurité de l'API, chapitre entier dans scantrad

- **Agent :** Cloud
- **Sécurité :** le Hub n'écoutait que sur 127.0.0.1, mais un site ouvert dans le navigateur pouvait lui envoyer
  un formulaire POST (arrêter le Hub, lancer un module ou WoW Assistant) ; un nom de domaine pointant sur
  127.0.0.1 permettait aussi de le joindre (DNS rebinding). Intergiciel `local_only` dans `core/api.py` :
  hôte local exigé, écritures refusées si `Origin` n'est pas local ou si `Sec-Fetch-Site: cross-site`.
  Tests paramétrés (7 cas) ; tableau de bord vérifié en réel.
- **Chapitre :** plusieurs pages traduites à la suite (ordre naturel des noms), galerie, correction par page.
  L'essai a révélé un bogue : `event.submitter` est vide quand le formulaire part sans clic (touche Entrée,
  envoi par programme) ; le bouton est pris dans le formulaire.
- **Détection :** « だよ » (page de test) restait à demi visible, séparé de « 星がきれい » par un trou plus large
  que le seuil (kana en plusieurs traits). Un caractère isolé rejoint désormais un bloc en forme de ligne ou
  de colonne, aligné, à moins de 1,5 caractère, 3 au plus, sans enchaînement. **Première tentative ratée** :
  rattachement en chaîne → grands blocs sur le dessin, que l'OCR a lus en voyant le texte d'une bulle voisine
  dans la marge de découpe → « Ce monde » et « Mariage » posés sur l'image. Corrigé aussi côté OCR : la marge
  de découpe est blanchie au-delà d'une petite bordure. Vraie page revenue à 4 bulles, 7 faux positifs écartés.
- **Tests :** ruff propre ; pytest vert (2 tests de non-régression ajoutés).

## 2026-11-17 — J8 (8) : assistant appuyé sur la base, déchargement d'un modèle, domaine des modèles

- **Agent :** Cloud
- **Fichiers :** `core/daemon.py` (`ask_messages(passages)`), `core/api.py` (`use_knowledge`, `relevant_passages`,
  `POST /llm/unload`), `core/web/dashboard.*` (case « chercher dans la base », sources sous la réponse, bouton
  « Décharger »), `modules/mangastudio/README.md` (domaine SDXL), `AGENT_HANDOFF.md`, tests, suivi.
- **Calibrage mesuré** sur la base réelle : couvert 0,70-0,81, hors sujet 0,55-0,61 → seuil 0,65 et 0,08 sous le
  meilleur. Préfixes `search_query:`/`search_document:` essayés sur une copie réindexée : pas de meilleure
  séparation (hors sujet jusqu'à 0,64), non retenus.
- **Réel :** « un parsec vaut environ 3,26 années-lumière [1] » avec la page Parsec en source ; question sur les
  crêpes : aucune source jointe, réponse de culture générale.
- **Domaine :** HandSegNet/FootSegNet entraînés uniquement sur des images SDXL (précision de Jérémy) : noté.
- **Tests :** ruff propre ; pytest vert.

## 2026-11-22 16h55 — Retours de Jérémy sur les tests 15 à 19

- **Agent :** Cloud
- **Fichiers :** `PROJECT_STATUS.md`, `logs/CHANGELOG_DEV.md`
- **Retours :** 15 (HD-2D) OK, sans saccade ; 16 (mot à mot) OK ; « Décharger » OK. 17 (Scantrad) : marche,
  mais la détection a des limites → demande d'un mode manuel (zones à la souris dans l'ordre de lecture,
  gomme blanche, réincrustation). 18 (Studio) : marche aussi sur photos, masque parfois trop large → « en cours ».
  19 (son) : à différencier par type de lieu, ajouter un volume. La case numérique de l'onglet Éther est la graine
  de « Nouvelle partie » (non expliquée à l'écran).
- **Constat sur sa capture de l'Accueil :** VRAM mesurée 29,83 Go pour un budget de 28,66 Go : Inoue compte les
  réservations déclarées mais ne refuse rien sur la base de la mesure réelle.
- **Tests :** aucun code modifié.
## 2026-11-22 soir — Scantrad : mode manuel (demande de Jérémy, test 17)

- **Agent :** Cloud
- **Fichiers :** `modules/scantrad/manual.py` (nouveau), `modules/scantrad/module.py`, `modules/scantrad/hub_stages.py`,
  `core/api.py`, `core/web/dashboard.{html,js,css}`, `tests/scantrad/test_manual.py`, `tests/scantrad/test_scantrad_module.py`
- **Quoi :** onglet Scantrad, section « Mode manuel » : envoi d'une page, zones tracées à la souris (numérotées
  dans l'ordre de tracé = ordre de lecture, réordonnables), « Partir de la détection automatique » en option,
  « Lire le texte » (OCR par zone), « Traduire », gomme blanche à taille réglable avec annulation, « Aperçu de
  l'effacement », « Réincruster ». Le texte resté dans les zones est effacé automatiquement (case à décocher).
  La correction ligne à ligne existante marche aussi sur ces pages.
- **API :** `POST /scantrad/upload`, `POST /scantrad/manual/{suggest,read,translate,erase,compose}`,
  `POST /scantrad/manual/cleaned?image=` (page gommée, PNG). Noms de fichiers contrôlés comme avant.
- **Essai réel :** sur la page de Jérémy, Hub lancé sur 5750 (le sien était arrêté). Premier essai : le bloc
  horizontal de 3 lignes lu « AUCUN » → consigne `MANUAL_OCR_PROMPT` sans cette échappatoire (la zone est posée
  par l'utilisateur, il y a du texte) : 2 zones lues. Fantôme gris après effacement → l'encre et son halo clair
  sont recouverts de la couleur du papier sur une bulle blanche (inpainting gardé sur trame).
- **Tests :** 7 nouveaux ; suite complète verte, ruff propre.
## 2026-11-22 soir — Inoue tient compte de la VRAM mesurée

- **Agent :** Cloud
- **Fichiers :** `core/guardians/inoue.py`, `core/web/dashboard.{html,js}`, `tests/core/test_guardians.py`
- **Pourquoi :** capture de l'Accueil de Jérémy : 29,83 Go mesurés pour 28,66 Go de budget (RTX 5060 Ti à 99 %).
  Inoue ne comptait que les réservations ; le reste (embedding appelé hors routeur, contexte CUDA de
  `mangastudio`, navigateur, jeux) lui échappait.
- **Quoi :** place libre = budget − max(réservé, mesuré). État : `unaccounted_gb`, `over_budget`. L'Accueil
  affiche la part hors réservations et une alerte au-dessus du budget.
- **Réel :** Hub relancé ; à vide 1,9 Go mesurés (bureau) ; `qwen3-27b` chargé par `/ask` : 18,0 Go réservés,
  19,0 mesurés, 9,6 Go libres annoncés.
- **Tests :** 1 nouveau ; suite verte.
## 2026-11-22 soir — Jeu : vue RPG 16 bits, chats, minicarte, sons par lieu (carte blanche de Jérémy)

- **Agent :** Cloud
- **Fichiers :** `core/web/ether_scene.js` (réécrit), `core/web/dashboard.{html,js}`, `modules/if_game/world.py`,
  `tests/if_game/test_if_game.py`
- **Demande :** que le jeu ressemble davantage à FF6, Chrono Trigger ou Seiken Densetsu (style seulement : rien
  n'est repris, tout est dessiné par le code), Fuma et Inoue en chats, minicarte (les mondes sont fixés par la
  graine), ambiance sonore propre à chaque type de lieu, réglage du volume, graine expliquée.
- **Moteur :** chaque lieu a une case `[x, y, niveau]` ; un chemin vers une case déjà connue y mène (dans les
  deux sens) au lieu d'en recréer une ; un nouveau lieu se raccorde à ses voisins. `view()` donne `map`, `pos`
  et `bag` (sac regroupé : « Une plume de nuage » = « plume de nuage »). Anciennes sauvegardes : positions
  déduites des chemins (sur la partie de Jérémy : 50 lieux, 2 chemins historiques non alignés, sans perte).
- **Rendu :** vue de dessus 320×180 ×3, tuiles 16 px, 11 décors choisis par le premier mot-clé du nom
  (« Jardin des Larmes de Lune » est un jardin), jour / crépuscule / nuit, lumières (réverbères, cristaux,
  queue d'Inoue selon son énergie), eau animée, particules, bannière du lieu, fenêtre de dialogue, étiquettes
  des sorties, minicarte (M). Fuma : flèches / ZQSD ou clic ; Inoue suit ; Espace lit une stèle ou parle à Inoue.
- **Son :** 11 ambiances (accords, timbre, motif, bruits) + carillon ; volume (curseur, retenu localement).
- **Vérifié :** dans le navigateur, 7 décors, déplacement au clavier et à la souris, passage nord vers un lieu
  inventé par `qwen3-27b`, son activé sur 7 ambiances sans erreur (pas écouté). La partie de Jérémy a été
  sauvegardée avant l'essai et restaurée à l'identique (empreinte vérifiée).
- **Tests :** 3 nouveaux (grille, conversion des sauvegardes, carte et sac) ; suite verte.
## 2026-11-22 nuit — Retours des tests 20 à 23 : Inoue à distance, colonnes lues une à une, zones étroites

- **Agent :** Cloud
- **Fichiers :** `core/web/ether_scene.js`, `modules/scantrad/{manual,module,hub_stages}.py`,
  `tests/scantrad/test_manual.py`, `PROJECT_STATUS.md`
- **Jeu (test 21) :** Inoue collait à Fuma, impossible de lui faire face pour lui parler. Elle suit désormais
  avec deux pas de retard, sa case arrête Fuma (il s'arrête devant elle), et Espace lui parle si elle est devant
  ou juste à côté (Fuma se tourne vers elle). Les déplacements à la souris la contournent. Vérifié dans le
  navigateur : réplique d'Inoue obtenue par Espace. Partie de Jérémy sauvegardée puis restaurée (empreinte).
- **Scantrad, mode manuel (test 20, sur sa capture) :**
  - bulle de 4 colonnes courtes lue dans le désordre : le sens du texte est mesuré sur l'encre (largeur des
    espaces entre colonnes / entre lignes) ; un texte vertical est découpé en colonnes, lues une par une de
    droite à gauche puis recollées. Réel sur sa page OPM : 6 zones sur 6 justes (dont « 貴様ら人間は地球の命を
    蝕み続ける病原菌に他ならない », lu auparavant « 他病蝕地人貴原み… ») ; une consigne « colonnes » seule
    ou des recadrages plus serrés ou plus grands ne suffisaient pas (essayés) ;
  - texte minuscule dans les zones étroites (« Je suis Vaccine Man. ») : la zone d'écriture s'élargit dans le
    papier clair autour de la colonne. Recomposé hors de ses fichiers : lisible.
- **Tests :** 3 nouveaux ; suite verte.
## 2026-11-22 nuit (2) — Scantrad : enregistrer, lecture par colonnes en automatique, mesure par les pages manuelles ; documents remis à jour

- **Agent :** Cloud
- **Fichiers :** `core/web/dashboard.{html,js}`, `core/api.py`, `modules/scantrad/{detect,manual,module,hub_stages,cli}.py`,
  `modules/scantrad/README.md`, `tests/scantrad/*`, `PROJECT_STATUS.md`, `AGENT_HANDOFF.md`, `README.md`
- **Enregistrer :** « Enregistrer cette page traduite », « Enregistrer tout le chapitre » (automatique) et
  « Enregistrer l'image » (manuel) : téléchargement du navigateur sous `<nom d'origine>_fr.png`. Non cliqués
  dans un vrai navigateur.
- **Apprentissage par les pages manuelles (question de Jérémy) :** chaque page réincrustée en manuel garde
  `mode: manuel`, la page source et la série dans son `_travail.json` ; `python -m modules.scantrad --evaluate`
  mesure la détection automatique (bulles retrouvées, fausses détections, ordre). Les deux pages manuelles de
  Jérémy ont été marquées. Premier constat sur sa double page OPM : 8/8 bulles retrouvées, ordre 4/7.
- **Corrections guidées par cette mesure :** double page lue page de droite d'abord ; rangées par recouvrement
  réel (au lieu de bandes fixes) ; fusion de blocs bornée (deux bulles reliées par des onomatopées étaient
  fusionnées : texte posé sur le visage de Saitama dans sa capture) → ordre 7/7. Une borne de largeur pour le
  texte vertical a été essayée, sans effet, et retirée.
- **Lecture par colonnes en automatique :** une première lecture (avec « AUCUN ») trie les faux positifs, puis
  un bloc vertical de plusieurs colonnes est relu colonne par colonne. Colonnes parasites écartées (traces plus
  grandes qu'un caractère, ou collées au bord du cadre : contour de bulle). Réel sur la double page : 8 bulles
  lues justes (la 3 perd « である »). Reste : en automatique, un bloc qui englobe du dessin l'abîme à
  l'effacement et le texte peut déborder dessus (le mode manuel règle ces pages).
- **Documents :** lignes périmées corrigées (Fuma, ordonnanceur — réellement inutilisé, signalé —, `/ask`, OBS
  réel, vecteurs, test 15, liste « Reste à faire ») ; README provisoire : tableau d'état, lancement, vérifié /
  non vérifié ; AGENT_HANDOFF : situation au 22/11. Le changelog, historique, n'est pas réécrit.
- **Tests :** 404 (400 verts, 4 réels ignorés) ; ruff propre.
## 2026-11-22 nuit (3) — Langues, annexes, export texte, onglet Traduction, serveurs IA multiples

- **Agent :** Cloud
- **Quoi :** Scantrad en japonais, chinois, coréen, anglais (`modules/scantrad/languages.py`), type de page
  simple / double, « Gommer les bulles (1 clic) », zones annexes (contour blanc ou effacement), export .txt ;
  onglet **Traduction** (`core/translate.py`, `/translate/{text,image,voice}`) ; WoW Assistant : liste de serveurs
  IA actifs / inactifs ; `Installer AetherTwin.bat` (Bypass pour ce lancement seulement) et `setup.ps1 -Voice` ;
  interface plus aérée ; Inoue ne compte plus deux fois un modèle déjà chargé par un autre client (trouvé en réel).
- **Réel :** traduction japonais et coréen, image de manga lue puis traduite (la consigne « AUCUN » retirée).
  Non essayés : pages chinoises / coréennes / anglaises, voix (faster-whisper non installé), boutons d'export.
- **Tests :** 419 (415 verts, 4 réels ignorés) ; ruff propre.
## 2026-11-22 nuit (4) — LaMa, outil Reconstruire, import .txt, voix installée, fournisseurs des serveurs IA

- **Agent :** Cloud (accords de Jérémy : installer la voix, télécharger LaMa, l'inscrire dans requirements.txt)
- **LaMa :** `Carve/LaMa-ONNX` (`lama_fp32.onnx`, Apache 2.0, 198 Mo, `models/scantrad/`, aussi par
  `setup.ps1 -Weights`), `onnxruntime==1.32.0` dans `requirements.txt`, sur le processeur. `modules/scantrad/lama.py`
  découpe chaque zone avec du contexte, reconstruit en 512, ne recolle que les pixels masqués. Comparé sur la page
  OPM : sur papier blanc, le remplissage existant est plus propre (LaMa y laisse un fantôme) ; sur le dessin
  (« メキ »), LaMa prolonge les hachures là où OpenCV fait des taches. D'où : LaMa pour les bulles sur trame, les
  annexes « effacer » (traits épais seulement) et le nouvel outil **Reconstruire** (peindre en rouge, « Redessiner »).
  Réel : « ザ » retirée de la page OPM2 dans le navigateur.
- **Import .txt :** format de l'export ; automatique : pages du même nom, réincrustées ; manuel : zones de même
  numéro. Réel : le fichier de Jérémy importé dans le mode manuel (3 / 3).
- **Voix :** faster-whisper 1.2.1 installé ; réel : message anglais synthétisé (voix Windows) retranscrit mot pour
  mot, 17 s au premier appel (téléchargement du modèle `small`), 3 s ensuite.
- **WoW Assistant :** fournisseur de chaque serveur (deviné par le port, un clic pour changer), affiché sur les
  modèles. À recopier dans `D:\Hermes-Agent`.
- **Suivi :** retours des tests 25 à 29 ; tests 30 à 33 ; idée ComfyUI simplifié notée pour après le dépôt ;
  THIRD_PARTY.md (onnxruntime, faster-whisper, LaMa, Whisper).
- **Tests :** 422 (418 verts, 4 réels ignorés) ; ruff propre.
## 2026-11-22 nuit (5) — Zoom du mode manuel, consigne de traduction (formules, noms), glossaire expliqué

- **Agent :** Cloud
- **Zoom :** molette sur l'image du mode manuel, de la page entière à la taille réelle (pas au-delà), point visé
  gardé sous la souris, vue qui défile. Vérifié dans le navigateur : 898 → 1601 px et retour ; une zone tracée
  en vue zoomée tombe au bon pixel. Premier ajustement recalculé à l'image suivante (onglet pas encore à sa taille).
- **Traduction :** test 33 de Jérémy (« ジェルミ » → « Jermi », « よろしくお願いします » → « Merci de votre
  bienveillance »). Consigne ajoutée (formules toutes faites par leur équivalent français, noms étrangers dans leur
  graphie d'origine), mesurée avec `qwen3-27b` sur 4 phrases : « Gelmi » → « Jérémy », « いただきます » « Je vous
  remercie » → « Bon appétit ». Aussi dans la consigne de Scantrad (plus : onomatopées par un équivalent court).
- **Glossaire :** texte d'explication et exemple dans le champ « Ton ».
- **Tests :** suite verte.
## 2026-11-22 nuit (6) — WoW Assistant : Hôtel des ventes, addons existants, rendus officiels, Mythique+

- **Agent :** Cloud (champ libre donné par Jérémy)
- **Fichiers :** `modules/gaming_hud/app/` : `bnet.py`, `media.py`, `addon_data.py`, `tabs_market.py` (nouveaux),
  `ui.py`, `tabs.py`, `tabs_collections.py`, `tabs_data.py`, `game_connection.py`, `gamedata.py`,
  `character.py`, `main.py`, `README.md` ; addon `HermesAssistant` 1.7 ; tests `tests/gaming_hud/test_market.py`,
  `test_addon_lua.py` ; `requirements-dev.txt` (lupa), `THIRD_PARTY.md`.
- **Modèles 3D :** le 17/11, abandonnés faute de source. Source trouvée : l'**API Battle.net** de Blizzard
  (officielle, client gratuit) donne le rendu du personnage tel qu'il est équipé et l'image des montures. Branchée
  à la place des silhouettes (téléchargement en arrière-plan, cache, erreur affichée sans planter). Un modèle qui
  tourne demanderait d'extraire les fichiers du jeu (outil tiers comme wow.export, puis un moteur 3D dans l'appli)
  ou une visionneuse web tierce : écarté pour l'instant (lourd, et zone grise vis-à-vis des droits de Blizzard).
- **Hôtel des ventes :** nouvel onglet. Prix de trois sources : Battle.net (marchandises de la région + objets du
  royaume connecté, prix « du marché » = moyenne des 15 % les moins chers), TradeSkillMaster (données de
  l'application TSM), Auctionator (scans, avec historique). Valeur des sacs et des banques, recherche, courbe,
  conseil de vente par Hermes.
- **Addons existants :** lecteurs dédiés TSM et Auctionator (formats déduits de leurs fichiers, lecteurs tolérants,
  **non vérifiés sur de vraies données** : Jérémy n'a que HermesAssistant et ElitePlayerFrame) ; explorateur
  générique des SavedVariables de n'importe quel addon, vérifié en réel sur ses deux addons.
- **Fonction oubliée :** Mythique+ (cote, clé, donjons, semaine) exporté par l'addon 1.7 et affiché dans l'onglet
  Instances ; la région du compte aussi (règle Battle.net). L'addon est maintenant **compilé à chaque lancement de
  la suite** et sa collecte M+ exécutée contre de fausses API du jeu (lupa) : on le modifiait sans pouvoir le lancer.
- **Bogue trouvé par les tests :** les rendus de Blizzard viennent de `render.worldofwarcraft.com`, refusé par la
  première liste d'hôtes.
- **Tests :** 13 nouveaux ; suite verte ; ruff propre.
## 23/11/2026 : WoW Assistant, plantage au démarrage
- `main.py` appelait `WoWConfig.BASE_DIR` (variable du module `config`, pas de la classe) : AttributeError au lancement, signalé par Jérémy après copie dans Hermes-Agent. Corrigé (import de `BASE_DIR`). FAIT-TESTÉ : lancement réel 12 s sans erreur.
- Nouveau test `tests/gaming_hud/test_config_refs.py` : tout `WoWConfig.X` utilisé existe (échoue sans le correctif).


## 23/11/2026 : WoW Assistant, banque du personnage et aperçus des Collections
- Tests 36 à 39 : **OK (Jérémy)**. Il choisit de s'en tenir aux images de l'API Battle.net (pas d'extraction des
  fichiers du jeu).
- **Banque du personnage** (oubliée) : addon 1.8, `ScanCharacterBank` (onglets de banque 11.2+ par
  `C_Bank.FetchPurchasedBankTabData(Enum.BankType.Character)`, sinon ancienne banque `-1` + sacs de banque +
  banque de composants) ; lue avec la banque de bataillon à chaque ouverture chez le banquier. Onglet Sacs :
  bouton « Banque du personnage » ; Hôtel des ventes : comptée dans « Valeur des banques ». FAIT-TESTÉ sur un faux
  jeu (lupa, les deux variantes) ; **pas encore en jeu**.
- **Collections** : l'aperçu prend toute la hauteur que le texte laisse (fini le grand vide sous la description).
  Ce que l'API Battle.net propose, vérifié avec les identifiants de Jérémy : mascottes → créature → affichage →
  image 600×600 (comme les montures) ; jouets, héritage, apparences → **seulement l'icône 56 px** (aucun rendu
  d'objet ; le média d'apparence répond 404) ; ensembles → liste des apparences, donc des pièces. D'où : image
  pour les mascottes, grande icône pour les objets (avec la mention), icônes des pièces pour les ensembles.
- **Rendu du personnage recadré** : les marges transparentes du rendu 1600×1200 sont retirées
  (`media.trim_transparent`) ; sur le vrai rendu de Jérémy le personnage passe de 82 à 289 px de haut dans le cadre.
- Texte des sources : un code d'icône coupé par la limite de longueur (`|TINTERFACE\ICONS\…` sans `|t`) est retiré.
- Message 404 de Battle.net : la mention « personnage jamais vu » ne s'affiche plus que pour un personnage.
- **Tests :** 8 nouveaux (`test_collections_media.py`, `test_addon_lua.py`) ; suite verte ; ruff propre.

## 23/11/2026 : identifiants Battle.net perdus au redémarrage
- Tests 40 à 42 : OK (Jérémy), sauf les identifiants Battle.net qui ne survivaient pas à la fermeture.
- Cause : `Settings` ne gardait au chargement que les clés des valeurs par défaut ; `bnet` n'y était pas. Corrigé (valeurs par défaut + clés inconnues gardées). FAIT-TESTÉ (enregistrer, relire, réenregistrer).
- Identifiants déplacés dans Paramètres généraux > Jeu (demande de Jérémy) ; l'onglet Hôtel des ventes garde l'état et un bouton « Régler ».

## 23/11/2026 : WoW Assistant, onglet Bestiaire
- Demande de Jérémy : créatures rencontrées et tuées, aptitudes, nombre de fois tuées, PV / mana, niveau, lieu,
  objets obtenus et or moyen, note, image, Wowhead, Hermes.
- Deux sources (aucune ne suffit seule) :
  - **journal de combat** (`Logs/WoWCombatLog*.txt`, `/ha combatlog on`), lu par l'appli toutes les 5 s dans un
    fil (`bestiary.py`) : tuée = `UNIT_DIED` d'une créature que « moi » (drapeau d'affiliation) a engagée, ou
    `PARTY_KILL` ; aptitudes = sorts lancés par une créature engagée ; PV, ressource, carte, niveau = champs de la
    journalisation avancée. Positions mémorisées par fichier ; un fichier antérieur à la création du bestiaire
    n'est pas relu ; 24 Mo au plus par passage. Depuis Midnight les addons n'ont plus le journal de combat, le
    fichier reste écrit ;
  - **addon 1.9** : cible, survol, barres d'info → niveau, rang, type, famille, PV max (sauf valeurs « secrètes »),
    zone ; fenêtre de butin (`GetLootSourceInfo`) → objets et or par corps, un corps compté une fois.
- `bestiary.json` (ignoré par Git) garde les fiches, les positions de lecture et les notes.
- Image : API Battle.net (`/data/wow/creature/{id}` → affichage → image).
- Barre d'onglets : marges et police réduites automatiquement pour que les 12 onglets tiennent.
- **Non vérifié** : pas de fichier de journal de combat chez Jérémy ; format Midnight du journal à confirmer (test 44).
- **Tests :** 9 nouveaux (`test_bestiary.py`) ; suite verte ; ruff propre.

## 23/11/2026 : WoW Assistant, vue 3D incrustée, Essayage, confirmation de fermeture
- **Agent :** Cloud
- Tests 43 et 44 : OK (Jérémy). Demandes : la vue 3D (déjà vue en fenêtre à part) **incrustée** dans la fenêtre
  de l'appli, partout où c'est possible ; confirmation avant de quitter.
- **Vue 3D** (`model3d.py`, `web3d/viewer.html`, `webhost.py --embedded`) : visionneuse de Wowhead (ZamModelViewer)
  relayée par un serveur local 127.0.0.1 (seuls `modelviewer/live/…` et jQuery de cdnjs ; cache disque) ; la page
  pywebview est rattachée comme fenêtre enfant (Win32 `SetParent`, styles enfant) de la fenêtre pygame et placée à
  chaque image sur le cadre de l'aperçu, mise à l'échelle SCALED et bandes noires comprises (`client_rect`).
  Masquée sans aperçu, sous une modale ou un menu. Option désactivée par défaut ; images Battle.net par défaut.
  Constats : la page restait blanche tant que pywebview n'avait pas reçu « show » (fenêtre créée masquée) ;
  ensuite le rendu est correct avec les moteurs SDL direct3d, opengl et software (captures).
- **Modèles** : personnage (Battle.net « appearance » : race, sexe, personnalisation, apparences portées),
  montures, mascottes, créatures (affichage Battle.net) ; essayage = pièces remplaçant leur emplacement.
- **Essayage** (Transmoglyphe) : fiche de personnage ; apparence → son emplacement, ensemble → toutes ses pièces
  (`bnet.set_pieces` donne maintenant `slotType` et `display`) ; mise en page calculée sur la hauteur du cadre.
- **Quitter** : `UI.request_quit` (croix, Alt+F4, Échap) → modale « Quitter WoW Assistant ? » ; « Non » rend la
  modale précédente ; une 2e demande d'affilée quitte.
- Vrai journal de combat de Jérémy relu : version 22, build 12.1.5, `ADVANCED_LOG_ENABLED,0` ; `PARTY_KILL` puis
  `UNIT_DIED` au format attendu ; nouvel événement `SWING_DAMAGE_LANDED` (sans effet sur le bestiaire).
- **Tests :** 6 nouveaux (`test_model3d.py`), 2 (`test_collections_media.py` : essayage), 1 (`test_ui_fixes.py` :
  confirmation) ; tests de fermeture adaptés ; suite verte ; ruff propre. Bout en bout dans de vraies fenêtres
  (Python 3.11 + pywebview) : vue incrustée sur l'onglet Personnage, masquée sous la confirmation et sur un autre
  onglet.
- **Non vérifié chez Jérémy** : tests 45 à 48.

## 23/11/2026 : fermeture qui partait seule, identifiants perdus dans la copie Hermes
- **Agent :** Cloud
- Tests 45 à 48 : OK (Jérémy), sauf deux défauts.
- **Fermeture** : reproduit avec un vrai `WM_CLOSE` (l'appli se fermait en 0,1 s) : un clic sur la croix envoie
  WINDOWCLOSE puis QUIT ; la 2e demande d'affilée valait « Oui ». Une demande pendant que la question est posée est
  maintenant ignorée ; seuls « Oui » et Entrée quittent. Revérifié : ouverte 6 s après la croix, Échap = Non.
- **Identifiants** : le code des deux dossiers est identique ; le `settings.json` de `D:\Hermes-Agent` est un fichier à
  part qui n'a jamais reçu d'identifiants (région vide aussi). Une copie normale de l'appli les garde (tracé de
  chaque sauvegarde : lancement et fermeture). Désormais `Settings` les garde aussi dans le profil Windows
  (`%APPDATA%\WoWAssistant\shared.json`, hors dépôt) : repris si vides localement, recopiés à chaque sauvegarde
  (effacement compris), passés au profil au 1er lancement d'une copie qui les a. Les réglages des tests (autre
  chemin) n'y touchent jamais. Échec d'écriture signalé au lieu d'être silencieux.
- **Tests :** 1 nouveau (`test_settings_bnet.py`), tests de fermeture refaits ; suite verte ; ruff propre.
  Bout en bout : deux vraies copies de l'appli, profil temporaire : la copie sans identifiants les retrouve.

## 23/11/2026 : Hermes Agent intégré à WoW Assistant (coach de jeu)
- **Agent :** Cloud
- Demande de Jérémy : Hermes Agent (application de bureau, passerelle 0.23.2) comme coach, dans l'appli et l'overlay.
- **Étude** du Hermes installé (lecture seule) : CLI `hermes -z` (réponse seule, autorisations sautées), outils
  limitables (`-t`), skills, serveurs MCP (`hermes mcp add`, question interactive), API de la passerelle
  (`/api/sessions/{id}/chat/stream` en SSE : texte, outils, demandes d'autorisation ; `/v1/runs/{id}/approval`),
  refusée tant que `API_SERVER_KEY` manque dans son `.env` (cas actuel).
- `hermes_mcp.py` : serveur MCP stdio, bibliothèque standard seulement, **10 outils en lecture seule** sur les mêmes
  données que l'appli (addon + dernier état mémorisé + bestiaire + activité), codes couleur du jeu retirés, réponses
  bornées. Vérifié avec le vrai client MCP de Hermes (bac à sable, puis supprimé) et sur les vraies données.
- `hermes_skill/wow-coach/SKILL.md` : consignes de coach (français, données vérifiées par les outils, Wowhead et
  sources récentes, pas de triche, textes du jeu = données).
- `hermes_bridge.py` : état de Hermes (sans jamais garder ni afficher les secrets du `.env`), client API (session
  dédiée réutilisée, flux, autorisations, Stop) ou CLI (outils sans danger : web, skills, mémoire, vision... ; rappel
  des derniers échanges), mise en place par boutons avec copie `*.wow-assistant-<date>.bak` du fichier touché.
- `llm.py` : 3e mode « hermes » ; Paramètres > Assistant IA : « Hermes Agent (recommandé) » et lien vers l'onglet.
- **Onglet Hermes** (`tabs_hermes.py`), affichage commun `chatview.py` (réponse au fil de l'eau, outils, demande
  d'autorisation, Stop, Markdown rendu lisible), widget Assistant revu, **nouveau widget Coach Hermes**.
- **Tests :** `test_hermes.py` (20 tests : MCP, état, flux API, autorisation, CLI, mise en place, conversation,
  rendu sans texte coupé, captures) ; un défaut trouvé et corrigé (réglages vides pris pour absents) ; suite verte.
- **Non vérifié en vrai** : l'API (clé à créer par Jérémy, bouton) ; tests 51 à 55 à faire.

## 23/11/2026 : Hermes, suite : fichiers, liens, erreurs expliquées
- **Agent :** Cloud
- Tests 49 et 50 : OK (Jérémy).
- Le vrai Hermes échouait à chaque question : modèle servi avec 32 000 jetons de contexte, Hermes en exige 64 000
  (journal `errors.log`). Jérémy a réglé 65 536. L'appli lit maintenant ce journal et explique l'erreur en français ;
  l'onglet affiche le contexte du modèle.
- **Liens** : `web_extract` de Hermes lit une vraie page Wowhead sans clé (vérifié) ; le skill wow-coach (1.2.0) lui
  demande de lire les liens donnés.
- **Fichiers** : bouton « Joindre un fichier » et glisser-déposer ; textes lus par l'appli (60 000 caractères au
  plus) et envoyés comme données encadrées ; images envoyées comme captures.
- Mode « Programme local (exe) » retiré des Paramètres (il servait à lancer Hermes) ; un réglage « exe » devient
  « hermes ».
- **Tests :** 5 nouveaux dans `test_hermes.py` (25) ; suite verte.

## 23/11/2026 : Hermes, réflexion « high » refusée par Qwen 3.5
- **Agent :** Cloud
- Retours de Jérémy (tests 51 à 56) : toutes les questions échouaient, Ollama répondait 500 : « Unexpected reasoning
  effort high. Supported types are xhigh (default), medium, and low » (modèle de conversation de `qwen3-27b`). Hermes
  a `agent.reasoning_effort: high` et réessaie 3 fois par appel : d'où les 5 min 20 du test précédent (pas le
  modèle : 28 jetons/s en direct).
- WoW Assistant choisit la réflexion à chaque question (`--reasoning` en CLI, `model_options.reasoning_effort` par
  l'API), « medium » par défaut ; choix dans l'onglet Hermes ; erreur expliquée en français ; « Your request was not
  processed » reconnu comme un échec.
- Vérifié en vrai : question via la CLI en 16 s, réponse tirée des outils de jeu.
- **Tests :** 1 nouveau (26 dans `test_hermes.py`) ; suite verte.

## 23/11/2026 : réglages de l'assistant perdus en recopiant l'appli
- **Agent :** Cloud
- Retour de Jérémy : serveurs enregistrés à ressaisir. Cause : recopier le dossier de l'appli écrase son
  `settings.json`. Le mode, les serveurs, le modèle, la clé et les réglages Hermes sont maintenant aussi dans le profil
  Windows (`%APPDATA%\WoWAssistant\shared.json`, hors dépôt) ; le dernier enregistré l'emporte. Profil amorcé avec
  les réglages de sa copie Hermes.
- Sa copie `D:\Hermes-Agent\wow_assistant_v9` n'avait pas encore le correctif de la réflexion : d'où les 500
  persistants. À recopier.
- **Tests :** 2 nouveaux (`test_settings_bnet.py`) ; suite verte.

## 23/11/2026 : API de Hermes démarrée, terminal qui restait ouvert
- **Agent :** Cloud
- L'API ne démarrait pas malgré la clé : la passerelle de Hermes est un service en arrière-plan (lancé le 22/11 à
  13:45) que fermer l'application ne relance pas ; elle lit le `.env` à son démarrage. Relancée avec
  `hermes gateway restart` (aucun agent actif) : port 8642 ouvert, question via l'API en 35 s avec les données du jeu.
- Bouton « Relancer la passerelle (API) » dans l'onglet Hermes ; message de l'activation corrigé.
- Terminal de WoW Assistant resté ouvert après fermeture : l'application Hermes, lancée par le bouton avec
  `os.startfile`, héritait de sa console (et y écrivait ses erreurs). Lancée maintenant détachée (sans console, sorties
  ignorées).
- **Tests :** 2 nouveaux ; suite verte.

## 23/11/2026 : vérification d'une vraie réponse de Hermes (API), corrections
- **Agent :** Cloud
- Réponse « Analyse mon perso » de Hermes (API, plusieurs minutes : 6 outils de jeu + recherche web) comparée aux
  vraies données (mêmes outils) : chiffres justes (caractéristiques, métiers, quêtes, hauts faits, or) ; erreurs :
  qualité « bleue » (vert en réalité), décompte des talents, **talent de héros conseillé au niveau 48** (pas encore
  accessible), campagne présentée comme source d'XP (les quêtes donnent 0 XP), touche des talents (« R » au lieu de
  N), et dans une réponse précédente progression du niveau fausse (58 % au lieu de 25,6 %).
- Outils de jeu : qualité avec sa couleur, progression du niveau calculée (pourcentage, XP restants), « aucune (0) »
  pour une quête sans XP. Skill wow-coach 1.3.0 : chiffres repris tels quels, fonctionnalité vérifiée selon le niveau,
  pas de raccourci clavier deviné. Noms d'outils affichés sans « _ » (API).
- **Tests :** 1 nouveau ; suite verte.

## 23/11/2026 : base de connaissances du coach (corrections du joueur, faits vérifiés)
- **Agent :** Cloud
- **Fichiers :** `coach_knowledge.py` (nouveau), `hermes_mcp.py`, `widgets_builtin.py`, `tabs_hermes.py`,
  `chatview.py`, `hermes_bridge.py`, `hermes_skill/wow-coach/SKILL.md` (1.4.0), tests.
- **Raison :** demande de Jérémy : que Hermes se constitue une base juste, sur le modèle de Scantrad (le travail
  manuel fait foi).
- Statuts : **joueur** (correction, priorité absolue, jamais périmée), **sourcé** (lien http obligatoire, à
  revérifier après 45 jours), **rejeté** (gardé pour ne pas être réenregistré). Un fait en ligne ne remplace jamais
  une correction du joueur. Fichier dans le profil Windows, écrit de façon atomique, relu s'il change (Hermes et
  l'appli écrivent le même).
- Outils MCP `wow_knowledge_search` / `wow_knowledge_save` (12 outils ; seul ce dernier écrit, dans ce fichier
  seulement). Corrections rappelées dans chaque question à Hermes. Onglet : « Corriger la réponse », vue
  « Connaissances » (filtres, recherche, C'est juste / Rejeter / Supprimer, règle ajoutée à la main).
- **Tests :** 4 nouveaux, 2 adaptés ; suite verte.

## 23/11/2026 : test 57, bouton « Faire vérifier »
- **Agent :** Cloud
- Test 57 de Jérémy : après la relance de la passerelle, Hermes a bien les 12 outils et cherche dans la base
  (`wow_knowledge_search` dans ses journaux), mais n'enregistre rien : sa réponse n'a pas fait de recherche web, et
  aucune correction n'est partie (aucun message reçu par Hermes). « Corriger » vérifié par un clic simulé : la
  correction est bien enregistrée.
- Ajouts : bouton **« Faire vérifier »** (Hermes vérifie sa dernière réponse en ligne et enregistre les faits avec
  leur lien) ; vue Connaissances vide qui explique comment la remplir ; compteur relu quand Hermes écrit.
- **Tests :** 1 nouveau ; suite verte.

## 23/11/2026 : feuille de route WoW Assistant, étape 1 : base liée à la version du jeu
- **Agent :** Cloud
- **Fichiers :** `gameversion.py` (nouveau), `coach_knowledge.py`, `hermes_mcp.py`, `tabs_hermes.py`, skill 1.4.1.
- Version du jeu lue dans `.build.info` (dossier de WoW, lecture seule ; ligne du produit du dossier `_retail_`,
  `_classic_`... ; variante retail / forever / classic). Chaque fait enregistré porte le patch (12.1.5) ; un fait
  vérifié en ligne est à revérifier dès que le patch change (les correctifs du même patch ne comptent pas) ou après
  45 jours ; les corrections du joueur ne périment jamais. `wow_status` donne la version du jeu.
- Vérifié sur le vrai fichier de Jérémy : 12.1.5.70961, produit `wow`.
- **Tests :** 2 nouveaux ; suite verte.

## 23/11/2026 : feuille de route, étape 2 : routine de la semaine
- **Agent :** Cloud
- **Fichiers :** `routine.py`, `tabs_routine.py` (nouveaux), `ui.py`, `tabs.py`, `main.py`, `widgets_builtin.py`,
  `hermes_mcp.py` (outil `wow_routine` : 13 outils), `hermes_bridge.py`, skill 1.5.0, addon 1.10, tests.
- Onglet **Semaine** : remises à zéro (addon 1.10 : `C_DateAndTime.GetSecondsUntilWeeklyReset`,
  `GetQuestResetTime` ; sinon EU mercredi 04:00 UTC, Amériques mardi 15:00 UTC), liste automatique (chambre forte,
  monnaies plafonnées, quêtes hebdo / journalières via `freq`, verrouillages, M+), tâches perso décochées à la remise
  à zéro, autres personnages (résumé gardé à chaque lecture : le fichier de l'addon n'a que le dernier joué), plan
  demandé à Hermes selon le temps de jeu. Progression d'avant la remise à zéro comptée comme zéro.
- Données dans `%APPDATA%\WoWAssistant
outine.json` ; le serveur MCP ne fait que le lire.
- **Tests :** 7 nouveaux (`test_routine.py`) ; les tests n'écrivent plus jamais dans le profil Windows (fixture).

## 23/11/2026 : feuille de route, étape 3 : bilans de combat
- **Agent :** Cloud
- **Fichiers :** `combat_report.py`, `tabs_reports.py` (nouveaux), `bestiary.py` (lignes partagées avec d'autres
  lecteurs : le fichier n'est lu et découpé qu'une fois), `main.py`, `ui.py`, `tabs.py`, `hermes_mcp.py` (outil
  `wow_combat_reports` : 14 outils), skill 1.6.0, tests.
- Onglet **Bilans** : un bilan par boss (ENCOUNTER_START / END, durée du jeu) et par clé Mythique+ (CHALLENGE_MODE_*,
  temps total, boss de la clé) : DPS / HPS (sans surplus) / dégâts subis / interruptions / dissipations / morts par
  joueur du groupe, derniers coups reçus avant chaque mort, ce qui a fait le plus mal au joueur. Marche avec et sans
  journalisation avancée (décalage détecté ligne par ligne). « Analyser avec Hermes », « Copier le bilan ».
- Analyse après coup, hors du jeu (le jeu écrit toujours le fichier depuis Midnight). Bilans dans
  `%APPDATA%\WoWAssistant\combat_reports.json` (noms du groupe : jamais dans le dépôt).
- **Tests :** 4 nouveaux (`test_combat_report.py`) ; suite verte.

## 23/11/2026 : feuille de route, étape 4 : Raidbots
- **Agent :** Cloud
- **Fichiers :** `simc.py` (nouveau), `ui.py` (boutons du cadre d'équipement, onglet Personnage), `main.py`, tests.
- Profil SimulationCraft construit depuis l'addon : `itemString` décodé (enchantement, gemmes, bonus, contexte,
  niveau d'obtention = modificateur 9 → `drop_level`), spécialisation par son identifiant (103 = farouche) ou son nom
  français, race, royaume, métiers, code de talents. Vérifié sur le vrai instantané de Jérémy (16 emplacements).
- Résultat Raidbots : le format de `data.json` / `data.csv` n'est documenté nulle part et le site répond 403 aux
  lectures automatiques : pas d'import fragile. Le texte du rapport est collé (presse-papiers, sur clic), gardé dans
  la base de connaissances (statut joueur, lien du rapport) et analysé par Hermes.
- **Tests :** 4 nouveaux (`test_simc.py`) ; suite verte.

## 23/11/2026 : feuille de route, étape 5 : montée de niveau et points de route
- **Agent :** Cloud
- **Fichiers :** addon (`/ha way`, coordonnées des quêtes : `C_QuestLog.GetNextWaypoint`, `GetQuestsOnMap`),
  `waypoints.py` (nouveau), `quests.py`, `tabs.py`, `chatview.py`, `tabs_hermes.py`, `hermes_mcp.py`, skill 1.7.0.
- `/ha way [carte] x y` : `C_Map.SetUserWaypoint` + suivi (virgule française acceptée). Quêtes : bouton « Copier le
  point de route ». Réponses de Hermes : `/ha way` et `/way #carte x y` (TomTom) repérés et copiables. Question
  « Niveau » (parcours vérifié en ligne). `wow_quests` donne `point_de_route`.
- **Bug corrigé** : `wow_quests` lisait `finished` alors que l'addon exporte `done` : les objectifs faits n'étaient
  jamais marqués « (fait) » pour Hermes.
- **Tests :** 5 nouveaux, dont 2 qui exécutent l'addon sous Lua (lupa) contre de fausses API du jeu ; suite verte.

## 23/11/2026 : feuille de route, étape 6 : décors du logis et rentabilité des recettes
- **Agent :** Cloud
- **Fichiers :** addon 1.11 (`ScanDecor`, `/ha scan logis` ; `ScanRecipes` ajoute `out` / `outQty` depuis
  `GetRecipeSchematic`), `game_connection.py` (`_normalize_decor`), `gamedata.py`, `craft.py`, `profit.py` (nouveau),
  `tabs_collections.py` (« Décors du logis »), `tabs_market.py` (« Rentabilité des recettes »), `hermes_mcp.py`
  (`wow_collections` decor, `wow_professions` rentabilite, `GameData.market()` : TSM / Auctionator en lecture seule,
  relus au plus toutes les 10 min), skill 1.8.0.
- API du logis (`C_HousingCatalog`, 11.2.7+, aussi sur Forever) : `GetDecorTotalOwnedCount` / `GetDecorMaxOwnedCount`
  sûrs ; la liste passe par `CreateCatalogSearcher` + `GetAllSearchItems`, dont la conversion en fiches n'est pas
  documentée : `GetCatalogEntryInfo` puis `GetCatalogEntryInfoByRecordID` en appels protégés, rappel de fin ou délai
  de 4 s (une seule fin). Non vérifié en jeu (test 62).
- Rentabilité : composants de base au moins cher de leurs rangs, vente × quantité moyenne × 0,95 ; recette sans prix
  pour un composant = « incomplet » (pas de faux bénéfice).
- **Tests :** 4 nouveaux (`test_profit.py`, Lua `test_housing_decor_scan_is_defensive`) ; suite verte.

## 23/11/2026 : feuille de route, étape 7 : version WoW Forever et Questie
- **Agent :** Cloud
- **Fichiers :** `features.py` (nouveau), `ui.py` (variante dans l'en-tête, Raidbots, note à l'assistant),
  `tabs_data.py` (Mythique+, Chambre forte), `tabs_collections.py` (logis), `hermes_mcp.py` (`variante` dans
  `wow_status`, `questie` dans `wow_quests`), `quests.py`, `tabs.py` (« À rendre à »), addon 1.12, skill 1.9.0.
- Recherche (23/11, sites de joueurs, pas de source officielle lue) : Forever = niveau 60, 9 classes, pas de M+,
  Gouffres, saisons, logis ni vol ; Camping et Héritage en plus. Questie a une version Forever (avec QuestieDB) ;
  « Questie AI » est un autre produit (service payant de partage d'écran).
- Addon : Interface 16001 ajoutée (non confirmée), `OptionalDeps: Questie`, journal de quêtes par
  `GetQuestLogTitle` / `GetQuestLogLeaderBoard` si `C_QuestLog.GetInfo` manque, Questie lu par
  `QuestieLoader:ImportModule("QuestieDB")` (`GetQuest`, `GetNPC`, `ZoneDB:GetUiMapIdByAreaId`), appels protégés.
- **Tests :** 4 nouveaux (`test_forever.py`, Lua `test_classic_quest_log_and_questie`) ; suite verte.

## 23/11/2026 : feuille de route, étape 8 : version anglaise
- **Agent :** Cloud
- **Fichiers :** `i18n.py`, `i18n_en.json` (nouveaux), `scripts/extract_ui_strings.py` (nouveau), `ui.py`
  (`text` / `fit` / `wrap` traduisent, `raw=True` pour la saisie de l'utilisateur, `width()` pour dimensionner
  boutons et onglets sur le libellé traduit, choix de la langue, infobulles), `chatview.py`, `tabs*.py`,
  `widgets_builtin.py` (largeurs), `llm.py` (consigne système anglaise), `main.py`, `settings.py` (`ui.language`),
  addon (messages en anglais si `GetLocale() ~= "frFR"`), skill 1.10.0.
- Choix : pas de réécriture du code (1 600 textes dans 40 fichiers) mais une traduction à l'affichage : texte
  exact, puis modèle de f-string (`{0} objets` → `{0} items`, valeurs traduites à leur tour), puis morceaux connus ;
  mémoire cache. Les clés internes (noms d'onglets, états) restent en français : le code ne change pas.
- **Tests :** 5 nouveaux (`test_i18n.py` : tous les onglets en anglais sans texte coupé ; messages de l'addon) ;
  suite verte.

## 23/11/2026 : Strata, moteur secondaire pour les gros modèles « mélange d'experts »
- **Agent :** Cloud
- **Fichiers :** `core/strata.py` (nouveau), `core/llm_router.py`, `core/daemon.py`, `core/api.py`
  (`/strata/start`, `/strata/stop`, `owned_by` dans `/v1/models`), `core/web/dashboard.html` et `.js` (Accueil),
  `config/local.example.yaml` (section `strata`), `config/hardware_profiles.yaml` (ce qui tient avec 32 Go de RAM),
  WoW Assistant `llm.py` / `ui.py` / `i18n_en.json` (fournisseur Strata, bouton « Ajouter Strata »), README
  (installation optionnelle), `tests/core/test_strata.py` (nouveau), `tests/gaming_hud/test_ui_fixes.py`.
- **Raison :** demande de Jérémy (note préparée avec Gemini) : un moteur pour les gros modèles MoE à côté d'Ollama.
- **Choix :**
  - Strata ne remplace pas Ollama ; désactivé par défaut ; arrêté ou absent = repli sur Ollama, sans erreur.
  - Modèles nommés `strata/<id>` : le Hub, ses clients (WoW Assistant via le Hub) et `/v1/models` les voient.
  - Strata garde son modèle tant qu'il tourne (pas de `keep_alive`) : il tient la place du gros modèle auprès
    d'Inoue ; un gros modèle Ollama est refusé avec un message clair au lieu d'arrêter Strata sans prévenir.
    Démarrage et arrêt : seulement sur un clic (Accueil).
  - Port 8090 : 8080 est pris par Open WebUI sur le poste.
  - Clé éventuelle : lue dans la variable d'environnement nommée par `strata.key_env`, jamais écrite.
- **Vérifié dans la doc de Strata (docs/MODELS.md), contre la note de départ :** Qwen3.8-Flash-Next garde ses
  experts en RAM (34 Go pour Q2_0, 50 Go pour IQ3_S, plus ~10 Go pour le système) : il ne tient pas avec 32 Go
  sans lire les experts sur le SSD. Choix de Jérémy : Qwen3.6-35B-A3B UD-Q4_K_XL (22,9 Go).
- **Installation (hors dépôt) :** script officiel lu avant exécution, `STRATA_DATA_DIR=D:\Strata`,
  `STRATA_NO_PATH=1` (PATH inchangé) ; somme SHA-256 et signature de la publication vérifiées par le script.
- **Tests :** 10 nouveaux (faux serveur OpenAI sur 127.0.0.1 : modèles, réponse entière et diffusée, déchargement
  d'Ollama avant Strata, refus d'un gros modèle Ollama pendant Strata, repli, lanceur, API) ; suite verte.
- **Essai réel :** 36 à 48 jetons/s par le routeur ; le moteur qwen36 n'utilise qu'une carte : préréglage passé sur
  la RTX 5060 Ti (la 5080 reste au jeu). Strata prend 21 à 24 Go de RAM : trois tests scantrad ont manqué de mémoire
  pendant qu'il tournait (verts après l'arrêt). Démarrage et arrêt par le Hub vérifiés ; Strata laissé arrêté.
- **Conclusion (retour de Jérémy) :** manques de mémoire jusque dans le navigateur pendant l'essai. Strata demande
  64 Go de DDR4 pour tourner pleinement ; une 3e carte ne réduit pas la RAM demandée. Noté dans
  `config/hardware_profiles.yaml`, `PROJECT_STATUS.md` et le README.


## 23/11/2026 : le Professeur devient un enseignant du CP à la terminale
- **Agent :** Cloud
- **Fichiers :** `modules/genesis_lab/programmes.yaml`, `curriculum.py`, `teacher.py`, `sims.py`, `sources.py`,
  `sims/*.html` (10 simulations) — nouveaux ; `modules/genesis_lab/module.py` (nouvelles commandes, travaux en
  arrière-plan), `manifest.json` (0.2.0, `fr.wikipedia.org`) ; `core/api.py` (`/prof/sims/{id}` sous CSP isolée,
  `frame-src 'self'`) ; `core/web/professeur.js` (nouveau), `dashboard.html`, `dashboard.css` ;
  `config/local.example.yaml` (section `genesis_lab` complétée, sans chemin personnel) ;
  `tests/genesis_lab/test_professeur.py` (nouveau), `tests/core/test_dashboard.py`,
  `tests/core/test_knowledge_service.py`.
- **Raison :** demande de Jérémy : un vrai enseignant de l'Éducation nationale (programme annuel par niveau et par
  matière, cours et exercices adaptés, schémas, simulations, Claude Code local, outils existants).
- **Choix :**
  - « Le code calcule, le modèle explique » est gardé : le modèle remplit des gabarits JSON vérifiés (cours,
    schéma, exercices) ; un exercice incohérent (choix inexistant, nombre illisible) est écarté ; le corrigé ne
    quitte jamais le Hub avant la correction.
  - Rédactions longues en « travaux » d'arrière-plan suivis par le tableau de bord (pas de délai d'attente du bus).
  - Sources : la base locale n'est citée que si elle parle du chapitre. Essai réel : pour « L'électricité »,
    les vecteurs rapprochaient « Quantité de matière » à 0,70 (la base n'a pas d'article sur l'électricité) ;
    d'où le filtre par mots du chapitre (titre, ou deux mots dans le texte), en plus du seuil de l'assistant.
  - Wikipédia : pages `/wiki/<Titre>` seulement (robots.txt interdit l'API), par le `PoliteFetcher` du Hub.
  - Hermes : ligne de commande `hermes -z` avec les outils sûrs de WoW Assistant, sans sa compétence de jeu ;
    rien n'est modifié côté Hermes.
  - Simulations : pages autonomes contrôlées (aucun `fetch`, script externe, adresse web, `eval`, stockage…),
    servies avec `sandbox allow-scripts` et `default-src 'none'`.
  - Claude Code local : le Professeur écrit une demande dans son dossier et l'ouvre d'un clic ; le lanceur
    (`.bat`) n'est jamais lu.
- **Tests :** 36 nouveaux (programmes, cours, correction, remarques, Hermes, sources, simulations dangereuses
  refusées, Claude Code local, commandes du module, route isolée) ; suite complète verte (579, dont 4 réels GPU
  non lancés).
- **Essai réel (`qwen3-27b`) :** cours de 4e « L'électricité » en 113 s, deux articles de Wikipédia lus ;
  exercices aux calculs justes (U = 50 × 0,2 = 10 V ; R = 12 / 0,3 = 40 Ω) ; copie corrigée dans le navigateur
  (83 %, « acquis », rédaction jugée par le modèle) ; version simplifiée en 84 s ; réécriture avec seulement des sources pertinentes en 85 s ; « Faire vérifier » : Hermes a répondu par une erreur de son fournisseur (HTTP 500, effort de raisonnement « high » refusé par le modèle, réglage côté Hermes), prise à tort pour un verdict « à corriger » : détection ajoutée, la fausse note retirée du cours.
  Demande « La photosynthèse » écrite pour le Claude Code local (non traitée). Simulation « Les phases de la Lune »
  programmée par `qwen3-coder` en 32 s : acceptée par le contrôle et affichée, mais fausse sur le fond (nouvelle
  lune mal placée) ; le contrôle protège la page, pas l’exactitude scientifique.

---

## 2026-11-23 — Calculatrice à calcul formel (`calc_cas`), branche `feature/calc-cas`

- **Agent :** Cloud (worktree `D:\AetherTwin\AetherTwin-calc`, en parallèle d'une autre session sur `main`)
- **Fichiers :** `modules/calc_cas/` (nouveau : `engine.py`, `worker.py`, `graph.py`, `stats.py`, `agent.py`,
  `mcp_server.py`, `module.py`, `demos.py`, `manifest.json`, `README.md`), `tests/calc_cas/` (nouveau),
  `core/web/calc_cas.js` et `calc_cas.css` (nouveaux), `core/web/dashboard.html` (un onglet, un panneau, deux
  liens), `requirements.txt` (sympy épinglé), `THIRD_PARTY.md`, `PROJECT_STATUS.md`, `ARCHITECTURE_MAP.md`.
- **Raison :** demande de Jérémy : calculatrice haut de gamme avec CAS, module du Hub, outil exact pour les agents.
- **Tests :** 211 tests `tests/calc_cas` verts ; ruff propre sur le module. Suite complète : 787 verts, 5 ignorés (152 s) ; le test de la carte, rouge sur `main`, repasse au vert après régénération.
  Avant le travail, `main` avait déjà 1 test rouge (`test_architecture_map_is_up_to_date`, carte non régénérée)
  et 1 erreur ruff (`tests/gaming_hud/test_profit.py`, imports non triés) : préexistants, non touchés.
- **Essais réels :** Hub de test isolé (port 5760, configuration temporaire) piloté dans le navigateur intégré ;
  délégation par `qwen3-27b` : `solve(x^2 - 2x = 0, x)` puis `integrate(2x - x^2, x, 0, 2)` → 4/3, 22 s.

### Décisions

1. **SymPy** (BSD, Python, déjà présent dans le venv) plutôt que Giac : pas de binaire à embarquer.
2. **Saisie jamais exécutée telle quelle** : code produit par l'analyseur de SymPy vérifié par son arbre
   syntaxique (pas d'attributs, de noms `_…`, de lambdas), évalué sans `__builtins__`.
3. **Délai par processus séparé** (`multiprocessing` spawn) : SymPy ne s'interrompt pas dans un fil ; l'enfant est
   tué au-delà de `timeout_s` (10 s) et les définitions sont rejouées.
4. **MathML natif** pour l'affichage (pas de KaTeX/MathJax : aucune ressource externe, CSP inchangée).
5. **Délégation par protocole texte `CAS:`** : le routeur du Hub ne transmet pas les « tools » natifs ; aucun
   changement au cœur. Serveur MCP stdio fourni pour Hermes (branchement côté Hermes non fait).
6. Conventions statistiques et autres choix simples : voir `modules/calc_cas/README.md` (« Choix faits »).
7. Fichiers de suivi mis à jour dans le dernier commit de la branche seulement, pour limiter les conflits avec
   la session parallèle.

### Suite du 23/11 — fenêtre de bureau et programmes

- **Demande de Jérémy :** fenêtre lancée par le Hub, inspirée d'une calculatrice graphique de poche (sans copie),
  redimensionnable avec une interface qui s'équilibre ; mode programmation en bac à sable ; logo AetherTwin.
- **Fichiers :** `modules/calc_cas/sandbox.py`, `app.py` (nouveaux), `manifest.json` (champ `app`), `engine.py`
  (degrés, `→`), `worker.py` (opérations `program`, `settings`, `table`), `graph.py` (`table`), `module.py`,
  `core/web/calc_app.html`, `calc_app.js`, `calc_app.css` (nouveaux), `core/web/dashboard.html` et `calc_cas.js`
  (bouton « Ouvrir la calculatrice »), tests `tests/calc_cas/test_sandbox.py`, `test_app.py`.
- **Tests :** 274 tests `tests/calc_cas` verts. **Essais réels** sur le Hub de test : fenêtre Edge ouverte et
  fermée par `/modules/calc_cas/app/start|stop`, mises en page 460×640, 500×900, 1100×680, programme avec saisie.
- **Décisions :** Edge `--app` plutôt que pywebview (non installé) ; objet de tâche Windows « tuer à la fermeture »
  pour que l'arrêt depuis le Hub ferme aussi la fenêtre ; Python restreint vérifié par l'arbre syntaxique, dans un
  processus borné en temps et en mémoire ; `input()` par rejeu avec graine fixe.
- **Puis :** onglet du tableau de bord renommé « Outils » (demande de Jérémy) ; application **Géométrie** dans la
  fenêtre (`core/web/calc_geo.js`, construction recalculée dans la page) et mesures exactes côté moteur
  (`modules/calc_cas/geometry.py`, commande `geometry`, `tests/calc_cas/test_geometry.py`). Choix : géométrie
  calculée dans la page pour un déplacement fluide, le moteur n'intervient que pour les valeurs exactes.

## 23/11/2026 : retours sur les simulations, Hermes réglé

- **Agent :** Cloud
- **Fichiers :** `modules/genesis_lab/sims.py`, `module.py`, `sources.py`, `core/web/professeur.js`,
  `core/web/dashboard.html`, `tests/genesis_lab/test_professeur.py`, `PROJECT_STATUS.md`.
- **Raison :** Jérémy : « il a juste besoin de deux ou trois retours » pour la simulation de la Lune ;
  « corrige le réglage de Hermes ».
- **Choix :**
  - `review` : le modèle du Professeur lit le code et liste au plus 5 erreurs (science d'abord) ; le texte
    est placé dans le champ de retour, à relire avant d'envoyer.
  - `improve` : le codeur reçoit la page actuelle, le nouveau retour et les retours précédents ; même contrôle
    qu'à la création (deux essais). L'ancienne version va dans `simulations/versions/`, `undo` la rétablit.
    Une simulation intégrée (dans le dépôt) n'est jamais réécrite : sa version corrigée est une nouvelle page.
  - Hermes : `reasoning_effort: "high"` → `"medium"` dans `%LOCALAPPDATA%\hermes\config.yaml`, sauvegarde
    horodatée `.bak` à côté ; `hermes_verifier` passe aussi `--reasoning medium` (ne dépend plus du réglage).
- **Tests :** 2 nouveaux (allers-retours, versions, retour arrière, intégrée jamais modifiée) ; contrôle de
  `--reasoning` ajouté ; tests du Professeur et du tableau de bord verts.
- **Essai réel :**
  - Hermes : relecture du cours « L'électricité » en 305 s, « Verdict : correct », avec sources (programme du
    cycle 4, Eduscol) et deux remarques (sécurité électrique absente, puissance P = U × I).
  - « Les phases de la Lune » (`qwen3-coder`, ~40 s par tour) : la relecture du Professeur (32 s) trouve des
    erreurs réelles (période synodique et non sidérale, étiquettes décalées, bouton Pause) mais pas la
    principale (position de la nouvelle lune). Six retours : 1) positions et angle Soleil-Terre-Lune ;
    2) méthode exacte (Soleil à gauche, angle a = π + 2π·d/29,53, fraction éclairée) : vue de dessus juste ;
    3) et 4) code exact de la fonction qui dessine la Lune vue de la Terre (ma première formule était fausse pour
    la Lune décroissante, corrigée et vérifiée aux 8 phases dans le navigateur) ; 5) bug `innerHTML +=` qui
    effaçait les vignettes ; 6) redessin en pause et mise en page. Version 7 juste aux 8 phases.
  - Leçon : le modèle codeur corrige bien ce qu'on lui montre précisément ; les erreurs de géométrie (sens des
    angles du canvas) demandent un retour avec la formule.

## 23/11/2026 : onglets Développement et Outils, Claude Code local dans le Hub, pont MCP avec Hermes

- **Agent :** Cloud
- **Fichiers :** `modules/dev_launcher/` (nouveau : `catalog.py`, `launch.py`, `tasks.py`, `hermes_link.py`,
  `bridge_mcp.py`, `relay_check.py`, `module.py`), `core/terminals.py` (nouveau), `core/api.py`,
  `core/web/dashboard.html`, `core/web/dev.*`, `core/web/terminal.*`, `core/web/xterm*` (+ licences),
  `scripts/relay_orchestrator.py`, `config/local.example.yaml`, `requirements.txt`, `THIRD_PARTY.md`,
  `tests/dev_launcher/`, `PROJECT_STATUS.md`, `README.md`.
- **Raison :** Jérémy : onglets « Développement » puis « Outils » ; son lanceur Claude Code Local en premier module,
  amélioré ; lancement dans Windows Terminal ou dans le Hub ; MCP entre Claude Code local et Hermes dans les deux
  sens, quel que soit le canal de Hermes ; vérifier que le relais fonctionne (accusé de réception seulement, aucun
  travail sur le dépôt du concours).
- **Choix :**
  - OmniRoute facultatif : Ollama 0.40 sert `/v1/messages` ; route directe par défaut, `claude_model` dans le relais.
  - Lancement : `.bat` sans secret (jeton factice « ollama », `ANTHROPIC_API_KEY` vidée), variables de la session
    Claude Code parente effacées, contexte servi (`num_ctx`) annoncé à Claude Code, réserve de réponse 8 k.
  - Terminal du Hub : pywinpty, WebSocket `/terminals/{id}/ws` (hôte et origine vérifiés, id aléatoire), page
    `/terminal` sous CSP propre ; seuls les `.bat` du dossier de lancements du module s'ouvrent.
  - Pont MCP `bridge_mcp.py` (bibliothèque standard), rôle `hermes` (confier, suivre, tâches, dossiers) ou `claude`
    (demander à Hermes, suivre) ; déclaré chez Hermes par un bouton (`hermes mcp add`, sauvegarde `.bak`).
  - Tâches confiées : dossier autorisé seulement, `--tools Read,Write,Edit,Glob,Grep`, Bash et web refusés, lecture
    des fichiers sensibles refusée, variables secrètes retirées, `--strict-mcp-config`.
- **Tests :** 15 nouveaux (`tests/dev_launcher/`) ; suite complète : 596 tests, 592 verts, 4 réels sur GPU ignorés par défaut
  (le garde-fou a refusé `OMNIROUTE_API_KEY` dans `local.example.yaml` : valeur laissée vide, nom par défaut dans le module).
- **Essais réels :**
  - Hermes → Claude Code : 1er essai sans outil (la passerelle de Hermes n'avait chargé le serveur MCP qu'après la
    question) ; 2e : tâche confiée et suivie, mais « Autocompact is thrashing » (32 k servis par Ollama) ; avec
    `devstral:24b-64k`, le modèle décrit l'appel sans le faire ; avec `qwen3-coder` 64 k (variante créée dans Ollama,
    `PARAMETER num_ctx 65536`, mêmes poids) et 5 outils, `bonjour.py` créé en 5 s ; chaîne complète par Hermes en 184 s.
  - Claude Code → Hermes : « La capitale de l'Australie est Canberra. » (60 s).
  - Terminal du Hub : réponse « : » vide puis appel `mcp__rea__hub_etat` : les serveurs MCP globaux (dont un de ~300
    outils) remplissaient le contexte (« 0 % until auto-compact ») ; option « Outils essentiels » =
    `--tools` + `--strict-mcp-config` ; ensuite `hub_etat` appelé et réponse juste (14 s).
  - Relais : « RELAI REÇU » (sans S, toléré), titre daté de `AGENT_HANDOFF.md` recopié, `git status` identique avant
    et après.

## 2026-11-24 01:00 — Garde-fous du Hub, Accueil façon Gestionnaire des tâches, sous-onglets, compléments du lanceur

- **Agent :** Cloud
- **Fichiers :** `core/module_api.py`, `core/module_runner.py`, `core/daemon.py`, `core/api.py`,
  `core/hardware/system_info.py`, `core/hardware/asus_fan_probe.ps1`, `core/web/dashboard.{html,js,css}`,
  `core/web/system.{js,css}`, `core/web/dev.js`, `modules/dev_launcher/{catalog,launch,tasks,module,bridge_mcp}.py`,
  manifestes `scantrad`, `mangastudio`, `if_game` (`command_timeout_s`), tests.
- **Raison :** demandes de Jérémy du 24/11 (garde-fous sur tout le Hub, Inoue inspiré de « sys_guardian », Accueil comme
  le Gestionnaire des tâches et Paramètres › À propos, rendu d'Armoury Crate, outils ASUS, sous-onglets, trois ajouts
  du lanceur).
- **Décisions :**
  - Battement des modules (2 s) ; refus immédiat d'une commande vers un module occupé depuis 60 s ou avec 4 demandes en
    attente ; Fuma redémarre un module muet 30 s ou bloqué au-delà de `command_timeout_s` (300 s, réglable par manifeste).
  - État du PC : lecture seule, sans administrateur ; fenêtres de Windows, outils et modes d'alimentation en listes
    fermées ; fermeture d'un programme seulement sur clic confirmé, nom revérifié, processus système et du Hub refusés.
  - Ventilateurs : pas d'`ASUSHW` (accès brut aux ports et au SMBus), pas de pilote noyau installé ; lecture des courbes
    par l'interface officielle `ASUSManagement` (admin, sur clic) ; écriture en cours, après une lecture réelle réussie.
  - Capteurs de la carte mère par LibreHardwareMonitor facultatif (serveur web local) ; Armoury Crate sans API publique.
  - Sous-onglets génériques (`data-subtabs` / `data-sub`) ; la calculatrice n'a reçu que des attributs `data-sub`.
- **Tests :** suite complète : 909 tests, 905 verts, 4 réels sur GPU ignorés par défaut, aucun échec (plus le test du relais ajouté pendant la suite, vert à part) ; ruff propre sur mes fichiers (reste un tri d'imports dans tests/gaming_hud/test_profit.py, pas de moi). Nouveaux : `tests/core/test_system_info.py` (8), sous-onglets et fichiers servis, modules
  coincés (refus rapide puis redémarrage), variante 64 k, mode « confirmer », historique par origine.
- **Essais réels :** Hub d'essai sur le port 5760 (celui de Jérémy laissé en marche) : tous les sous-onglets affichés avec
  les vraies valeurs ; variante 64 k : bouton masqué pour `devstral:24b` (variante déjà présente) ; historique : 5 tâches,
  origines Hermes / Hub.
  - Relais : le vrai message de quota du 23/11 à 21 h 25, retrouvé dans les journaux de Claude Code (« You've hit your
    5-hour limit · resets 12:30am (Europe/Paris) », `error: rate_limit`), est bien classé QUOTA par le relais ; ajouté
    aux tests. La bascule complète déclenchée par ce vrai message n'a pas encore été observée.

## 2026-11-24 — calc_cas : onglet Outils épuré, résultats en image, jeux, émulateurs, géométrie exacte

- **Agent :** Cloud (session de la calculatrice, branche `feature/calc-cas`)
- **Fichiers :** `modules/calc_cas/` (`render.py`, `games.py`, `games_examples.py`, `emulators.py` nouveaux ;
  `geometry.py`, `module.py`, `worker.py`, `engine.py`, `sandbox.py`, `mcp_server.py`, `README.md`),
  `core/web/dashboard.html`, `core/web/calc_cas.*`, `core/web/calc_app.*`, `core/web/calc_geo.js`,
  `modules/dev_launcher/hermes_link.py`, `tests/calc_cas/`, `tests/dev_launcher/`, `tests/gaming_hud/test_profit.py`,
  `requirements.txt`, `THIRD_PARTY.md`, `PROJECT_STATUS.md`.
- **Raison :** demandes de Jérémy (24/11) : onglet Outils = la calculatrice seule (les modèles passent par le MCP) ;
  résultats en vraies formules (`sympy.latex()` + matplotlib, repli `sympy.pretty`) ; import/export des programmes ;
  jeux Python ; lanceur d'émulateurs externes prévu large en puissance ; reste de la liste précédente (ruff, Hermes,
  transformations et lieux, valeurs exactes des points construits).
- **Choix :**
  - Rendu : mathtext de matplotlib (pas de LaTeX installé), encre noire inversée en écran sombre, matrices mises en
    page à la main, `None` → repli texte ; images non gardées dans `session.json` (commande `render`).
  - Jeux : module `jeu` en français sur pygame, processus `python -I games.py`, même contrôle AST, jamais d'objet
    pygame rendu au programme ; `from jeu import _x` désormais refusé (alias vérifié aussi sur le nom importé).
  - Émulateurs : détection seulement (chemins connus, PATH, configuration), ROM prises dans `data/calc_cas/roms`
    uniquement, `Popen` en liste, processus détaché ; aucun téléchargement, aucune ROM, aucun BIOS.
  - Géométrie : la page envoie la construction, le moteur la refait en exact ; lieux : élimination du paramètre.
  - Hermes : `hermes_link.register_server()` généralisé (nom validé) ; `mcp_server.py` lançable comme script.
- **Tests :** `ruff check .` propre ; suite complète après fusion de `main` : 943 réussis, 5 ignorés.
- **Essais réels :** Hub de test (5760) : onglet Outils, Calculs en image, géométrie (lieu, rotation), Pong lancé
  et arrêté, dialogue des émulateurs, import/export ; Hermes → `cas_compute` → e − 2 (31 s). Rapport pour l'autre
  session : `logs/RAPPORT_calc_cas.md`.

## 2026-11-24 — calc_cas : équation des lieux qui passent par une racine carrée

- **Agent :** Cloud (session de la calculatrice)
- **Fichiers :** `modules/calc_cas/geometry.py`, `tests/calc_cas/test_geometry.py`, `modules/calc_cas/README.md`,
  `PROJECT_STATUS.md`, `logs/RAPPORT_calc_cas.md`.
- **Raison :** point « en cours » du rapport : un lieu dont le point tracé vient d'une intersection avec un cercle
  n'avait pas d'équation.
- **Choix :** chaque racine carrée qui dépend du paramètre devient une inconnue `w` avec `w² = radicande` (de
  l'intérieur vers l'extérieur), puis élimination de Gröbner ; l'équation couvre le lieu algébrique entier (les
  deux points d'intersection).
- **Tests :** 1 nouveau (cercle mobile ∩ droite → `y = 0` ; milieu d'une corde par C → `x² − x + y² − 3y = 0`).

## 2026-11-24 — calc_cas : lancement réel d'un émulateur

- mGBA 0.10.5 (portable, GPL) et le jeu libre µCity (GPL-3) téléchargés hors du dépôt ; la commande
  `emulator_launch` ouvre la fenêtre « mGBA - MICROCITY (60 fps) », fermée ensuite. Ligne de statut passée
  à `FAIT-TESTÉ`, README et rapport mis à jour.

## 2026-11-24 — Studio pixel art (`pixel_studio`), branche `feature/pixel-studio`

Proposé à Jérémy avec d'autres outils « aussi poussés que la calculatrice » ; il a retenu le studio pixel (jeu façon
RPG 16 bits avec Fuma et Inoue).

- **Module** `modules/pixel_studio/` : format `.aether-pixel` (JSON, un PNG base64 par case calque × image),
  contrôle complet côté serveur, exports Pillow (PNG, planche + JSON, GIF animé, carte + JSON), palettes créées
  pour AetherTwin et rampes à glissement de teinte, palette tirée d'une image, stockage atomique.
- **Page** `core/web/pixel_app.*` : 10 outils de dessin, symétries, sélection flottante, calques, images et durées,
  pelure d'oignon, aperçu animé, carte en tuiles (sol, décor, cases bloquantes), annuler/rétablir, enregistrement
  automatique, thème clair/sombre, raccourcis (F1). Fenêtre de bureau (`app.py`, réutilise le lanceur de la
  calculatrice ; `browser_args` prend maintenant une taille de fenêtre).
- **Tableau de bord** : l'onglet Outils a deux sous-onglets, « Calculatrice » et « Studio pixel » (`pixel_tool.*`) ;
  `tests/core/test_dashboard.py` exige désormais 2 sous-onglets pour Outils.
- **Calculatrice** : `jeu.sprite`, `jeu.carte`, `jeu.bloque` dans le mode jeu ; le dossier des sprites est passé au
  processus du jeu (`pixel_studio.data_dir` respecté).
- **Agents** : 6 outils (`agent.py`), serveur MCP stdio `aethertwin_pixel`.
- Vérifié pour de vrai sur un Hub de test (5760) : dessin à la souris, carte, exports, bouton Jeu puis partie lancée
  (carte et sprite animé visibles), fenêtre de bureau. Trouvé à l'essai et corrigé : vue ajustée avant la mise en
  page (zoom 25 %), cases sautées par un glissé rapide sur la carte, ombrage qui changeait de teinte, dossier des
  sprites ignoré par les jeux quand `data_dir` est configuré, nom « Cœur » vidé (ligature œ).
- Fusion dans `main` en avance rapide (`ad61b2e`), suite complète : 959 réussis, 5 ignorés ; ruff propre.
- **Hermes réel** : serveur `aethertwin_pixel` déclaré (sauvegarde `.bak` horodatée du `config.yaml`),
  `hermes mcp test` → 6 outils ; « crée un sprite essai_hermes en croix » → sprite 5×5 exact (66 s), puis supprimé.

## 2026-11-24 — Voix locale et studio audio (`voice`), branche `feature/voice`

Demandé par Jérémy :
- un « synthé et séquenceur audio » avec un modulateur vocal en direct ;
- des réponses parlées et le micro dans WoW Assistant, le Hub et ses outils IA ;
- des voix modifiables, la sienne comprise ;
- MCP ;
- VB-Cable pour Discord et les jeux, avec seulement le lien de téléchargement et un bouton de vérification.

Il a autorisé les téléchargements nécessaires.

- **Module** `modules/voice/` :
  - écoute faster-whisper, un seul modèle chargé ;
  - Piper et voix de Windows, chaque moteur dans son propre processus ;
  - profils de synthèse et de micro dans `data/voice/profiles.json` ;
  - effets NumPy ;
  - installateur à adresses fixes (archive vérifiée contre la sortie de dossier) ;
  - détection de VB-Cable ;
  - 5 outils d'agent et serveur MCP `aethertwin_voice` ;
  - fenêtre de bureau.
- **Choix des voix :**
  - binaire Piper MIT ; espeak-ng (GPL-3) seulement dans le processus de Piper ;
  - 4 voix françaises aux licences relevées dans leurs MODEL_CARD ; « tom » écartée (AGPL) ;
  - révision v1.0.0 des voix imposée (la configuration de `main` fait échouer ce binaire : « "aɪ" is not a single
    codepoint ») ;
  - Kokoro écarté pour l'instant : espeak-ng lié dans le même processus, et plus lourd.
- **API** (`core/api.py`) :
  - `/v1/audio/speech` et `/v1/audio/transcriptions`, compatibles OpenAI ; multipart lu avec `email.parser`
    (python-multipart absent) ;
  - `/voice/settings` et `/voice/profiles`, sans lancer le module ;
  - l'audio passe par des fichiers d'échange `data/voice/tmp/` (le bus porte 8 Mo au plus).
- **Hub, onglet Assistant** (`voice.js`, `voice.css`) :
  - micro (MediaRecorder) ;
  - lecture phrase par phrase par Web Audio (la CSP interdit `<audio>` sur blob:) ;
  - choix de la voix, volume, Silence ;
  - `dashboard.js` émet `aether-ask` et `aether-reply`.
- **Studio audio** (`audio_app.*`, `audio_worklet.js`, `audio_tool.js`) :
  - synthé et séquenceur, export WAV ;
  - modulateur vocal en direct ;
  - profils de voix (essai d'un profil non enregistré : `profile_data`) ;
  - VB-Cable ;
  - sous-onglet « Studio audio » de l'onglet Outils.
- **WoW Assistant** :
  - voix « Voix du Hub » (`voice.tts.hub_url`, `voice.tts.hub_voice`) ;
  - exemple d'adresse STT pointant sur le Hub ;
  - 5 chaînes anglaises ajoutées.
- **Trouvé à l'essai et corrigé :**
  - la commande « stop » arrêtait le module : la voix se coupe maintenant avec `silence` ;
  - « Æther » mal prononcé : table de prononciation ;
  - volume trop fort, signalé par Jérémy : volume égalisé à −23 dB, crêtes à 0,7, et réglette de volume dans la
    page.
- **Tests :**
  - `tests/voice/` (12) ;
  - `test_routine.py::test_store_keeps_alts_tasks_and_unchecks_them_at_reset` échoue aussi sur `main` sans ces
    changements : il dépend du jour (mardi, jour de remise à zéro) ; à corriger à part.
- Fusion dans `main` en avance rapide (`3140578`), worktree et branche supprimés ; Piper et ses voix copiés dans
  `data/voice/piper` du dépôt principal (hors Git).
- **Hermes réel** :
  - serveur `aethertwin_voice` déclaré (sauvegarde `.bak` horodatée du `config.yaml`) ;
  - `hermes mcp test` → 5 outils ;
  - « dis … avec le profil narrateur » → `voice_profiles` puis `voice_speak` (5,45 s d'audio), entendu et validé
    par Jérémy.

## 2026-11-24 — Guides dans l'interface, test de routine stabilisé

- **Agent :** Cloud
- **Demande de Jérémy :** mettre les liens des guides dans l'interface quand c'est possible.
- **Fichiers :**
  - `core/api.py` : `guide_catalog()`, `GET /guides`, `GET /guides/{id}` ;
  - `core/web/guide.html|css|js` : page « Guides » (Markdown rendu sans `innerHTML`, sommaire, recherche,
    liens entre README) ;
  - `core/web/dashboard.html|css|js`, `audio_app.html`, `pixel_app.html|css`, `calc_app.html|css` : liens 📖 ;
  - `modules/gaming_hud/app/ui.py`, `i18n_en.json` : bouton « Guide de la voix » (ouvre la page du Hub, adresse
    locale seulement) ;
  - `modules/gaming_hud/app/routine.py` : identifiants de tâches distincts.
- **Décision :** la page reçoit un identifiant, jamais un chemin ; la liste est calculée côté serveur (README du
  dépôt, de WoW Assistant et `modules/*/README.md`).
- **Test de routine :** `test_store_keeps_alts_tasks_and_unchecks_them_at_reset` ne dépendait pas du jour ; deux
  tâches ajoutées dans la même milliseconde recevaient le même identifiant, et en supprimer une supprimait
  l'autre. Corrigé dans `RoutineStore.add_task` (vrai défaut, rare à la main).
- **Tests :** `tests/core/test_dashboard.py::test_guides_catalog_and_page` ; `test_routine.py` vert 4 fois de
  suite ; essai réel de la page et des liens sur le Hub de test (5760).

## 2026-11-24 — Conversion de voix (kNN-VC) avec consentement, NVIDIA Broadcast

- **Agent :** Cloud
- **Demande de Jérémy :** suite prévue après le premier passage voix ; il a installé NVIDIA Broadcast (écho des
  enceintes, voix autour) et autorise à s'en servir.
- **Choix du moteur :** kNN-VC (MIT), sans entraînement, une voix = des enregistrements. Écartés : RVC (entraînement
  par voix, lourd), OpenVoice (dépendances figées), Seed-VC (GPL, pas dans le processus). PyTorch 2.11 (CUDA 12.8)
  était déjà dans l'environnement ; ni `torchaudio` ni `transformers` ajoutés.
- **Fichiers :**
  - `modules/voice/vc/` : WavLM et générateur HiFi-GAN repris de kNN-VC (MIT), non reformatés, exclus de ruff ;
  - `modules/voice/convert.py` : banque de voix, poids vérifiés, conversion ;
  - `service.py` : `Timbre` appliqué après la synthèse ;
  - `profiles.py` : champ `convert` ;
  - `module.py` : commandes `vc_*` ;
  - `core/web/audio_app.*` : onglet « Ma voix (IA) », choix « Timbre » des profils, micro NVIDIA Broadcast ;
  - `core/web/voice.js` : dictée sur NVIDIA Broadcast ;
  - `tests/voice/test_convert.py` ; `pyproject.toml` ; `THIRD_PARTY.md` ; `modules/voice/README.md`.
- **Sécurité :**
  - WavLM faisait `eval()` sur un texte lu dans le fichier de poids : remplacé par `parse_conv_layers`, qui n'accepte
    que « [(a,b,c)] * n + … » ;
  - poids chargés avec `weights_only=True`, taille et SHA-256 figés ;
  - adresse de téléchargement limitée aux publications de kNN-VC.
- **Consentement :**
  - attestation cochée ;
  - phrase de consentement dite avec le prénom, retrouvée par Whisper ;
  - textes affichés à lire, chacun vérifié (60 % de ressemblance au moins) ;
  - aucune importation de fichier ;
  - voix prête à 30 s de lecture.
- **Trouvé à l'essai et corrigé :**
  - `decode` rééchantillonnait dans le mauvais sens (voix ralenties et plus graves) ;
  - un enregistrement muet n'était pas retiré ;
  - la phrase « Quatre-vingt-dix-neuf… » échouait (Whisper écrit « 99 ») : remplacée ;
  - 21 s de lecture donnaient un résultat peu compréhensible : seuil « prête » à 30 s, progression affichée.
- **Essais réels :**
  - Piper « gilles » converti vers « siwis » : hauteur 97 → 197 Hz (cible 187 Hz), 73 % du texte reconnu par Whisper
    avec 54 s de référence ;
  - processeur : 12 à 16 s de chargement, puis 1,6 s pour 5 s de parole ; carte graphique : 0,05 s ;
  - Hub de test : création refusée sans attestation, autre phrase refusée, consentement et prises acceptés, `vc_convert`
    et `/v1/audio/speech` avec « Timbre ».
- **En cours :** essai avec la vraie voix de Jérémy et NVIDIA Broadcast.

## 2026-11-24 — atelier circuits : console 8 bits à monter, téléviseur, programmation

- **Agent :** Cloud
- **Demande de Jérémy :** monter virtuellement les composants d'une console 8 bits, la lancer sur un téléviseur
  ouvrable façon tube cathodique, et écrire des jeux en ROM pour la machine montée.
- **Fichiers :**
  - `core/web/nes_cpu.js` : processeur 6502 (instructions officielles et non officielles courantes) et désassembleur ;
  - `core/web/asm6502.js` : assembleur deux passes, messages en français, directives `.tile`, `.vectors`, `.ines` ;
  - `core/web/nes_ppu.js` : processeur vidéo ligne par ligne, sprite 0, palette calculée depuis le signal NTSC ;
  - `core/web/nes_machine.js` : carte mère à 12 composants, pannes réelles quand l'un manque, son, manettes, DMA ;
  - `core/web/crt.js`, `crt.html`, `crt.css`, `crt_tv.js` : écran cathodique WebGL et fenêtre « Grand écran » ;
  - `core/web/circuit_app.*`, `circuit_audio.js` : établi, programmation, débogueur, son (AudioWorklet, volume 20 %) ;
  - `core/web/circuit_tool.js`, `dashboard.html` : sous-onglet « Atelier circuits » de l'onglet Outils ;
  - `modules/circuit_lab/` : module (exemples, programmes enregistrés), fenêtre de bureau, README (guide),
    jeu d'exemple `examples/etoiles.asm` ;
  - `tests/circuit_lab/` : `test_module.py` et vérifications Node (`asm_check.js`, `machine_check.js`, `demo_check.js`),
    `nestest_run.js` (ROM de test non fournie).
- **Trouvé à l'essai et corrigé :**
  - teintes de la palette décalées : phase du signal corrigée ;
  - écran noir : `out` est un mot réservé du GLSL, le shader ne se liait pas ; repli 2D rendu sûr ;
  - lignes de balayage en moiré sur le petit écran : estompées quand il y a moins de 3 pixels par ligne ;
  - taille du programme comptait tout l'espace jusqu'aux vecteurs : on compte les octets écrits.
- **Tests :** `nestest` identique (8 991 lignes) ; `pytest tests/circuit_lab` vert ; essai réel sur le Hub de test.
- **En cours :** voie DMC, mappeurs au-delà de 0, banc logique, microcontrôleurs ; fenêtre « Grand écran » à essayer
  dans la fenêtre Edge du Hub.

## 2026-11-24 — simulations du Professeur : retours de Jérémy, pause commune

- **Agent :** Cloud
- **Demande de Jérémy :** essai du Hub « comme quelqu'un qui ne le connaît pas » ; puis « ajouter la pause dans tous
  les simulateurs ».
- **Fichiers :**
  - `modules/genesis_lab/sims/fluides.html` : refaite en deux parties, vagues (eau peu profonde, vue liquide ou
    particules, batteur, plage) et baignoire en coupe en pixel art (canard, sous-marin à ballasts, robinet, bonde,
    trop-plein, vidange de Torricelli, jouets à attraper) ; simplifications écrites sous la simulation ;
  - `gaz_parfait.html` : note sur l'absence de chocs entre particules ;
  - `coeur.html` : les trois temps du cycle affichés en permanence, celui en cours mis en avant ;
  - `neurone.html` : étiquette « moelle épinière » au-dessus du bloc, étiquettes hors du trajet nerveux ;
  - `systeme_solaire.html` : zoom à la molette vers le pointeur, déplacement, suivi d'une planète, échelle ;
  - `modules/genesis_lab/sims.py`, `sim_tools.js`, `core/api.py` : bouton Pause et hauteur ajoutés à chaque page ;
  - `core/web/professeur.js` : cadre ajusté à la hauteur reçue ; chapitre précédent/suivant sans rédaction ;
  - `tests/genesis_lab/test_professeur.py` : script ajouté vérifié, scripts des simulations compilés.
- **Lune (version 7, Claude Code local) :** version 8 enregistrée par l'historique des simulations (la 7 reste
  rétablissable avec « Revenir ») : Soleil décalé pour ne plus être coupé, textes sous la Lune descendus.
- **Trouvé :** la page des fluides ne démarrait pas (erreur de syntaxe `-(x)**2`), d'où « il ne se passe rien ».
- **Tests :** `pytest tests/genesis_lab` vert ; chaque page essayée sur le Hub de test.
- **En cours :** ajustement du cadre vu dans le Hub (le navigateur intégré de l'essai bloque les cadres) ;
  chapitre suivant essayé avec un vrai cours.

## 2026-11-24 — voix (100 prises), ArtCraft (intégration externe), labo de chimie, explorateur de données

- **Agent :** Cloud
- **Demande de Jérémy :** plus de prises et de textes pour la voix ; « Labo de chimie » et « Explorateur de données »
  avec des fonctionnalités étoffées (équations dans le tableau, résultats en simulation) ; un onglet Outils pour
  installer et brancher en MCP la suite libre ArtCraft, présentée comme une intégration externe.
- **Fichiers :**
  - `modules/voice/convert.py`, `module.py`, `core/web/audio_app.*` : 100 prises, 75 textes, textes longs en parties,
    « Autre texte ↻ » ;
  - `modules/artcraft/` (`suite.py`, `module.py`, README), `core/web/artcraft_tool.*`, `dashboard.html` ;
    `modules/dev_launcher/hermes_link.py` : `register_server(..., command=)` pour un serveur MCP externe ;
  - `core/mcp_stdio.py` : serveur MCP stdio commun (outils au format « function calling ») ;
  - `modules/chem_lab/` (`elements.py`, `chemistry.py`, `solutions.py`, `agent.py`, `mcp_server.py`, `module.py`,
    `app.py`, README), `core/web/chem_app.*` ;
  - `modules/data_lab/` (`formula.py`, `analysis.py`, `workbooks.py`, `agent.py`, `mcp_server.py`, `module.py`,
    `app.py`, README), `core/web/data_app.*` ;
  - `core/web/labs_tool.js` : sous-onglets « Labo de chimie » et « Explorateur de données » ;
  - `tests/artcraft/`, `tests/chem_lab/`, `tests/data_lab/`.
- **Décisions :**
  - ArtCraft : rien n'est fourni avec AetherTwin ; téléchargement à la demande depuis `github.com/storytold`, empreinte
    obligatoire ; nom et logos ArtCraft = marques de leurs auteurs (hors licence libre), icônes gardées sur le PC
    seulement ; mention « intégration externe, non affiliée à Adobe ni Microsoft » dans l'onglet et le guide.
    Le règlement du concours n'a pas pu être vérifié ici : à confirmer par Jérémy.
  - Le tableur calcule en Python (même moteur pour la fenêtre et pour les agents), sans `eval`.
- **Trouvé à l'essai et corrigé :**
  - icônes ArtCraft manquantes : le Hub refuse deux commandes simultanées au même module (409) → commandes en file ;
  - serveur MCP ArtCraft sans accès fichier : dossiers d'automatisation accordés (dossier d'échange seulement) ;
  - références absolues `$F$2` non reconnues dans les formules ; Entrée validait puis rouvrait la cellule suivante.
- **Tests :** voir la suite complète ci-dessous ; essais réels sur le Hub de test 5760.
- **En cours :** branchement Hermes d'ArtCraft essayé sur une vraie configuration ; acides polyprotiques ;
  feuilles multiples et questions à un modèle local dans l'explorateur.

## 2026-11-24 — bac à sable Python pour les agents, vagues sur une plage, plein écran du téléviseur

- **Agent :** Cloud
- **Demande de Jérémy :** les agents locaux doivent avoir accès au bac à sable de code ; particules des vagues figées
  et mal réparties, une vraie plage en pente qui amplifie la vague ; F11 éteint le téléviseur de l'atelier.
- **Fichiers :** `modules/calc_cas/agent.py`, `mcp_server.py`, `module.py`, `sandbox.py`, `worker.py`, `render.py`
  (`python_run`, `lire_csv()`, `DONNEES`, `drawings_png`) ; `modules/genesis_lab/sims/fluides.html` ;
  `core/web/circuit_app.js`, `core/web/crt_tv.js` (`AetherCircuit.pump`) ; `tests/calc_cas/test_agent.py`.
- **Cause trouvée :** les particules suivaient l'écoulement et dérivaient (dérive de Stokes) jusqu'au bord droit où
  elles restaient bloquées : elles oscillent maintenant autour de leur position de repos. Le téléviseur en plein
  écran recouvre l'atelier, que le navigateur met en veille : plus d'images, l'écran s'éteignait.
- **En cours :** plein écran F11 à confirmer sur le PC de Jérémy.

## 2026-11-24 — veilleur de quota : passation interactive vers Claude Code local

- **Agent :** Cloud
- **Demande de Jérémy :** un vrai test de passation en fin de quota : l'agent local confirme prendre le relais et
  demande s'il faut continuer ou attendre.
- **Fichiers :** `modules/dev_launcher/quota_watch.py` (nouveau), `modules/dev_launcher/launch.py`
  (`batch_script(..., prompt=)` : premier message), `tests/dev_launcher/test_quota_watch.py` ; lignes Claude Code du
  Hub avec `--scope user` (`modules/artcraft/suite.py`, README d'artcraft, chem_lab, data_lab).
- **Décision :** le relais existant ne voit que l'agent cloud qu'il lance ; le veilleur lit les transcriptions de
  toutes les sessions (format réel : `You've hit your 5-hour limit · resets 7:30pm (Europe/Paris)`, erreur
  `rate_limit`). L'agent local est ouvert en mode « demander avant chaque action ».
- **En cours :** passation réelle à la prochaine fin de quota.

## 2026-11-24 — atelier circuits : établi console 16 bits

- **Agent :** Cloud
- **Demande de Jérémy :** ajouter à l'atelier circuits un établi de console 16 bits. Règle de nommage : jamais le nom
  commercial d'une console (marques protégées), mais origine + couleur + nombre de bits + date de sortie.
- **Fichiers :** `core/web/c16_cpu.js` (65C816), `c16_ppu.js` (vidéo), `c16_apu.js` (SPC700 + DSP),
  `c16_machine.js` (carte, bus, DMA/HDMA, cartouches, pièces), `asm65816.js` (assembleur) ; `circuit_app.js`,
  `circuit_app.html` (deux établis, programmation selon l'établi), `crt.js` (images RGBA directes) ;
  `modules/circuit_lab/examples/lune16.asm`, `lab.py` ; `tests/circuit_lab/c16_check.js`, `test_module.py`.
- **Décisions :** la ROM de démarrage du module son (microcode du fabricant) n'est pas incluse ; son protocole public
  de chargement est reproduit en JavaScript. Interpolation du DSP calculée (cubique), pas de table copiée. Le module
  son est rattrapé à chaque accès à ses ports et à chaque fin de ligne.
- **En cours :** modes vidéo autres que le mode 1 (écrits, à essayer sur des programmes de test), écho du DSP,
  cartouches à coprocesseur ; son à écouter au casque ; téléviseur « Grand écran » avec la console 16 bits.

## 2026-11-24 — Hub : charte des studios, fenêtre à part, icône AetherTwin

- **Agent :** Cloud
- **Demande de Jérémy :** harmoniser tout le Hub avec la charte du studio audio, lancer le Hub dans sa propre fenêtre
  plutôt que dans un onglet, avec l'icône d'AetherTwin. WoW Assistant garde sa charte (style du jeu).
- **Fichiers :** `core/web/dashboard.css` (palette et composants des studios), `dashboard.html` (barre de marque,
  bouton de thème), `dashboard.js` (thème), `dev.css` ; `core/app_window.py` (fenêtre d'application, identité
  Windows et icône), `core/hub_window.py`, `core/daemon.py` (`--open` ouvre la fenêtre) ; `core/api.py` (PNG, ICO,
  `/favicon.ico`) ; `core/web/logo.ico`, `logo-256.png`, `logo-32.png` (rendus depuis `logo.svg`) ; lien d'icône
  PNG dans toutes les pages ; fenêtres des studios et ateliers (`modules/*/app.py`) ; `scripts/setup.ps1`
  (icône du raccourci) ; `Lancer AetherTwin.bat` ; `tests/test_hub_window.py`.
- **Décision :** une fenêtre « --app » de Chromium se range sous l'icône du navigateur ; on lui donne sa propre
  identité Windows (AppUserModelID `AetherTwin.Hub`, icône de relance) et on pose l'icône sur la fenêtre.
- **À faire de ton côté :** relancer `Installer AetherTwin.bat -Shortcut` pour que le raccourci du bureau prenne
  l'icône.

## 2026-11-25 — atelier circuits : banc logique et microcontrôleurs

- **Agent :** Cloud
- **Demande de Jérémy :** remplacer l'onglet « Banc logique et microcontrôleurs : en cours » par les deux établis
  annoncés ; garder les onglets de l'atelier sur une ligne dans le Hub ; mettre à jour le sous-titre du Hub.
- **Fichiers :** `core/web/logic_sim.js` (simulateur), `logic_app.js` (éditeur, chronogramme) ; `mcu_asm.js`
  (assembleurs AVR et Thumb), `mcu_avr.js` (cœur AVR), `mcu_rp2040.js` (cœur RP2040), `mcu_board.js` (cartes, écran
  LCD), `mcu_examples.js`, `mcu_app.js` (onglet) ; `circuit_app.html`, `circuit_app.css`, `circuit_app.js` (onglets
  courts, pleine largeur sans téléviseur) ; `dashboard.html` (sous-titre) ; `modules/circuit_lab` (manifeste, notes,
  README) ; `tests/circuit_lab/logic_check.js`, `mcu_check.js`, `test_module.py`.
- **Décisions :** le programme du RP2040 est chargé en SRAM comme par un débogueur (pas de ROM de démarrage ni de
  flash externe à simuler) ; les blocs IO_BANK0, PADS_BANK0 et TIMER démarrent en reset comme sur la puce, avec un
  diagnostic si on oublie de les libérer. La luminosité des LED est mesurée sur le temps passé à 1, pour que la MLI
  et le multiplexage se voient.
- **En cours :** second cœur, interruptions, PIO, UART, ADC et PWM du RP2040 ; minuteries 1 et 2, UART et ADC de
  l'AVR.

## 2026-11-25 — J9 : dossier de candidature et archive installable

- **Agent :** Cloud
- **Demande de Jérémy :** préparer les documents de candidature et une version déployable sur une installation
  neuve, à refaire facilement après chaque ajout.
- **Fichiers :** `README.md` (version finale), `docs/HARDWARE_FIT.md`, `docs/DEMO_SCRIPT.md`,
  `docs/CANDIDATURE.md`, `docs/RELEASE.md`, `research/overlord_notes.md`, `scripts/build_release.py`,
  `tests/test_build_release.py`, `scripts/gen_architecture_map.py`, `tests/test_architecture_map.py`,
  `modules/voice/convert.py`, `tests/voice/test_convert.py`, `PROJECT_STATUS.md`, `ARCHITECTURE_MAP.md`.
- **Documents :** écrits uniquement d'après les mesures et statuts déjà consignés ; ce qui manque porte un
  marqueur `[À COMPLÉTER PAR JÉRÉMY : …]` (adresse du dépôt, vidéo, questionnaire Ov3rLoRd).
- **Archive :** `scripts/build_release.py` fait un `git archive` du commit, refuse secrets, chemins personnels,
  prompt privé, `config/local.yaml` et poids de modèles, ajoute `RELEASE.txt` et l'empreinte SHA-256.
  `--verify` installe l'archive à neuf **hors du dépôt** (`%TEMP%\AetherTwin-verify`) avec `setup.ps1`, puis
  lance toute la suite dans la copie installée.
- **Ce que la vérification à neuf a trouvé (corrigé) :**
  1. `tests/voice/test_convert.py` importait PyTorch au chargement : sans `-Gpu`, toute la collecte des tests
     s'arrêtait (la CI Ubuntu aurait échoué de même). Import déplacé dans le test, sauté sans PyTorch.
  2. Sans PyTorch, la conversion de voix plantait (`ModuleNotFoundError`) au lieu du message clair prévu :
     `convert()` vérifie maintenant PyTorch et les poids avant d'importer PyTorch.
  3. Vérifiée dans `dist/`, la copie voyait le dépôt parent par `git check-ignore` : la carte d'architecture y
     semblait périmée. La vérification se fait hors du dépôt ; la carte n'interroge Git que si le projet a son
     propre `.git` ; son test de fraîcheur est sauté dans une copie sans Git.
- **Tests :** `ruff check .` propre ; `pytest` (venv de développement) : 1 102 réussis, 5 sautés ; copie
  installée à neuf : voir la ligne de l'archive dans `PROJECT_STATUS.md`.
- **Décisions :** aucune branche `concours`, aucun tag, aucun push : gestes de Jérémy (`docs/CANDIDATURE.md` §6).

## 2026-11-25 — J9 : boîte d'erreur .NET à la fermeture des widgets web

- **Agent :** Cloud
- **Demande de Jérémy :** plusieurs boîtes « Microsoft .NET Framework — CoreWebView2Controller members cannot be
  accessed after the WebView2 control is disposed » depuis la veille ; corriger.
- **Cause :** le processus `webhost.py` (pywebview, WebView2) détruisait sa fenêtre alors qu'elle était encore
  rattachée à la fenêtre de l'appli (vue 3D incrustée). Un déplacement ou redimensionnement pendant la fermeture
  faisait prévenir un moteur WebView2 déjà détruit ; sans gestionnaire, WinForms ouvrait sa boîte. Seul ce
  petit processus était touché, déjà en train de se fermer.
- **Fichiers :** `modules/gaming_hud/app/webhost.py`, `tests/gaming_hud/test_webhost_close.py`,
  `ARCHITECTURE_MAP.md`.
- **Correctif :** avant `destroy()`, la fenêtre est masquée et détachée (`SetParent` à rien), seulement si elle
  appartient à ce processus ; un gestionnaire `Application.ThreadException` est posé sur le fil d'affichage de
  pywebview (le gestionnaire WinForms vaut pour un seul fil) : une erreur .NET y devient une ligne sur stderr.
- **Tests :** essai réel (Python 3.11, pywebview, WebView2) : gestionnaire posé, erreur volontaire sur le fil
  d'affichage écrite sur stderr sans boîte, détachement fait, fenêtre d'un autre programme ignorée. Non
  reproduit : la course exacte de la fermeture pendant un déplacement (aléatoire). `ruff check .` propre ;
  `pytest` complet vert (code de sortie 0).

## 2026-11-25 — J9 : retours de Jérémy après une installation neuve

- **Agent :** Cloud
- **Demande de Jérémy :** après avoir installé l'archive sur une autre partition Windows (« pour AetherTwin tout
  est ok »), une série d'ajustements avant le dépôt de la candidature.
- **Fichiers :** `scripts/setup.ps1`, `Installer AetherTwin.bat`, `core/setup_jobs.py` (nouveau), `core/api.py`,
  `core/hardware/system_info.py`, `core/web/dashboard.html`, `dashboard.js`, `dashboard.css`, `system.js`,
  `system.css`, `dev.css`, `deps.js` (nouveau), `segnet.css` (nouveau), `circuit_app.html`, `circuit_app.css`,
  `audio_app.js`, `audio_app.css`, tests `tests/core/test_setup_jobs.py` et `test_dashboard.py`, documents.
- **Fait :**
  1. Installation : `Installer AetherTwin.bat` passe `-Ask` ; à la fin, une fenêtre propose les raccourcis du
     bureau « AetherTwin » (logo) et « WoW Assistant ». `-Shortcut` les crée sans question ; `--verify` n'affiche
     pas la fenêtre.
  2. Onglets : Accueil › Vue d'ensemble reçoit Performance et Lecteurs, Système reçoit Périphériques ; Jeu sur une
     seule page ; Connaissances devient un sous-onglet du Professeur (l'ancien lien `#connaissances` y mène) ;
     « Studio » devient « Studio image », « Éther » devient « AetherTwin I&F Hommage ». Pages jusqu'à 1 680 px,
     sections côte à côte quand elles s'y prêtent. Changer l'adresse `#onglet` change d'onglet.
  3. Studio image : module « Hand & Foot SegNet », un sous-onglet par modèle avec sa fiche (chiffres, données,
     limites, licence des poids) et ses liens GitHub et Hugging Face, lus le 25/11 ; poids et dépendances
     installables depuis la page (liste fermée de tâches côté Hub : `/setup/dependencies`, `/setup/run`) ;
     outil de masque en trois étapes, réglé sur le modèle du sous-onglet.
  4. Outils ASUS : lien de la page officielle de chaque outil (« Télécharger » s'il manque). GPU Tweak III (et
     son moniteur, GPU-Z ASUS) : page ASUS donnée par Jérémy ; GPU-Z : site qui refuse les robots, adresse non
     vérifiée par la page elle-même.
  5. Développement : sous-onglet « Dépendances » (Python, Git, Ollama, Claude Code, Windows Terminal, Hermes Agent,
     OmniRoute, faster-whisper) ; le violet de Claude Code devient l'orange du Hub.
  6. AetherTwin I&F Hommage : bandeau de dédicace à la mémoire d'Inoue et de Fuma, scène à gauche et journal à
     droite sur grand écran, touches présentées en touches de clavier.
  7. Atelier circuits : les onglets gardent leur largeur, le message d'état se raccourcit à la place.
  8. Studio audio : chaque valeur du panneau d'instrument et des effets se tape au clavier (Entrée pour appliquer,
     Échap pour annuler ; unité affichée par défaut, ms, s, k ou % acceptés), colonne élargie.
- **Tests :** `ruff check .` propre ; `pytest` complet vert (code de sortie 0) ; vérification visuelle sur un Hub de test (port 5760) : Studio image, Accueil,
  Jeu, Outils ASUS, Dépendances, Hommage, atelier circuits à 1 150 px, saisie audio.
- **Non essayé en réel :** la fenêtre des raccourcis, l'installation des poids et de PyTorch depuis la page.

## 2026-11-25 — J9 : essais réels des ajouts du jour sur une installation neuve

- **Agent :** Cloud
- **Demande de Jérémy :** finir les deux essais restants (fenêtre des raccourcis ; poids et PyTorch depuis la page).
- **Fichiers :** `scripts/setup.ps1` (`-Desktop` pour les essais, chemin du raccourci WoW corrigé),
  `tests/test_repo_hygiene.py` (aucun caractère de contrôle dans les scripts et pages),
  `core/hardware/system_info.py` (lien de GPU Tweak III donné par Jérémy), `PROJECT_STATUS.md`.
- **Essai 1, fenêtre des raccourcis :** archive installée à neuf, `setup.ps1 -Ask -Desktop <dossier d'essai>`, la
  vraie fenêtre de Windows reçoit « Oui » au clavier. Premier essai : seul « AetherTwin » créé, `setup.ps1` en
  erreur (`ArgumentException` sur `TargetPath`) : le chemin `…\gaming_hud\app\…` contenait un caractère BEL
  (« \a » interprété lors d'une modification par script). Corrigé, test ajouté (il échoue sur l'ancienne
  version). Second essai sur l'archive `9c456af` : les deux raccourcis, cible, dossier de travail et logo justes.
- **Essai 2, depuis la page Studio image (Hub de la copie installée, port 5760) :** « Installer » des dépendances
  (clic dans la page) et des deux poids (même requête que les boutons) ; PyTorch 2.11 CUDA visible, poids complets
  (374 979 240 octets chacun) ; après redémarrage du Hub, `simulation: false` et segmentation réelle des deux
  modèles sur une image du dépôt (boîte arbitraire : la qualité du masque n'est pas jugée ici).
- **Tests :** la vérification de l'archive a d'abord échoué sur le nouveau test : ce journal contenait lui-même
  deux caractères BEL (même piège). Corrigé ; `pytest` complet vert ensuite ; copies d'essai supprimées.

## 2026-11-25 — J9 : retours du soir, MCP pour OBS, intro de la vidéo

- **Agent :** Cloud
- **Demandes de Jérémy :** supprimer les anciennes archives ; ouvrir le Hub sur Accueil › Vue d'ensemble au
  redémarrage ; noter la seconde RTX 5060 Ti (achetée), l'apport d'une carte de 32 Go pour l'image et la vidéo
  (ComfyUI) et le reste de la plateforme (carte mère, processeur, 64 à 128 Go de RAM) ; un MCP pour OBS ; une
  vidéo du logo (partie 1 de la vidéo) à mettre en ligne.
- **Fichiers :** `core/web/dashboard.js` (onglet de départ), `tests/core/test_dashboard.py`, `docs/HARDWARE_FIT.md`
  (§1, §4, nouveau §4 bis, §5), `docs/CANDIDATURE.md`, `README.md`, `modules/gaming_hud/obs_control.py`,
  `modules/gaming_hud/obs_mcp.py`, `tests/gaming_hud/test_obs_control.py`, `PROJECT_STATUS.md`.
- **Décisions :** le MCP d'OBS n'a aucun outil de diffusion (enregistrer oui, diffuser non) ; il ne se connecte
  qu'à 127.0.0.1 ; les captures et enregistrements vont dans un seul dossier (`AETHERTWIN_OBS_OUT`, sinon
  `cache/obs`) ; le mot de passe vient de `OBS_WEBSOCKET_PASSWORD` ou des réglages locaux d'OBS.
- **Vidéo :** intro de 8 s (logo, titre, accroche) faite dans EffectCraft, rendue en H.264 1080p hors du dépôt.
  YouTube ne permet pas de remplacer le fichier d'une vidéo en gardant son lien (aide officielle de YouTube).
- **Tests :** `ruff check .` propre ; tests du tableau de bord et d'OBS verts ; suite complète lancée avant le commit.

## 2026-11-25 — J9 : textes du formulaire Gleam

- **Agent :** Cloud
- **Demande de Jérémy :** les champs à remplir du formulaire du concours (capture de la page Gleam).
- **Fichiers :** `docs/CANDIDATURE.md` (§1 bis : un texte par champ, limites de mots comptées ; catégorie High-End),
  `CLAUDE.md` (nom de la catégorie).
- **Constats sur la page :** catégories AI Entry, Developer, High-End ; en High-End, dépôt GitHub et démo
  téléchargeable obligatoires, vidéo optionnelle (non répertoriée acceptée). Le règlement dit clôture le 25/11 à
  23 h 59 CET ; le compte à rebours du formulaire va jusqu'au 06/12/2026 à 23 h 59 CET.
- **Tests :** test d'hygiène vert (documents seulement).

## 2026-11-25 — J9 : réponses de Jérémy, OBS réel, préparation du gel

- **Agent :** Cloud
- **Demande de Jérémy :** remplir les documents avec ses réponses, noter que le projet a pu évoluer si la date de
  clôture était erronée, activer le serveur WebSocket d'OBS, puis créer le dépôt, pousser, publier la Release, et
  finir par la vidéo. Feu vert donné pour le push et la Release.
- **Fichiers :** `research/overlord_notes.md` (dates, chiffres publiés des modèles, archives non consultées),
  `README.md` (état soumis = tag), `docs/CANDIDATURE.md` (dépôt, Release, note sur la date), `docs/DEMO_SCRIPT.md`,
  `PROJECT_STATUS.md`.
- **OBS :** serveur WebSocket activé dans les réglages d'OBS (copie de l'ancien fichier gardée à côté) ; le MCP
  `aethertwin-obs` lit l'état du vrai OBS 32.2.2 avec authentification.
- **Tests :** voir la vérification de l'archive du gel.

## 2026-11-25 — J9 : vidéo de présentation

- **Agent :** Cloud
- **Demande de Jérémy :** finir par la vidéo : tournage OBS sur l'écran libre, montage avec les outils ArtCraft,
  voix off par IA (il enregistrera la sienne pour comparer). Musique libre ou aucune ; publication non répertoriée.
- **Fait :** 10 plans enregistrés par OBS via le MCP `aethertwin-obs` (le plan Scantrad refait avec une vraie
  traduction de la page de test) ; voix Piper ; montage EffectCraft (cadrages zoomés, sous-titres, bandeau sur la
  coupe du chargement du modèle, carton final) ; rendu H.264 1080p de 108 s, hors du dépôt.
- **CI :** GitHub Actions verte sur `f961442` (Windows).
- **Tests :** aucun code modifié ; rendu vérifié sur une planche d'images, durée et piste son contrôlées.

## 2026-11-26 — Revue jury

- Revue jury réalisée, rapport dans `docs/REVUE_JURY.md`, aucune modification du code.

- Réponses de Jérémy versées dans `docs/REVUE_JURY.md` (§ 8) : relais réel le 25/11 (README et `PROJECT_STATUS.md` alignés), modules annexes (`pixel_studio`, `circuit_lab`, `artcraft`) sortis du tableau principal du README. Aucune modification du code.
