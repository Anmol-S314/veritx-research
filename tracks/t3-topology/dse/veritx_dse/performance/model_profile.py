"""veritx_dse.performance.model_profile — measured compute/memory profile.

Derives per-layer compute durations and memory-operand bytes for a real
model from the data the repo already ships:

  * architecture   `third_party/llmservingsim/configs/model/**/<name>.json`
  * weight bytes   llmservingsim `serving.core.memory_model.calculate_sizes`
                   (the SAME authority the serving simulator uses — never a
                   second weight math), sharded by tp/ep and dtype
  * durations      `third_party/llmservingsim/profiler/perf/<hw>/<model>/
                   <variant>/tp<N>/{attention,dense,moe,per_sequence}.csv`
                   (measured on the recorded hardware; nearest-row lookup)

Absence is ABSENCE, never a guess: a component with no measured row becomes
``None`` with a reason, and a stage whose duration cannot be established is
reported as unavailable rather than filled with a placeholder. See
docs/decisions/compute-memory-intent.md.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from veritx_dse.core.errors import SemanticError
from veritx_dse.model.compute_intent import ComputeSource

class ModelProfileError(ValueError, SemanticError):
    """The profile cannot be established for this model/geometry."""

def _repo_root() -> Path:
    from veritx_dse.core.paths import REPO
    return REPO

def _llmserving_roots() -> tuple[Path, Path]:
    base = _repo_root() / "third_party" / "llmservingsim"
    return base / "configs" / "model", base / "profiler" / "perf"

@dataclass(frozen=True)
class ProfileShape:
    """The serving shape a duration is looked up at (nearest-row)."""

    prefill_chunk: int = 0
    kv_prefill: int = 0
    n_decode: int = 1
    kv_decode: int = 16
    tokens: int = 1
    sequences: int = 1

@dataclass(frozen=True)
class ProfileValue:
    """A measured value with its source, or an explicit absence."""

    value: int | None
    source: str
    reason: str = ""

    @property
    def available(self) -> bool:
        return self.value is not None

#: Profile coverage states. Only PROFILED and MISSING are emitted today:
#: a layer either carries a measured duration or names why it does not.
#: INTERPOLATED / DECLARED / UNSUPPORTED are reserved vocabulary for future
#: producers — nothing may emit them without a producer that defines them,
#: and nothing may extrapolate a MISSING duration into a number.
PROFILE_COVERAGE_STATES = (
    "PROFILED", "INTERPOLATED", "DECLARED", "MISSING", "UNSUPPORTED",
)


@dataclass(frozen=True)
class LayerProfile:
    """One transformer layer's measured compute + memory demand.

    ``duration_ns`` is the sum of the layer's measured components; ``None``
    when ANY required component is unavailable (never a partial sum
    presented as the whole).
    """

    layer_index: int
    kind: str
    duration_ns: int | None
    duration_components: tuple[tuple[str, int | None], ...]
    missing: tuple[str, ...]
    input_bytes: int
    weight_bytes: int
    output_bytes: int
    weight_source: str

    @property
    def coverage(self) -> str:
        """PROFILED when this layer carries a measured duration, else
        MISSING (with the reasons in ``missing``). No other state is
        emitted: interpolation would invent demand."""
        return "PROFILED" if self.duration_ns is not None else "MISSING"

    def to_stage(self, *, stage_id: str, owner: int | None) -> dict[str, Any]:
        return {
            "stage_id": stage_id,
            "duration_ns": self.duration_ns,
            "input_bytes": self.input_bytes,
            "weight_bytes": self.weight_bytes,
            "output_bytes": self.output_bytes,
            "owner": owner,
            "input_loc": "LOCAL",
            "weight_loc": "LOCAL",
            "output_loc": "LOCAL",
        }

@dataclass(frozen=True)
class ModelProfile:
    model: str
    hardware: str
    variant: str
    tp: int
    ep: int
    layers: tuple[LayerProfile, ...]
    weight_source: str = field(default="")
    source: "ComputeSource" = field(
        default_factory=lambda: ComputeSource("unspecified"))

    @property
    def complete(self) -> bool:
        return all(l.duration_ns is not None for l in self.layers)

    @property
    def coverage(self) -> str:
        """PROFILED only when every layer is measured; otherwise MISSING.
        A partial profile never averages out to coverage — the missing
        layers are named by ``missing_layers``."""
        return "PROFILED" if self.complete else "MISSING"

    @property
    def missing_layers(self) -> tuple[int, ...]:
        """Layer indexes without a measured duration, in order."""
        return tuple(l.layer_index for l in self.layers
                     if l.duration_ns is None)

    def to_compute_intent(self, *, participants: int,
                          stage_prefix: str = "layer") -> dict[str, Any]:
        """A v4 ``compute`` block, one stage per layer component.

        Every stage carries the real measured values. ``owner`` places the
        stages over the participant ranks by LONGEST-PROCESSING-TIME-FIRST
        (assign each stage, heaviest first, to the least-loaded rank; ties
        break on rank index so the result is deterministic). LPT keeps the
        makespan within 4/3 of optimal — the earlier index-modulo rule was
        placement-shaped and could leave most ranks with no compute at all.

        The block carries its own provenance (``source``): the numbers are
        DERIVED from measured profiler rows plus a weight calculation, and
        the artifact says so. Unavailable durations are refused, never
        emitted.
        """
        if not self.layers:
            raise ModelProfileError(
                f"profile for {self.model!r} has no layers — refusing to "
                "emit an empty compute block")
        for layer in self.layers:
            if layer.duration_ns is None:
                raise ModelProfileError(
                    f"layer {layer.layer_index} {layer.kind}: duration "
                    f"unavailable ({', '.join(layer.missing)}); refusing to "
                    "emit a stage with an invented duration")

        ranks = max(participants, 1)
        order = sorted(range(len(self.layers)),
                       key=lambda i: (-self.layers[i].duration_ns, i))
        load = [0] * ranks
        owner_of: dict[int, int] = {}
        for i in order:
            rank = min(range(ranks), key=lambda r: (load[r], r))
            owner_of[i] = rank
            load[rank] += self.layers[i].duration_ns

        stages = [
            layer.to_stage(
                stage_id=f"{stage_prefix}{layer.layer_index}_{layer.kind}",
                owner=owner_of[i])
            for i, layer in enumerate(self.layers)]
        return {
            "stages": stages,
            "source": self.source.to_dict(),
        }

def _profiler_dir(model: str, hardware: str, variant: str) -> Path | None:
    _, perf = _llmserving_roots()
    d = perf / hardware / model / variant
    return d if d.is_dir() else None

@lru_cache(maxsize=64)
def _rows(path: str) -> tuple[dict[str, str], ...]:
    with open(path, newline="") as fh:
        return tuple(csv.DictReader(fh))

def _nearest(rows: tuple[dict[str, str], ...], keys: tuple[str, ...],
             want: tuple[int, ...], value_col: str) -> tuple[int, str] | None:
    if not rows:
        return None
    best = min(rows, key=lambda r: sum(
        abs(int(float(r[k])) - v) for k, v in zip(keys, want)))
    us = float(best[value_col])
    src = ",".join(f"{k}={best[k]}" for k in keys)
    return int(round(us * 1000.0)), src

def _dense(prof: Path, tp: int, layer: str, shape: ProfileShape,
           *, optional: bool = False) -> ProfileValue:
    path = prof / f"tp{tp}" / "dense.csv"
    if not path.is_file():
        return ProfileValue(None, f"tp{tp}/dense.csv", "no dense profile")
    rows = tuple(r for r in _rows(str(path)) if r.get("layer") == layer)
    if not rows:
        if optional:
            return ProfileValue(0, f"absent:{layer}", "")
        return ProfileValue(None, f"tp{tp}/dense.csv[{layer}]",
                            f"no row for layer {layer!r}")
    got = _nearest(rows, ("tokens",), (shape.tokens,), "time_us")
    if got is None:
        return ProfileValue(None, f"tp{tp}/dense.csv[{layer}]",
                            f"no row for layer {layer!r}")
    return ProfileValue(got[0], f"tp{tp}/dense.csv[{layer}] {got[1]}")

def _attention(prof: Path, tp: int, shape: ProfileShape) -> ProfileValue:
    path = prof / f"tp{tp}" / "attention.csv"
    if not path.is_file():
        return ProfileValue(None, f"tp{tp}/attention.csv", "no attention profile")
    got = _nearest(_rows(str(path)),
                   ("prefill_chunk", "n_decode", "kv_decode"),
                   (shape.prefill_chunk, shape.n_decode, shape.kv_decode),
                   "time_us")
    if got is None:
        return ProfileValue(None, f"tp{tp}/attention.csv", "empty")
    return ProfileValue(got[0], f"tp{tp}/attention.csv {got[1]}")

def _moe(prof: Path, tp: int, experts: int, shape: ProfileShape
         ) -> ProfileValue:
    path = prof / f"tp{tp}" / "moe.csv"
    if not path.is_file():
        return ProfileValue(
            None, f"tp{tp}/moe.csv",
            f"no MoE profile at tp{tp} (measured only where the file exists)")
    got = _nearest(_rows(str(path)), ("tokens", "activated_experts"),
                   (shape.tokens, experts), "time_us")
    if got is None:
        return ProfileValue(None, f"tp{tp}/moe.csv", "empty")
    return ProfileValue(got[0], f"tp{tp}/moe.csv {got[1]}")

def _calculate_sizes():
    import sys
    base = _repo_root() / "third_party" / "llmservingsim"
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))
    from serving.core.memory_model import calculate_sizes  # noqa: PLC0415
    return calculate_sizes

def _weights(model: str, tp: int, ep: int, is_moe: bool) -> dict[str, int]:
    calc = _calculate_sizes()
    fp = 2
    def w(name: str, parallel: int) -> int:
        return int(calc(model, name, 1, parallel=parallel, fp=fp)[1])
    out = {
        "qkv_proj": w("qkv_proj", tp),
        "o_proj": w("o_proj", tp),
        "layernorm": w("layernorm", tp),
    }
    if is_moe:
        out["moe"] = w("moe", ep)
    else:
        out["gate_up_proj"] = w("gate_up_proj", tp)
        out["down_proj"] = w("down_proj", tp)
    return out

def derive_profile(model: str, *, hardware: str = "RTXPRO6000",
                   variant: str = "bf16", tp: int, ep: int = 1,
                   shape: ProfileShape | None = None) -> ModelProfile:
    """Derive the measured per-layer profile for a real model."""
    shape = shape or ProfileShape()
    config_root, _ = _llmserving_roots()
    configs = list(config_root.rglob(Path(model).name + ".json"))
    if not configs:
        raise ModelProfileError(
            f"no architecture config for {model!r} under {config_root}")
    import json
    arch = json.loads(configs[0].read_text())
    is_moe = "num_experts" in arch or "num_local_experts" in arch
    experts = int(arch.get("num_experts", arch.get("num_local_experts", 0)))
    topk = int(arch.get("num_experts_per_tok", experts or 1))
    layers_n = int(arch["num_hidden_layers"])
    hidden = int(arch["hidden_size"])
    act = hidden * 2

    prof = _profiler_dir(model, hardware, variant)
    weights = _weights(model, tp, ep, is_moe)

    def take(name: str, *, optional: bool = False) -> ProfileValue:
        return _dense(prof, tp, name, shape, optional=optional) if prof \
            else ProfileValue(
                None, "no profiler dir",
                f"no profiler for {model}/{hardware}")

    attn_kernel = _attention(prof, tp, shape) if prof else ProfileValue(
        None, "no profiler dir", "no profiler")
    moe = _moe(prof, tp, topk, shape) if (prof and is_moe) else (
        ProfileValue(None, "n/a", "dense model"))

    out: list[LayerProfile] = []
    for i in range(layers_n):
        comps = [("attention", attn_kernel), ("qkv_proj", take("qkv_proj")),
                 ("o_proj", take("o_proj")),
                 ("rotary_emb", take("rotary_emb", optional=True)),
                 ("qk_norm", take("qk_norm", optional=True))]
        missing = tuple(n for n, v in comps if not v.available)
        dur = None if missing else sum(v.value for _, v in comps)
        out.append(LayerProfile(
            layer_index=i, kind="attention", duration_ns=dur,
            duration_components=tuple((n, v.value) for n, v in comps),
            missing=missing, input_bytes=act,
            weight_bytes=weights["qkv_proj"] + weights["o_proj"],
            output_bytes=act,
            weight_source="calculate_sizes(qkv_proj+o_proj, tp=%d, bf16)" % tp))
        if is_moe:
            m_missing = () if moe.available else (moe.reason,)
            out.append(LayerProfile(
                layer_index=i, kind="moe",
                duration_ns=moe.value if moe.available else None,
                duration_components=(("moe", moe.value),),
                missing=m_missing, input_bytes=act,
                weight_bytes=weights["moe"], output_bytes=act,
                weight_source="calculate_sizes(moe, ep=%d, bf16)" % ep))
        else:
            gu = take("gate_up_proj")
            dn = take("down_proj")
            af = take("act_fn", optional=True)
            f_comps = [("gate_up_proj", gu), ("down_proj", dn), ("act_fn", af)]
            f_missing = tuple(n for n, v in f_comps if not v.available)
            out.append(LayerProfile(
                layer_index=i, kind="dense_ffn",
                duration_ns=None if f_missing else
                sum(v.value for _, v in f_comps),
                duration_components=tuple((n, v.value) for n, v in f_comps),
                missing=f_missing, input_bytes=act,
                weight_bytes=weights["gate_up_proj"] + weights["down_proj"],
                output_bytes=act,
                weight_source="calculate_sizes(gate_up+down, tp=%d, bf16)" % tp))

    return ModelProfile(model=model, hardware=hardware, variant=variant,
                        tp=tp, ep=ep, layers=tuple(out),
                        weight_source="llmservingsim calculate_sizes",
                        source=ComputeSource(
                            kind="derived",
                            detail=(
                                "stage durations = nearest-row profiler CSV "
                                "lookup; operand bytes = parallel-sharded "
                                "weight sizes from llmservingsim "
                                "calculate_sizes + activation size"),
                            reference=(
                                f"llmservingsim calculate_sizes + profiler/"
                                f"{hardware}/{model}/{variant}/tp{tp}")))

__all__ = ["LayerProfile", "ModelProfile", "ModelProfileError",
           "ProfileShape", "ProfileValue", "derive_profile"]
