"use strict";
// Programmes d'exemple des cartes à microcontrôleur (Atelier circuits Æther). Chaque exemple précise le module à
// brancher (afficheur 7 segments ou écran LCD).
(function (root) {
  const RP_START = `
        @ Au démarrage, IO_BANK0, PADS_BANK0 et TIMER sont tenus en reset : on les libère
        @ (écriture dans l'alias « effacer » du registre RESET), puis on attend RESET_DONE.
        ldr r0, =RESETS_BASE + REG_ALIAS_CLR
        ldr r1, =RESET_IO_BANK0 | RESET_PADS_BANK0 | RESET_TIMER
        str r1, [r0]
        ldr r0, =RESETS_BASE
libere: ldr r2, [r0, #RESET_DONE]
        ands r2, r1
        cmp r2, r1
        bne libere
`;
  const RP_WAIT = `
@ attente_us : attend r0 microsecondes en lisant le compteur du TIMER (1 tic par µs).
@ Modifie r1, r2 et r3.
attente_us:
        ldr r1, =TIMER_BASE
        ldr r2, [r1, #TIMERAWL]         @ instant de départ
au1:    ldr r3, [r1, #TIMERAWL]
        subs r3, r3, r2                 @ temps écoulé
        cmp r3, r0
        blo au1
        bx lr
`;
  const AVR_STACK = `
debut:  ldi r16, high(RAMEND)           ; la pile part de la fin de la SRAM
        out SPH, r16
        ldi r16, low(RAMEND)
        out SPL, r16
`;

  const EXAMPLES = {
    rp2040: {
      clignotant: { title: "Clignotant (LED GP25)", module: "seg7", source: `@ Clignotant : la LED de la carte (GP25) change d'état toutes les 250 ms.
        .syntax unified
        .thumb
        .global main
main:
${RP_START}
        @ GP25 pilotée par le bloc SIO (fonction 5 du registre GPIO25_CTRL)
        ldr r0, =IO_BANK0_BASE + 25 * 8 + 4
        movs r1, #FUNCSEL_SIO
        str r1, [r0]
        @ GP25 en sortie
        ldr r6, =SIO_BASE
        ldr r4, =1 << 25
        str r4, [r6, #GPIO_OE_SET]
boucle: str r4, [r6, #GPIO_OUT_XOR]     @ inverse la LED
        ldr r0, =250000                 @ 250 000 µs = 250 ms
        bl attente_us
        b boucle
${RP_WAIT}` },
      chenillard: { title: "Chenillard GP0 à GP3, bouton GP10", module: "seg7", source: `@ Chenillard : une LED allumée défile de GP0 à GP3.
@ Tant que le bouton 1 (GP10) est appuyé, elle repart dans l'autre sens.
        .syntax unified
        .thumb
main:
${RP_START}
        @ GP0 à GP3 et GP10 : fonction SIO
        ldr r0, =IO_BANK0_BASE + 4      @ GPIO0_CTRL
        movs r1, #FUNCSEL_SIO
        str r1, [r0, #0]                @ GP0
        str r1, [r0, #8]                @ GP1
        str r1, [r0, #16]               @ GP2
        str r1, [r0, #24]               @ GP3
        ldr r0, =IO_BANK0_BASE + 10 * 8 + 4
        str r1, [r0]                    @ GP10
        ldr r6, =SIO_BASE
        movs r1, #0x0f
        str r1, [r6, #GPIO_OE_SET]      @ GP0 à GP3 en sortie ; GP10 reste une entrée
        movs r4, #1                     @ motif : une seule LED allumée
boucle: movs r1, #0x0f
        str r1, [r6, #GPIO_OUT_CLR]
        str r4, [r6, #GPIO_OUT_SET]
        ldr r0, =120000
        bl attente_us
        ldr r1, [r6, #GPIO_IN]
        lsrs r1, r1, #10                @ bit 10 → bit 0
        movs r2, #1
        tst r1, r2
        bne recule                      @ bouton appuyé : on recule
        lsls r4, r4, #1
        cmp r4, #16
        bne boucle
        movs r4, #1
        b boucle
recule: lsrs r4, r4, #1
        bne boucle
        movs r4, #8
        b boucle
${RP_WAIT}` },
      compteur: { title: "Compteur sur 7 segments (GP16 à GP23)", module: "seg7", source: `@ Compteur hexadécimal : le bouton 1 (GP10) ajoute 1, le bouton 2 (GP11) retire 1.
@ Afficheur 7 segments : a = GP16, b = GP17 … g = GP22, point = GP23.
        .syntax unified
        .thumb
main:
${RP_START}
        @ GP16 à GP23 : fonction SIO (une boucle sur les 8 registres GPIOn_CTRL)
        ldr r0, =IO_BANK0_BASE + 16 * 8 + 4
        movs r1, #FUNCSEL_SIO
        movs r2, #8
fonction:
        str r1, [r0]
        adds r0, #8
        subs r2, #1
        bne fonction
        ldr r0, =IO_BANK0_BASE + 10 * 8 + 4
        str r1, [r0]                    @ GP10
        str r1, [r0, #8]                @ GP11
        ldr r6, =SIO_BASE
        ldr r1, =0xff << 16
        str r1, [r6, #GPIO_OE_SET]      @ segments en sortie
        movs r4, #0                     @ le chiffre affiché
        movs r5, #0                     @ boutons au tour précédent
boucle: adr r0, chiffres
        ldrb r1, [r0, r4]               @ segments du chiffre
        lsls r1, r1, #16
        ldr r2, =0xff << 16
        str r2, [r6, #GPIO_OUT_CLR]
        str r1, [r6, #GPIO_OUT_SET]
        ldr r1, [r6, #GPIO_IN]
        lsrs r1, r1, #10
        movs r2, #3
        ands r1, r2                     @ bit 0 = GP10, bit 1 = GP11
        mov r2, r1
        bics r2, r5                     @ boutons qui viennent d'être enfoncés
        mov r5, r1
        movs r3, #1
        tst r2, r3
        beq pas_plus
        adds r4, #1
pas_plus:
        movs r3, #2
        tst r2, r3
        beq pas_moins
        subs r4, #1
pas_moins:
        movs r3, #15
        ands r4, r3                     @ on reste entre 0 et F
        ldr r0, =5000                   @ 5 ms : anti-rebond
        bl attente_us
        b boucle
${RP_WAIT}
        .align 2
chiffres:                               @ segments de 0 à F (bit 0 = a … bit 6 = g)
        .byte 0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07
        .byte 0x7f, 0x6f, 0x77, 0x7c, 0x39, 0x5e, 0x79, 0x71
` },
      lcd: { title: "Bonjour sur l'écran LCD", module: "lcd", source: `@ Écran LCD 16 × 2 (contrôleur HD44780) en mode 4 bits :
@ D4 à D7 = GP16 à GP19, RS = GP20, E = GP21 (R/W relié à la masse).
@ L'écran lit les 4 bits de données quand E redescend de 1 à 0.
        .syntax unified
        .thumb
main:
${RP_START}
        ldr r0, =IO_BANK0_BASE + 16 * 8 + 4
        movs r1, #FUNCSEL_SIO
        movs r2, #6
fonction:
        str r1, [r0]
        adds r0, #8
        subs r2, #1
        bne fonction
        ldr r6, =SIO_BASE
        ldr r1, =0x3f << 16
        str r1, [r6, #GPIO_OE_SET]      @ GP16 à GP21 en sortie
        ldr r0, =50000                  @ l'écran démarre
        bl attente_us
        @ passage en mode 4 bits : trois fois 3, puis 2
        movs r7, #0                     @ r7 = RS (0 : commande)
        movs r0, #3
        bl quartet
        ldr r0, =5000
        bl attente_us
        movs r0, #3
        bl quartet
        ldr r0, =200
        bl attente_us
        movs r0, #3
        bl quartet
        ldr r0, =200
        bl attente_us
        movs r0, #2
        bl quartet
        ldr r0, =200
        bl attente_us
        movs r0, #0x28                  @ 2 lignes, caractères 5 × 8
        bl octet
        movs r0, #0x0c                  @ écran allumé, sans curseur
        bl octet
        movs r0, #0x06                  @ le curseur avance vers la droite
        bl octet
        movs r0, #0x01                  @ efface l'écran
        bl octet
        ldr r0, =2000
        bl attente_us
        adr r1, ligne1
        bl texte
        movs r0, #0xc0                  @ début de la 2e ligne (adresse 0x40)
        bl octet
        adr r1, ligne2
        bl texte
fin:    wfi
        b fin

@ quartet : envoie les 4 bits de poids faible de r0 (RS = r7)
quartet:
        ldr r1, =0x3f << 16
        str r1, [r6, #GPIO_OUT_CLR]
        lsls r0, r0, #16
        orrs r0, r7
        str r0, [r6, #GPIO_OUT_SET]
        ldr r1, =1 << 21
        str r1, [r6, #GPIO_OUT_SET]     @ E = 1
        nop
        nop
        str r1, [r6, #GPIO_OUT_CLR]     @ E = 0 : l'écran lit D4 à D7
        bx lr

@ octet : envoie r0 en deux quartets (poids fort d'abord)
octet:  push {r4, lr}
        mov r4, r0
        lsrs r0, r0, #4
        bl quartet
        movs r0, #15
        ands r0, r4
        bl quartet
        ldr r0, =50
        bl attente_us
        pop {r4, pc}

@ texte : affiche la chaîne terminée par 0 rangée à l'adresse r1
texte:  push {r4, lr}
        mov r4, r1
        ldr r7, =1 << 20                @ RS = 1 : caractères
car:    ldrb r0, [r4]
        cmp r0, #0
        beq fin_texte
        bl octet
        adds r4, #1
        b car
fin_texte:
        movs r7, #0
        pop {r4, pc}
${RP_WAIT}
        .align 2
ligne1: .asciz "Bonjour Fuma !"
        .align 2
ligne2: .asciz "RP2040 en Thumb"
` },
    },

    avr: {
      clignotant: { title: "Clignotant (LED L sur PB5)", module: "seg7", source: `; Clignotant : la LED « L » de la carte (PB5) change d'état toutes les 250 ms environ.
        .org 0
        rjmp debut
${AVR_STACK}
        sbi DDRB, PB5                   ; PB5 en sortie
boucle: sbi PINB, PB5                   ; écrire 1 dans PINB inverse la sortie
        rcall attente
        rjmp boucle

; attente d'environ 250 ms : 16 000 000 × 0,25 = 4 000 000 de cycles
attente:
        ldi r18, 21
a1:     ldi r19, 255
a2:     ldi r20, 255
a3:     dec r20                         ; 1 cycle
        brne a3                         ; 2 cycles quand il saute
        dec r19
        brne a2
        dec r18
        brne a1
        ret
` },
      chenillard: { title: "Chenillard par interruption (minuterie 0)", module: "seg7", source: `; Chenillard sur PB0 à PB3, rythmé par l'interruption de débordement de la minuterie 0.
; Horloge / 1024 : un débordement toutes les 256 × 1024 = 262 144 cycles (16,4 ms).
; Le programme principal dort ; l'interruption fait tout le travail.
        .org 0
        rjmp debut
        .org OVF0addr                   ; vecteur « TIMER0 OVF »
        rjmp minuterie

        .org INT_VECTORS_SIZE
${AVR_STACK}
        ldi r16, 0b00001111
        out DDRB, r16                   ; PB0 à PB3 en sortie
        ldi r17, 1                      ; motif
        out PORTB, r17
        clr r18                         ; débordements comptés
        ldi r16, (1 << CS02) | (1 << CS00)
        out TCCR0B, r16                 ; minuterie : horloge / 1024
        ldi r16, 1 << TOIE0
        sts TIMSK0, r16                 ; interruption au débordement
        sei                             ; interruptions autorisées
dors:   sleep
        rjmp dors

minuterie:
        push r16
        in r16, SREG                    ; on sauve les drapeaux du programme interrompu
        inc r18
        cpi r18, 8                      ; 8 débordements ≈ 131 ms
        brne fin
        clr r18
        lsl r17
        cpi r17, 0b00010000
        brne affiche
        ldi r17, 1
affiche:
        out PORTB, r17
fin:    out SREG, r16
        pop r16
        reti
` },
      compteur: { title: "Compteur sur 7 segments (port D)", module: "seg7", source: `; Compteur hexadécimal : le bouton 1 (PC0) ajoute 1, le bouton 2 (PC1) retire 1.
; Afficheur 7 segments : a = PD0, b = PD1 … g = PD6, point = PD7.
; Les boutons relient la broche à la masse : on active le tirage haut (PORTC = 1).
        .org 0
        rjmp debut
${AVR_STACK}
        ser r16
        out DDRD, r16                   ; port D en sortie
        ldi r16, 0b00001111
        out PORTC, r16                  ; tirage haut sur PC0 à PC3
        clr r20                         ; le chiffre affiché
        ser r21                         ; boutons au tour précédent (1 = relâché)
boucle: rcall affiche
        in r22, PINC
        mov r23, r22
        com r23                         ; 1 = appuyé
        and r23, r21                    ; 1 = vient d'être appuyé
        mov r21, r22
        sbrc r23, 0
        inc r20
        sbrc r23, 1
        dec r20
        andi r20, 0x0f                  ; on reste entre 0 et F
        rcall pause
        rjmp boucle

affiche:
        ldi ZL, low(chiffres * 2)       ; adresse en octets de la table en flash
        ldi ZH, high(chiffres * 2)
        add ZL, r20
        clr r16
        adc ZH, r16
        lpm r16, Z
        out PORTD, r16
        ret

pause:  ldi r24, low(20000)             ; 20 000 × 4 cycles = 5 ms (anti-rebond)
        ldi r25, high(20000)
p1:     sbiw r24, 1
        brne p1
        ret

chiffres:                               ; segments de 0 à F (bit 0 = a … bit 6 = g)
        .db 0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07
        .db 0x7f, 0x6f, 0x77, 0x7c, 0x39, 0x5e, 0x79, 0x71
` },
      lcd: { title: "Bonjour sur l'écran LCD", module: "lcd", source: `; Écran LCD 16 × 2 (contrôleur HD44780) en mode 4 bits :
; D4 à D7 = PD4 à PD7, RS = PD2, E = PD3 (R/W relié à la masse).
; L'écran lit les 4 bits de données quand E redescend de 1 à 0.
        .org 0
        rjmp debut
${AVR_STACK}
        ser r16
        out DDRD, r16
        ldi r24, 50
        rcall attente_ms                ; l'écran démarre
        clr r18                         ; r18 = RS (0 : commande)
        ldi r17, 0x30                   ; passage en mode 4 bits : trois fois 3…
        rcall quartet
        ldi r24, 5
        rcall attente_ms
        ldi r17, 0x30
        rcall quartet
        ldi r24, 1
        rcall attente_ms
        ldi r17, 0x30
        rcall quartet
        ldi r24, 1
        rcall attente_ms
        ldi r17, 0x20                   ; … puis 2
        rcall quartet
        ldi r24, 1
        rcall attente_ms
        ldi r17, 0x28                   ; 2 lignes, caractères 5 × 8
        rcall octet
        ldi r17, 0x0c                   ; écran allumé, sans curseur
        rcall octet
        ldi r17, 0x06                   ; le curseur avance vers la droite
        rcall octet
        ldi r17, 0x01                   ; efface l'écran
        rcall octet
        ldi r24, 2
        rcall attente_ms
        ldi ZL, low(ligne1 * 2)
        ldi ZH, high(ligne1 * 2)
        rcall texte
        ldi r17, 0xc0                   ; début de la 2e ligne (adresse 0x40)
        rcall octet
        ldi ZL, low(ligne2 * 2)
        ldi ZH, high(ligne2 * 2)
        rcall texte
fin:    rjmp fin

; octet : envoie r17 en deux quartets (poids fort d'abord), RS = r18
octet:  push r17
        rcall quartet
        pop r17
        swap r17
        rcall quartet
        ldi r24, 1
        rjmp attente_ms

; quartet : envoie les 4 bits de poids fort de r17
quartet:
        andi r17, 0xf0
        or r17, r18
        out PORTD, r17
        sbi PORTD, PD3                  ; E = 1
        nop
        nop
        cbi PORTD, PD3                  ; E = 0 : l'écran lit D4 à D7
        ret

; texte : affiche la chaîne terminée par 0 rangée en flash à l'adresse Z
texte:  ldi r18, 1 << PD2               ; RS = 1 : caractères
t1:     lpm r17, Z+
        tst r17
        breq t2
        rcall octet
        rjmp t1
t2:     clr r18
        ret

; attente_ms : attend r24 millisecondes (16 000 cycles chacune)
attente_ms:
am1:    ldi r26, low(4000)
        ldi r27, high(4000)
am2:    sbiw r26, 1                     ; 2 cycles
        brne am2                        ; 2 cycles : 4 × 4000 = 16 000
        dec r24
        brne am1
        ret

ligne1: .db "Bonjour Fuma !", 0
ligne2: .db "AVR 8 bits", 0
` },
    },
  };

  root.AetherMcuExamples = EXAMPLES;
})(typeof window !== "undefined" ? window : globalThis);
