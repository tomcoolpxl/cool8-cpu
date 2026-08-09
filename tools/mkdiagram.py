#!/usr/bin/env python3
"""The SoC block diagram, generated from the RTL rather than drawn.

    python tools/mkdiagram.py -o docs/img/readme-soc.svg

yosys elaborates `cool8_soc` with every submodule kept as a black box,
and this script reduces the netlist to what a block diagram states: which
modules exist and which talk to which. Connectivity is traced *through*
the soc's glue -- the address decode and the read-data mux sit between
the CPU and every device, so raw net sharing would miss most edges; a
breadth-first walk from each module output across the glue cells finds
the modules it actually reaches.

Needs yosys (OSS CAD Suite) and graphviz `dot` on PATH.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "sim"))
import cosim

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOP = "cool8_soc"

# The children as boxes; rom/vram and the video internals stay inside
# them, which is the whole point of a block diagram. cool8_rom.v is not
# even read: it $readmemh's images this script has no reason to build.
FILES = ["soc/cool8_soc.v", "core/cool8_core.v", "soc/cool8_mem.v",
         "soc/cool8_video.v", "soc/cool8_uart.v", "soc/cool8_ps2.v",
         "soc/cool8_snd.v", "soc/cool8_flash.v", "soc/cool8_loader.v"]
BOXES = [os.path.splitext(os.path.basename(f))[0] for f in FILES[1:]]

LABEL = {
    "u_cpu": ("COOL8 CPU", "8-bit core, 511 encodings"),
    "u_mem": ("Memory", "64K RAM + 4K boot ROM"),
    "u_vid": ("Video", "VGA, 32 sprites, own 64K VRAM"),
    "u_uart": ("UART", "115200 8N1 console"),
    "u_ps2": ("PS/2", "keyboard decoder"),
    "u_snd": ("Sound", "8 voices, 1-bit DAC"),
    "u_fls": ("SPI flash", "8 MB, read and write"),
    "u_ldr": ("Loader", "host DMA (build option)"),
}
FILL = {"u_cpu": "#f6d55c", "u_mem": "#b5e0b5", "u_vid": "#9fc5e8",
        "u_snd": "#d5a6e0", "u_uart": "#e0c9a6", "u_ps2": "#e0c9a6",
        "u_fls": "#b5d0d0", "u_ldr": "#d9d9d9"}

# Top-level ports folded into the outside world they are: pin groups on
# the left, the host on the right.
WORLD = [("vga", r"hsync|vsync|rgb|vga|^o_[rgb]\d*$", "VGA\nconnector"),
         ("serial", r"uart|rx$|tx$", "serial\nconsole"),
         ("kbd", r"ps2", "PS/2\nkeyboard"),
         ("spi", r"flash|spi", "SPI flash\nchip"),
         ("audio", r"snd|audio|pwm|dac", "audio\njack")]


def netlist():
    files = " ".join(os.path.join(REPO, "rtl", f).replace(os.sep, "/")
                     for f in FILES)
    out = os.path.join(tempfile.gettempdir(), "cool8_soc_diagram.json")
    script = (f"read_verilog {files}; blackbox {' '.join(BOXES)}; "
              f"hierarchy -top {TOP}; proc; opt_clean; "
              f"write_json {out.replace(os.sep, '/')}")
    subprocess.run([cosim._tool("yosys"), "-q", "-p", script], check=True)
    with open(out) as fh:
        return json.load(fh)["modules"][TOP]


def bits(conn):
    return [b for b in conn if isinstance(b, int)]


def schematic(out):
    """The ALU, gate for gate: yosys elaborates it to RTL cells and
    netlistsvg draws the schematic -- adders, muxes and gates with
    their real symbols. The whole core renders too but comes out
    16,000 x 46,000 pixels of wire, which is why one block at full
    depth is the picture and the SoC gets the block diagram above.
    ImageMagick rasterises it: GitHub's dark theme is unreadable with
    netlistsvg's transparent background, a PNG carries its own."""
    tmp = os.path.join(tempfile.gettempdir(), "cool8_alu")
    src = os.path.join(REPO, "rtl", "core", "cool8_alu.v")
    subprocess.run([cosim._tool("yosys"), "-q", "-p",
                    f"read_verilog {src.replace(os.sep, '/')}; "
                    f"hierarchy -top cool8_alu; proc; opt -full; opt_clean; "
                    f"write_json {tmp}.json".replace(os.sep, "/")],
                   check=True)
    subprocess.run(["npx", "--yes", "netlistsvg", tmp + ".json",
                    "-o", tmp + ".svg"], check=True, shell=True)
    magick = shutil.which("magick") or \
        r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"
    subprocess.run([magick, "-background", "white", tmp + ".svg",
                    "-resize", "1600x", out], check=True)
    print(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--out", default="docs/img/readme-soc.svg")
    ap.add_argument("--alu", help="also draw the ALU schematic to this PNG")
    args = ap.parse_args()

    if args.alu:
        schematic(args.alu)

    mod = netlist()

    # Every endpoint a net bit can lead to. An endpoint is a module
    # instance or a top-level port group; a glue cell is a conductor.
    drives, feeds = {}, {}      # bit -> [(kind, name, port)]

    def note(table, bit, entry):
        table.setdefault(bit, []).append(entry)

    clocky = re.compile(r"clk|rst|reset", re.I)
    for pname, p in mod["ports"].items():
        if clocky.search(pname):
            continue
        group = next((g for g, pat, _ in WORLD if re.search(pat, pname, re.I)),
                     "host")
        for b in bits(p["bits"]):
            note(drives if p["direction"] == "input" else feeds,
                 b, ("world", group, pname))

    glue_in, glue_out = {}, {}  # cell -> [bits]
    for cname, c in mod["cells"].items():
        box = c["type"] in BOXES
        for port, conn in c["connections"].items():
            d = c["port_directions"].get(port, "input")
            if box and clocky.search(port):
                continue
            for b in bits(conn):
                if box:
                    note(drives if d == "output" else feeds,
                         b, ("inst", cname, port))
                else:
                    (glue_out if d == "output" else glue_in).setdefault(
                        cname, []).append(b)

    # bit -> glue cells reading it, for the walk
    readers = {}
    for cname, bs in glue_in.items():
        for b in bs:
            readers.setdefault(b, []).append(cname)

    # Direct edges: driver and sink on the very same net. Pin groups
    # only count these -- a stall that reaches the audio jack through
    # three OR gates is dataflow, not a wire to a pin.
    direct = set()
    for b, srcs in drives.items():
        for _, sname, _ in srcs:
            for _, dname, _ in feeds.get(b, ()):
                direct.add((sname, dname))

    edges = {}                  # (src, dst) -> set of source port names
    for b0, srcs in drives.items():
        seen_bits, seen_cells = {b0}, set()
        frontier = [b0]
        while frontier:
            b = frontier.pop()
            for cell in readers.get(b, ()):
                if cell in seen_cells:
                    continue
                seen_cells.add(cell)
                for nb in glue_out.get(cell, ()):
                    if nb not in seen_bits:
                        seen_bits.add(nb)
                        frontier.append(nb)
        for kind, name, port in srcs:
            src = name
            for b in seen_bits:
                for dkind, dname, dport in feeds.get(b, ()):
                    if dname != src:
                        edges.setdefault((src, dname), set()).add(port)

    # Shared glue -- the read-data mux, the OR of the stalls -- lets any
    # device's output reach any other's input, which is dataflow but not
    # architecture. A block diagram states the spokes: CPU and memory to
    # each device, and each device to the pins it serves.
    world = {g for g, _, _ in WORLD} | {"host"}

    def keep(s, d):
        if s in world or d in world:
            return (s, d) in direct and not (s in world and d in world)
        if "u_cpu" in (s, d):
            return True
        # Memory's only real peer besides the CPU is the video fetch.
        return {s, d} == {"u_mem", "u_vid"}

    edges = {(s, d): p for (s, d), p in edges.items() if keep(s, d)}

    # ---- dot
    lines = [
        "digraph cool8 {",
        '  rankdir=LR; bgcolor="white"; splines=true; nodesep=0.45;'
        ' ranksep=0.9;',
        '  node [fontname="Helvetica" fontsize=11 shape=box'
        ' style="rounded,filled" margin="0.18,0.10"];',
        '  edge [fontname="Helvetica" fontsize=8 color="#666666"'
        ' arrowsize=0.6 fontcolor="#444444"];',
    ]
    used = {n for pair in edges for n in pair}
    for inst in LABEL:
        if inst not in used:
            continue
        title, sub = LABEL[inst]
        lines.append(
            f'  "{inst}" [fillcolor="{FILL[inst]}" label=<<B>{title}</B>'
            f'<BR/><FONT POINT-SIZE="8">{sub}</FONT>>];')
    for group, _, label in WORLD + [("host", "", "iCELink\nhost")]:
        if group in used:
            nice = label.replace("\n", "<BR/>")
            lines.append(f'  "{group}" [shape=box style="filled" '
                         f'fillcolor="#eeeeee" color="#999999" '
                         f'label=<<FONT POINT-SIZE="9">{nice}</FONT>>];')
    for (src, dst), ports in sorted(edges.items()):
        label = ", ".join(sorted(p.lstrip("io_").lstrip("_")
                                 for p in ports)[:3])
        if len(ports) > 3:
            label += ", …"
        lines.append(f'  "{src}" -> "{dst}" [label="{label}"];')
    lines.append("}")

    dot = shutil.which("dot") or r"C:\Program Files\Graphviz\bin\dot.exe"
    fmt = os.path.splitext(args.out)[1].lstrip(".") or "svg"
    subprocess.run([dot, "-T" + fmt, "-o", args.out],
                   input="\n".join(lines).encode(), check=True)
    print("%s: %d blocks, %d edges" % (args.out, len(used), len(edges)))


if __name__ == "__main__":
    main()
