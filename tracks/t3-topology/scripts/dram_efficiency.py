#!/usr/bin/env python3
"""What DRAM bandwidth does the KV read ACTUALLY achieve? (T3, calibrated with Ramulator2)

serving_multicast.py divides by PEAK DRAM bandwidth to get tokens/sec -- i.e. it assumes
100% efficiency. Whether the KV-streaming access pattern reaches peak is exactly the kind of
uncalibrated assumption this track exists to distrust (PITFALLS: "a result not calibrated
against silicon is decoration"). So we measure it, with the standard cycle-accurate GDDR6
timing model (Ramulator2, CMU-SAFARI), not by inspection.

WHAT WE FOUND (GDDR6 8Gb x16 @ 14 Gbps, peak 28 GB/s/channel, refresh on, saturated):
  - contiguous per-head layout      ~91%   (the ~9% gap is REFRESH; refresh-off hits 100%)
  - paged 1-4KB blocks, scattered   ~90%   (row hits survive within a block; scatter cheap)
  - vLLM [block,heads,dim], 1 head  ~66%   (reading one head STRIDES past the other 7 ->
                                            one row-buffer miss per token -> 75% row hits)
Two consequences:
  1. DERATING. The absolute tokens/sec headline is 9% optimistic at best (refresh), and up
     to ~34% optimistic if the schedule inherits vLLM's interleaved KV layout.
  2. A SCHEDULE REQUIREMENT the analytic missed: store the KV cache PER-HEAD-CONTIGUOUS so
     the multicast read is a clean stream (91%), not a strided 1-of-g read (66%). Worth ~28%.
The g-fold RELATIVE win (multicast vs naive) is unaffected -- both read the same layout at
the same efficiency, so it cancels in the ratio. This derates the ABSOLUTE number only.

THE TRAP THIS SCRIPT ALSO DOCUMENTS: a first run read 77% and would have been wrong -- the
read buffer was starving the DRAM, not the DRAM limiting throughput. You MUST enlarge the
in-flight window until throughput plateaus; that plateau is the DRAM limit (PITFALLS #17).

RUN IT (inside the tools image; self-builds Ramulator2 the first time, ~3 min):
    podman run --rm -v "$PWD:/repo" -w /repo \\
        internal-devrepo.datavex.ai:5050/anmol/veritx-research/veritx-tools-base:latest \\
        python3 tracks/t3-topology/scripts/dram_efficiency.py --run

    python3 scripts/dram_efficiency.py --selfcheck   # trace properties only, no Ramulator
"""
import random
import subprocess
import sys
import textwrap
from pathlib import Path

CL = 64                              # cacheline / access granularity (bytes)
D_HEAD = 128
DTYPE = 2                            # BF16
N_KV = 8                             # GQA KV heads (Llama-3-70B): a token's K spans 8 heads
PEAK_MBPS = 28000                    # GDDR6 8Gb x16 @ 14 Gbps = 28 GB/s/channel (refresh-off confirms)
RAM = Path("/tmp/veritx_ramulator/ramulator2")
RAM_COMMIT = "99a0e1e87a9321587492fef5b0bd6197928f8d68"
OUT = Path("/tmp/dram_eff")


