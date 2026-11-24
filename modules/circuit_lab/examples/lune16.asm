; =====================================================================================================
;  Fuma au clair de lune — exemple 16 bits de l'atelier circuits (cartouche LoROM de 32 Ko)
;
;  Fuma, le chat, se promène sous la lune. Flèches gauche / droite pour marcher, B (touche W/Z) pour miauler
;  une note. Ce que montre le programme :
;    1. démarrage : passer le 65C816 en mode natif (CLC + XCE), registres 16 bits (REP #$30) ;
;    2. charger tuiles, carte et palettes par DMA (le processeur ne copie rien octet par octet) ;
;    3. un dégradé de ciel par HDMA : la couleur de fond change toutes les 8 lignes, sans le processeur ;
;    4. le module son : envoyer un petit programme au SPC700 par les 4 ports, puis lui dire quoi jouer ;
;    5. une boucle qui attend la NMI (60 fois par seconde) et lit la manette lue automatiquement.
; =====================================================================================================

.title "FUMA AU CLAIR DE LUNE"

; ---------- registres ----------
INIDISP = $2100      ; bit 7 : écran éteint ; bits 0-3 : luminosité
OBSEL   = $2101      ; taille et adresse des sprites
OAMADDL = $2102
OAMDATA = $2104
BGMODE  = $2105
BG1SC   = $2107      ; carte du plan 1
BG12NBA = $210B      ; tuiles des plans 1 et 2
BG1VOFS = $210E
VMAIN   = $2115
VMADDL  = $2116      ; adresse en mémoire vidéo (mots de 16 bits)
VMDATAL = $2118
CGADD   = $2121      ; numéro de couleur
CGDATA  = $2122
TM      = $212C      ; plans affichés
APUIO0  = $2140      ; ports du module son
APUIO1  = $2141
APUIO2  = $2142
APUIO3  = $2143
NMITIMEN = $4200
MDMAEN  = $420B
HDMAEN  = $420C
RDNMI   = $4210
HVBJOY  = $4212
JOY1H   = $4219      ; B Y Select Start Haut Bas Gauche Droite
DMAP0   = $4300      ; canal DMA 0 : mode, registre de destination, source, taille
BBAD0   = $4301
A1T0L   = $4302
A1B0    = $4304
DAS0L   = $4305

CAT_Y   = 167        ; le chat est posé sur l'herbe

; ---------- variables (mémoire de travail, page directe) ----------
.org $0000
cat_x:     .res 1
cat_attr:  .res 1    ; priorité 3, retourné horizontalement quand il marche à gauche
frame:     .res 1
pad_prev:  .res 1
note:      .res 1
snd_count: .res 1
zero:      .res 2

; ---------- programme ----------
.bank 0
reset:
  sei
  clc
  xce                  ; mode natif 65C816
  rep #$30             ; A, X, Y en 16 bits
  ldx #$1FFF
  txs                  ; pile en haut des 8 Ko visibles en banque 0
  lda #$0000
  tcd                  ; page directe en $0000
  sep #$20             ; A en 8 bits, X/Y restent en 16 bits
  lda #$80
  sta INIDISP          ; écran éteint pendant le chargement
  stz NMITIMEN
  stz HDMAEN
  stz zero
  stz zero+1

  ; --- mémoire vidéo : tout à zéro (DMA à source fixe) ---
  lda #$80
  sta VMAIN            ; +1 mot après chaque écriture de l'octet fort
  ldx #$0000
  stx VMADDL
  lda #$09             ; source fixe, 2 registres ($2118 / $2119)
  ldx #zero
  ldy #$0000           ; 0 = 65 536 octets
  jsr dma_vram

  ; --- tuiles du décor ($0000) et du chat ($2000 et $2100) ---
  ldx #$0000
  stx VMADDL
  lda #$01
  ldx #bg_tiles
  ldy #bg_tiles_end-bg_tiles
  jsr dma_vram
  ldx #$2000
  stx VMADDL
  lda #$01
  ldx #cat_top
  ldy #64
  jsr dma_vram
  ldx #$2100
  stx VMADDL
  lda #$01
  ldx #cat_bottom
  ldy #64
  jsr dma_vram

  ; --- palettes ---
  stz CGADD
  ldx #bg_palette
  ldy #32
  jsr dma_cgram
  lda #128
  sta CGADD
  ldx #obj_palette
  ldy #32
  jsr dma_cgram

  ; --- carte du plan 1 en $0400 : étoiles, lune, herbe, terre ---
  ldx #$0000
@stars:
  rep #$20
  lda star_pos,x
  cmp #$FFFF
  beq @moon
  clc
  adc #$0400
  sta VMADDL
  lda #$0001
  sta VMDATAL
  inx
  inx
  sep #$20
  bra @stars
@moon:
  rep #$20
  lda #$0400+4*32+24
  sta VMADDL
  lda #$0004
  sta VMDATAL
  lda #$0005
  sta VMDATAL
  lda #$0400+5*32+24
  sta VMADDL
  lda #$0006
  sta VMDATAL
  lda #$0007
  sta VMDATAL
  lda #$0400+23*32
  sta VMADDL
  ldx #32
@grass:
  lda #$0003
  sta VMDATAL
  dex
  bne @grass
  ldx #32*4
@ground:
  lda #$0002
  sta VMDATAL
  dex
  bne @ground
  sep #$20

  ; --- réglages vidéo ---
  lda #$01
  sta BGMODE           ; mode 1 : deux plans de 16 couleurs + un de 4
  lda #$04
  sta BG1SC            ; carte du plan 1 en $0400, 32×32 tuiles
  stz BG12NBA          ; tuiles en $0000
  lda #$FF
  sta BG1VOFS
  sta BG1VOFS          ; défilement vertical -1 : la 1re ligne visible montre la ligne 0
  lda #$01             ; sprites 8×8 et 16×16, tuiles en $2000
  sta OBSEL
  lda #$11
  sta TM               ; plan 1 + sprites

  ; --- sprites : tous cachés sauf le chat ---
  stz OAMADDL
  stz OAMADDL+1
  ldx #128
@hide:
  stz OAMDATA          ; x
  lda #240
  sta OAMDATA          ; y hors de l'écran
  stz OAMDATA
  stz OAMDATA
  dex
  bne @hide
  lda #$02             ; sprite 0 : grande taille (16×16)
  sta OAMDATA
  ldx #31
@hi:
  stz OAMDATA
  dex
  bne @hi

  lda #120
  sta cat_x
  lda #$30
  sta cat_attr

  ; --- dégradé du ciel : canal HDMA 1 vers la couleur 0 ($2121 deux fois, $2122 deux fois) ---
  lda #$03
  sta DMAP0+$10
  lda #$21
  sta BBAD0+$10
  ldx #sky
  stx A1T0L+$10
  stz A1B0+$10
  lda #$02
  sta HDMAEN

  jsr sound_boot

  lda #$0F
  sta INIDISP          ; écran allumé, pleine luminosité
  lda #$81
  sta NMITIMEN         ; NMI à chaque image + lecture automatique de la manette

; ---------- boucle principale ----------
main:
  wai                  ; dort jusqu'à la prochaine NMI
@joy:
  lda HVBJOY
  and #$01
  bne @joy             ; attendre la fin de la lecture des manettes
  lda JOY1H
  bit #$02
  beq @right
  lda cat_x
  cmp #10
  bcc @right
  dec a
  dec a
  sta cat_x
  lda #$70             ; retourné vers la gauche
  sta cat_attr
@right:
  lda JOY1H
  bit #$01
  beq @meow
  lda cat_x
  cmp #230
  bcs @meow
  inc a
  inc a
  sta cat_x
  lda #$30
  sta cat_attr
@meow:
  lda JOY1H
  and #$80
  tax                  ; garde l'état de B pour la prochaine image
  lda pad_prev
  eor #$80             ; $80 si B était relâché…
  and JOY1H            ; … et qu'il est enfoncé maintenant
  and #$80
  beq @done
  jsr play_note
@done:
  txa
  sta pad_prev
  jmp main

; ---------- NMI : début de la pause verticale ----------
nmi:
  rep #$30
  pha
  phx
  sep #$20
  lda RDNMI            ; acquitte la NMI
  stz OAMADDL
  stz OAMADDL+1
  lda cat_x
  sta OAMDATA
  lda #CAT_Y
  sta OAMDATA
  stz OAMDATA          ; tuile 0 (le 16×16 prend 0, 1, 16, 17)
  lda cat_attr
  sta OAMDATA
  inc frame            ; les étoiles scintillent : la couleur 1 change toutes les 8 images
  lda frame
  lsr a
  lsr a
  and #$0E
  rep #$20
  and #$00FF
  tax
  sep #$20
  lda #$01
  sta CGADD
  lda twinkle,x
  sta CGDATA
  lda twinkle+1,x
  sta CGDATA
  rep #$30
  plx
  pla
irq:
  rti

.a8                   ; les sous-programmes suivants sont appelés avec A en 8 bits
; ---------- DMA vers la mémoire vidéo : A = mode, X = source (banque 0), Y = taille ----------
dma_vram:
  sta DMAP0
  lda #$18
  sta BBAD0
  stx A1T0L
  stz A1B0
  sty DAS0L
  lda #$01
  sta MDMAEN
  rts
dma_cgram:
  stz DMAP0
  lda #$22
  sta BBAD0
  stx A1T0L
  stz A1B0
  sty DAS0L
  lda #$01
  sta MDMAEN
  rts

; ---------- module son ----------
; Au démarrage, le module attend : il écrit $AA et $BB dans ses ports 0 et 1. On lui envoie le programme
; octet par octet (port 1 = donnée, port 0 = numéro de l'octet, il répond en renvoyant le numéro), puis
; l'adresse où il doit sauter.
sound_boot:
  rep #$20
@wait:
  lda APUIO0
  cmp #$BBAA
  bne @wait
  lda #$0200
  sta APUIO2           ; adresse de destination (ports 2 et 3)
  sep #$20
  lda #$01
  sta APUIO1           ; « un bloc suit »
  lda #$CC
  sta APUIO0
@ack:
  cmp APUIO0
  bne @ack
  ldx #$0000
@byte:
  lda spc_code,x
  sta APUIO1
  txa
  sta APUIO0
@echo:
  cmp APUIO0
  bne @echo
  inx
  cpx #spc_end-spc_code
  bne @byte
  rep #$20
  lda #$0200
  sta APUIO2           ; adresse d'exécution
  sep #$20
  stz APUIO1           ; « fin, saute »
  txa
  inc a
  inc a
  sta APUIO0
  sta snd_count
@go:
  cmp APUIO0
  bne @go
  rts

; joue la note suivante : hauteur dans les ports 1 et 2, puis un nouveau numéro dans le port 0
play_note:
  phx
  lda note
  inc a
  and #$07
  sta note
  asl a
  rep #$20
  and #$00FF
  tax
  lda notes,x
  sta APUIO1           ; ports 1 (octet faible) et 2 (octet fort)
  sep #$20
  lda snd_count
  inc a
  sta snd_count
  sta APUIO0
  plx
  rts

; Programme du SPC700 (processeur du module son), chargé en $0200. Il règle le DSP puis attend :
; quand le port 0 change, il lit la hauteur (ports 1 et 2) et déclenche la voix 0.
;   mov $F2,#registre / mov $F3,#valeur  =  8F rr F2 / 8F vv F3
spc_code:
  .byte $8F,$6C,$F2, $8F,$20,$F3     ; FLG : son actif, écho sans écriture
  .byte $8F,$0C,$F2, $8F,$40,$F3     ; volume général gauche
  .byte $8F,$1C,$F2, $8F,$40,$F3     ; volume général droit
  .byte $8F,$5D,$F2, $8F,$03,$F3     ; répertoire des échantillons en $0300
  .byte $8F,$00,$F2, $8F,$30,$F3     ; voix 0 : volume gauche
  .byte $8F,$01,$F2, $8F,$30,$F3     ; voix 0 : volume droit
  .byte $8F,$04,$F2, $8F,$00,$F3     ; voix 0 : échantillon 0
  .byte $8F,$05,$F2, $8F,$8F,$F3     ; enveloppe : attaque immédiate
  .byte $8F,$06,$F2, $8F,$E8,$F3     ; puis décroissance douce
  .byte $E4,$F4                      ; mov a,$F4
  .byte $C4,$00                      ; mov $00,a   (numéro déjà vu)
; boucle ($023A)
  .byte $E4,$F4                      ; mov a,$F4
  .byte $64,$00                      ; cmp a,$00
  .byte $F0,$FA                      ; beq boucle
  .byte $C4,$00                      ; mov $00,a
  .byte $E4,$F5, $8F,$02,$F2, $C4,$F3 ; hauteur, octet faible
  .byte $E4,$F6, $8F,$03,$F2, $C4,$F3 ; hauteur, octet fort
  .byte $8F,$4C,$F2, $8F,$01,$F3     ; KON : déclenche la voix 0
  .byte $2F,$E2                      ; bra boucle
; répertoire ($0300 = $0200 + 256) : début et boucle de l'échantillon 0 en $0310
  .res 256-(*-spc_code), 0
  .word $0310, $0310
  .res 12, 0
; échantillon compressé (BRR) : un bloc de 16 points en créneau, qui boucle sur lui-même
  .byte $B3, $77,$77,$77,$77, $99,$99,$99,$99
spc_end:

; ---------- données ----------
notes:
  .word $0430, $04B3, $0546, $0646, $070A, $085F, $070A, $0646
twinkle:
  .word $67FF, $5B9F, $4F1F, $429F, $361F, $429F, $4F1F, $5B9F
star_pos:                            ; positions des étoiles dans la carte (ligne × 32 + colonne)
  .word $0043, $006C, $0033, $00C7, $011C, $012F, $0162, $0195, $01CA, $01FE, $0225, $0252, $005D, $00F6, $01BA, $FFFF
bg_palette:
  .word $0000, $7FFF, $5BDF, $4AF8, $1904, $2206, $2587, $0000, $0000, $0000, $0000, $0000, $0000, $0000, $0000, $0000
obj_palette:
  .word $0000, $1463, $5A94, $525F, $1BD8, $0000, $0000, $0000, $0000, $0000, $0000, $0000, $0000, $0000, $0000, $0000
sky:                                 ; HDMA : 8 lignes, puis $2121 = 0, 0 et $2122 = couleur (2 octets)
  .byte 8, 0, 0, $21, $18
  .byte 8, 0, 0, $21, $18
  .byte 8, 0, 0, $22, $1C
  .byte 8, 0, 0, $22, $1C
  .byte 8, 0, 0, $22, $1C
  .byte 8, 0, 0, $43, $1C
  .byte 8, 0, 0, $43, $20
  .byte 8, 0, 0, $43, $20
  .byte 8, 0, 0, $44, $20
  .byte 8, 0, 0, $44, $24
  .byte 8, 0, 0, $44, $24
  .byte 8, 0, 0, $45, $24
  .byte 8, 0, 0, $45, $28
  .byte 8, 0, 0, $45, $28
  .byte 8, 0, 0, $66, $28
  .byte 8, 0, 0, $66, $28
  .byte 8, 0, 0, $66, $2C
  .byte 8, 0, 0, $67, $2C
  .byte 8, 0, 0, $67, $2C
  .byte 8, 0, 0, $67, $30
  .byte 8, 0, 0, $68, $30
  .byte 8, 0, 0, $68, $30
  .byte 8, 0, 0, $68, $34
  .byte 8, 0, 0, $89, $34
  .byte 8, 0, 0, $89, $34
  .byte 8, 0, 0, $89, $34
  .byte 8, 0, 0, $8A, $38
  .byte 8, 0, 0, $8A, $38
  .byte 0

bg_tiles:
.tile4 "........", "........", "........", "........", "........", "........", "........", "........"   ; 0 : vide
.tile4 "........", "...1....", "...1....", ".11111..", "...1....", "...1....", "........", "........"   ; 1 : étoile
.tile4 "44444444", "44464444", "44444444", "44444464", "46444444", "44444444", "44444644", "44444444"   ; 2 : terre
.tile4 "..5...5.", ".55..555", "5555.555", "55555555", "44544454", "44444444", "44464444", "44444444"   ; 3 : herbe
.tile4 ".....222", "...22222", "..222222", ".2222222", ".2233222", "22233222", "22222222", "22222222"   ; 4-7 : lune
.tile4 "222.....", "22222...", "223322..", "2233222.", "2222222.", "22222222", "22232222", "22222222"
.tile4 "22222222", "22222233", "22222233", ".2222222", ".2222222", "..222222", "...22222", ".....222"
.tile4 "22222222", "22222222", "22222222", "2222232.", "2222222.", "222222..", "22222...", "222....."
bg_tiles_end:
cat_top:
.tile4 "........", "........", "........", "........", ".1......", "121.....", "121.....", ".121..11"   ; Fuma, haut
.tile4 "..1...1.", ".121.121", ".1222221", ".1242421", ".1222221", ".1223221", "..12221.", "1112221."
cat_bottom:
.tile4 "..121122", "..122222", "..122222", "..122222", "..122112", "..121.12", "..11..11", "........"   ; Fuma, bas
.tile4 "2222221.", "2222221.", "2222221.", "2222221.", "2211221.", "21.121..", "1..11...", "........"

.vectors nmi, reset, irq
