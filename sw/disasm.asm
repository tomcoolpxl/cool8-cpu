; ---------------------------------------------------------------------
; disasm.asm -- one instruction, printed.
;
; Part of the monitor. `disasm` takes X pointing at an opcode, prints the
; instruction, and leaves X pointing at the next one.
;
; **There is no 256-entry opcode table here and there must not be.** The
; primary page is `1 ooo dd ss` and `01 gg t dd b` all the way down --
; the encoding is bit fields, not a list -- so reading the fields costs a
; few hundred bytes where indexing every opcode would cost more ROM than
; exists. The only tables are the mnemonics, and they are indexed by the
; field that chose them.
;
; They are NUL-terminated strings rather than fixed-width slots, and that
; is not a style preference: `PUSHW` is five characters and `MOV` is
; three, and a fixed width wide enough for the first wastes it on every
; one of the others. `strn` walks to the Nth string, which costs about
; twenty bytes once and pays for itself several times over. Where a
; whole operand is a constant -- `JMP [X]`, `MOVW SP,Y` -- it lives in
; the string too, and the decode for that case disappears entirely.
;
; What this deliberately does not do is check that an encoding is legal.
; Page 2 has 22 reserved second bytes which trap on the real machine;
; here they print as `???` with the byte. A disassembler that refused to
; show you the byte you are looking at would be worse than one that
; guessed, because the reason you are looking is usually that something
; has already gone wrong.
; ---------------------------------------------------------------------

; A conditional branch reaches 127 bytes and the tables at the bottom of
; this file put every handler further away than that, so the dispatchers
; invert the test and let a JMP carry the distance. Written as macros
; because there are two dozen of them and the inversion is exactly the
; kind of thing that is wrong once and then wrong for ever.
.macro  jlo dest
        BHS  @sk
        JMP  \dest
@sk:
.endm

.macro  jhs dest
        BLO  @sk
        JMP  \dest
@sk:
.endm

.macro  jeq dest
        BNE  @sk
        JMP  \dest
@sk:
.endm

; disasm -- X = the instruction. Prints it; X ends past it.
disasm: PUSH R0
        PUSH R1
        PUSH R2
        PUSH R3

        LD   R3,[X]             ; the opcode, kept in R3 throughout
        INCW X

        MOV  R0,R3
        CMP  R0,#$20
        jlo  d_alui
        CMP  R0,#$30
        jlo  d_ctl
        CMP  R0,#$38
        jlo  d_stk
        CMP  R0,#$40
        jlo  d_qk
        CMP  R0,#$70
        jlo  d_mem
        CMP  R0,#$80
        jlo  d_br
        JMP  d_alur

; ---- $00-$1F  ALU Rd,#imm8 ------------------------------------------

d_alui: MOV  R1,R3
        SHR  R1
        SHR  R1
        AND  R1,#7
        CALL alu_name
        MOV  R1,R3
        CALL reg
        CALL comma
        MOV  R0,#'#'
        CALL putc
        CALL d_byte
        JMP  d_end

; ---- $80-$FF  ALU Rd,Rs ---------------------------------------------

d_alur: MOV  R1,R3
        SWAP R1
        AND  R1,#7
        CALL alu_name
        MOV  R1,R3
        SHR  R1
        SHR  R1
        CALL reg
        CALL comma
        MOV  R1,R3
        CALL reg
        JMP  d_end

; ---- $20-$2F  control ------------------------------------------------
;
; Ten of the sixteen have no operand and four carry their whole operand
; in the string, so this is a table lookup and one special case.

d_ctl:  MOV  R1,R3
        AND  R1,#$0F
        CMP  R1,#$0F
        jeq  d_p2
        PUSH R1
        CALL ctl_name
        POP  R1
        CMP  R1,#$08
        jlo  d_end
        CMP  R1,#$0A
        jhs  d_end
        CALL d_word             ; JMP abs16, CALL abs16
        JMP  d_end

; ---- $30-$37  PUSH/POP -----------------------------------------------

d_stk:  MOV  R1,R3
        SUB  R1,#$30
        SHR  R1
        SHR  R1
        PUSHW X
        LDW  X,#stk_ops
        CALL strn
        POPW X
        MOV  R1,R3
        CALL reg
        JMP  d_end

