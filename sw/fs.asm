; ---------------------------------------------------------------------
; fs.asm -- the COOL8 filesystem, machine side.
;
; Sixteen volumes of 448 KB above the $100000 hardware floor, mounted by
; number. One 4 KB directory sector of 256 sixteen-byte entries, 110
; sectors of data, and one scratch sector COMPACT keeps for itself.
; The format is documented in tools/cool8disk.py,
; which is the same filesystem written independently on the PC -- and
; sim/test_fs.py is the gate that makes the two agree.
;
; ## Built around what NOR flash can do
;
; Erase sets a 4 KB sector to $FF; programming can only clear bits. So:
;
;   creating a file  writes an entry that is still $FF -- no erase, no
;                    read-modify-write, and NO 4 KB BUFFER ANYWHERE
;   deleting one     clears its status byte to $00
;   free space       is the tail; there is no allocation bitmap
;   the free pointer is not stored, because a value that only increases
;                    cannot be rewritten in place. fs_mount derives it.
;
; ## The geometry pays off in the addressing
;
; A volume is 448 KB = 7 x 64 KB, so **every volume base is 64 KB
; aligned**: base = ($10 + drive*7) << 16, and its low sixteen bits are
; zero. A file starts on a 256-byte page, so the address of a file is
;
;       low  = 0
;       mid  = page low byte
;       high = base high byte + page high byte
;
; which is one add. That is not a coincidence -- 448 KB was chosen partly
; for it. A 500 KB volume would have cost a 24-bit multiply here.
;
; ## Entry layout
;
;   0-10   name, 8.3, space padded, upper case
;   11     status: $FF free, $00 deleted, $80 volume label, else type
;   12-13  start, in 256-byte pages from the volume base
;   14-15  length in bytes
; ---------------------------------------------------------------------

FLS_ADDR_L = $FE88
FLS_ADDR_M = $FE89
FLS_ADDR_H = $FE8A
FLS_DATA   = $FE8B
FLS_CTRL   = $FE8C
FLS_STAT   = $FE8D
FLS_WDATA  = $FE8E
FLS_WCTRL  = $FE8F

; ---- state
;
; This lived at $0100 and should not have. The boot ROM sets SP to $0200
; (boot.asm:339) and nothing moves it afterwards, so the CPU stack grows
; down through page 1 -- straight into this block at depth 210. The
; failure was quiet in the worst way: a deep expression corrupted the
; mounted volume rather than a return address, so the machine kept
; running and the disk went wrong later.
;
; Page 1 is now the stack and nothing else, which is what the BBC Micro
; does; its filing system workspace sits in page 0 at &B0-&CF for the
; same reason. There is no cost to being here -- COOL8 has no zero-page
; addressing mode (D6), so $0074 is neither faster nor slower than
; $0100.
FSVARS  = $0074                 ; 46 bytes, $0074-$00A1
fsdrv   = FSVARS+0              ; the mounted drive
fsbase  = FSVARS+1              ; 3: volume base, 24-bit little endian
fsfpg   = FSVARS+4              ; 2: first free page in the volume
fsfent  = FSVARS+6              ; 1: first free directory entry, $FF none
fsent   = FSVARS+7              ; 16: the entry last read, or being built
fsidx   = FSVARS+23             ; 1: its index
fsa     = FSVARS+24             ; 3: the flash address being worked
fslen   = FSVARS+27             ; 2: length, in and out
fsname  = FSVARS+29             ; 11: the name being sought
fstmp   = FSVARS+40             ; 2
fspg    = FSVARS+42             ; 2: the page fs_rdpg/fs_wrpg work on
fsbuf   = FSVARS+44             ; 2: and the 256 bytes they work through


; ---------------------------------------------------------------------
; The flash, at its own level.
; ---------------------------------------------------------------------

; fls_seek -- FLS_ADDR = [fsa]
fls_seek:
        PUSH R0
        LD   R0,[fsa]
        ST   [FLS_ADDR_L],R0
        LD   R0,[fsa+1]
        ST   [FLS_ADDR_M],R0
        LD   R0,[fsa+2]
        ST   [FLS_ADDR_H],R0
        POP  R0
        RET

fls_open:
        PUSH R0
        MOV  R0,#1
        ST   [FLS_CTRL],R0
        POP  R0
        RET

fls_close:
        PUSH R0
        CLR  R0
        ST   [FLS_CTRL],R0
        POP  R0
        RET

; fsa_inc -- fsa = fsa + 1
fsa_inc:
        PUSH R0
        LD   R0,[fsa]
        ADD  R0,#1
        ST   [fsa],R0
        BNE  .fi9
        LD   R0,[fsa+1]
        ADD  R0,#1
        ST   [fsa+1],R0
        BNE  .fi9
        LD   R0,[fsa+2]
        ADD  R0,#1
        ST   [fsa+2],R0
