# Dossier de candidature — ASUS Agent Computer Challenge (High-End)

Ce fichier rassemble ce qu'il faut pour remplir le formulaire de dépôt, et la liste des gestes du gel.
Les textes sont prêts à copier. Les marqueurs `[À COMPLÉTER PAR JÉRÉMY : …]` restent à remplir.

## 1. Fiche

| Champ | Valeur |
|---|---|
| Nom du projet | AetherTwin (I&F Core) |
| Auteur | Jérémy (Onibaku Gumi), développeur ML autodidacte — compte GitHub `Ov3rLoRd-MLEngineer` |
| Catégorie | High-End (projet finalisé ou en cours de finalisation) |
| Dépôt | `[À COMPLÉTER PAR JÉRÉMY : adresse du dépôt public]` |
| État évalué | tag `v0.1.0-concours`, branche `concours` |
| Licence | Apache 2.0 |
| Vidéo | `[À COMPLÉTER PAR JÉRÉMY : lien de la vidéo de 2 minutes]` (scénario : `docs/DEMO_SCRIPT.md`) |
| Matériel du poste | RTX 5080 16 Go + RTX 5060 Ti 16 Go, 32 Go de RAM, Windows 10, Ollama ; une seconde RTX 5060 Ti achetée, pas encore montée |

## 1 bis. Formulaire Gleam : un texte par champ (25/11)

Formulaire : https://gleam.io/SMomy/asus-agent-computer-challenge. Textes prêts à copier, limites de mots
respectées (comptées). Les champs personnels (nom, e-mail, téléphone, date de naissance) sont à remplir par
Jérémy et ne sont **jamais** écrits dans le dépôt.

Dates : le règlement dit clôture le **25/11 à 23 h 59 CET** (avec une coquille « 2027 ») ; le compte à rebours
du formulaire Gleam va jusqu'au **06/12/2026 à 23 h 59 CET**. Par prudence, déposer le 25/11.

### Choix du niveau d'avancement du projet

High-End - Projet finalisé ou en cours de finalisation

### Nom du projet

AetherTwin (I&F Core)

### Problème à résoudre (max. 100 mots)

Un PC de joueur bien équipé reste sous-exploité par l'IA locale : chaque outil (assistant, traduction, tutorat, calcul) charge son propre modèle et se dispute une VRAM limitée, jusqu'à planter ou tout ralentir. Et la plupart des assistants envoient écrans de jeu, documents et voix dans le cloud. AetherTwin fait du PC un seul hub d'agents, entièrement local, qui sait quel modèle peut se charger, quand et sur quelle carte, et qui confie les calculs à de vrais outils au lieu de laisser un modèle deviner.

### Présentation de votre Agent IA (max. 150 mots)

AetherTwin (I&F Core) est un hub d'agents IA 100 % local pour Windows. Un démon observe la machine (jeu lancé, GPU, températures) et active le bon module : WoW Assistant en lecture seule avec overlay OBS filtré, traduction de manga (vision + langue), Professeur du CP à la terminale, calculatrice formelle, tableur, labo de chimie, studio d'image avec mes modèles HandSegNet et FootSegNet, studios de pixel art et d'audio, atelier de circuits. Deux gardiens veillent : Inoue répartit la VRAM entre les modèles Qwen d'Ollama, Fuma relance les modules plantés et surveille les températures. Les agents appellent de vrais outils (calcul exact, Python en bac à sable, données), servis aussi en MCP à Claude Code local et à Hermes Agent. Le projet est lui-même développé par deux agents qui se relaient, cloud puis local. Installation par une archive, plus de 1 100 tests.

### Fonctionnement de votre Agent IA (max. 150 mots)

Entrée : une question dans le Hub, une page de manga, l'état du jeu lu en lecture seule, ou un événement de la machine. Traitement : le démon local (FastAPI) passe la demande au module concerné, qui tourne dans son propre processus. Le routeur choisit le modèle (Qwen3 27B pour le texte, Qwen2.5-VL 7B pour la vision). Inoue vérifie la VRAM mesurée : elle décharge le gros modèle précédent ou met la demande en attente. Le modèle appelle des outils : calcul formel, Python en bac à sable, tableur, chimie, segmentation. C'est le résultat de l'outil, pas une estimation, qui revient dans la réponse, affichée mot à mot. Pendant ce temps, Fuma surveille la stabilité et les températures. Sortie : une réponse, une page traduite et réincrustée, un overlay OBS filtré, une simulation ou un fichier. Les mêmes outils sont exposés en MCP.

