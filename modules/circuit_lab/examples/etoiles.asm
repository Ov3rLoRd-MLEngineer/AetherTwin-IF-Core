; =====================================================================================================
;  Fuma et les étoiles — jeu d'exemple de l'atelier circuits (cartouche de 16 Ko, mappeur 0)
;
;  Fuma, le chat, attrape les étoiles qui tombent. Flèches gauche et droite (ou Q et D au clavier).
;  Le programme suit le schéma classique d'un jeu de cette console :
;    1. au démarrage : attendre que la vidéo soit prête, vider la mémoire, charger palette et décor ;
;    2. une boucle principale qui attend la NMI (envoyée par la vidéo à chaque image, 60 fois par seconde) ;
;    3. pendant la NMI : copier les sprites (DMA) et le score à l'écran, quand la vidéo ne dessine pas.
; =====================================================================================================

; ---------- registres de la console ----------
PPUCTRL   = $2000      ; NMI, tables de motifs
PPUMASK   = $2001      ; affichage des fonds et sprites
PPUSTATUS = $2002      ; bit 7 : la vidéo est entre deux images (vblank)
PPUSCROLL = $2005
PPUADDR   = $2006      ; adresse dans la mémoire vidéo (deux écritures : fort puis faible)
PPUDATA   = $2007
OAMDMA    = $4014      ; copie d'une page de 256 octets vers les sprites
PAD1      = $4016
OAM       = $0200      ; copie des 64 sprites en RAM (4 octets : y, tuile, attributs, x)

