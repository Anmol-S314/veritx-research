# Track-local model config overlay

This directory holds model configs that are tracked with t3-topology instead of
being vendored under `third_party/llmservingsim/configs/model`. The deployment
builder scans both trees; a config is addressed by its path relative to its
model base without `.json`, so the file here is
`deepseek-ai/DeepSeek-V3.2-Exp`.

## `deepseek-ai/DeepSeek-V3.2-Exp.json`

| Field | Value |
| --- | --- |
| Upstream repository | LLMServingSim (https://github.com/KAIST-AILab/LLMServingSim) |
| Upstream commit | `560ce8210f8a1ab0be67a7ae66cce085ea990051` |
| Upstream path | `configs/model/deepseek-ai/DeepSeek-V3.2-Exp.json` |
| Retrieved | 2026-11-05 |
| Scope | Full checkpoint config (61 layers, 256 routed experts, top-8) |

This is the full DeepSeek-V3.2-Exp checkpoint config. It is not the 16-layer /
64-expert diagnostic config, which is intentionally not tracked.
