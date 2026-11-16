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