BTN_LEFT  = %00000010
BTN_RIGHT = %00000001
CAT_Y     = 191        ; ligne du haut du chat (un sprite s'affiche une ligne plus bas)

; ---------- variables en page zéro (accès rapides) ----------
.org $0000
nmi_done: .res 1       ; mis à 1 par la NMI : une nouvelle image commence
pad:      .res 1       ; boutons : A B Select Start Haut Bas Gauche Droite (bit 7 → bit 0)
seed:     .res 1       ; graine du hasard
cat_x:    .res 1
score:    .res 3       ; centaines, dizaines, unités (0 à 9)
star_x:   .res 4
star_y:   .res 4
star_v:   .res 4       ; vitesse de chute (1 ou 2 points par image)

; ---------- programme ----------
.org $C000
reset:
  sei                  ; pas d'interruption pendant l'initialisation
  cld
  ldx #$40
  stx $4017            ; coupe l'IRQ du séquenceur de son
  ldx #$ff
  txs                  ; pile en $01FF
  inx                  ; X = 0
  stx PPUCTRL          ; NMI coupée
  stx PPUMASK          ; écran éteint
@vblank1:
  bit PPUSTATUS        ; attendre une 1re image : la vidéo se réveille
  bpl @vblank1

  lda #0
@clear:
  sta $0000,x          ; mémoire à zéro…
  sta $0100,x
  sta $0300,x
  sta $0400,x
  sta $0500,x
  sta $0600,x
  sta $0700,x
  lda #$ff
  sta OAM,x            ; …et sprites cachés sous l'écran
  lda #0
  inx
  bne @clear
@vblank2:
  bit PPUSTATUS        ; 2e image : la vidéo est prête
  bpl @vblank2

  jsr load_palette
  jsr draw_background

  lda #$a7
  sta seed
  lda #120
  sta cat_x
  ldx #3
@stars:
  jsr new_star
  dex
  bpl @stars

  lda #%00000001
  sta $4015            ; active la 1re voix carrée (bruitage)
  lda #0
  sta PPUSCROLL
  sta PPUSCROLL
  lda #%10000000
  sta PPUCTRL          ; NMI à chaque image
  lda #%00011110
  sta PPUMASK          ; fonds et sprites visibles, y compris à gauche

main:
@wait:
  lda nmi_done         ; une image par tour de boucle
  beq @wait
  lda #0
  sta nmi_done
  jsr read_pad
  jsr move_cat
  jsr move_stars
  jsr build_oam
  jmp main

; ---------- NMI : la vidéo a fini une image ----------
nmi:
  pha
  txa
  pha
  tya
  pha
  lda #>OAM
  sta OAMDMA           ; 256 octets de $0200 vers les sprites (513 cycles)
  lda #$20             ; score : écran 0, ligne 2, colonne 8 → $2048
  sta PPUADDR
  lda #$48
  sta PPUADDR
  ldx #0
@digit:
  lda score,x
  clc
  adc #$10             ; les chiffres sont les tuiles $10 à $19
  sta PPUDATA
  inx
  cpx #3
  bne @digit
  lda #0               ; écrire en mémoire vidéo a déplacé le défilement : on le remet
  sta PPUSCROLL
  sta PPUSCROLL
  lda #%10000000
  sta PPUCTRL
  inc nmi_done
  pla
  tay
  pla
  tax
  pla
  rti

; ---------- manette : 8 boutons lus un par un ----------
read_pad:
  lda #1
  sta PAD1             ; « strobe » : la manette fige ses boutons
  lda #0
  sta PAD1
  ldx #8
@bit:
  lda PAD1
  lsr a                ; bouton dans la retenue
  rol pad              ; puis dans `pad`
  dex
  bne @bit
  rts

move_cat:
  lda pad
  and #BTN_LEFT
  beq @right
  lda cat_x
  cmp #10
  bcc @right
  sec
  sbc #2
  sta cat_x
@right:
  lda pad
  and #BTN_RIGHT
  beq @done
  lda cat_x
  cmp #230
  bcs @done
  clc
  adc #2
  sta cat_x
@done:
  rts

move_stars:
  ldx #3
@star:
  lda star_y,x
  clc
  adc star_v,x
  sta star_y,x
  cmp #204             ; arrivée au sol : une autre étoile
  bcs @again
  cmp #182             ; pas encore à hauteur du chat
  bcc @next
  lda star_x,x         ; chevauchement horizontal : étoile + 8 > chat et étoile < chat + 16
  clc
  adc #8
  cmp cat_x
  bcc @next
  lda cat_x
  clc
  adc #16
  cmp star_x,x
  bcc @next
  jsr add_point
  jsr beep
@again:
  jsr new_star
@next:
  dex
  bpl @star
  rts

; nouvelle étoile X en haut, à une place et une vitesse au hasard
new_star:
  jsr rand
  cmp #232
  bcc @x
  and #$7f
@x:
  sta star_x,x
  jsr rand
  and #$3f
  sta star_y,x
  jsr rand
  and #1
  clc
  adc #1
  sta star_v,x
  rts

; hasard : registre à décalage à rétroaction (8 bits), ne touche pas X
rand:
  lda seed
  asl a
  bcc @no
  eor #$1d
@no:
  sta seed
  rts

add_point:
  inc score+2
  lda score+2
  cmp #10
  bcc @ok
  lda #0
  sta score+2
  inc score+1
  lda score+1
  cmp #10
  bcc @ok
  lda #0
  sta score+1
  inc score
  lda score
  cmp #10
  bcc @ok
  lda #0
  sta score
@ok:
  rts

; petit « ding » discret sur la voix carrée 1
beep:
  lda #%10010101       ; rapport cyclique 50 %, volume constant 5
  sta $4000
  lda #0
  sta $4001            ; pas de glissando
  lda #$7e             ; période → environ 880 Hz
  sta $4002
  lda #$10             ; durée courte, octet fort de la période
  sta $4003
  rts

; sprites : le chat (4 sprites de 8×8) puis les 4 étoiles
build_oam:
  lda #CAT_Y
  sta OAM+0
  sta OAM+4
  lda #CAT_Y+8
  sta OAM+8
  sta OAM+12
  lda #$20
  sta OAM+1
  lda #$21
  sta OAM+5
  lda #$22
  sta OAM+9
  lda #$23
  sta OAM+13
  lda #0               ; palette de sprite 0
  sta OAM+2
  sta OAM+6
  sta OAM+10
  sta OAM+14
  lda cat_x
  sta OAM+3
  sta OAM+11
  clc
  adc #8
  sta OAM+7
  sta OAM+15
  ldx #3
@star:
  txa
  asl a
  asl a
  tay                  ; Y = X × 4
  lda star_y,x
  sta OAM+16,y
  lda #$24
  sta OAM+17,y
  lda #1               ; palette de sprite 1 (jaune)
  sta OAM+18,y
  lda star_x,x
  sta OAM+19,y
  dex
  bpl @star
  rts

load_palette:
  lda #$3f
  sta PPUADDR
  lda #$00
  sta PPUADDR
  ldx #0
@color:
  lda palettes,x
  sta PPUDATA
  inx
  cpx #32
  bne @color
  rts

draw_background:
  lda #$20
  sta PPUADDR
  lda #$00
  sta PPUADDR
  lda #0               ; 1 024 octets à 0 : écran vide et attributs (palette 0 partout)
  ldy #4
  ldx #0
@zero:
  sta PPUDATA
  inx
  bne @zero
  dey
  bne @zero
  lda #$23             ; herbe : ligne 26 ($2340)
  sta PPUADDR
  lda #$40
  sta PPUADDR
  lda #1
  ldx #32
@grass:
  sta PPUDATA
  dex
  bne @grass
  lda #2               ; terre : lignes 27 à 29 (96 tuiles, l'écriture continue d'elle-même)
  ldx #96
@dirt:
  sta PPUDATA
  dex
  bne @dirt
  lda #$20             ; « SCORE » ligne 2, colonne 2
  sta PPUADDR
  lda #$42
  sta PPUADDR
  ldx #0
@text:
  lda score_text,x
  sta PPUDATA
  inx
  cpx #5
  bne @text
  ldx #0               ; petites étoiles du décor
@twinkle:
  lda twinkles+1,x
  sta PPUADDR
  lda twinkles,x
  sta PPUADDR
  lda #3
  sta PPUDATA
  inx
  inx
  cpx #24
  bne @twinkle
  rts

; ---------- données ----------
palettes:
  .byte $02,$30,$1a,$17, $02,$28,$38,$30, $02,$30,$1a,$17, $02,$30,$1a,$17   ; fonds
  .byte $02,$27,$0f,$30, $02,$28,$38,$30, $02,$27,$0f,$30, $02,$27,$0f,$30   ; sprites
score_text:
  .byte $40,$41,$42,$43,$44
twinkles:
  .word $2085,$209b,$20e9,$2112,$2167,$219c,$21c3,$220e,$2259,$2294,$22c8,$22ea

.vectors nmi, reset, reset

; ---------- motifs (8 Ko) : 0 ou . = transparent, 1 2 3 = couleurs de la palette ----------
.segment chr
.org $0010             ; tuile $01 : herbe
.tile "..2...2.", ".222.222", "22222222", "22322222", "33333333", "33333333", "33333333", "33333333"
.tile "33333333", "33333333", "333.3333", "33333333", "33333333", "333333.3", "33333333", "33333333"
.tile "........", "........", "...1....", "..111...", "...1....", "........", "........", "........"
.org $0100             ; tuiles $10 à $19 : chiffres
.tile "..111...", ".1...1..", ".1..11..", ".1.1.1..", ".11..1..", ".1...1..", "..111...", "........"
.tile "...1....", "..11....", "...1....", "...1....", "...1....", "...1....", "..111...", "........"
.tile "..111...", ".1...1..", ".....1..", "....1...", "...1....", "..1.....", ".11111..", "........"
.tile ".11111..", "....1...", "...11...", ".....1..", ".....1..", ".1...1..", "..111...", "........"
.tile "....1...", "...11...", "..1.1...", ".1..1...", ".11111..", "....1...", "....1...", "........"
.tile ".11111..", ".1......", ".1111...", ".....1..", ".....1..", ".1...1..", "..111...", "........"
.tile "...11...", "..1.....", ".1......", ".1111...", ".1...1..", ".1...1..", "..111...", "........"
.tile ".11111..", ".....1..", "....1...", "...1....", "..1.....", "..1.....", "..1.....", "........"
.tile "..111...", ".1...1..", ".1...1..", "..111...", ".1...1..", ".1...1..", "..111...", "........"
.tile "..111...", ".1...1..", ".1...1..", "..1111..", ".....1..", "....1...", "..11....", "........"
.org $0200             ; tuiles $20 à $23 : Fuma (16×16) ; $24 : étoile
.tile "..2.....", ".212....", ".2112...", ".2111222", ".2111111", "21111111", "21132111", "21132111"
.tile ".....2..", "....212.", "...2112.", "2221112.", "1111112.", "11111112", "11123112", "11123112"
.tile "21111112", "21111212", ".2111111", "..211111", "..211111", "..213311", "..222222", "........"
.tile "21111112", "21211112", "1111112.", "111112..", "111112..", "113312..", "222222..", "........"
.tile "...11...", "...11...", "11122111", ".112211.", "..1221..", ".11..11.", ".1....1.", "........"
.org $0400             ; tuiles $40 à $44 : S C O R E
.tile "..1111..", ".1......", ".1......", "..111...", ".....1..", ".....1..", ".1111...", "........"
.tile "..1111..", ".1......", ".1......", ".1......", ".1......", ".1......", "..1111..", "........"
.tile "..111...", ".1...1..", ".1...1..", ".1...1..", ".1...1..", ".1...1..", "..111...", "........"
.tile ".1111...", ".1...1..", ".1...1..", ".1111...", ".1.1....", ".1..1...", ".1...1..", "........"
.tile ".11111..", ".1......", ".1......", ".1111...", ".1......", ".1......", ".11111..", "........"