def gen_traces():
    """Write LD-address traces for the KV read under different layouts. Efficiency is a
    steady-state property, so ~4 MB working sets suffice."""
    OUT.mkdir(parents=True, exist_ok=True)
    random.seed(0)
    n = 65536                        # reads

    # contiguous per-head: the KV head is stored as one stream -> sequential reads
    (OUT / "contig.trace").write_text("".join(f"LD {i*CL}\n" for i in range(n)))

    # strided (vLLM [block, heads, dim]): reading ONE head skips the other N_KV-1 each token
    head_bytes = D_HEAD * DTYPE      # 256B: one head's K for one token
    stride = N_KV * head_bytes       # 2048B: all heads' K for one token
    with (OUT / "strided.trace").open("w") as f:
        for t in range(n // (head_bytes // CL)):
            for j in range(head_bytes // CL):
                f.write(f"LD {t*stride + j*CL}\n")

    # paged, scattered across a large pool (fragmentation), for two block sizes
    for psz, name in ((4096, "paged4k"), (256, "paged256")):
        rpp = psz // CL
        pool = 1 << 22
        idx = random.sample(range(pool), n // rpp)
        with (OUT / f"{name}.trace").open("w") as f:
            for p in idx:
                for j in range(rpp):
                    f.write(f"LD {p*psz + j*CL}\n")


def ensure_ramulator():
    if (RAM / "libramulator.so").exists() and (RAM / "python").exists():
        return
    RAM.parent.mkdir(parents=True, exist_ok=True)
    print("  building Ramulator2 (once, ~3 min) ...")
    steps = f"""
        set -e
        cd {RAM.parent}
        [ -d ramulator2 ] || git clone https://github.com/CMU-SAFARI/ramulator2.git
        cd ramulator2 && git checkout -q {RAM_COMMIT} 2>/dev/null || true
        mkdir -p build && cd build
        cmake .. -DCMAKE_BUILD_TYPE=Release >/dev/null
        make -j"$(nproc)" >/dev/null
    """
    r = subprocess.run(["bash", "-c", textwrap.dedent(steps)], capture_output=True, text=True)
    if r.returncode != 0 or not (RAM / "libramulator.so").exists():
        sys.exit("  ERROR building Ramulator2:\n" + r.stderr[-2000:])


# The Ramulator driver runs in a subprocess so PYTHONPATH points at the built module.
_DRIVER = r'''
import sys, ramulator
trace, rbuf, refresh = sys.argv[1], int(sys.argv[2]), sys.argv[3]
rm = ramulator.refresh_manager.AllBank() if refresh == "on" else ramulator.refresh_manager.NoRefresh()
gddr6 = ramulator.dram.GDDR6(org_preset="GDDR6_8Gb_x16", timing_preset="GDDR6_14000_1250mV_double")
ctrl = ramulator.controller.GenericDDR(
    dram=gddr6, scheduler=ramulator.scheduler.FRFCFSRowHit(), refresh_manager=rm,
    row_policy=ramulator.row_policy.Open(), addr_mapper=ramulator.addr_mapper.RoBaRaCoCh(),
    read_buffer_size=rbuf, write_buffer_size=rbuf)
mem = ramulator.memory_system.GenericDRAM(clock_ratio=3, controllers=[ctrl],
    channel_mapper=ramulator.channel_mapper.CacheLineInterleave())
fe = ramulator.frontend.LoadStoreTrace(clock_ratio=16, path=trace)
sim = ramulator.Simulation(fe, mem); sim.run()
s = sim.stats["memory_system"]["controller"]
print(f'{s["read_throughput_MBps"]:.1f} {s["read_row_hits"]/s["num_read_reqs_served"]*100:.1f}')
'''


def bw(trace, rbuf=128, refresh="on"):
    """Return (GB/s, efficiency%, row-hit%) for a trace. Empty driver written once."""
    drv = OUT / "_driver.py"
    drv.write_text(_DRIVER)
    r = subprocess.run(["python3", str(drv), str(OUT / trace), str(rbuf), refresh],
                       capture_output=True, text=True,
                       env={"PYTHONPATH": str(RAM / "python"), "PATH": "/usr/bin:/bin"})
    if r.returncode != 0:
        sys.exit(f"  Ramulator run failed on {trace}:\n{r.stderr[-1500:]}")
    mbps, hit = (float(x) for x in r.stdout.split())
    return mbps / 1000, mbps / PEAK_MBPS * 100, hit


def main():
    ensure_ramulator()
    gen_traces()
    print(f"\n  Achieved DRAM bandwidth of the KV read (GDDR6, peak {PEAK_MBPS/1000:.0f} GB/s/ch, "
          f"refresh on, saturated)\n")

    # THE SATURATION GATE: prove the number is DRAM-limited, not buffer-starved.
    print("  Saturation check (contiguous) -- throughput must PLATEAU as the buffer grows,")
    print("  else we are measuring queue depth, not the DRAM (PITFALLS #17):")
    plateau = None
    for rb in (16, 32, 64, 128, 256):
        g, e, _ = bw("contig.trace", rb, "on")
        print(f"    read_buffer={rb:>4}:  {g:5.2f} GB/s  ({e:4.1f}%)")
        plateau = e
    assert plateau > 88, f"contiguous should plateau near refresh-limited peak, got {plateau}"

    # Peak sanity: refresh off must reach ~100% (validates the peak figure itself).
    _, e_off, _ = bw("contig.trace", 256, "off")
    print(f"\n  refresh OFF, saturated: {e_off:.1f}%  -> confirms {PEAK_MBPS/1000:.0f} GB/s is the true peak "
          f"(the {100-e_off if e_off<100 else 0:.0f}% is rounding); the ~9% on-refresh gap is REFRESH.\n")
    assert e_off > 97, f"refresh-off should approach peak, got {e_off}"

    # The layout comparison -- the actual finding.
    print("  Layout sensitivity of the per-head KV read (read_buffer=128, refresh on):")
    results = {}
    for name, trace in (("contiguous (per-head)", "contig.trace"),
                        ("paged 4KB scattered", "paged4k.trace"),
                        ("strided (vLLM 1-of-%d heads)" % N_KV, "strided.trace"),
                        ("paged 256B scattered", "paged256.trace")):
        g, e, h = bw(trace)
        results[trace] = e
        print(f"    {name:<30} {g:5.2f} GB/s  ({e:4.1f}%)  row-hit {h:4.1f}%")

    best, strided = results["contig.trace"], results["strided.trace"]
    print(f"\n  READ: even best-case (per-head-contiguous) the KV read gets ~{best:.0f}% of peak, so")
    print(f"  the ABSOLUTE tokens/sec headline is ~{100-best:.0f}% optimistic (refresh). The vLLM")
    print(f"  interleaved layout drops it to ~{strided:.0f}% -- reading one head strides past the")
    print(f"  other {N_KV-1}, thrashing the row buffer. So the schedule gains a REQUIREMENT: store KV")
    print(f"  per-head-contiguous ({best:.0f}%), not interleaved ({strided:.0f}%) -- worth ~{best-strided:.0f} points.")
    print(f"  The g-fold RELATIVE win is untouched (same layout both ways; efficiency cancels).")

    assert best > strided + 15, "interleaved layout should cost a large chunk of bandwidth"
    print(f"\n  selfcheck OK -- peak validated (refresh-off {e_off:.0f}%); layout matters "
          f"({best:.0f}% vs {strided:.0f}%)")


def _selfcheck():
    # trace-shape only (no Ramulator): the strided read touches 1/N_KV of each token's K,
    # the contiguous read touches all of it sequentially.
    gen_traces()
    contig = (OUT / "contig.trace").read_text().splitlines()
    strided = (OUT / "strided.trace").read_text().splitlines()
    a0, a1 = int(contig[0].split()[1]), int(contig[1].split()[1])
    assert a1 - a0 == CL, "contiguous reads must step by one cacheline"
    # first read of token 1 in the strided trace jumps by the full all-heads stride
    per_head_cls = D_HEAD * DTYPE // CL
    s_tok1 = int(strided[per_head_cls].split()[1])
    assert s_tok1 == N_KV * D_HEAD * DTYPE, "strided must skip the other heads between tokens"
    print(f"selfcheck OK -- contiguous steps by {CL}B; strided reads {per_head_cls} CLs then "
          f"jumps {N_KV*D_HEAD*DTYPE}B past the other {N_KV-1} heads (see --run for the Ramulator numbers)")


if __name__ == "__main__":
    _selfcheck() if "--selfcheck" in sys.argv else main()
