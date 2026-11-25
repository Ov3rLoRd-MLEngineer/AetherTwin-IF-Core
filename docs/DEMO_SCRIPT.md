# Scénario de la vidéo de présentation (2 minutes)

But : montrer en deux minutes un Hub d'agents **locaux** qui observe la machine, choisit le bon module et
partage la VRAM, sur le poste réel (RTX 5080 + RTX 5060 Ti, Ollama). Pas de montage trompeur : chaque
plan est filmé en direct. Les temps de chargement à froid peuvent être coupés, et le montage le signale
par un fondu et un compteur (« chargement du modèle : 11 s »).

## Préparation (hors caméra)

1. `Lancer AetherTwin.bat` ; le Hub s'ouvre dans sa fenêtre. Thème sombre.
2. Ollama démarré, `qwen3-27b` et `qwen2.5vl:7b` installés. Rien de chargé au départ (onglet Accueil :
   aucun modèle).
3. Une page de manga **libre de droits** prête (par exemple la page de test du dépôt). Aucune page
   protégée à l'écran.
4. Si WoW est montré : personnage de test, noms masqués (`hide_character_names`), OBS ouvert pour le
   mode Showcase.
5. Fermer les notifications de Windows. Masquer la barre des favoris et tout chemin personnel.

## Déroulé

| Temps | Image | Voix off (à dire, ou à mettre en sous-titres) |
|---|---|---|
| 0:00–0:10 | Logo Yin et Yang, puis l'Accueil du Hub : les deux cartes, leur charge, le budget d'Inoue | « AetherTwin est un hub d'agents qui tourne entièrement sur ma machine. Deux cartes, 32 Go de VRAM, et aucun appel au cloud. » |
| 0:10–0:25 | Accueil : budget VRAM d'Inoue, état de Fuma ; une question à l'Assistant ; la réponse s'écrit mot à mot ; la jauge de VRAM monte | « Inoue garde la mémoire des cartes : un seul gros modèle à la fois, 10 % de réserve. Fuma surveille la stabilité et les températures. » |
| 0:25–0:45 | Onglet Jeu : WoW Assistant, état du personnage lu en lecture seule ; OBS s'ouvre, l'overlay bascule en Showcase (noms et or masqués) | « Quand je joue, le module de jeu lit l'état de la partie, sans rien modifier. Si je diffuse, tout passe par un filtre de confidentialité. » |
| 0:45–1:05 | Onglet Scantrad : la page de test ; bulles détectées dans l'ordre de lecture, lues par le modèle de vision, traduites, réincrustées ; une zone corrigée à la main | « Un modèle de vision lit les bulles, un modèle de langue traduit, et je garde la main sur chaque zone. Les deux modèles se relaient dans la VRAM. » |
| 1:05–1:25 | Onglet Professeur : un chapitre de 4e, un exercice corrigé ; une simulation créée par le modèle local s'ouvre | « Le Professeur suit les programmes du CP à la terminale. Il cite ses sources, et peut écrire lui-même une simulation. » |
| 1:25–1:40 | Onglet Outils : la calculatrice donne un résultat exact ; un agent appelle `python_run` ; l'atelier circuits allume une LED sur la carte RP2040 simulée | « Les agents ont de vrais outils : calcul exact, Python en bac à sable, données, chimie, pixel art, voix, exposés aussi en MCP. » |
| 1:40–1:52 | Onglet Développement : le relais Cloud ⇄ Local en simulation (`--dry-run`), passage au local puis retour | « Le projet lui-même est développé par deux agents qui se relaient : quand le quota du cloud tombe, un agent local reprend, avec une passation écrite. » |
| 1:52–2:00 | Onglet AetherTwin I&F Hommage : le bandeau de dédicace, Fuma et Inoue au bord du lac ; puis « À Inoue et Fuma. » sur fond sombre et l'adresse du dépôt | (silence) |

## Ce qu'il ne faut pas montrer ou dire

- Ni clé, ni jeton, ni chemin de dossier personnel, ni nom de compte Battle.net.
- Ne pas annoncer de mesure qui ne figure pas dans `docs/HARDWARE_FIT.md`.
- Ne pas dire que la topologie à trois cartes ou une carte de 32 Go ont été testées : elles ne l'ont pas été.
- Le relais Cloud ⇄ Local est **testé en simulation** : le montrer comme tel (`--dry-run`), sans prétendre
  qu'il a déjà tenu une vraie coupure de quota.

`[À COMPLÉTER PAR JÉRÉMY : durée réelle de chaque plan après le tournage, et musique éventuelle (libre de droits)]`