.fi9:   POP  R0
        RET

; fls_prog -- program R0 at [fsa], then advance fsa.
;
; The address does not auto-advance on a program the way it does on a
; read -- the hardware sends one opcode per byte -- so every byte costs a
; seek. See the note in sim/test_fs.py about what that means for speed.
fls_prog:
        PUSH R1
        CALL fls_seek
        ST   [FLS_WDATA],R0
        MOV  R1,#1
        ST   [FLS_WCTRL],R1
.fp1:   LD   R1,[FLS_WCTRL]
        BTST R1,#$01
        BNE  .fp1
        CALL fsa_inc
        POP  R1
        RET

; ---------------------------------------------------------------------
; Whole pages, for COMPACT.
;
; The caller puts a page number in [fspg] and a 256-byte buffer address
; in [fsbuf]; every volume base is 64 KB aligned, so the flash address
; is base + (page << 8) and that is one add.
;
; These are the only routines that erase.
; ---------------------------------------------------------------------

; fs_seekpg -- fsa = the flash address of page [fspg]
fs_seekpg:
        PUSH R0
        PUSH R1
        CLR  R0
        ST   [fsa],R0
        LD   R0,[fspg]
        ST   [fsa+1],R0
        LD   R0,[fsbase+2]
        LD   R1,[fspg+1]
        ADD  R0,R1
        ST   [fsa+2],R0
        POP  R1
        POP  R0
        RET

; fs_rdpg -- page [fspg] into [fsbuf], 256 bytes.
fs_rdpg:
        PUSH R0
        PUSH R1
        PUSHW Y
        CALL fs_seekpg
        CALL fls_seek
        CALL fls_open
        LDW  Y,[fsbuf]
        CLR  R1
.rg1:   LD   R0,[FLS_DATA]
        ST   [Y],R0
        INCW Y
        ADD  R1,#1
        BNE  .rg1
        CALL fls_close
        POPW Y
        POP  R1
        POP  R0
        RET

; fs_wrpg -- [fsbuf] into page [fspg]. The page must be erased first;
; programming only clears bits.
fs_wrpg:
        PUSH R0
        PUSH R1
        PUSHW Y
        CALL fs_seekpg
        LDW  Y,[fsbuf]
        CLR  R1
.wg1:   LD   R0,[Y]
        CALL fls_prog                   ; advances fsa itself
        INCW Y
        ADD  R1,#1
        BNE  .wg1
        POPW Y
        POP  R1
        POP  R0
        RET

; fs_erapg -- erase the 4 KB sector holding page [fspg].
fs_erapg:
        PUSH R0
        CALL fs_seekpg
        CALL fls_seek
        MOV  R0,#2
        ST   [FLS_WCTRL],R0
.eg1:   LD   R0,[FLS_WCTRL]
        BTST R0,#$01
        BNE  .eg1
        POP  R0
        RET


; fsa_base -- fsa = fsbase
fsa_base:
        PUSH R0
        LD   R0,[fsbase]
        ST   [fsa],R0
        LD   R0,[fsbase+1]
        ST   [fsa+1],R0
        LD   R0,[fsbase+2]
        ST   [fsa+2],R0
        POP  R0
        RET

; fs_rdent -- read the next sixteen bytes of an open stream into fsent
fs_rdent:
        PUSH R0
        PUSH R1
        PUSHW X
        LDW  X,#fsent
        MOV  R1,#16
.re1:   LD   R0,[FLS_DATA]
        ST   [X],R0
        INCW X
        SUB  R1,#1
        BNE  .re1
        POPW X
        POP  R1
        POP  R0
        RET


; ---------------------------------------------------------------------
; fs_mount -- R0 = drive 0..15.
;
; Sets fsbase, then scans all 256 entries to derive the first free page
; and the first free entry. Neither is stored on the medium: a pointer
; that only ever increases cannot be rewritten in place on flash, and a
; scan of one sector is cheap enough that it does not need to be.
; ---------------------------------------------------------------------
fs_mount:
        PUSH R1
        PUSH R2
        PUSH R3
        ST   [fsdrv],R0

        ; base = ($10 + drive*7) << 16
        MOV  R1,#7
        MUL  R0,R1
        MOV  R0,XL
        ADD  R0,#$10
        ST   [fsbase+2],R0
        CLR  R0
        ST   [fsbase],R0
        ST   [fsbase+1],R0

        ; data starts at page 16; no entry is free yet
        MOV  R0,#16
        ST   [fsfpg],R0
        CLR  R0
        ST   [fsfpg+1],R0
        MOV  R0,#$FF
        ST   [fsfent],R0

        CALL fsa_base
        CALL fls_seek
        CALL fls_open

        CLR  R2                         ; entry index
