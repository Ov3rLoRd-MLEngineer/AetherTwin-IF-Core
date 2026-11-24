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
| pygame | 2.6.1 | LGPL-2.1 | interface de WoW Assistant / `gaming_hud` ; mode jeu de `calc_cas` |
| pillow | 13.0.0 | MIT-CMU | captures d'écran, presse-papier image, exports du studio pixel |

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

| Ajouté le 22/11/2026 | Version | Licence | Usage |
|---|---|---|---|
| onnxruntime | 1.32.0 | MIT | exécute LaMa sur le processeur (Scantrad) |
| faster-whisper (facultatif, `-Voice`) | 1.2.1 | MIT | reconnaissance vocale locale (onglet Traduction, module `voice`) |
| lupa (développement seulement) | 2.8 | MIT | tests : compile l'addon HermesAssistant et exécute ses fonctions sur un faux jeu |
| sympy (ajouté le 23/11) | 1.14.0 | BSD-3-Clause | calcul formel du module `calc_cas` |
| mpmath (apporté par sympy) | 1.3.0 | BSD-3-Clause | arithmétique multiprécision de SymPy |
| matplotlib (ajouté le 24/11) | 3.10.7 | Matplotlib License (PSF) | `calc_cas` : formules des résultats en PNG (mathtext) |
| contourpy, cycler, kiwisolver (apportés par matplotlib) | 1.3.3, 0.12.1, 1.5.1 | BSD-3-Clause | dépendances de matplotlib |
| fonttools, pyparsing (apportés par matplotlib) | 4.68.0, 3.3.3 | MIT | dépendances de matplotlib |
| python-dateutil, packaging (apportés par matplotlib) | 4.0.0, 26.3 | BSD-3-Clause ; Apache-2.0 ou BSD-2-Clause | dépendances de matplotlib |

| Ajouté le 23/11/2026 (onglet Développement) | Version | Licence | Usage |
|---|---|---|---|
| pywinpty (Windows) | 3.1.2 | MIT | terminal intégré au Hub (pseudo-console, `core/terminals.py`) |
| websockets | 17.4 | BSD-3-Clause | WebSocket du terminal intégré (serveur uvicorn) |
| xterm.js (`@xterm/xterm`, copié dans `core/web/xterm.*`) | 6.0.0 | MIT (`core/web/LICENSE.xterm.txt`) | affichage du terminal intégré |
| `@xterm/addon-fit` (`core/web/xterm-addon-fit.js`) | 0.11.0 | MIT (`core/web/LICENSE.xterm-addon-fit.txt`) | ajuste le terminal à son cadre |

Services en ligne facultatifs (désactivés tant que l'utilisateur n'y met pas ses identifiants) :

| Service | Conditions | Usage |
|---|---|---|
| API Battle.net (Blizzard) | conditions d'utilisation des API de Blizzard (développeur gratuit) | WoW Assistant : rendus du personnage, images des montures, prix de l'Hôtel des ventes |
| Visionneuse 3D de Wowhead (ZamModelViewer) et ses modèles (`wow.zamimg.com/modelviewer/live/`) | propriété de Wowhead / Blizzard, non redistribués : téléchargés à la demande (option désactivée par défaut), cache local non versionné, usage personnel, mention « Visionneuse 3D : Wowhead » | WoW Assistant : vue 3D facultative (personnage, essayage, montures, mascottes, créatures) |
| wow-model-viewer (globales `window.WH` reprises dans `web3d/viewer.html`) | ISC | WoW Assistant : page de la vue 3D |
| jQuery 3.7.1 (cdnjs, téléchargé à la demande, non versionné) | MIT | exigé par la visionneuse de Wowhead |

Modèles téléchargés (non versionnés, dans `models/` ou le cache Hugging Face) :