### Exécution locale de l'Agent (max. 100 mots)

Confidentialité : écrans de jeu, documents, pages et voix ne quittent jamais la machine, et l'overlay diffusé passe par un filtre. Disponibilité : tout marche hors ligne, sans quota ni panne d'API. Latence : l'assistant de jeu et la traduction répondent sur place, sans aller-retour réseau. Contrôle : je choisis les modèles, leur quantification et leur contexte, et les outils agissent dans un bac à sable que je maîtrise. Coût : aucun abonnement à la requête, le matériel déjà acheté sert à tout. Le cloud sert à développer le projet, jamais à le faire tourner.

### Technologies / Modèles / APIs / Frameworks utilisés

Python 3.11, FastAPI et Uvicorn (API locale compatible OpenAI), pywebview (fenêtre WebView2). Modèles sous Ollama : Qwen3 27B, Qwen3-Coder 30B-A3B, Qwen2.5-VL 7B (Q4_K_M, contexte fixé à 32 768). Option : Strata pour un modèle « mélange d'experts » Qwen3.6-35B-A3B. PyTorch CUDA et Segment Anything (ViT-B) avec mes modèles HandSegNet et FootSegNet (Hugging Face). SymPy (calcul formel), NumPy, Matplotlib, OpenCV, ONNX Runtime ; Piper (synthèse vocale) et faster-whisper (écoute) ; pynvml pour mesurer les GPU. Protocole MCP (serveurs stdio des modules, dont un pour OBS par obs-websocket). Agents de développement : Claude Code (cloud et local via Ollama) et Hermes Agent, en relais. Qualité : pytest (plus de 1 100 tests), ruff, CI GitHub Actions. Licence Apache 2.0.

### Environnement hardware / software actuel

PC sous Windows 10 Professionnel. Deux cartes NVIDIA : RTX 5080 16 Go et RTX 5060 Ti 16 Go (ASUS Dual), soit 32 Go de VRAM au total ; 32 Go de RAM. Une seconde RTX 5060 Ti 16 Go (ASUS Prime) est achetée, pas encore montée. Logiciels : Ollama (cache KV q8_0, flash attention), Python 3.11 en environnement virtuel, OBS Studio, World of Warcraft pour le module de jeu, ComfyUI que j'utilise aussi. Mesures publiées et datées dans docs/HARDWARE_FIT.md du dépôt.

### Bénéfices apportés par du matériel ASUS performant (max. 100 mots)

Une carte de 32 Go comme la Radeon AI PRO R9700 lèverait le mur que je mesure : mes modèles de 27 à 30 milliards de paramètres (16,8 à 19,7 Go) tiendraient sur une seule carte avec leur contexte, vision et langage ensemble, sans découpage entre deux GPU. Elle ouvrirait aussi l'image et la vidéo par IA (ComfyUI), dont les modèles ne se répartissent pas sur plusieurs cartes. Mes RTX resteraient au jeu, à OBS et à la segmentation. Et j'ajouterais au Hub un backend AMD, aujourd'hui non testé.

### Liens

- Repository GitHub (obligatoire en High-End) : `[À COMPLÉTER PAR JÉRÉMY : adresse du dépôt public]`
- Démo du projet (obligatoire en High-End, lien de téléchargement) : l'archive `dist/AetherTwin-IF-Core-…zip`
  publiée comme Release GitHub du tag `v0.1.0-concours` : `[À COMPLÉTER PAR JÉRÉMY : lien de la Release]`
- Vidéo de présentation (optionnelle ; non répertoriée acceptée) : `[À COMPLÉTER PAR JÉRÉMY : lien]`

## 2. Résumé court (environ 300 caractères)

> AetherTwin est un hub d'agents IA 100 % local : un démon observe la machine, active le bon module (jeu,
> traduction de manga, Professeur, labos, studios) et partage la VRAM entre les modèles Qwen sous Ollama.
> Deux gardiens, Inoue et Fuma, tiennent la mémoire et la stabilité.

## 3. Résumé long (environ 1 500 caractères)

