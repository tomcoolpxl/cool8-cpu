; ---------------------------------------------------------------------
; fscmd.asm -- the disk commands: SAVE, LOAD, DIR, ERA, COMPACT, DRIVE.
;
; `sw/fs.asm` below this owns the volume format and the flash; this is
; the language's side of it -- parse a name, call the right primitive,
; say what went wrong. Cold code, and the least exercised in the image,
; which is why every routine here is small and obvious rather than
; clever ([D68]).
;
; ## COMPACT, and why it needs a scratch sector
;
; Deleting a file clears its status byte and leaves the bytes where they
; are, because that is all NOR flash lets you do cheaply. COMPACT gets
; the space back by sliding the live files down and rewriting the
; directory.
;
; Sliding means erasing a 4 KB sector before rewriting it, which
; destroys whatever else lives in that sector -- so the contents have to
; be somewhere else first. There is nowhere in RAM to put 4 KB: main RAM
; holds the user's program and video RAM holds their sprites. So the
; somewhere else is the last sector of the volume, reserved for exactly
; this.
; ---------------------------------------------------------------------

; The 8.3 field is fs.asm's own sname -- "the name being sought" --
; not a second buffer here. It was one until the suite read it back as
; zeros: the two names fold together in a case-insensitive symbol
; lookup, and fs_find copies into its own anyway, so a claim here was
; eleven bytes of duplicate state pointed at by nothing.
FSADDR  = $7C9A                 ;: 2 where the bytes are, or go
FSLENW  = $7C98                 ;: 2 how many of them
FSDRV   = $7C97                 ;: 1 the mounted drive
FSIDX   = $7C96                 ;: 1 the directory entry being read
FSOK    = $7C95                 ;: 1 did the last call succeed
FSCI    = $7C93                 ;: 2 COMPACT: the entry the scan is on
FSCSRC  = $7C91                 ;: 2 COMPACT: the page it is feeding out
FSCLEFT = $7C8F                 ;: 2 COMPACT: pages left in this file
FSPG16  = $7C7F                 ;: 16 COMPACT: one sector's source pages

; fs.asm's own state, by name now rather than by address. The compiled
; version reached `fsent` and `fsfpg` as the literals $007B and $0078
; with a comment saying they must track FSVARS -- which is the invisible
; allocator [D67] spent a session removing everywhere else.
FSPBUF  = $7F00                 ; one page in transit, over the string
                                ;   accumulator: the two lifetimes cannot
                                ;   meet, since SACC exists only while a
                                ;   program runs and every command here
                                ;   runs from the editor
VOLPGS  = 1776                  ; data pages; the rest is scratch

        .include "edit.asm"     ; which brings prog, token, num, console
        .include "fs.asm"

; =====================================================================
; The primitives, wrapped so a caller sees one flag
; =====================================================================

; fsc_mount -- mount the drive in FSDRV.
fsc_mount:
        LD   R0,[FSDRV]
        JMP  fs_mount

; fsc_ok / fsc_bad -- carry in, FSOK out. Every wrapper ends this way so
; the callers below test one byte rather than remembering which
; primitive reports how.
fsc_ok: MOV  R0,#1
        ST   [FSOK],R0
        RET
fsc_bad:
        CLR  R0
        ST   [FSOK],R0
        RET

; fsc_find -- is fsname on the volume? Sets FSLENW from the entry.
fsc_find:
        LDW  X,#fsname
        CALL fs_find
        BCC  fsc_bad
        LD   R0,[fsent+14]
        ST   [FSLENW],R0
        LD   R0,[fsent+15]
        ST   [FSLENW+1],R0
        BRA  fsc_ok

; fsc_save -- FSLENW bytes from FSADDR, as fsname.
fsc_save:
        LD   R0,[FSLENW]
        ST   [fslen],R0
        LD   R0,[FSLENW+1]
        ST   [fslen+1],R0
        LDW  X,#fsname
        LDW  Y,[FSADDR]
        CALL fs_save
        BCC  fsc_bad
        BRA  fsc_ok

