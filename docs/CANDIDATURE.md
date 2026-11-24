# Dossier de candidature — ASUS Agent Computer Challenge (Advanced / High-End)

Ce fichier rassemble ce qu'il faut pour remplir le formulaire de dépôt, et la liste des gestes du gel.
Les textes sont prêts à copier. Les marqueurs `[À COMPLÉTER PAR JÉRÉMY : …]` restent à remplir.

## 1. Fiche

| Champ | Valeur |
|---|---|
| Nom du projet | AetherTwin (I&F Core) |
| Auteur | Jérémy (Onibaku Gumi), développeur ML autodidacte — compte GitHub `Ov3rLoRd-MLEngineer` |
| Catégorie | Advanced / High-End |
| Dépôt | `[À COMPLÉTER PAR JÉRÉMY : adresse du dépôt public]` |
| État évalué | tag `v0.1.0-concours`, branche `concours` |
| Licence | Apache 2.0 |
| Vidéo | `[À COMPLÉTER PAR JÉRÉMY : lien de la vidéo de 2 minutes]` (scénario : `docs/DEMO_SCRIPT.md`) |
| Matériel du poste | RTX 5080 16 Go + RTX 5060 Ti 16 Go, 32 Go de RAM, Windows 10, Ollama |

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
> de quota), avec une passation écrite. Il est dédié à Inoue et Fuma.

## 4. Les critères du jury, et où regarder

| Critère | Poids | Où le voir |
|---|---|---|
| Agentic AI / IA locale | 30 % | README, sections « Agentic AI » et « relais » ; `core/llm_router.py` ; serveurs MCP des modules ; `scripts/relay_orchestrator.py` |
| Faisabilité, reproductibilité | 30 % | archive de la version + `Installer AetherTwin.bat` ; `scripts/setup.ps1` ; `scripts/build_release.py --verify` (installation à neuf et tests) ; `pytest` ; `PROJECT_STATUS.md` (statuts honnêtes) |
| Originalité | 20 % | gardiens Inoue et Fuma branchés dans le démon ; modèles de segmentation publiés par l'auteur (HandSegNet, FootSegNet) ; atelier de circuits ; relais Cloud ⇄ Local |
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
