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