; fsc_load -- fsname to FSADDR; FSLENW comes back with the length.
fsc_load:
        LDW  X,#fsname
        LDW  Y,[FSADDR]
        CALL fs_load
        BCC  fsc_bad
        LD   R0,[fslen]
        ST   [FSLENW],R0
        LD   R0,[fslen+1]
        ST   [FSLENW+1],R0
        BRA  fsc_ok

; fsc_erase -- fsname's entry cleared.
fsc_erase:
        LDW  X,#fsname
        CALL fs_delete
        BCC  fsc_bad
        BRA  fsc_ok

; fsc_rdpg / fsc_wrpg / fsc_erapg -- whole pages, for COMPACT. R0:R1 is
; the page number.
fsc_rdpg:
        ST   [fspg],R0
        MOV  R0,R1
        ST   [fspg+1],R0
        LDW  X,#FSPBUF
        STW  [fsbuf],X
        JMP  fs_rdpg
fsc_wrpg:
        ST   [fspg],R0
        MOV  R0,R1
        ST   [fspg+1],R0
        LDW  X,#FSPBUF
        STW  [fsbuf],X
        JMP  fs_wrpg
fsc_erapg:
        ST   [fspg],R0
        MOV  R0,R1
        ST   [fspg+1],R0
        JMP  fs_erapg

; fsc_readent -- directory entry FSIDX into fs.asm's fsent.
fsc_readent:
        LD   R0,[FSIDX]
        CALL fs_seekent
        CALL fls_seek
        CALL fls_open
        CALL fs_rdent
        JMP  fls_close

; =====================================================================
; Parsing a name
; =====================================================================

; fsc_name -- a file name at EDIP -- NAME, "NAME", or either with .EXT --
; into fsname as the eleven-byte 8.3 field the directory holds. Carry
; set if there was one.
fsc_name:
        PUSHW X
        LDW  X,#fsname          ; blank the field first
        MOV  R3,#11
        MOV  R2,#$20
.b:     ST   [X],R2
        INCW X
        SUB  R3,#1
        BNE  .b
        POPW X

        CALL ed_skipsp
        CLR  R3                 ; inside quotes?
        LD   R0,[EDIP]
        LD   R1,[LLEN]
        CMP  R0,R1
        BHS  .scan
        PUSHW X
        LDW  X,#LBUF
        ADDW X,R0
        LD   R1,[X]
        POPW X
        CMP  R1,#$22            ; '"'
        BNE  .scan
        MOV  R3,#1
        ADD  R0,#1
        ST   [EDIP],R0

.scan:  CLR  R2                 ; where in the field the next byte goes
.l:     LD   R0,[EDIP]
        LD   R1,[LLEN]
        CMP  R0,R1
        BHS  .done
        PUSHW X
        LDW  X,#LBUF
        ADDW X,R0
        LD   R0,[X]
        POPW X
        CALL tok_upper
        CMP  R0,#$22            ; a closing quote ends it, and is eaten
        BNE  .nq
        LD   R0,[EDIP]
        ADD  R0,#1
        ST   [EDIP],R0
        BRA  .done
.nq:    TST  R3                 ; unquoted: a space or comma ends it
        BNE  .ch
        CMP  R0,#$20
        BEQ  .done
        CMP  R0,#$2C
        BEQ  .done
.ch:    CMP  R0,#$2E            ; the dot jumps to the extension field
        BNE  .put
        MOV  R2,#8
        BRA  .nx
.put:   CMP  R2,#11
        BHS  .nx
        PUSHW X
        LDW  X,#fsname
        ADDW X,R2
        ST   [X],R0
        POPW X
        ADD  R2,#1
.nx:    LD   R0,[EDIP]
        ADD  R0,#1
        ST   [EDIP],R0
        BRA  .l

.done:  LD   R0,[fsname]        ; nothing at all is not a name
        CMP  R0,#$20
        BEQ  .none
        ; Nothing typed after the dot: a program is a .BAS.
        LD   R0,[fsname+8]
        CMP  R0,#$20
        BNE  .yes
        MOV  R0,#$42            ; 'B'
        ST   [fsname+8],R0
        MOV  R0,#$41            ; 'A'
        ST   [fsname+9],R0
        MOV  R0,#$53            ; 'S'
        ST   [fsname+10],R0
