# Notes sur le laboratoire Ov3rLoRd

AetherTwin ne part pas de rien. Il s'appuie sur des mois de travail de Jérémy dans un laboratoire de
recherche personnel, **Ov3rLoRd**. Ce document dit ce qu'on en sait, et d'où on le sait.

Règle de lecture :

- **vérifié** : contrôlé dans un dépôt public ou sur ce poste, avec la date ;
- **déclaré** : dit par Jérémy, pas contrôlé par l'agent qui a écrit ce document ;
- `[À COMPLÉTER PAR JÉRÉMY : …]` : il manque l'information. Rien n'a été inventé pour combler le trou.

## 1. Les traces publiques

| Élément | Lien | Statut |
|---|---|---|
| Compte GitHub | <https://github.com/Ov3rLoRd-MLEngineer> | vérifié |
| Dépôt du laboratoire | <https://github.com/Ov3rLoRd-MLEngineer/OVERLORD> (public) | **vérifié le 16/11/2026** : 237 commits sur `main`, 239 toutes branches, 26 branches, du 23/06/2026 au 10/08/2026 |
| HandSegNet-Anime-SDXL | GitHub et Hugging Face `Ov3rLoRd-MLEngineer/handsegnet-anime-sdxl` | poids **téléchargés et exécutés** dans AetherTwin (17/11) ; pages déclarées |
| FootSegNet-Anime-SDXL | GitHub et Hugging Face `Ov3rLoRd-MLEngineer/footsegnet-anime-sdxl` | poids **téléchargés et exécutés** dans AetherTwin (17/11) ; pages déclarées |

Le 16/11/2026, une recherche de motifs de clés dans l'état courant du dépôt OVERLORD n'a rien trouvé.
Son historique n'a pas été scanné.

## 2. D'où vient le laboratoire

