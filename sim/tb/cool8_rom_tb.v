// cool8_rom_tb — is the ROM image really in the ROM?
//
// Reads all 4096 bytes out through the port and holds them against the
// file they came from. Deliberately touches nothing inside the module,
// so the same testbench runs against the RTL and against the netlist
// `synth_ice40` produces — and the netlist run is the one that matters.
// The RTL's `$readmemh` proves the file parses; only the mapped
// SB_RAM40_4K blocks, with their INIT_0..INIT_F baked in, prove the
// image will be in the bitstream. Those are different claims, and a boot
// ROM that is right in simulation and empty on the board is not a
// hypothetical failure.
//
//   vvp cool8_rom_tb.vvp +expect=boot.hex
//
// The module initialises itself from its own INIT_FILE, so run this with
// the working directory that filename resolves in.
//
// Plusargs:
//   +expect=FILE  the 4096-line image the ROM should hold
//   +vcd=FILE     dump waves

`default_nettype none
`timescale 1ns / 1ps

module cool8_rom_tb;

    reg          clk = 1'b0;
    integer      errors, i, shown;
    reg [1023:0] expectfile, vcdfile;
    reg [7:0]    want [0:4095];
    reg [7:0]    got;

    reg          read;
    reg [11:0]   addr;
    wire [7:0]   rdata;

    always #5 clk = ~clk;

    cool8_rom u_rom (
        .clk(clk), .read(read), .addr(addr), .rdata(rdata)
    );

    // One byte per two clocks, the same launch-then-data shape
    // cool8_mem.v drives it with.
    task fetch;
        input [11:0] a;
        output [7:0] d;
        begin
            addr <= a;
            read <= 1'b1;
            @(posedge clk);
            read <= 1'b0;
            @(posedge clk);
            d = rdata;
        end
    endtask

    initial begin
        errors = 0;
        shown  = 0;
        read   = 1'b0;
        addr   = 12'h000;

        for (i = 0; i < 4096; i = i + 1) want[i] = 8'h00;
        if (!$value$plusargs("expect=%s", expectfile)) begin
            $display("FAIL: no +expect= given");
            $finish;
        end
        $readmemh(expectfile, want);

        if ($value$plusargs("vcd=%s", vcdfile)) begin
            $dumpfile(vcdfile);
            $dumpvars(0, cool8_rom_tb);
        end

        repeat (4) @(posedge clk);

        for (i = 0; i < 4096; i = i + 1) begin
            fetch(i[11:0], got);
            if (got !== want[i]) begin
                errors = errors + 1;
                if (shown < 8) begin
                    $display("FAIL offset $%03h ($%04h): got %02h, expected %02h",
                             i[11:0], 16'hF000 + i[15:0], got, want[i]);
                    shown = shown + 1;
                end
            end
        end

        $display("4096 bytes read back, %0d wrong", errors);
        if (errors == 0) $display("PASS");
        else             $display("FAIL");
        $finish;
    end

endmodule

`default_nettype wire