.yes:   SEC
        RET
.none:  CLC
        RET

; =====================================================================
; The commands
; =====================================================================

; fsc_drive -- DRIVE n.
fsc_drive:
        AND  R0,#15
        ST   [FSDRV],R0
        JMP  fsc_mount

; fsc_save_prog -- SAVE. Write first, delete second.
;
; **The order matters twice over.** Deleting first would drop the old
; file out of the scan that derives the free pointer, so the new version
; would be programmed on top of the old one's pages -- and programming
; only clears bits, so what came back would be the two versions ANDed
; together. It is also the safe order across a power cut: the worst that
; can be interrupted is a second copy nobody is using yet, and the old
; one still loads. `fs_find` takes the first match from entry zero,
; which is the older of the two, so the delete afterwards removes the
; right one.
fsc_save_prog:
        CALL fsc_find
        LD   R0,[FSOK]
        PUSH R0                 ; was there one already?
        MOV  R0,#<PROGBOT
        ST   [FSADDR],R0
        MOV  R0,#>PROGBOT
        ST   [FSADDR+1],R0
        LD   R0,[PROGEND]
        LD   R1,[PROGEND+1]
        MOV  R2,#<PROGBOT
        MOV  R3,#>PROGBOT
        SUB  R0,R2
        SBC  R1,R3
        ST   [FSLENW],R0
        MOV  R0,R1
        ST   [FSLENW+1],R0
        CALL fsc_save
        POP  R0
        LD   R1,[FSOK]
        TST  R1
        BEQ  .bad
        TST  R0
        BEQ  .out
        JMP  fsc_erase
.bad:   CLC
        RET
.out:   SEC
        RET

; fsc_load_prog -- LOAD, replacing whatever is there.
fsc_load_prog:
        CALL prg_new
        MOV  R0,#<PROGBOT
        ST   [FSADDR],R0
        MOV  R0,#>PROGBOT
        ST   [FSADDR+1],R0
        CALL fsc_load
        LD   R0,[FSOK]
        TST  R0
        BEQ  .bad
        MOV  R0,#<PROGBOT       ; progend = PROG + length
        MOV  R1,#>PROGBOT
        LD   R2,[FSLENW]
        LD   R3,[FSLENW+1]
        ADD  R0,R2
        ADC  R1,R3
        ST   [PROGEND],R0
        MOV  R0,R1
        ST   [PROGEND+1],R0
        SEC
        RET
.bad:   CLC
        RET

; fsc_dir -- DIR: every live entry, then what is left.
fsc_dir:
        CLR  R0
        ST   [FSIDX],R0
.e:     CALL fsc_readent
        LD   R0,[fsent+11]
        CMP  R0,#$FF            ; the first unused entry ends the walk
        BEQ  .tail
        TST  R0                 ; $00 deleted
        BEQ  .nx
        CMP  R0,#$80            ; $80 the volume label
        BEQ  .nx
        CLR  R3                 ; the name, with a dot before the ext
.n:     CMP  R3,#8
        BNE  .nd
        MOV  R0,#$2E
        PUSH R3
        CALL con_emit
        POP  R3
.nd:    PUSHW X
        LDW  X,#fsent
        ADDW X,R3
        LD   R0,[X]
        POPW X
        PUSH R3
        CALL con_emit
        POP  R3
        ADD  R3,#1
        CMP  R3,#11
        BLO  .n
        MOV  R0,#$20
        CALL con_emit
        LD   R0,[fsent+14]
        LD   R1,[fsent+15]
        CALL num_put
        CALL con_nl
.nx:    LD   R0,[FSIDX]
        ADD  R0,#1
        ST   [FSIDX],R0
        BNE  .e                 ; 256 entries, and the byte wraps to 0
.tail:  ; What is left, in KB: 448 KB of pages does not fit sixteen bits.
        MOV  R0,#<VOLPGS
        MOV  R1,#>VOLPGS
        LD   R2,[fsfpg]
        LD   R3,[fsfpg+1]
        SUB  R0,R2
        SBC  R1,R3
        SHR  R1                 ; pages of 256 bytes, so >> 2 is KB
        ROR  R0
        SHR  R1
        ROR  R0
        JMP  num_put

