# circuit_lab — atelier circuits Æther

Un établi d'électronique virtuel. On y monte une **console de jeu 8 bits** composant par composant, on l'allume
sur un **téléviseur cathodique**, et on écrit ses propres **cartouches** en assembleur 6502.

Ouverture : Hub → onglet **Outils** → **Atelier circuits**, ou le bouton **Ouvrir l'atelier** pour sa propre fenêtre.

## L'établi : monter la console

La carte mère a douze supports. Chaque pièce a son rôle, sa vraie référence et une panne précise quand elle manque :

| Pièce | Référence | Si elle manque |
|---|---|---|
| Alimentation 5 V | régulateur 7805 | rien ne s'allume |
| Quartz 21,477 MHz | oscillateur NTSC | aucune puce n'avance, la télé montre de la neige |
| Processeur 6502 + son | type RP2A03 | l'écran reste uni, rien ne bouge |
| Mémoire de travail 2 Ko | SRAM 6116 | le programme lit du bruit et plante |
| Décodeur d'adresses | 74LS139 | personne n'est sélectionné, démarrage n'importe où |
| Processeur vidéo | type RP2C02 | pas de signal vidéo (neige) |
| Mémoire vidéo 2 Ko | SRAM 6116 | décor remplacé par des motifs répétés |
| Verrou d'adresses vidéo | 74LS373 | tuiles brouillées, image en morceaux |
| Connecteur de cartouche | 72 broches | ni programme ni motifs |
| Cartouche | ROM programme + ROM motifs | vecteur de démarrage au hasard |
| Ports de manettes | 2 × 7 broches | les boutons ne répondent pas |
| Sortie vidéo composite | modulateur | la console tourne, la télé ne reçoit rien |

Ces pannes ne sont pas des messages écrits à l'avance : la machine tourne vraiment avec la pièce en moins
(bus de données « flottant », adresses mélangées…), et l'écran montre ce qui se passerait sur une vraie carte.

- **Monter** : glisser une pièce sur son support, ou cliquer dessus dans la liste.
- **Retirer** : double-clic sur la pièce, ou le bouton dans sa fiche.
- **Allumer**, **Reset**, choix de la **cartouche** : l'exemple, ton programme, ou un fichier `.nes` à toi.
- Pendant que la console tourne, les pistes et les puces s'éclairent selon les accès sur les bus.

## Le téléviseur

L'écran à droite imite un tube cathodique : verre bombé, lignes de balayage, masque de phosphore, halo,
neige sans signal, point blanc à l'extinction. **Grand écran** l'ouvre dans sa propre fenêtre (réglages du verre,
des lignes et du halo, plein écran avec F11). La case **Effet cathodique** donne une image nette.

Manette 1 au clavier : flèches, **X** = A, **W** (ou Z) = B, **Entrée** = Start, **Maj droite** = Select.
Une manette USB branchée marche aussi. Le volume part bas (20 %).

## La programmation

L'onglet **Programmation** est un éditeur d'assembleur 6502 avec un assembleur intégré :

- **Assembler** : les erreurs s'affichent en français avec leur ligne (clic → la ligne est sélectionnée) ;
- **Lancer sur la console** (Ctrl+Entrée) : assemble, insère la cartouche et allume ;
- **Exporter .nes** : la cartouche au format iNES (mappeur 0), lisible par les émulateurs courants ;
- **Enregistrer / Ouvrir** : les programmes sont rangés dans `data/circuit_lab/programs/`.

L'exemple **« Fuma et les étoiles »** (le chat attrape des étoiles qui tombent, score affiché, petit bip) montre
tout ce qu'il faut : démarrage de la console, palettes, tuiles dessinées en texte (`.tile`), sprites par DMA,
lecture de la manette, son, interruption de fin d'image. L'aide-mémoire sous l'éditeur liste les directives
et les registres.

Le panneau **débogueur** montre les registres du processeur et les prochaines instructions (avec leur ligne
dans ton programme) ; **Pause**, **Image suivante** et **Instruction suivante** permettent d'avancer pas à pas.

## Ce qui est simulé, et ce qui ne l'est pas

- Processeur 6502 exact à l'instruction près (vérifié avec le test de référence `nestest`, instructions officielles
  et non officielles courantes).
- Vidéo : fonds, sprites, défilement, détection du sprite 0, rendu ligne par ligne. Palette calculée à partir du
  signal NTSC.
- Son : deux voies carrées, triangle et bruit. La voie d'échantillons (DMC) est **en cours**.
- Cartouches : mappeur 0 (NROM, 32 Ko de programme et 8 Ko de motifs). Les autres mappeurs sont **en cours**.
- Au niveau des transistors, une console entière est trop lente pour tourner en direct : l'atelier simule
  chaque puce par son comportement, et les pannes par ce qu'elles font sur les bus.
- **Banc logique** (portes et bascules façon FPGA) et **microcontrôleurs** (RP2040 du Raspberry Pi Pico, AVR) :
  **en cours**. Un Raspberry Pi complet (processeur ARM sous Linux) dépasse ce qu'une page peut simuler en direct.

Aucun jeu commercial, logo ni marque n'est fourni : la console de l'atelier est une machine **compatible** avec le
format de cartouche iNES. Tu peux y charger tes propres fichiers `.nes` (mappeur 0).

## Commandes du module

`POST /modules/circuit_lab/command/<commande>` (ou bus `module.circuit_lab.cmd.<commande>`) :
`examples`, `example {"name"}`, `projects`, `project_load {"name"}`, `project_save {"name", "source"}`,
`project_delete {"name"}`. L'émulation et l'assemblage tournent dans la page (JavaScript, sans dépendance externe).
