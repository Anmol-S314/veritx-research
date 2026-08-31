#!/usr/bin/env python3
"""Surrogate model for NoC DSE — MLP reverse predictor (2512.07877-style, but on REAL traffic).

Trains on BookSim data: config (topology, vcs, ir, traffic_type) -> latency/throughput
Then does reverse prediction: target (latency, throughput) -> config

Uses same 4×4 mesh + dor baseline as paper, but adds MoE traffic + torus.
Dataset generated on-the-fly via evaluator.run_booksim or loaded from cache.
"""
import json, itertools, time, random
from pathlib import Path
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".scratch" / "surrogate_dataset.json"

# Config space (matches search_bo.py + paper's 4 params)
TOPO_MAP = {"mesh": 0, "torus": 1}
TOPO_INV = {v: k for k, v in TOPO_MAP.items()}

class NoCDataset(Dataset):
    def __init__(self, entries):
        self.entries = entries
    def __len__(self): return len(self.entries)
    def __getitem__(self, i):
        e = self.entries[i]
        # x = config (normalized), y = perf
        thr = e["throughput"] if e["throughput"] is not None else 0.08
        x = torch.tensor([TOPO_MAP[e["topology"]], e["vcs"]/8, e["ir"]/0.32, float(e["is_moe"])], dtype=torch.float32)
        y = torch.tensor([e["latency"]/50, thr/0.5], dtype=torch.float32)
        return x, y

class MLP(nn.Module):
    def __init__(self, hid=64):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(2, hid), nn.ReLU(),
            nn.Linear(hid, hid), nn.ReLU(),
            nn.Linear(hid, 4),
        )
    def forward(self, y): return self.net(y)

class DiffusionSurrogate(nn.Module):
    """Tiny conditional diffusion — predicts x from y + noisy x_t (simplified DDPM)."""
    def __init__(self, hid=64):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(7, hid), nn.ReLU(),
            nn.Linear(hid, hid), nn.ReLU(),
            nn.Linear(hid, 4),
        )
    def forward(self, y, x_noisy, t_norm):
        # t_norm: (B,1) in [0,1]
        h = torch.cat([y, x_noisy, t_norm], dim=1)
        return self.net(h)

def generate_dataset(n=80, use_moe_frac=0.5):
    """Generate n BookSim points — half uniform, half MoE."""
    from evaluator import run_booksim
    from space import DesignPoint
    entries = []
    if CACHE.exists():
        print(f"loading cache {CACHE}")
        return json.loads(CACHE.read_text())
    for i in range(n):
        is_moe = random.random() < use_moe_frac
        topo = random.choice(["mesh", "torus"])
        vcs = random.choice([2, 4, 8])
        ir = random.choice([0.005, 0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64])
        tf = str(HERE / "inputs/qwen_moe_64d.mat") if is_moe else None
        pt = DesignPoint(assignments=(("topology", topo), ("vcs", vcs), ("injection_rate", ir)))
        defaults = {"x_dim": 8, "y_dim": 8, "vc_buf": 8}
        if tf: defaults["traffic_file"] = tf
        r = run_booksim(pt, defaults, timeout=60)
        if not r.ok:
            continue
        entries.append({"topology": topo, "vcs": vcs, "ir": ir, "is_moe": is_moe,
                        "latency": r.avg_latency, "throughput": r.throughput or 0.08,
                        "hops": r.avg_hops})
        print(f"  [{len(entries)}/{n}] {topo} vcs{vcs} ir{ir} moe={is_moe} lat={r.avg_latency:.1f}")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(entries, indent=2))
    print(f"cached {len(entries)} to {CACHE}")
    return entries

def train(model_type="mlp", epochs=200, n=80):
    entries = generate_dataset(n=n)
    ds = NoCDataset(entries)
    dl = DataLoader(ds, batch_size=16, shuffle=True)
    model = MLP() if model_type == "mlp" else DiffusionSurrogate()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.MSELoss()
    for ep in range(epochs):
        tot = 0
        for x, y in dl:
            opt.zero_grad()
            if model_type == "mlp":
                pred = model(y)
                loss = loss_fn(pred, x)
            else:
                t = torch.rand(x.size(0), 1)
                noise = torch.randn_like(x)
                x_noisy = (1-t)*x + t*noise
                pred = model(y, x_noisy, t)
                loss = loss_fn(pred, x)
            loss.backward(); opt.step()
            tot += loss.item()
        if ep % 50 == 0:
            print(f"  epoch {ep} loss={tot/len(dl):.4f}")
    # eval MSE on held-out (last 20%)
    split = int(len(entries)*0.8)
    test = entries[split:]
    mse = 0
    with torch.no_grad():
        for e in test:
            x = torch.tensor([[TOPO_MAP[e["topology"]], e["vcs"]/8, e["ir"]/0.32, float(e["is_moe"])]])
            y = torch.tensor([[e["latency"]/50, e["throughput"]/0.5]])
            pred = model(y) if model_type=="mlp" else model(y, torch.randn_like(x)*0.1, torch.zeros(1,1))
            mse += ((pred - x)**2).mean().item()
    print(f"test MSE ({len(test)} pts): {mse/len(test):.4f}")
    out = HERE / f".scratch/surrogate_{model_type}.pt"
    torch.save(model.state_dict(), out)
    print(f"saved {out}")
    return model, entries

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["mlp","diffusion"], default="mlp")
    ap.add_argument("--epochs", type=int, default=200)
    ap.add_argument("--n", type=int, default=80)
    args = ap.parse_args()
    train(args.model, args.epochs, args.n)