- **Origine (déclaré)** : une chaîne automatisée de production d'anime et de manga en Python
  (ComfyUI et SDXL ; API d'Anthropic avec repli sur Ollama). L'ambition de départ : un film de
  24 minutes. Premières versions : 71 fichiers, 52 agents Python.
- **Pivot (déclaré)** : vers un RPG en 2D / 2,5D, avec des dialogues de PNJ tenus par un modèle local
  (machine à états de comportement, plus une couche de conversation avec garde-fous et base de données).
- **Dates (déclaré, 25/11)** : le laboratoire commence fin juin 2026 ; le pivot vers le RPG date de fin août
  2026. Peu après, la santé de ses chats oblige Jérémy à tout mettre en pause. C'est de là que viennent les
  mini-jeux du Hub et son jeu-hommage, AetherTwin I&F Hommage, dédié à Inoue et Fuma.

## 3. Un échec assumé, et ce qu'il apprend

Constat de Jérémy (**déclaré**) : en 2026, une production d'anime autonome, sans jugement artistique
humain, n'est pas viable. Les échecs relevés :

- une hétérochromie (yeux de deux couleurs) ratée quatre fois de suite ;
- l'interpolation de poses abandonnée, remplacée par des mouvements de caméra ;
- le flou de mouvement des combats, jamais résolu.

Ce constat a orienté AetherTwin : les outils de création du Hub (`mangastudio`, `scantrad`,
`pixel_studio`) **assistent** une personne. Ils ne remplacent pas son œil. Dans `scantrad`, par exemple,
chaque zone détectée se corrige à la main avant la réincrustation.

## 4. Les modèles publiés

- **HandSegNet-Anime-SDXL** et **FootSegNet-Anime-SDXL** : segmentation des mains et des pieds dans des
  images de style anime. Poids sous Apache 2.0 (Hugging Face), code d'inférence sous MIT (GitHub).
  **Vérifié** : les poids se téléchargent depuis Hugging Face (`setup.ps1 -Weights`) et tournent dans
  AetherTwin. HandSegNet a donné un masque en 0,17 s sur la RTX 5080 une fois chargé, avec 2,8 Go de VRAM.
- Ils n'ont vu que des images SDXL à l'entraînement (précision de Jérémy). Sur de vraies pages de manga,
  ils sortent de leur domaine : deux masques sur cinq ont débordé lors de l'essai du 17/11.
- FootSegNet : val_IoU de 0,9277, arrondi à 0,928 sur sa page (**déclaré**, non recalculé ici).
- Le pipeline d'entraînement reste privé. Seules l'inférence et la conversion sont publiées (**déclaré**).
- Quatre modules de segmentation existent : pieds, mains, visage, corps (**déclaré** ; seuls les deux
  premiers sont publiés : les annotations du visage et du corps ne sont pas faites).
- Chiffres publiés sur les pages GitHub des deux modèles (repris dans l'onglet Studio image) : HandSegNet,
  IoU 0,888 avec la boîte exacte (0,722 avec une boîte trouvée automatiquement), 320 images annotées à la main
  dont 32 pour la validation ; FootSegNet, IoU 0,928, 300 images dont 30 pour la validation. Seul le décodeur de
  masque de SAM ViT-B est entraîné (≈ 4 M de paramètres sur 93,7 M). Le matériel et la durée d'entraînement sont
  dans les archives privées de Jérémy, **non consultées** pour ce dossier.

## 5. L'infrastructure d'exécution

Tout ce paragraphe est **déclaré**, sauf mention contraire.

- Orchestration « Hermes » : un registre (`REGISTRE.md`), des dossiers OUTBOX et INBOX.
- Claude Code comme exécuteur autonome.
- Aider avec `qwen3-coder:30b-a3b-q4_K_M` sur une RTX 5060 Ti, avec `num_ctx=32768` obligatoire.
  Aider n'est plus installé sur ce poste (**vérifié** le 16/11) : l'agent local de Jérémy est aujourd'hui
  Claude Code branché sur Ollama par un routeur local, OmniRoute.
- Un routeur de modèles avec repli sur Ollama (`llm_router.py`, `config/llm_endpoints.json`). AetherTwin
  reprend l'idée dans `core/llm_router.py`, réécrit et testé ici.
- Une recherche documentaire hybride (BM25 + sémantique) sur 682 fragments.
- Un essai de fine-tuning QLoRA (« ov3rlord-coder »).
- Le détail de cet essai (modèle de base, données, durée) est dans les archives privées de Jérémy, **non
  consultées** pour ce dossier.

## 6. Les leçons techniques

Ces leçons sont **déclarées** par Jérémy. Plusieurs ont été retrouvées en construisant AetherTwin ; c'est
indiqué.

1. **Le fine-tuning transmet le style, pas les faits.** Le modèle affiné inventait des chemins et des
   configurations, de façon convaincante. Conclusion : la recherche documentaire (RAG) n'est pas
   optionnelle. Dans AetherTwin, le Professeur et l'assistant citent leurs sources (base locale
   `core/knowledge/`).
2. **Le contexte par défaut fait planter le chargement.** Un modèle de 30 B annonce 262 144 jetons de
   contexte ; laissé tel quel, l'allocation échoue au chargement. `num_ctx` doit être fixé.
   **Retrouvé ici** : `ollama show` annonce bien 262 144 pour les trois Qwen ; AetherTwin fixe 32 768.
3. **VRAM d'une RTX 5060 Ti** : environ 14,4 Go avec le 30 B en Q4 chargé, libérés après le `keep_alive`
   d'Ollama. Mesure d'AetherTwin, dans d'autres conditions (deux cartes, contexte de 32 768) :
   19,69 Gio répartis sur les deux cartes, puis 0 Mio sur la RTX 5060 Ti après déchargement.
4. **SeedVR2** : 64 images au plus par passe.
5. **La RAM** : plantage du système vers 97 % de RAM occupée ; le passage de 32 à 64 Go de RAM est le
   goulot suivant. **Retrouvé ici** le 23/11 avec Strata : manques de mémoire avec 32 Go de RAM.
6. **Variables d'environnement d'Ollama** : contournement `GGML_CUDA_NO_PINNED=1`, et lancement d'Ollama
   par un `.bat` pour que la variable atteigne bien le serveur.
7. **Sous Git Bash, la sortie d'Aider est peu fiable.** Vérifier avec `git log` et le contenu des
   fichiers, ou lancer depuis `cmd.exe`.

## 7. Pourquoi la VRAM, et pas le calcul

Les faits ci-dessus pointent tous vers la mémoire : le contexte qui ne s'alloue pas (leçon 2), un 30 B qui
remplit presque une carte de 16 Go (leçon 3), la RAM qui sature (leçon 5). Le détail, avec les mesures
d'AetherTwin, est dans [`docs/HARDWARE_FIT.md`](../docs/HARDWARE_FIT.md).

## 8. Questionnaire pour Jérémy

**Répondu par Jérémy le 25/11/2026** ; les réponses sont reportées plus haut. Les essais d'anime n'ont pas été
concluants : aucune démonstration publique n'en est citée.

1. En quelle année (et quel mois) le laboratoire Ov3rLoRd a-t-il commencé ?
2. Date du pivot de la chaîne d'anime vers le RPG ? Que reste-t-il du RPG ?
3. HandSegNet : val_IoU ? FootSegNet : confirmes-tu 0,9277 ?
4. Taille des jeux d'entraînement des modèles de segmentation, matériel et durée d'entraînement ?
5. Fine-tuning « ov3rlord-coder » : modèle de base, taille du jeu de données, durée ?
6. Les modules visage et corps sont-ils publiables, ou restent-ils privés ?
7. Y a-t-il une démonstration publique (vidéo, image) des essais d'anime que tu acceptes de citer ?
