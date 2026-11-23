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
