# circuit_lab — atelier circuits Æther

Un établi d'électronique virtuel. On y monte une **console de jeu 8 bits** ou une **console 16 bits** composant
par composant, on l'allume sur un **téléviseur cathodique**, et on écrit ses propres **cartouches** en assembleur
6502 ou 65816. Deux autres établis : un **banc logique** (portes, bascules, compteurs à câbler, chronogramme) et des
**cartes à microcontrôleur** (RP2040 et AVR) à programmer, avec LED, boutons, afficheur ou écran.

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

## L'établi 16 bits : la console « Japon grise 16 bits 1990 »

Le deuxième onglet d'établi monte une **console 16 bits** (les noms commerciaux des consoles sont des marques : chaque
machine de l'atelier est nommée par son origine, sa couleur, son nombre de bits et sa date de sortie). Douze pièces
aussi, chacune avec sa panne :

| Pièce | Référence | Si elle manque |
|---|---|---|
| Alimentation 5 V | régulateur 7805 | rien ne s'allume |
| Quartz 21,477 MHz | oscillateur NTSC | aucune puce n'avance, neige |
| Processeur 65C816 | 65C816 + DMA | la vidéo reste « écran éteint » : image noire |
| RAM de travail 128 Ko | DRAM 128K | la pile est perdue, le programme plante |
| Puce vidéo 1 | PPU1 | plus aucun motif : seule la couleur de fond sort |
| Puce vidéo 2 | PPU2 | pas de synchro : la télé n'a aucun signal |
| Mémoire vidéo 64 Ko | 2 × SRAM 32K | motifs parasites à la place du décor |
| Module son | SPC700 + DSP + 64 Ko | silence, et le programme qui attend le module reste bloqué au démarrage |
| Connecteur de cartouche, cartouche, ports de manettes, sortie vidéo | | comme sur la console 8 bits |

Ce qui est simulé :

- **Processeur 65C816** complet (mode émulation 6502 et mode natif, registres 8 ou 16 bits, 16 Mo d'adresses,
  décimal, MVN/MVP) ; le temps se compte en cycles de l'horloge maître (6, 8 ou 12 par accès selon la zone, comme
  sur la vraie carte). Multiplication et division matérielles, minuterie H/V, lecture automatique des manettes.
- **DMA** (8 canaux, tous les modes) et **HDMA** (direct et indirect) : changer un registre à chaque ligne sans le
  processeur (dégradés, ondulations).
- **Vidéo** : modes 0 à 7 (dont la rotation du mode 7), 128 sprites de 8×8 à 64×64, fenêtres, transparences
  (addition, soustraction, moitié), mosaïque, luminosité, 32 768 couleurs.
- **Module son** : processeur SPC700 avec ses minuteries, DSP à 8 voix (échantillons BRR, enveloppes ADSR et GAIN,
  bruit, modulation de hauteur, écho à 8 coefficients). La petite ROM de démarrage du module est un microcode du
  fabricant : elle **n'est pas fournie**, son protocole public de chargement (attente de `$CC`, octets numérotés,
  saut au programme) est reproduit en JavaScript.
- **Cartouches** `.sfc` / `.smc` : cartes « LoROM » et « HiROM » reconnues par leur en-tête, en-tête de copieur de
  512 octets retiré, mémoire de sauvegarde. Les cartouches à puce supplémentaire (coprocesseur) sont refusées avec
  un message : **en cours**.

L'onglet **Programmation** suit l'établi choisi : avec la console 16 bits, c'est un assembleur **65816** (directives
`.bank`, `.long`, `.tile4` pour les tuiles 16 couleurs, `.title`, largeurs suivies automatiquement après
`rep`/`sep` ou fixées par `.a8 .a16 .i8 .i16`, suffixes `.b .w .l`, `^etiquette` pour la banque). Il produit une
cartouche LoROM avec son en-tête et sa somme de contrôle (**Exporter .sfc**). Les programmes enregistrés de chaque
établi sont gardés à part dans la page.

L'exemple **« Fuma au clair de lune »** : un ciel en dégradé par HDMA, la lune, des étoiles qui scintillent, Fuma
qui marche sur l'herbe (flèches) et miaule une note (B) : le programme envoie au module son un petit programme
SPC700 puis lui dit quoi jouer. Manette 16 bits au clavier : flèches, **X** = A, **W/Z** = B, **Q/A** = Y,
**S** = X, **D** = L, **C** = R, **Entrée** = Start, **Maj droite** = Select.

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

## Le banc logique (façon FPGA)

Onglet **Banc logique** : on pose des pièces sur une grille et on les câble à la souris (clic sur une sortie, à
droite d'une pièce, puis sur une entrée, à gauche ; ou l'inverse). Les fils allumés portent un 1.

