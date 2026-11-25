# Construire et vérifier l'archive installable

L'archive est la version d'AetherTwin qu'on installe sur une machine neuve, sans Git. Elle se refait en une
commande après chaque ajout au projet.

## Construire

```powershell
.\.venv\Scripts\python.exe scripts\build_release.py
```

Résultat dans `dist\` (ignoré par Git) :

- `AetherTwin-IF-Core-<version>-<commit>.zip` : le dépôt tel qu'il est **commité**, dans un dossier du même
  nom, avec un fichier `RELEASE.txt` (commit, date, marche à suivre) ;
- `AetherTwin-IF-Core-<version>-<commit>.zip.sha256` : l'empreinte de l'archive.

Ce qui n'est pas commité n'y entre pas : le script le signale. Il refuse aussi de construire si l'archive
contiendrait un secret, un chemin personnel, le prompt de mission privé, `config/local.yaml` ou des poids
de modèles (mêmes motifs que `tests/test_repo_hygiene.py`).

Options :

| Option | Effet |
|---|---|
| `--ref <commit, branche ou tag>` | empaqueter un autre état que `HEAD`, par exemple `--ref v0.1.0-concours` |
| `--version <x.y.z>` | numéro de version du nom de fichier (défaut : celui de `pyproject.toml`) |
| `--out <dossier>` | autre dossier de sortie |
| `--verify` | installer l'archive à neuf, puis lancer toute la suite de tests dans la copie installée |
| `--setup-args "-Gpu"` | options passées à `setup.ps1` pendant `--verify` |
| `--verify-dir <dossier>` | où faire la vérification (défaut : `%TEMP%\AetherTwin-verify`), toujours hors du dépôt |

## Vérifier à neuf

```powershell
.\.venv\Scripts\python.exe scripts\build_release.py --verify
```

Le script décompresse l'archive dans `%TEMP%\AetherTwin-verify\`, hors du dépôt, lance `scripts\setup.ps1` dans ce dossier (nouveau
venv Python 3.11, dépendances, `config\local.yaml` créé depuis l'exemple), puis `pytest` dans la copie
installée. Il s'arrête avec un message clair à la première étape qui échoue. Ce dossier peut
être supprimé ensuite.

Dans la copie installée, il n'y a pas de dossier `.git` : les tests qui demandent le dépôt Git (empaquetage,
fichiers ignorés par Git, fraîcheur de `ARCHITECTURE_MAP.md`) sont sautés, et le garde-fou anti-secrets parcourt alors tout le dossier.

## Installer sur une machine neuve

1. Installer **Python 3.11** (python.org, avec le lanceur `py`) et, de préférence, **Ollama**.
2. Décompresser l'archive dans le dossier voulu.
3. Double-clic sur `Installer AetherTwin.bat`. Options possibles, à passer depuis un terminal :
   `"Installer AetherTwin.bat" -Gpu -Weights -Voice -Shortcut` (voir le README).
4. Double-clic sur `Lancer AetherTwin.bat`. Le Hub s'ouvre sur `http://127.0.0.1:5750/`.
5. Modèles conseillés : `ollama pull qwen3-27b`, `ollama pull qwen2.5vl:7b`, `ollama pull nomic-embed-text`.

Sans Ollama, ou sans carte NVIDIA, le Hub démarre en mode dégradé : les modules qui demandent un modèle le
disent.

## Après un ajout au projet

1. Tests verts et `ruff check .` propre.
2. Commit.
3. `.\.venv\Scripts\python.exe scripts\build_release.py --verify`