.mn1:   CALL fs_rdent
        LD   R0,[fsent+11]
        CMP  R0,#$FF
        BNE  .mn2
        LD   R1,[fsfent]                ; free -- remember the first
        CMP  R1,#$FF
        BNE  .mn8
        ST   [fsfent],R2
        BRA  .mn8
.mn2:   TST  R0
        BEQ  .mn8                       ; deleted
        CMP  R0,#$80
        BEQ  .mn8                       ; volume label

        ; end page = start page + ceil(length / 256)
        PUSH R2
        CLR  R3
        LD   R2,[fsent+15]
        LD   R0,[fsent+14]
        TST  R0
        BEQ  .mn3
        ; CLR is SUB Rd,Rd and so it SETS carry. It has to happen before
        ; the ADD, not between the ADD and the ADC that reads its carry
        ; -- that way round every file with a partial last page pushed
        ; the derived free pointer 256 pages too high.
        CLR  R0
        ADD  R2,#1
        ADC  R3,R0
.mn3:   LD   R0,[fsent+12]
        ADD  R0,R2
        LD   R1,[fsent+13]
        ADC  R1,R3
        ST   [fstmp],R0
        ST   [fstmp+1],R1
        ; if end >= fsfpg then fsfpg = end
        LD   R2,[fsfpg]
        LD   R3,[fsfpg+1]
        SUB  R0,R2
        SBC  R1,R3
        BLO  .mn4
        LD   R0,[fstmp]
        ST   [fsfpg],R0
        LD   R0,[fstmp+1]
        ST   [fsfpg+1],R0
.mn4:   POP  R2

.mn8:   ADD  R2,#1
        BEQ  .mn9                       ; 256 entries, and it wrapped
        JMP  .mn1
.mn9:   CALL fls_close
        POP  R3
        POP  R2
        POP  R1
        RET


; ---------------------------------------------------------------------
; fs_find -- X points at an 11-byte name. C=1 and fsent/fsidx set if it
; is there, C=0 if not.
; ---------------------------------------------------------------------
fs_find:
        PUSH R0
        PUSH R1
        PUSH R2
        PUSH R3
        PUSHW X
        PUSHW Y

        LDW  Y,#fsname
        MOV  R1,#11
.ff1:   LD   R0,[X]
        ST   [Y],R0
        INCW X
        INCW Y
        SUB  R1,#1
        BNE  .ff1

        CALL fsa_base
        CALL fls_seek
        CALL fls_open
        CLR  R2
.ff2:   CALL fs_rdent
        LD   R0,[fsent+11]
        CMP  R0,#$FF
        BEQ  .ff8
        TST  R0
        BEQ  .ff8
        CMP  R0,#$80
        BEQ  .ff8
        LDW  X,#fsent
        LDW  Y,#fsname
        MOV  R1,#11
.ff3:   LD   R0,[X]
        LD   R3,[Y]
        CMP  R0,R3
        BNE  .ff8
        INCW X
        INCW Y
        SUB  R1,#1
        BNE  .ff3
        ST   [fsidx],R2
        CALL fls_close
        POPW Y
        POPW X
        POP  R3
        POP  R2
        POP  R1
        POP  R0
        SEC
        RET
.ff8:   ADD  R2,#1
        BEQ  .ff9
        JMP  .ff2
.ff9:   CALL fls_close
        POPW Y
        POPW X
        POP  R3
        POP  R2
        POP  R1
        POP  R0
        CLC
        RET


; fs_seekfile -- fsa = the flash address of the entry in fsent.
; One add, because every volume base is 64 KB aligned.
fs_seekfile:
        PUSH R0
        PUSH R1
        CLR  R0
        ST   [fsa],R0
        LD   R0,[fsent+12]
        ST   [fsa+1],R0
        LD   R0,[fsbase+2]
        LD   R1,[fsent+13]
        ADD  R0,R1
        ST   [fsa+2],R0
        POP  R1
        POP  R0
        RET

; fs_seekent -- fsa = the flash address of directory entry R0
fs_seekent:
        PUSH R1
        MOV  R1,#16
        MUL  R0,R1
        MOV  R0,XL
        ST   [fsa],R0
        MOV  R0,XH
        LD   R1,[fsbase+1]
        ADD  R0,R1
        ST   [fsa+1],R0
        LD   R0,[fsbase+2]
        ST   [fsa+2],R0
        POP  R1
        RET


; ---------------------------------------------------------------------
; fs_load -- X points at a name, Y is where it goes.
; C=1 and fslen set on success, C=0 if there is no such file.
; ---------------------------------------------------------------------
fs_load:
        PUSH R0
        PUSH R2
        PUSH R3
        CALL fs_find
        BCC  .fl9

        LD   R0,[fsent+14]
        ST   [fslen],R0
        LD   R0,[fsent+15]
        ST   [fslen+1],R0

        CALL fs_seekfile
        CALL fls_seek
        CALL fls_open
        LD   R2,[fsent+14]
        LD   R3,[fsent+15]