| Modèle | Licence | Usage |
|---|---|---|
| LaMa (big-lama), export ONNX `Carve/LaMa-ONNX` | Apache-2.0 | effacement par reconstruction (Scantrad) |
| Whisper `small` (OpenAI), conversion CTranslate2 de faster-whisper | MIT | reconnaissance vocale |

## Outils externes (non distribués avec le projet)

| Outil | Usage |
|---|---|
| Ollama | serveur de modèles local |
| Claude Code | agent cloud du relais de développement |
| Aider, OpenCode | agent local du relais de développement |
| Git | gestion de versions |
| Claude Code local (Claude Code avec des modèles Ollama, OmniRoute facultatif) | onglet Développement : lancé depuis le Hub (Windows Terminal ou terminal intégré) ou par Hermes via le pont MCP `aethertwin_dev` |
| Hermes Agent (Nous Research), installé par l'utilisateur | coach de WoW Assistant : appelé par sa CLI ou l'API locale de sa passerelle (127.0.0.1) ; WoW Assistant lui fournit un skill et un serveur MCP (bibliothèque standard) |
| `nestest.nes` et son journal (test de référence du 6502, Kevin Horton) | vérification ponctuelle du processeur de l'atelier circuits (`tests/circuit_lab/nestest_run.js`) ; non fourni |

Le produit final ne fait aucune requête de génération vers un service cloud. Le cloud ne sert qu'au
développement du projet.

## Téléchargés à la demande (hors du dépôt, module `voice`)

Installés dans `data/voice/piper/` par le bouton « Installer » du studio audio, depuis des adresses fixes ; aucun
de ces fichiers n'est versionné ni redistribué par AetherTwin.

| Élément | Version | Licence | Usage |
|---|---|---|---|
| Piper (rhasspy/piper, `piper_windows_amd64.zip`) | 2023.11.14-2 | MIT | synthèse vocale, lancée comme programme séparé |
| espeak-ng (inclus dans l'archive de Piper) | — | GPL-3.0 | phonétisation, dans le processus de Piper uniquement (aucune liaison avec AetherTwin) |
| Voix `fr_FR-siwis-medium` (rhasspy/piper-voices v1.0.0) | v1.0.0 | CC-BY 4.0 (corpus SIWIS) | voix « aether », « fuma » |
| Voix `fr_FR-upmc-medium` | v1.0.0 | CC-BY-SA 4.0 | voix « narrateur » |
| Voix `fr_FR-gilles-low` | v1.0.0 | CC0 | voix « inoue », « robot » |
| Voix `fr_FR-mls-medium` | v1.0.0 | CC-BY 4.0 (Multilingual LibriSpeech) | voix « radio », 125 locuteurs |

Conversion de voix (module `voice`, `convert.py`). Les poids sont téléchargés à la demande dans
`data/voice/knnvc/`, depuis les publications de kNN-VC, taille et SHA-256 vérifiés. Le code est repris dans
`modules/voice/vc/` (`LICENSE-knn-vc`) :

| Élément | Version | Licence | Usage |
|---|---|---|---|
| kNN-VC (bshall/knn-vc) : code du modèle WavLM et du générateur HiFi-GAN, repris dans `modules/voice/vc/` | master (2023) | MIT | conversion de voix ; `eval` de la configuration remplacé par un analyseur strict |
| WavLM-Large (`WavLM-Large.pt`, Microsoft, via les publications de kNN-VC v0.1) | v0.1 | MIT (microsoft/unilm) | encodeur de parole (couche 6) |
| Vocodeur `prematch_g_02500000.pt` (kNN-VC v0.1) | v0.1 | MIT | HiFi-GAN entraîné sur LibriSpeech (CC-BY 4.0) |
| PyTorch (déjà présent dans l'environnement) | 2.11.0 | BSD-3-Clause | exécute WavLM et HiFi-GAN |

VB-Cable (VB-Audio, donationware) n'est ni fourni ni téléchargé : la page donne le lien du site officiel et vérifie
seulement s'il est installé.
