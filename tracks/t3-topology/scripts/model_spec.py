"""HF config.json -> ModelSpec (plan.md Section 6, step 1)."""
import json
from ir import ModelSpec


def load_model_spec(config_path, seq_len: int, dtype_bytes: int = 2) -> ModelSpec:
    """seq_len and dtype_bytes aren't in a HF config.json (they're runtime /
    dtype choices, not architecture), so they're supplied by the caller."""
    with open(config_path) as f:
        cfg = json.load(f)

    hidden_size = cfg["hidden_size"]
    num_heads = cfg["num_attention_heads"]
    num_kv_heads = cfg.get("num_key_value_heads", num_heads)
    head_dim = cfg.get("head_dim", hidden_size // num_heads)

    ffn = cfg.get("intermediate_size")
    if ffn is None:
        raise KeyError("config.json is missing 'intermediate_size' (FFN width).")

    num_layers = cfg.get("num_hidden_layers")
    if num_layers is None:
        raise KeyError("config.json is missing 'num_hidden_layers'.")

    return ModelSpec(
        hidden_size=hidden_size,
        num_heads=num_heads,
        num_kv_heads=num_kv_heads,
        head_dim=head_dim,
        ffn_intermediate_size=ffn,
        seq_len=seq_len,
        num_layers=num_layers,
        dtype_bytes=dtype_bytes,
    )