- **Entrées** : interrupteur (clic), bouton poussoir (tant qu'on appuie), horloge (demi-période réglable),
  constantes 0 et 1.
- **Sorties** : LED (4 couleurs), sonde, afficheur 7 segments hexadécimal (4 bits) ou brut (8 segments).
- **Portes** : NON, ET, OU, NON-ET, NON-OU, OU exclusif, NON-OU exclusif.
- **Bascules** : verrou SR, bascules D, T et JK (front montant, remise à zéro immédiate).
- **Blocs** : compteur 4 bits (validation, remise à zéro, chargement, retenue), registre 4 bits, additionneur
  complet, additionneur 4 bits, multiplexeurs (1 bit et 4 bits), décodeur 2 vers 4, mémoire ROM 16 × 8 éditable.

**Lancer**, **Pas** (touche Espace : une demi-période d'horloge) et **Remise à zéro**. Le **chronogramme** trace les
entrées, horloges, LED et sondes. Toutes les bascules d'un même front prennent leur nouvel état en même temps,
calculé sur les entrées d'avant le front (comme en vrai). Une boucle sans bascule qui ne se stabilise pas (un
inverseur rebouclé sur lui-même) est signalée : « instable : le circuit oscille ».

Montages d'exemple : demi-additionneur, additionneur complet en portes, verrou SR en portes NON-OU, diviseur
d'horloge en bascules D, compteur 4 bits sur 7 segments, et un **petit processeur 4 bits** (compteur de programme,
ROM, additionneur, multiplexeur, accumulateur ; trois instructions : CHARGE, AJOUTE, SAUTE). Le montage se garde
dans la page et s'exporte ou s'importe en fichier `.logique.json`.

## Les microcontrôleurs

Onglet **Microcontrôleurs** : deux cartes, simulées instruction par instruction, à programmer en assembleur.

- **Carte RP2040** (le microcontrôleur du Raspberry Pi Pico : un cœur ARM Cortex-M0+, jeu Thumb, 125 MHz).
  LED sur GP0 à GP3 et GP25 (LED de la carte), boutons 1 à 4 sur GP10 à GP13 (appuyé = 1). Le programme est
  chargé en SRAM à `0x20000000` et démarre à l'étiquette `main`. Comme sur la vraie puce, il faut libérer
  IO_BANK0, PADS_BANK0 et TIMER (registre RESETS), choisir la fonction 5 (SIO) de chaque broche, puis activer la
  sortie (`GPIO_OE_SET`). Le TIMER compte les microsecondes (`TIMERAWL`). Alias atomiques des registres
  (`+0x1000` XOR, `+0x2000` SET, `+0x3000` CLR) ; une erreur d'accès arrête le cœur avec un message « HardFault ».
- **Carte AVR 8 bits** (ATmega328P, 16 MHz). LED sur PB0 à PB3 et PB5 (LED « L »), boutons 1 à 4 sur PC0 à PC3
  (reliés à la masse : il faut activer le tirage haut). Ports B, C, D (`DDRx`, `PORTx`, `PINx`), minuterie 0
  (pré-diviseur, débordement, mode CTC) et ses interruptions, `sleep`, pile, lecture de la flash par `lpm`.
- **Module** branché sur la carte, au choix : **afficheur 7 segments** ou **écran LCD 16 × 2** (contrôleur HD44780
  en mode 4 bits : il faut l'initialiser comme un vrai, trois fois 3 puis 2).

La luminosité d'une LED ou d'un segment est la part du temps où sa broche est restée à 1 : une modulation de
largeur d'impulsion ou un affichage multiplexé se voient comme sur une vraie carte. Le panneau montre les
registres, la ligne du programme en cours, et un diagnostic (broche oubliée en entrée, fonction SIO non choisie,
bloc encore en reset…). **Pause**, **Instruction suivante** et **RESET** ; les boutons se pressent à la souris ou
avec les touches 1 à 4. Huit exemples : clignotant, chenillard (par interruption sur l'AVR), compteur sur
7 segments avec deux boutons, « Bonjour » sur l'écran LCD, pour chaque carte.

Les deux assembleurs suivent la syntaxe habituelle : celle d'avra pour l'AVR (`.org`, `.equ`, `.def`, `.db`,
`low()`, `high()`), celle de GNU as pour le Thumb (`movs`, `ldr r0, =valeur`, `push {r4, lr}`, `.word`, `.ltorg`).
L'aide-mémoire sous l'éditeur donne les broches, les registres et les instructions de chaque carte.

## Ce qui est simulé, et ce qui ne l'est pas

- Processeur 6502 exact à l'instruction près (vérifié avec le test de référence `nestest`, instructions officielles
  et non officielles courantes).
- Vidéo : fonds, sprites, défilement, détection du sprite 0, rendu ligne par ligne. Palette calculée à partir du
  signal NTSC.
- Son : deux voies carrées, triangle et bruit. La voie d'échantillons (DMC) est **en cours**.
- Cartouches : mappeur 0 (NROM, 32 Ko de programme et 8 Ko de motifs). Les autres mappeurs sont **en cours**.
- Au niveau des transistors, une console entière est trop lente pour tourner en direct : l'atelier simule
  chaque puce par son comportement, et les pannes par ce qu'elles font sur les bus.
- Microcontrôleurs : cœurs complets (jeu Thumb ARMv6-M, jeu AVR sauf quelques multiplications signées et
  `elpm`) ; périphériques limités à ce que les cartes utilisent. Le second cœur du RP2040, ses interruptions, PIO,
  UART, ADC et PWM matériel, et sur l'AVR les minuteries 1 et 2, l'UART et l'ADC sont **en cours**. Un Raspberry Pi
  complet (processeur ARM sous Linux) dépasse ce qu'une page peut simuler en direct.

Aucun jeu commercial, logo ni marque n'est fourni : la console de l'atelier est une machine **compatible** avec le
format de cartouche iNES. Tu peux y charger tes propres fichiers `.nes` (mappeur 0).

## Commandes du module

`POST /modules/circuit_lab/command/<commande>` (ou bus `module.circuit_lab.cmd.<commande>`) :
`examples`, `example {"name"}`, `projects`, `project_load {"name"}`, `project_save {"name", "source"}`,
`project_delete {"name"}`. L'émulation et l'assemblage tournent dans la page (JavaScript, sans dépendance externe).
