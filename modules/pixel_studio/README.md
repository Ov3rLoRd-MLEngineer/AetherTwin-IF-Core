# pixel_studio — studio pixel art

Studio de pixel art du Hub, pensé pour le jeu façon RPG 16 bits d'AetherTwin : **sprites, animations, cartes en
tuiles**, exports PNG, planches de sprites, GIF animés, et des **outils pour les agents locaux** (un modèle dessine
un sprite en texte, le studio le range). Tout est local : Pillow (MIT-CMU) côté serveur, Canvas 2D dans la page,
aucune ressource externe, aucune VRAM.

## Ouvrir

- Tableau de bord → onglet **Outils** → sous-onglet **Studio pixel** (le studio intégré, sur toute la largeur).
- Bouton **Ouvrir le studio** (ou « Lancer » sur la carte du module) : fenêtre de bureau (Edge en mode application,
  1320×860, profil `data/pixel_studio/window-profile`), fermée par « Arrêter l'application ».

Configuration facultative, section `pixel_studio` de `config/local.yaml` :

```yaml
pixel_studio:
  data_dir: "data/pixel_studio"   # projets, exports, sprites pour les jeux (ignoré par Git)
```

## Ce que fait la page (`core/web/pixel_app.*`)

| Zone | Contenu |
|---|---|
| Outils | crayon (taille 1 à 8), gomme, pot (Maj : toute la couleur), pipette (Alt), ligne (Maj : 45°), rectangle et ellipse (Maj : pleins), sélection (déplacer, copier, couper, coller, retourner, flèches), tramage, ombrage le long de la palette ; symétries gauche-droite et haut-bas, grille, pelure d'oignon |
| Couleurs | principale (clic gauche) et secondaire (clic droit), transparent ; palettes intégrées ; double-clic sur une couleur : la change **partout** dans le projet ; rampe de 5 tons avec glissement de teinte ; palette tirée d'une image |
| Calques | jusqu'à 32 : visibilité, opacité, ordre, renommer (double-clic), dupliquer, fusionner vers le bas |
| Images | jusqu'à 256 : ajouter, dupliquer (Ctrl+D), déplacer, durée par image, lecture (Entrée), aperçu animé ×1 à ×8 sur fond au choix |
| Carte | les images du projet servent de tuiles ; couches sol et décor ; cases bloquantes (⛔) ; poser, effacer, remplir, prendre ; 128×128 cases au plus |
| Projet | nouveau (tailles types 8 à 128), projets enregistrés avec vignettes, enregistrement automatique 1,5 s après une modification, taille de la toile (clic sur la taille en bas), import d'une image (toile vide : la toile prend sa taille ; sinon collée en sélection flottante) |
| Exports | PNG de l'image courante, planche + JSON, GIF animé en boucle, carte + JSON, agrandissement ×1 à ×16 ; fichiers téléchargés et gardés dans `data/pixel_studio/exports` |
| Jeu | bouton **Jeu** : sprite et carte écrits dans `data/pixel_studio/sprites` pour les jeux Python de la calculatrice |

Annuler / rétablir : 80 pas (Ctrl+Z, Ctrl+Y). Raccourcis : touche **F1** ou bouton « ? ». Thème sombre ou clair.

## Format `.aether-pixel`

JSON dans `data/pixel_studio/projects/<nom>.aether-pixel` ; chaque case (calque × image) est un PNG RGBA en base64 :

```json
{"format": "aether-pixel", "version": 1, "name": "fuma", "width": 32, "height": 32,
 "palette": ["#0e1116", "…"],
 "layers": [{"name": "Fond", "visible": true, "opacity": 1.0}],
 "frames": [{"duration": 120, "cels": ["<PNG base64>"]}],
 "tilemap": {"cols": 20, "rows": 12, "ground": [-1, 3], "decor": [], "solid": [0, 1]}}
```

Le serveur contrôle tout ce qu'il reçoit (`project.validate`) : tailles (512 px de côté, 32 calques, 256 images,
64 millions de pixels au total, 40 Mo par fichier), PNG décodables et à la bonne taille, indices de carte. Les noms
de fichiers sont nettoyés (minuscules, chiffres, `_`, `-` ; « Cœur » → `coeur`) : jamais de chemin.

## Dans les jeux de la calculatrice

```python
import jeu
jeu.fenetre(480, 360, "Démo")
n = 0
while jeu.image(30):
    jeu.effacer("noir")
    jeu.carte("niveau", 0, 0, echelle=2)                  # sol puis décor
    jeu.sprite("fuma", 200, 160, echelle=3, image=n // 4)  # image prise modulo le nombre d'images
    if jeu.bloque("niveau", 210, 200, 0, 0, 2): ...        # le point tombe-t-il sur une case bloquante ?
    n += 1
```

Le processus du jeu lit seulement le dossier des sprites (nom vérifié), comme le reste du bac à sable.

## Pour les agents (bus du Hub et MCP)

Commande `tool` du module, ou serveur MCP stdio **`aethertwin_pixel`** (`modules/pixel_studio/mcp_server.py`,
bouton « Brancher sur Hermes » du sous-onglet). Six outils :

| Outil | Rôle |
|---|---|
| `pixel_list_projects` | projets (nom, taille, images, carte) |
| `pixel_palettes` | palettes intégrées ; l'indice d'une couleur est son symbole dans les grilles |
| `pixel_make_palette` | rampe de tons autour d'une couleur |
| `pixel_create_sprite` | sprite (64×64 au plus) depuis des grilles de texte, une image ou une animation |
| `pixel_read_sprite` | une image en grille de texte, avec sa palette |
| `pixel_export_for_game` | prépare le sprite pour `jeu.sprite()` / `jeu.carte()` |

Grille de texte : une chaîne par ligne, `.` transparent, `0-9`, `a-z`, `A-Z` = indice dans la palette. Un cœur 7×6
sur `aether16` (`c` = rouge) : `[".cc.cc.", "ccccccc", "ccccccc", ".ccccc.", "..ccc..", "...c..."]`.

## Commandes du module

`projects`, `project_load`, `project_save`, `project_delete`, `palettes`, `palette_ramp`, `palette_from_image`,
`export`, `game_export`, `exports_open`, `hermes`, `hermes_register`, `tools`, `tool` (détail en tête de
`module.py`).

## Palettes intégrées

Créées pour AetherTwin (aucune palette reprise d'un jeu ou d'une console) : Æther 16, Æther 32 (rampes), Pelages
(Fuma et Inoue), Console 4 verts, Gris 8 tons, Forêt et pierre.

## Limites

- Couleurs RGBA libres : la palette sert de nuancier, pas d'indexation stricte ; un GIF de plus de 255 couleurs est
  quantifié image par image. Les images GIF identiques consécutives sont fusionnées (durées additionnées).
- Pas de calques de groupe ni de modes de fusion ; pas d'import de planches (une image à la fois).
- La carte utilise les images d'un seul projet comme tuiles (pas de jeu de tuiles partagé entre projets).
- L'interface a été vérifiée dans le navigateur intégré (Chromium) et la fenêtre Edge ; pas sur écran tactile.

## Tests

`tests/pixel_studio/` (15 tests) : palettes, noms sûrs, contrôle des projets, grilles de texte, assemblage des
calques, exports, stockage, outils des agents, MCP (dans le processus et en sous-processus), sprites dans `jeu`
(pygame sans écran), fenêtre et page (identifiants, aucune ressource externe, CSP du Hub).