; ---- $38-$3F  the one-byte pointer operations ------------------------

d_qk:   MOV  R1,R3
        SUB  R1,#$38
        PUSHW X
        LDW  X,#qk_ops
        CALL strn
        POPW X
        JMP  d_end

; ---- $40-$6F  load and store -----------------------------------------
;
; Three groups on one layout, `01 gg t dd b`: bit 3 is load or store,
; bits 2:1 the register, bit 0 the pointer -- or, in the third group,
; the addressing form. One printer, three tails.

d_mem:  MOV  R1,R3
        BTST R1,#$08
        BNE  .st
        MOV  R1,#0              ; "LD   "
        CALL mem_name
        MOV  R1,R3
        SHR  R1
        CALL reg
        CALL comma
        CALL d_ea
        JMP  d_end
.st:    MOV  R1,#1              ; "ST   "
        CALL mem_name
        CALL d_ea
        CALL comma
        MOV  R1,R3
        SHR  R1
        CALL reg
        JMP  d_end

; d_ea -- the effective address, from the opcode's group and bit 0.
d_ea:   PUSH R0
        PUSH R1
        MOV  R1,R3
        CMP  R1,#$60
        BHS  .third
        MOV  R0,#'['
        CALL putc
        CALL ptr
        CMP  R1,#$50
        BLO  .close
        MOV  R0,#'+'
        CALL putc
        CALL d_byte
.close: MOV  R0,#']'
        CALL putc
        BRA  .out
.third: BTST R1,#$01
        BNE  .abs
        PUSHW X                 ; X is the instruction pointer, not spare
        LDW  X,#sp_txt
        CALL puts
        POPW X
        CALL d_byte
        MOV  R0,#']'
        CALL putc
        BRA  .out
.abs:   MOV  R0,#'['
        CALL putc
        CALL d_word
        MOV  R0,#']'
        CALL putc
.out:   POP  R1
        POP  R0
        RET

; ---- $70-$7F  branches -----------------------------------------------
;
; The displacement is relative to the *next* instruction, so the target
; is printed instead of the offset. An offset is the one thing you can
; always work out for yourself and never want to.

d_br:   MOV  R1,R3
        AND  R1,#$0F
        PUSHW X
        LDW  X,#br_ops
        CALL strn
        POPW X
        LD   R2,[X]
        INCW X                  ; X is now the next instruction
        PUSHW X
        MOV  R1,#0
        BTST R2,#$80
        BEQ  .pos
        MOV  R1,#$FF            ; sign extend into the high half
.pos:   ADDW X,R2
        MOV  R0,XH
        ADD  R0,R1
        MOV  XH,R0
        MOV  R0,#'$'
        CALL putc
        CALL puthex4
        POPW X
        JMP  d_end

; ---- $2F  page two ---------------------------------------------------

d_p2:   LD   R3,[X]
        INCW X

        MOV  R0,R3
        CMP  R0,#$14
        jlo  .xor
        CMP  R0,#$2C
        jlo  .un
        CMP  R0,#$2E
        jlo  .addwi
        CMP  R0,#$30
        jlo  .bad
        CMP  R0,#$3C
        jlo  .bit
        CMP  R0,#$40
        jlo  .bad
        CMP  R0,#$60
        jlo  .half
        CMP  R0,#$80
        jlo  .w16
        CMP  R0,#$C0
        jlo  .idx
        CMP  R0,#$E0
        jlo  .auto
        CMP  R0,#$F0
        jlo  .sys
        JMP  .mul

        ; $00-$0F XOR Rd,Rs, $10-$13 XOR Rd,#imm8
.xor:   MOV  R1,#0
        CALL p2_name            ; "XOR  "
        MOV  R1,R3
        MOV  R0,R3
        CMP  R0,#$10
        BHS  .xori
        SHR  R1
        SHR  R1
        CALL reg
        CALL comma
        MOV  R1,R3
        CALL reg
        JMP  d_end
.xori:  CALL reg
        CALL comma
        MOV  R0,#'#'
        CALL putc
        CALL d_byte
        JMP  d_end

        ; NOT NEG SWAP SHR SAR ROR -- four opcodes each from $14
