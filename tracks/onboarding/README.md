# Onboarding — Toolchain Validation

Verify that the CI container has all tools installed correctly.

## What This Tests

- Booksim 2.0 compiles and runs a basic mesh
- Python toolchain (numpy, matplotlib, pandas, seaborn, jupyter)
- Accelergy import
- Yosys + SymbiYosys + CBMC + z3 (formal tools)
- Write access (git push triggers your first green CI badge)

## Usage

```
git checkout -b onboarding/verify-tools
git push -u origin onboarding/verify-tools
```

Open a PR, check CI. If the **onboarding** cell is green, your account works.

## Files

| File | Purpose |
|------|---------|
| `scripts/sanity_test.py` | Validates all tool versions |

## Expected CI Output

```
  ✓ Booksim OK (mesh 4x4 latency = 50.2)
  ✓ Yosys OK (0.66+)
  ✓ CBMC OK (6.10.0)
  ✓ SymbiYosys OK
  ✓ Python OK
  → results/sanity_result.json
```

## Next Steps

Once onboarding passes, start your assigned track:
- [T2 — Deadlock](../t2-deadlock/README.md)
- [T3 — Topology](../t3-topology/README.md)
- [T4 — Formal](../t4-formal/README.md)