> AetherTwin (I&F Core) est un hub d'agents qui tourne entièrement sur un PC Windows équipé de deux cartes
> NVIDIA grand public (32 Go de VRAM au total). Un démon central expose une API locale, compatible
> OpenAI, et lance chaque module dans son propre processus : assistant de jeu en lecture seule avec
> overlay OBS filtré, traduction locale de manga (modèle de vision + modèle de langue), Professeur du CP à
> la terminale, calculatrice formelle, tableur, labo de chimie, studios de pixel art et d'audio, atelier
> de circuits.
>
> Les modèles locaux ne devinent pas ce qu'ils peuvent calculer : ils délèguent à des outils exacts
> (calcul formel, Python en bac à sable, tableur), servis aussi en MCP à d'autres agents comme Claude Code
> local ou Hermes Agent.
>
> La contrainte matérielle est au centre du projet. Les modèles de 27 à 30 milliards de paramètres
> dépassent une carte de 16 Go, même en Q4_K_M : Inoue, la gardienne de la VRAM, n'autorise qu'un gros
> modèle à la fois et garde 10 % de réserve ; Fuma relance les modules plantés et surveille les
> températures. Les mesures sont publiées, datées, avec ce qui n'a pas pu être vérifié.
>
> Le projet est lui-même développé par deux agents qui se relaient (cloud, puis local pendant les coupures
> de quota), avec une passation écrite. Son jeu, AetherTwin I&F Hommage, est dédié à la mémoire d'Inoue et Fuma.

## 4. Les critères du jury, et où regarder

| Critère | Poids | Où le voir |
|---|---|---|
| Agentic AI / IA locale | 30 % | README, sections « Agentic AI » et « relais » ; `core/llm_router.py` ; serveurs MCP des modules ; `scripts/relay_orchestrator.py` |
| Faisabilité, reproductibilité | 30 % | archive de la version + `Installer AetherTwin.bat` ; `scripts/setup.ps1` ; `scripts/build_release.py --verify` (installation à neuf et tests) ; `pytest` ; `PROJECT_STATUS.md` (statuts honnêtes) |
| Originalité | 20 % | gardiens Inoue et Fuma branchés dans le démon ; modèles de segmentation publiés par l'auteur (HandSegNet, FootSegNet), présentés avec leurs dépôts et installables en un clic dans l'onglet Studio image ; atelier de circuits ; relais Cloud ⇄ Local |
| Adéquation matérielle | 20 % | `docs/HARDWARE_FIT.md` : mesures réelles, mur de la VRAM, ce qu'une carte de 32 Go simplifierait, ce qui n'est pas prouvé |

## 5. Contenu du dossier

| Fichier | Rôle |
|---|---|
| `README.md` | présentation, architecture, installation, démo, vérifié / non vérifié, feuille de route |
| `docs/HARDWARE_FIT.md` | adéquation matérielle |
| `docs/DEMO_SCRIPT.md` | scénario de la vidéo de 2 minutes |
| `docs/RELEASE.md` | construire et vérifier l'archive installable |
| `research/overlord_notes.md` | le laboratoire Ov3rLoRd, dont vient le projet (avec questionnaire) |
| `PROJECT_STATUS.md` | état de chaque brique, mesures, essais restants |
| `ARCHITECTURE_MAP.md` | carte du code, générée |
| `AGENT_HANDOFF.md`, `logs/CHANGELOG_DEV.md` | passation entre agents, journal de développement |
| `THIRD_PARTY.md`, `LICENSE`, `NOTICE` | licences |

## 6. Le gel (à faire par Jérémy, dans cet ordre)

Rien de ceci n'a été fait automatiquement : le push et le tag restent des décisions de Jérémy.

1. Relire le README, `docs/HARDWARE_FIT.md` et `research/overlord_notes.md` ; remplir les marqueurs.
2. Refaire l'archive et la vérifier :

   ```powershell
   .\.venv\Scripts\python.exe scripts\build_release.py --verify
   ```

3. Vérifier qu'aucun secret n'est dans l'**historique** (le test d'hygiène ne regarde que l'état courant) :

   ```powershell
   git log -p --all | Select-String -Pattern 'sk-ant-|ghp_|hf_[A-Za-z0-9]{30}|AKIA|BEGIN .*PRIVATE KEY'
   ```

   Aucune ligne attendue.
4. Figer l'état évalué :

   ```powershell
   git branch concours main
   git tag -a v0.1.0-concours concours -m "État soumis au concours ASUS Agent Computer Challenge"
   ```

5. Créer le dépôt public sur GitHub, puis pousser `main`, `concours` et le tag.
6. Vérifier sur GitHub que la CI passe (Windows et Ubuntu) et que le dépôt s'ouvre sans être connecté.
7. Déposer la candidature avec le lien du dépôt, le tag et la vidéo.