.fl1:   MOV  R0,R2
        OR   R0,R3
        BEQ  .fl8
        LD   R0,[FLS_DATA]
        ST   [Y],R0
        INCW Y
        SUB  R2,#1
        BCS  .fl1
        SUB  R3,#1
        BRA  .fl1
.fl8:   CALL fls_close
        POP  R3
        POP  R2
        POP  R0
        SEC
        RET
.fl9:   POP  R3
        POP  R2
        POP  R0
        CLC
        RET


; ---------------------------------------------------------------------
; fs_save -- X points at a name, Y at the data, [fslen] is the length.
; C=1 on success; C=0 if the volume is full of files or of bytes.
;
; The data goes at the tail and the entry goes in the first free slot.
; Neither needs an erase, because both are still $FF.
; ---------------------------------------------------------------------
fs_save:
        PUSH R0
        PUSH R1
        PUSH R2
        PUSH R3
        PUSHW X

        LD   R0,[fsfent]
        CMP  R0,#$FF
        BEQ  .fsx                       ; no free entry

        ; And the tail has to hold it. Without this, programming runs
        ; off the end of the volume and into the next one -- which is
        ; not a full disk, it is someone else's data. Data ends at page
        ; $06F0; the sixteen pages above that are COMPACT's scratch. The
        ; file needs its whole pages plus one for a partial.
        LD   R0,[fsfpg]
        LD   R2,[fsfpg+1]
        LD   R1,[fslen+1]
        ADD  R0,R1
        BCC  .fsp1
        ADD  R2,#1
.fsp1:  LD   R1,[fslen]
        TST  R1
        BEQ  .fsp2
        ADD  R0,#1
        BCC  .fsp2
        ADD  R2,#1
.fsp2:  CMP  R2,#6
        BCC  .fsp3                      ; end page high < 6: it fits
        BNE  .fsx                       ; high > 6: it does not
        CMP  R0,#$F1
        BCC  .fsp3                      ; $06xx, up to $06F0 exactly
.fsx:   JMP  .fs9                       ; out of reach of a Bcc from here
.fsp3:

        ; the name, into the entry being built
        PUSHW Y
        LDW  Y,#fsent
        MOV  R1,#11
.fs1:   LD   R0,[X]
        ST   [Y],R0
        INCW X
        INCW Y
        SUB  R1,#1
        BNE  .fs1
        POPW Y

        MOV  R0,#1                      ; status: an ordinary file
        ST   [fsent+11],R0
        LD   R0,[fsfpg]
        ST   [fsent+12],R0
        LD   R0,[fsfpg+1]
        ST   [fsent+13],R0
        LD   R0,[fslen]
        ST   [fsent+14],R0
        LD   R0,[fslen+1]
        ST   [fsent+15],R0

        ; the data
        CALL fs_seekfile
        LD   R2,[fslen]
        LD   R3,[fslen+1]
.fs2:   MOV  R0,R2
        OR   R0,R3
        BEQ  .fs3
        LD   R0,[Y]
        CALL fls_prog
        INCW Y
        SUB  R2,#1
        BCS  .fs2
        SUB  R3,#1
        BRA  .fs2

        ; the entry
.fs3:   LD   R0,[fsfent]
        CALL fs_seekent
        PUSHW Y
        LDW  Y,#fsent
        MOV  R1,#16
.fs4:   LD   R0,[Y]
        CALL fls_prog
        INCW Y
        SUB  R1,#1
        BNE  .fs4
        POPW Y

        ; the free page and the free entry both moved; a rescan is one
        ; sector read and is always right, where incrementing is not.
        LD   R0,[fsdrv]
        CALL fs_mount

        POPW X
        POP  R3
        POP  R2
        POP  R1
        POP  R0
        SEC
        RET
.fs9:   POPW X
        POP  R3
        POP  R2
        POP  R1
        POP  R0
        CLC
        RET


; ---------------------------------------------------------------------
; fs_delete -- X points at a name. One byte programmed, nothing erased.
; ---------------------------------------------------------------------
fs_delete:
        PUSH R0
        CALL fs_find
        BCC  .fd9
        LD   R0,[fsidx]
        CALL fs_seekent
        LD   R0,[fsa]
        ADD  R0,#11                     ; the status byte
        ST   [fsa],R0
        CLR  R0
        CALL fls_prog
        LD   R0,[fsdrv]
        CALL fs_mount
        POP  R0
        SEC
        RET
.fd9:   POP  R0
        CLC
        RET