.un:    MOV  R1,R3
        SUB  R1,#$14
        SHR  R1
        SHR  R1
        ADD  R1,#1              ; the unary block starts at p2_ops[1]
        CALL p2_name
        MOV  R1,R3
        CALL reg
        JMP  d_end

.addwi: MOV  R1,#7              ; "ADDW "
        CALL p2_name
        CALL ptr
        CALL comma
        MOV  R0,#'#'
        CALL putc
        CALL d_word
        JMP  d_end

        ; BSET BCLR BTST -- four opcodes each from $30
.bit:   MOV  R1,R3
        SUB  R1,#$30
        SHR  R1
        SHR  R1
        ADD  R1,#8
        CALL p2_name
        MOV  R1,R3
        CALL reg
        CALL comma
        MOV  R0,#'#'
        CALL putc
        CALL d_byte
        JMP  d_end

        ; MOV Rd,<pp> and MOV <pp>,Rs
.half:  MOV  R1,#0
        CALL alu_name           ; "MOV  "
        MOV  R1,R3
        BTST R1,#$10
        BNE  .h2
        MOV  R1,R3
        SHR  R1
        SHR  R1
        CALL reg
        CALL comma
        MOV  R1,R3
        CALL pp
        JMP  d_end
.h2:    MOV  R1,R3
        CALL pp
        CALL comma
        MOV  R1,R3
        SHR  R1
        SHR  R1
        CALL reg
        JMP  d_end

        ; $60-$6F -- the 16-bit block. Irregular enough that the operand
        ; text lives in the strings and only the numbers are decoded.
.w16:   MOV  R1,R3
        CMP  R1,#$80
        BHS  .w2
        SUB  R1,#$60
        PUSHW X
        LDW  X,#w16_ops
        CALL strn
        POPW X
        MOV  R1,R3
        CMP  R1,#$66
        BLO  .wword             ; $60-$65 carry a word
        CMP  R1,#$6C
        BLO  .wnone             ; $66-$6B carry nothing
        CMP  R1,#$6F
        BHS  .wnone
        CALL d_byte             ; $6C-$6E carry a byte
        MOV  R1,R3
        CMP  R1,#$6D
        BLO  .wnone
        MOV  R0,#']'
        CALL putc
.wnone: JMP  d_end
.wword: CALL d_word
        MOV  R1,R3
        CMP  R1,#$62
        BLO  .wnone
        MOV  R0,#']'
        CALL putc
        MOV  R1,R3
        CMP  R1,#$64
        BLO  .wnone
        CALL comma              ; STW [abs16],X
        CALL ptr
        JMP  d_end

        ; $70-$7F ADDW/SUBW X|Y,Rd
.w2:    MOV  R1,R3
        SUB  R1,#$70
        BTST R1,#$08
        BEQ  .wadd
        MOV  R1,#$0B            ; "SUBW "
        BRA  .wn
.wadd:  MOV  R1,#7              ; "ADDW "
.wn:    CALL p2_name
        MOV  R1,R3
        SHR  R1
        SHR  R1
        BTST R1,#$01
        BEQ  .wx
        MOV  R0,#'Y'
        BRA  .wq
.wx:    MOV  R0,#'X'
.wq:    CALL putc
        CALL comma
        MOV  R1,R3
        CALL reg
        JMP  d_end

        ; $80-$BF register indexed, $C0-$DF auto
.idx:   MOV  R1,R3
        BTST R1,#$20
        BNE  .ist
        MOV  R1,#0
        CALL mem_name
        MOV  R1,R3
        SHR  R1
        SHR  R1
        CALL reg
        CALL comma
        CALL ea_idx
        JMP  d_end
.ist:   MOV  R1,#1
        CALL mem_name
        CALL ea_idx
        CALL comma
        MOV  R1,R3
        SHR  R1
        SHR  R1
        CALL reg
        JMP  d_end

.auto:  MOV  R1,R3
        BTST R1,#$08
        BNE  .ast
        MOV  R1,#0
        CALL mem_name
        MOV  R1,R3
        SHR  R1
        CALL reg
        CALL comma
        CALL ea_auto
        JMP  d_end
.ast:   MOV  R1,#1
        CALL mem_name
        CALL ea_auto
        CALL comma
        MOV  R1,R3
        SHR  R1
        CALL reg
        JMP  d_end

