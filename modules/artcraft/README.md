# artcraft — intégration externe de la suite libre ArtCraft

Onglet **Outils → ArtCraft** du Hub : installer, ouvrir et brancher sur un agent (MCP) les dix logiciels libres de
l'écosystème **ArtCraft**, écrits en Rust par l'équipe ArtCraft (Brandon Thomas et contributeurs).

> **Intégration externe.** Ces logiciels ne font pas partie d'AetherTwin et ne sont pas fournis avec lui. Ils sont
> publiés sous double licence **MIT ou Apache 2.0** sur [github.com/storytold](https://github.com/storytold)
> ([getartcraft.com](https://getartcraft.com)). Ils n'ont aucun lien avec Adobe ni Microsoft : les noms de ces
> éditeurs servent seulement à dire quel usage chaque logiciel couvre. Le nom, le logo et les icônes ArtCraft sont
> des marques de l'équipe ArtCraft et ne relèvent pas de la licence libre : AetherTwin ne les copie pas dans son dépôt.

| Famille | Logiciel | Pour |
|---|---|---|
| Création | PhotoCraft | retouche photo (comme Photoshop) |
| Création | VectorCraft | dessin vectoriel (comme Illustrator) |
| Création | FilmCraft | montage vidéo (comme Premiere Pro) |
| Création | LightCraft | catalogue photo, RAW (comme Lightroom) |
| Création | EffectCraft | effets et animation (comme After Effects) |
| Création | DesignCraft | mise en page (comme InDesign) |
| Création | PdfCraft | PDF (comme Acrobat Pro) |
| Bureautique | WordCraft | traitement de texte .docx (comme Word) |
| Bureautique | GridCraft | tableur .xlsx (comme Excel) |
| Bureautique | DeckCraft | présentations .pptx (comme PowerPoint) |

Ces logiciels sont jeunes (alpha ou en développement) : garde une copie de tes fichiers importants. Un logiciel
qui n'a pas encore de version Windows publiée affiche simplement « pas de version Windows x64 ».

## Installer

Bouton **Installer** d'une carte. Le Hub :

1. demande à l'API GitHub la dernière publication de `storytold/<logiciel>` ;
2. choisit la version **portable** Windows x64 (un zip, sans droits administrateur), sinon l'installateur `.msi` ;
3. télécharge aussi `SHA256SUMS.txt` et **compare l'empreinte SHA-256** : fichier refusé si elle diffère ou manque ;
4. extrait le zip dans `data/artcraft/apps/<logiciel>/` (aucun fichier ne peut sortir de ce dossier).

Avec un `.msi`, l'installateur officiel s'ouvre : c'est toi qui l'acceptes dans sa fenêtre. **Mettre à jour**
refait la même chose avec la dernière publication ; **Retirer** supprime la version portable (un `.msi` se
désinstalle dans les paramètres de Windows).

Le module ne contacte que `api.github.com`, `github.com` (et ses serveurs de fichiers) et
`raw.githubusercontent.com`, toujours sous `storytold/`.

## Icônes

Bouton **Icônes officielles** : télécharge les icônes du kit presse ArtCraft
([getartcraft.com/press-kit](https://getartcraft.com/press-kit)) et les garde **sur ce PC** (`data/artcraft/icons/`,
réduites à 128 px pour l'affichage, sans retouche). Sans elles, chaque carte montre une initiale.

## Brancher sur un agent (MCP)

Chaque logiciel livre un outil en ligne de commande `<logiciel>-cli` dont la commande `mcp` démarre un serveur MCP
(stdio) : un agent peut créer et modifier des images, des documents, des feuilles de calcul…

- **Claude Code** : bouton **MCP**, puis copier la ligne `claude mcp add <logiciel> -- "<chemin>\<logiciel>-cli.exe" mcp`.
- **Hermes Agent** : bouton **Brancher sur Hermes** (serveur nommé `artcraft_<logiciel>`).

## Commandes du module

`catalog`, `icons`, `icon {app}`, `install {app}`, `uninstall {app}`, `launch {app}`, `mcp {app}`,
`hermes {app, register?}` — voir `module.py`.
