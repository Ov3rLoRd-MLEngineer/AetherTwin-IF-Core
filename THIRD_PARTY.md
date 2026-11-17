# Dépendances tierces et licences

Liste tenue à jour à chaque ajout de dépendance. Licences relevées dans les métadonnées des paquets.

## Exécution

| Paquet | Version | Licence | Usage |
|---|---|---|---|
| PyYAML | 6.0.3 | MIT | lecture des fichiers de configuration |
| nvidia-ml-py | 13.615.71 | BSD-3-Clause | mesure des GPU NVIDIA (`core/hardware/gpu_monitor.py`) |
| psutil | 7.2.2 | BSD-3-Clause | surveillance des processus (`core/daemon.py`) |
| fastapi | 0.163.1 | MIT | API HTTP locale (`core/api.py`) |
| uvicorn | 0.54.0 | BSD-3-Clause | serveur de l'API locale |
| pygame | 2.6.1 | LGPL-2.1 | interface de WoW Assistant / `gaming_hud` |
| pillow | 13.0.0 | MIT-CMU | captures d'écran, presse-papier image |

## Optionnelles

| Paquet | Version | Licence | Usage |
|---|---|---|---|
| anthropic | 2.9.0 | MIT | backend `--backend api` du relais de développement uniquement |

## Développement

| Paquet | Version | Licence | Usage |
|---|---|---|---|
| pytest | 9.2.0 | MIT | tests |
| ruff | 0.17.5 | MIT | lint |
| httpx | 0.28.1 | BSD-3-Clause | client de test de l'API locale |
| playwright | 1.65.2 | Apache-2.0 | capture de rendu de l'overlay OBS (test ignoré si aucun navigateur n'est pilotable) |

FastAPI installe aussi `starlette` (BSD-3-Clause) et `pydantic` (MIT).

## Outils externes (non distribués avec le projet)

| Outil | Usage |
|---|---|
| Ollama | serveur de modèles local |
| Claude Code | agent cloud du relais de développement |
| Aider, OpenCode | agent local du relais de développement |
| Git | gestion de versions |

Le produit final ne fait aucune requête de génération vers un service cloud. Le cloud ne sert qu'au
développement du projet.