.sys:   MOV  R1,R3
        SUB  R1,#$E0
        CMP  R1,#3
        BHS  .bad
        ADD  R1,#$0C            ; PUSH F, POP F, CLV
        CALL p2_name
        JMP  d_end

.mul:   MOV  R1,#$0F            ; "MUL  "
        CALL p2_name
        MOV  R1,R3
        SHR  R1
        SHR  R1
        CALL reg
        CALL comma
        MOV  R1,R3
        CALL reg
        JMP  d_end

.bad:   MOV  R1,#$10            ; "???  "
        CALL p2_name
        MOV  R0,#'$'
        CALL putc
        MOV  R0,R3
        CALL puthex2
        JMP  d_end

; ---------------------------------------------------------------------
; The pieces. Every one of these preserves X, because X is the
; instruction pointer for the whole of the above and a table lookup
; that clobbered it would be very hard to see.
; ---------------------------------------------------------------------

; strn -- print the R1'th NUL-terminated string in the block at X.
strn:   PUSH R0
        PUSH R1
.sk:    TST  R1
        BEQ  .go
.f:     LD   R0,[X]
        INCW X
        TST  R0
        BNE  .f
        SUB  R1,#1
        BRA  .sk
.go:    CALL puts
        POP  R1
        POP  R0
        RET

alu_name:
        PUSHW X
        LDW  X,#alu_ops
        CALL strn
        POPW X
        RET

ctl_name:
        PUSHW X
        LDW  X,#ctl_ops
        CALL strn
        POPW X
        RET

mem_name:
        PUSHW X
        LDW  X,#mem_ops
        CALL strn
        POPW X
        RET

p2_name:
        PUSHW X
        LDW  X,#p2_ops
        CALL strn
        POPW X
        RET

; reg -- "R0".."R3" from the low two bits of R1.
reg:    PUSH R0
        MOV  R0,#'R'
        CALL putc
        MOV  R0,R1
        AND  R0,#3
        ADD  R0,#'0'
        CALL putc
        POP  R0
        RET

; ptr -- "X" or "Y" from bit 0 of the opcode.
ptr:    PUSH R0
        MOV  R0,R3
        BTST R0,#$01
        BEQ  .x
        MOV  R0,#'Y'
        BRA  .p
.x:     MOV  R0,#'X'
.p:     CALL putc
        POP  R0
        RET

; pp -- "XL" "XH" "YL" "YH" from the low two bits of R1.
pp:     PUSH R0
        MOV  R0,R1
        BTST R0,#$02
        BEQ  .x
        MOV  R0,#'Y'
        BRA  .p
.x:     MOV  R0,#'X'
.p:     CALL putc
        MOV  R0,R1
        BTST R0,#$01
        BEQ  .l
        MOV  R0,#'H'
        BRA  .e
.l:     MOV  R0,#'L'
.e:     CALL putc
        POP  R0
        RET

; $2C and not #',' -- an operand field is split on commas before any
; string literal in it is recognised, so the character comma reads as
; two operands and no encoding matches.
comma:  PUSH R0
        MOV  R0,#$2C
        CALL putc
        POP  R0
        RET

; d_byte -- "$xx" from the byte at X, which is consumed.
d_byte: PUSH R0
        MOV  R0,#'$'
        CALL putc
        LD   R0,[X]
        INCW X
        CALL puthex2
        POP  R0
        RET

; d_word -- "$xxxx" from the little-endian word at X, both consumed.
d_word: PUSH R0
        PUSH R1
        PUSH R2
        MOV  R0,#'$'
        CALL putc
        LD   R1,[X]
        INCW X
        LD   R2,[X]
        INCW X
        MOV  R0,R2
        CALL puthex2
        MOV  R0,R1
        CALL puthex2
        POP  R2
        POP  R1
        POP  R0
        RET

; ea_idx -- "[X+Rs]" for the register-indexed page-2 group.
ea_idx: PUSH R0
        PUSH R1
        MOV  R0,#'['
        CALL putc
        MOV  R0,R3
        BTST R0,#$10
        BEQ  .x
        MOV  R0,#'Y'
        BRA  .p
