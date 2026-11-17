# CLAUDE.md — AetherTwin (I&F Core)

Hub d'agents locaux, 100 % exécuté en local, développé en solo par Jérémy pour le
concours ASUS Agent Computer Challenge (catégorie Advanced / High-End).
**Clôture : 25 novembre 2026.** Plan et priorités : `PROJECT_STATUS.md`.

## Avant de travailler

1. Lis `PROJECT_STATUS.md`, puis `ARCHITECTURE_MAP.md`. Ne charge pas tout le dépôt.
2. Un agent local à contexte limité lit `AGENT_HANDOFF.md` à la place de ce fichier.
3. Le dossier voisin `D:\Claude Code API` est hors périmètre : n'y touche pas.

## Langue

- Documentation, messages à Jérémy, chaînes d'interface : **français**.
- Code, noms de fonctions, commentaires techniques : anglais accepté.

## Environnement

- Python **3.11** (venv dans le dépôt). Toujours `.venv\Scripts\python.exe`,
  jamais un `python` nu (le `python` du PATH peut être une autre version).
- Tests : `.venv\Scripts\python.exe -m pytest`
- Lint : `.venv\Scripts\python.exe -m ruff check .`
- Carte d'architecture : `.venv\Scripts\python.exe scripts\gen_architecture_map.py`

## Conventions de code

- Typage sur toute fonction publique. `from __future__ import annotations`.
- `ruff` propre avant commit (configuration dans `pyproject.toml`).
- Dépendances minimales. Toute dépendance lourde (PyTorch, ComfyUI, Biopython…)
  est **optionnelle** : son absence met le module en mode dégradé, sans planter le Hub.
- Chaque module a un test de démarrage en mode dégradé (sans GPU, sans jeu, sans OBS).
- `modules/gaming_hud/app/` est le **code d'origine de WoW Assistant** (imports à plat, hors
  lint). Ne le modifie que pour un correctif ou un branchement demandé ; garde-le lançable seul.
  Reporte alors les mêmes fichiers dans `D:\Hermes-Agent\wow_assistant_v9` (copie d'usage de
  Jérémy) et ajoute un test dans `tests/gaming_hud/`. Tout code nouveau va dans
  `modules/gaming_hud/` (adaptateurs, module du Hub), jamais dans `app/`.

## Structure du dépôt

```
core/            daemon, bus, contrat de module, routeur LLM, ordonnanceur
core/guardians/  inoue.py (VRAM, énergie) · fuma.py (stabilité, mode nocturne)
core/hardware/   gpu_monitor.py (pynvml + repli « inconnu »)
modules/<nom>/   un dossier par module, avec manifest.json
scripts/         relay_orchestrator.py, gen_architecture_map.py, setup.ps1
config/          *.example.yaml versionnés ; local.yaml ignoré par Git
tests/           pytest ; tests/data/ = données libres de droits uniquement
docs/ research/ assets/ logs/
```

## Règles VRAM strictes

1. **Un seul gros modèle de langage chargé à la fois** par défaut. Décharge les
   autres (`keep_alive` Ollama) avant d'en charger un nouveau.
2. Tout module déclare `vram_min_gb` et `vram_comfort_gb` dans son manifeste.
   Inoue refuse ou met en file d'attente ce qui dépasse le budget.
3. **Marge de sécurité de 10 %** de la VRAM totale, jamais consommée.
4. Vision et diffusion (scantrad, mangastudio) passent par la **file d'attente
   GPU unique** (`core/scheduler.py`).
5. Ne présume jamais qu'un modèle tient : **mesure** (`ollama show`, `nvidia-smi`)
   et consigne dans `docs/HARDWARE_FIT.md`. Fixe toujours `num_ctx`.
6. L'adresse de l'API Ollama est **configurable** (hôte:port). Jamais codée en dur.
7. Pas de portage AMD/ROCm. Seul backend GPU : `pynvml`, avec repli « inconnu »
   qui n'empêche jamais le démarrage.

## Secrets : zéro clé en dur

- Aucune clé API, mot de passe, jeton ou chemin personnel dans le dépôt.
- Tout passe par variables d'environnement ou `config/local.yaml` (ignoré par Git).
- `tests/test_repo_hygiene.py` scanne les fichiers suivis : il doit rester vert.
- Le règlement du concours interdit explicitement de soumettre des credentials.

## Sécurité

- Écoute réseau sur `127.0.0.1` **uniquement**.
- **Aucune commande système issue d'une sortie de LLM** sans entrée explicite dans
  `config/allowlist.yaml`. Jamais de `shell=True` avec une chaîne issue d'un LLM.
- `subprocess` : toujours une liste d'arguments, jamais une chaîne de shell.
- Widgets et pages web : processus isolé, liste blanche de domaines.
- Données de jeu : **lecture seule** (CGU). Aucune lecture mémoire, aucune
  automatisation, aucun envoi d'entrées.
- Scraping : `robots.txt`, limitation de débit, `User-Agent` explicite, cache
  disque, journal des sources.
- Aucun contenu protégé (pages de manga, etc.) dans le dépôt.

## Honnêteté des statuts

Chaque fonctionnalité a un statut explicite dans `PROJECT_STATUS.md` :

| Statut | Signification |
|---|---|
| `FAIT-TESTÉ` | Exécuté réellement, tests automatiques verts |
| `FAIT-NON-TESTÉ` | Écrit, mais non exécuté dans les conditions réelles |
| `SIMULÉ` | Fonctionne avec un mock (LLM, GPU, jeu, OBS factices) |
| `À FAIRE` | Absent ou squelette |

- N'écris jamais « fonctionne » pour ce qui n'a pas été exécuté.
- Ce qui ne peut pas être testé ici (GPU réels, jeu réel, OBS réel) reçoit un
  script de test que Jérémy lance lui-même, listé dans `PROJECT_STATUS.md`.
- N'invente aucun résultat, métrique, commit ou date. Marqueur à utiliser :
  `[À COMPLÉTER PAR JÉRÉMY : …]`.
- Orthographe imposée : « Ov3rLoRd ».

## Procédure de commit

1. `pytest` vert et `ruff check .` propre.
2. Mets à jour **les 3 fichiers de suivi** (voir ci-dessous).
3. Régénère la carte : `scripts\gen_architecture_map.py`.
4. Commit atomique, message clair, préfixe conventionnel
   (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `wip(local):` pour l'agent local).
5. Jamais de `git push --force`, jamais de réécriture d'historique publié.

## Les 3 fichiers de suivi (obligatoires à chaque étape significative)

- `PROJECT_STATUS.md` — statut de chaque brique, reste à faire, tests à faire par Jérémy.
- `ARCHITECTURE_MAP.md` — arborescence, signatures publiques (auto), flux (manuel).
- `logs/CHANGELOG_DEV.md` — date/heure, agent (Cloud / Local), fichiers, raison,
  résultat des tests, décisions. **Modifier le code sans écrire ici est une faute.**

## Autonomie

Avance sans demander de validation pour les choix techniques courants. Choisis,
consigne la décision dans `logs/CHANGELOG_DEV.md` (section « Décisions »), continue.
Ne pose une question que si la décision est irréversible ou bloque tout.
En cas de retard : coupe dans les P2, jamais dans la qualité des P0.
