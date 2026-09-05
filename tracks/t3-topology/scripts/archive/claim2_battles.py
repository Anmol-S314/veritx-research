#!/usr/bin/env python3
"""Definitive Claim-2 test: per-window BookSim battles UNDER LOAD.
For each real LLMServingSim window (38 total, CHAT+AGENTIC), run all four
topologies at matched IRs and record mean latency. Reveals whether phase
windows produce different rankings / utilization stress."""
import os, glob, pickle, subprocess, statistics
from pathlib import Path

BS = str(Path(__file__).resolve().parent.parent.parent.parent / "third_party/booksim2/src")
WIN = pickle.load(open('/tmp/regime_windows.pkl','rb'))
TOPOS = {
    'gec':    ("topology = gec; k = 8; c = 1; o = 7; d = 1; mesh = 0;\nrouting_function = dor;", 0),
    'HYB':    ("topology = anynet; network_file = hybrid_v2_priced.anynet;\nrouting_function = min;", 1),
    'BFLY':   ("topology = anynet; network_file = bfly_priced.anynet;\nrouting_function = min;", 1),
    'mesh':   ("topology = mesh; k = 8; n = 2;\nrouting_function = dor;", 1),
}
IRS = [0.02, 0.05, 0.10]

os.chdir(BS)
results = {}
for regime in ['CHAT','AGENTIC']:
    mats = WIN[regime]['mats']
    print(f"=== {regime}: {len(mats)} windows ===", flush=True)
    results[regime] = []
    for wi, M in enumerate(mats):
        mfile = f"/tmp/win_{regime}_{wi}.matrix"
        open(mfile,'w').write('\n'.join(' '.join(f'{v:.6e}' for v in row) for row in M)+'\n')
        row = {'window': wi}
        for name,(topo,wfc) in TOPOS.items():
            lat = None
            for ir in IRS:
                cfg = f"bb_w{wi}_{name}.cfg"
                open(cfg,'w').write(f"""{topo}
num_vcs = 2; vc_buf_size = 8; wait_for_tail_credit = {wfc};
traffic = matrix({mfile});
packet_size = 4; sim_type = latency; injection_rate = {ir}; seed = 42; use_noc_latency = 1;
""")
                try:
                    r = subprocess.run([f"timeout 60 ./booksim {cfg}"], shell=True,
                                       capture_output=True, text=True, timeout=70)
                    last=None
                    for line in r.stdout.split("\n"):
                        if "Packet latency average" in line:
                            last = line.split("=")[1].strip().split("(")[0].strip()
                    if last is not None:
                        v=float(last)
                        # saturated if unstable or huge
                        if 'unstable' in r.stdout or v > 200:
                            lat = f"SAT@{ir}"; break
                        lat = v
                except subprocess.TimeoutExpired:
                    lat = f"TIMEOUT@{ir}"; break
                finally:
                    os.remove(cfg)
            row[name] = lat
        results[regime].append(row)
        print(f"  win{wi}: " + " | ".join(f"{n}={row[n]}" for n in TOPOS), flush=True)

pickle.dump(results, open('/tmp/claim2_battle.pkl','wb'))
print("saved /tmp/claim2_battle.pkl")