.x:     MOV  R0,#'X'
.p:     CALL putc
        MOV  R0,#'+'
        CALL putc
        MOV  R1,R3
        CALL reg
        MOV  R0,#']'
        CALL putc
        POP  R1
        POP  R0
        RET

; ea_auto -- "[X+]" or "[-X]".
ea_auto:
        PUSH R0
        MOV  R0,#'['
        CALL putc
        MOV  R0,R3
        BTST R0,#$10
        BNE  .dec
        CALL ptr
        MOV  R0,#'+'
        CALL putc
        BRA  .cl
.dec:   MOV  R0,#'-'
        CALL putc
        CALL ptr
.cl:    MOV  R0,#']'
        CALL putc
        POP  R0
        RET

d_end:  POP  R3
        POP  R2
        POP  R1
        POP  R0
        RET

; ---------------------------------------------------------------------
; The mnemonics. Padded so the operand column lines up; the padding is
; inside the string, which is where it costs nothing to change.
; ---------------------------------------------------------------------

alu_ops:
        .asciz "MOV  "
        .asciz "ADD  "
        .asciz "ADC  "
        .asciz "SUB  "
        .asciz "SBC  "
        .asciz "AND  "
        .asciz "OR   "
        .asciz "CMP  "

mem_ops:
        .asciz "LD   "
        .asciz "ST   "

; $20-$2E. The four that go through a pointer carry the whole operand,
; which is what makes d_ctl a lookup and a single special case.
ctl_ops:
        .asciz "NOP"
        .asciz "HALT"
        .asciz "RET"
        .asciz "RETI"
        .asciz "EI"
        .asciz "DI"
        .asciz "CLC"
        .asciz "SEC"
        .asciz "JMP  "
        .asciz "CALL "
        .asciz "JMP  [X]"
        .asciz "JMP  [Y]"
        .asciz "CALL [X]"
        .asciz "CALL [Y]"
        .asciz "BRK"

stk_ops:
        .asciz "PUSH "
        .asciz "POP  "

qk_ops:
        .asciz "INCW X"
        .asciz "INCW Y"
        .asciz "DECW X"
        .asciz "DECW Y"
        .asciz "PUSHW X"
        .asciz "PUSHW Y"
        .asciz "POPW X"
        .asciz "POPW Y"

br_ops:
        .asciz "BRA  "
        .asciz "???  "
        .asciz "BEQ  "
        .asciz "BNE  "
        .asciz "BCS  "
        .asciz "BCC  "
        .asciz "BMI  "
        .asciz "BPL  "
        .asciz "BVS  "
        .asciz "BVC  "
        .asciz "BHI  "
        .asciz "BLS  "
        .asciz "BGE  "
        .asciz "BLT  "
        .asciz "BGT  "
        .asciz "BLE  "

p2_ops:
        .asciz "XOR  "          ; 0
        .asciz "NOT  "          ; 1
        .asciz "NEG  "          ; 2
        .asciz "SWAP "          ; 3
        .asciz "SHR  "          ; 4
        .asciz "SAR  "          ; 5
        .asciz "ROR  "          ; 6
        .asciz "ADDW "          ; 7
        .asciz "BSET "          ; 8
        .asciz "BCLR "          ; 9
        .asciz "BTST "          ; A
        .asciz "SUBW "          ; B
        .asciz "PUSH F"         ; C
        .asciz "POP  F"         ; D
        .asciz "CLV"            ; E
        .asciz "MUL  "          ; F
        .asciz "???  "          ; 10

; $60-$6F. The operand text is here because it is a constant for ten of
; the sixteen, and the six that are not need only a number after it.
w16_ops:
        .asciz "LDW  X,#"
        .asciz "LDW  Y,#"
        .asciz "LDW  X,["
        .asciz "LDW  Y,["
        .asciz "STW  ["
        .asciz "STW  ["
        .asciz "MOVW X,Y"
        .asciz "MOVW Y,X"
        .asciz "MOVW SP,X"
        .asciz "MOVW SP,Y"
        .asciz "MOVW X,SP"
        .asciz "MOVW Y,SP"
        .asciz "ADDW SP,#"
        .asciz "LEA  X,[SP+"
        .asciz "LEA  Y,[SP+"
        .asciz "???"

sp_txt: .asciz "[SP+"