; =====================================================================
; COMPACT
; =====================================================================

SCRATCH = 1776                  ; the reserved sector, and the data end
LASTSEC = 110                   ; the last sector of data

; fsc_entpages -- R0:R1 = how many pages the entry in fsent occupies.
; A partial page still costs a page.
fsc_entpages:
        LD   R0,[fsent+15]
        CLR  R1
        LD   R2,[fsent+14]
        TST  R2
        BEQ  .out
        ADD  R0,#1
        MOV  R2,#0
        ADC  R1,R2
.out:   RET

; fsc_entpage -- R0:R1 = the page the entry's data starts at.
fsc_entpage:
        LD   R0,[fsent+12]
        LD   R1,[fsent+13]
        RET

; fsc_nextsrc -- the live files' pages, in order, one per call. R0:R1 is
; 0 when there are no more.
;
; Entries are appended and data goes at the tail, so walking the
; directory in index order walks the pages in increasing order too --
; which is what lets COMPACT read a sector's worth of sources knowing
; they are all at or above the destination.
fsc_nextsrc:
.l:     LD   R0,[FSCLEFT]       ; still feeding out a file?
        LD   R1,[FSCLEFT+1]
        OR   R0,R1
        BNE  .give
        LD   R0,[FSCI]          ; no: find the next live entry
        LD   R1,[FSCI+1]
        TST  R1
        BNE  .none              ; past 255: the walk is over
        ST   [FSIDX],R0
        ADD  R0,#1
        ST   [FSCI],R0
        MOV  R0,#0
        ADC  R1,R0
        ST   [FSCI+1],R1
        CALL fsc_readent
        LD   R0,[fsent+11]
        CMP  R0,#$FF            ; unused: nothing beyond it either
        BEQ  .stop
        TST  R0
        BEQ  .l                 ; deleted
        CMP  R0,#$80
        BEQ  .l                 ; the volume label
        CALL fsc_entpage
        ST   [FSCSRC],R0
        MOV  R0,R1
        ST   [FSCSRC+1],R0
        CALL fsc_entpages
        ST   [FSCLEFT],R0
        MOV  R0,R1
        ST   [FSCLEFT+1],R0
        BRA  .l
.give:  LD   R0,[FSCSRC]        ; hand out one page and step
        LD   R1,[FSCSRC+1]
        PUSH R0
        PUSH R1
        ADD  R0,#1
        MOV  R2,#0
        ADC  R1,R2
        ST   [FSCSRC],R0
        MOV  R0,R1
        ST   [FSCSRC+1],R0
        LD   R0,[FSCLEFT]
        LD   R1,[FSCLEFT+1]
        MOV  R2,#1
        SUB  R0,R2
        MOV  R2,#0
        SBC  R1,R2
        ST   [FSCLEFT],R0
        MOV  R0,R1
        ST   [FSCLEFT+1],R0
        POP  R1
        POP  R0
        RET
.stop:  MOV  R0,#0              ; nothing further can be live
        ST   [FSCI],R0
        MOV  R0,#1
        ST   [FSCI+1],R0
.none:  CLR  R0
        CLR  R1
        RET

; fsc_pbfill -- the page buffer to $FF, which is what an erased page is.
fsc_pbfill:
        PUSHW X
        LDW  X,#FSPBUF
        MOV  R2,#$FF
        CLR  R3
.f:     ST   [X],R2
        INCW X
        SUB  R3,#1
        BNE  .f
        POPW X
        RET

; fsc_rewritedir -- the directory rebuilt: the live entries at their new
; page numbers, in the same order, with the deleted ones gone.
;
; Built in the scratch sector first, so the old directory is still there
; to read while the new one is being written.
FSSLOT  = $7C7E                 ;: 1 rewritedir: entries written so far
FSDST   = $7C7C                 ;: 2 rewritedir: the next data page

fsc_rewritedir:
        MOV  R0,#<SCRATCH
        MOV  R1,#>SCRATCH
        CALL fsc_erapg
        CALL fsc_pbfill
        CLR  R0
        ST   [FSSLOT],R0
        ST   [FSIDX],R0
        MOV  R0,#16             ; data starts after the directory sector
        ST   [FSDST],R0
        CLR  R0
        ST   [FSDST+1],R0
