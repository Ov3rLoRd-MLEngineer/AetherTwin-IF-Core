# Dépendances tierces et licences

Liste tenue à jour à chaque ajout de dépendance. Licences relevées dans les métadonnées des paquets.

## Exécution

| Paquet | Version | Licence | Usage |
|---|---|---|---|
| PyYAML | 6.0.3 | MIT | lecture des fichiers de configuration |

## Optionnelles

| Paquet | Version | Licence | Usage |
|---|---|---|---|
| anthropic | 2.9.0 | MIT | backend `--backend api` du relais de développement uniquement |

## Développement

| Paquet | Version | Licence | Usage |
|---|---|---|---|
| pytest | 9.2.0 | MIT | tests |
| ruff | 0.17.5 | MIT | lint |

## Outils externes (non distribués avec le projet)

| Outil | Usage |
|---|---|
| Ollama | serveur de modèles local |
| Claude Code | agent cloud du relais de développement |
| Aider, OpenCode | agent local du relais de développement |
| Git | gestion de versions |

Le produit final ne fait aucune requête de génération vers un service cloud. Le cloud ne sert qu'au
développement du projet.