.e:     CALL fsc_readent
        LD   R0,[fsent+11]
        CMP  R0,#$FF
        BEQ  .flush
        TST  R0
        BEQ  .nx                ; deleted: it simply does not come across
        PUSH R0
        ; copy the sixteen bytes into the slot
        LD   R0,[FSSLOT]
        AND  R0,#15
        CLR  R1
        SHL  R0
        ROL  R1
        SHL  R0
        ROL  R1
        SHL  R0
        ROL  R1
        SHL  R0
        ROL  R1
        PUSHW X
        LDW  X,#FSPBUF
        CALL addx16
        PUSHW Y
        MOVW Y,X
        LDW  X,#fsent
        MOV  R3,#16
.c:     LD   R0,[X]
        ST   [Y],R0
        INCW X
        INCW Y
        SUB  R3,#1
        BNE  .c
        POPW Y
        POPW X
        POP  R0
        CMP  R0,#$80            ; the label has no data pages
        BEQ  .slot
        ; give it its new start page, and advance the destination
        PUSH R0
        LD   R0,[FSSLOT]
        AND  R0,#15
        CLR  R1
        SHL  R0
        ROL  R1
        SHL  R0
        ROL  R1
        SHL  R0
        ROL  R1
        SHL  R0
        ROL  R1
        ADD  R0,#12
        MOV  R2,#0
        ADC  R1,R2
        PUSHW X
        LDW  X,#FSPBUF
        CALL addx16
        LD   R0,[FSDST]
        ST   [X],R0
        INCW X
        LD   R0,[FSDST+1]
        ST   [X],R0
        POPW X
        CALL fsc_entpages
        LD   R2,[FSDST]
        LD   R3,[FSDST+1]
        ADD  R2,R0
        ADC  R3,R1
        ST   [FSDST],R2
        MOV  R0,R3
        ST   [FSDST+1],R0
        POP  R0
.slot:  LD   R0,[FSSLOT]
        ADD  R0,#1
        ST   [FSSLOT],R0
        AND  R0,#15
        BNE  .nx                ; the slot page is full: write it out
        LD   R0,[FSSLOT]
        CALL fsc_scrpg
        CALL fsc_wrpg
        CALL fsc_pbfill
.nx:    LD   R0,[FSIDX]
        ADD  R0,#1
        ST   [FSIDX],R0
        BNE  .e
.flush: LD   R0,[FSSLOT]        ; a partial page still has to go out
        AND  R0,#15
        BEQ  .swap
        LD   R0,[FSSLOT]
        ADD  R0,#16
        CALL fsc_scrpg
        CALL fsc_wrpg
        ; Everything above the entries stays $FF from the erase, so the
        ; swap only has to carry the pages that were written.
.swap:  MOV  R0,#0
        MOV  R1,#0
        CALL fsc_erapg          ; sector 0: the directory
        CLR  R3
.s:     PUSH R3
        MOV  R0,R3
        MOV  R1,#<SCRATCH
        MOV  R2,#>SCRATCH
        ADD  R0,R1
        MOV  R1,R2
        MOV  R2,#0
        ADC  R1,R2
        CALL fsc_rdpg
        POP  R3
        PUSH R3
        MOV  R0,R3
        CLR  R1
        CALL fsc_wrpg
        POP  R3
        ADD  R3,#1
        LD   R0,[FSSLOT]
        SHR  R0
        SHR  R0
        SHR  R0
        SHR  R0
        CMP  R3,R0
        BLS  .s
        RET

; fsc_scrpg -- R0:R1 = SCRATCH + (R0 >> 4) - 1, the scratch page a slot
; count belongs to. Split out because rewritedir wants it twice and the
; shift is four instructions.
fsc_scrpg:
        SHR  R0
        SHR  R0
        SHR  R0
        SHR  R0
        SUB  R0,#1
        MOV  R1,#<SCRATCH
        MOV  R2,#>SCRATCH
        ADD  R0,R1
        MOV  R1,R2
        MOV  R2,#0
        ADC  R1,R2
        RET
