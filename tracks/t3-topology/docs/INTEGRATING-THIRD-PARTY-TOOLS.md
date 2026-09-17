# Integrating Third-Party Tools

How to add new simulators, trace generators, or analysis tools to the VeritX repo.

## Directory Structure

The repo has two places for third-party tools. They serve different purposes:

```
veritx-research/
  third_party/          Tools we EDIT directly (our fork)
    booksim2/           BookSim2 NoC simulator (we maintain veritx extensions)
    timeloop/           Timeloop energy model

  serving/              Tools we VENDOR from upstream (read-only fork)
    astra-sim/          ASTRA-sim multi-die simulator
    LLMServingSim/      Traffic trace generator
    results/            Research data
```

### When to use which

| Scenario | Where | Why |
|----------|-------|-----|
| We modify the source (add features, fix bugs) | `third_party/` | We own the fork, we edit it |
| We vendor upstream as-is (build against it) | `serving/` | Upstream may change, we pin a version |
| We need a C/C++ simulation engine | `third_party/` | Direct access to source for debugging |
| We need a Python tool or trace generator | `serving/` | Usually upstream, less modification |
| We need a library we link against | `third_party/` | Build system integration |

## Adding a Tool to third_party/

Use this when you need to modify the source (add VeritX extensions, fix bugs).

### Step 1: Create the directory

```bash
mkdir -p third_party/my-tool/src
cd third_party/my-tool
```

### Step 2: Copy or clone the source

```bash
# Option A: Clone from upstream
git clone https://github.com/upstream/my-tool.git src/

# Option B: Copy specific files
cp /path/to/my-tool/src/*.cpp src/
cp /path/to/my-tool/src/*.hpp src/
```

### Step 3: Add METADATA.json

Track what version you pinned:

```json
{
  "name": "my-tool",
  "version": "1.2.3",
  "upstream": "https://github.com/upstream/my-tool",
  "pin": "abc1234",
  "pin_date": "2026-08-31",
  "notes": "Added VeritX trace replay extension"
}
```

### Step 4: Add to paths.py

Edit `veritx_dse/paths.py`:

```python
# Key directories
MY_TOOL_DIR = REPO / "third_party" / "my-tool" / "src"

# Key binaries
MY_TOOL_BIN = MY_TOOL_DIR / "my-tool"
```

### Step 5: Add a Makefile or build script

```bash
# third_party/my-tool/src/Makefile
CXX = g++
CXXFLAGS = -O3 -std=c++17
SRCS = $(wildcard *.cpp)
OBJS = $(SRCS:.cpp=.o)

my-tool: $(OBJS)
	$(CXX) $(CXXFLAGS) -o $@ $^

clean:
	rm -f *.o my-tool
```

### Step 6: Add .gitignore

```gitignore
# third_party/my-tool/src/.gitignore
my-tool
*.o
*.d
```

### Step 7: Wire into the CLI (optional)

If you want a CLI command that uses this tool:

```python
# In cli.py, add a command handler:
def cmd_my_tool(ctx: Ctx, args):
    """Run my-tool analysis."""
    from veritx_dse.paths import MY_TOOL_BIN
    import subprocess
    r = subprocess.run(
        [str(MY_TOOL_BIN), args.trace],
        capture_output=True, text=True, timeout=300
    )
    # Parse output, print results...
```

### Step 8: Document it

Add a section to `README.md`:

```markdown
## N. my-tool

Brief description. What it does, why we use it.

### Build
\`\`\`bash
cd third_party/my-tool/src && make -j$(nproc)
\`\`\`

### Usage
\`\`\`bash
veritx my-tool --trace runs/traces/my.trace
\`\`\`
```

## Adding a Tool to serving/

Use this when you vendor upstream as-is (don't modify the source).

### Step 1: Create the directory

```bash
mkdir -p serving/my-tool
```

### Step 2: Copy the source

```bash
# Copy from upstream or a working directory
cp -r /path/to/my-tool/* serving/my-tool/
```

### Step 3: Add METADATA.json (optional but recommended)

```json
{
  "name": "my-tool",
  "version": "2.0.1",
  "upstream": "https://github.com/upstream/my-tool",
  "pin": "def5678",
  "pin_date": "2026-08-31",
  "notes": "Vendored for trace generation"
}
```

### Step 4: Add to paths.py

```python
# Key directories
MY_TOOL_DIR = REPO / "serving" / "my-tool"

# Key binaries (if applicable)
MY_TOOL_BIN = MY_TOOL_DIR / "bin" / "my-tool"
```

### Step 5: Add .gitignore for build artifacts

Add patterns to `serving/.gitignore`:

```gitignore
# my-tool build artifacts
my-tool/build/
my-tool/*.o
my-tool/*.a
```

### Step 6: Update serving/README.md

Document what it is and how to build it.

## Syncing Source Between Locations

Some tools appear in multiple places (e.g., BookSim2 in `third_party/` and inside ASTRA-sim). Use a sync script:

```bash
# third_party/my-tool/sync_to_vendor.sh
#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

SRC="${SCRIPT_DIR}/src"
DST="${REPO_ROOT}/serving/vendor-tool/my-tool/src"

# Sync source files only (not binaries, not build artifacts)
for f in "$SRC"/*.cpp "$SRC"/*.hpp "$SRC"/*.h; do
    [ -f "$f" ] || continue
    rel="${f#$SRC/}"
    if ! diff -q "$f" "$DST/$rel" > /dev/null 2>&1; then
        cp "$f" "$DST/$rel"
        echo "  SYNCED: $rel"
    fi
done

echo "Done. Rebuild vendor tool to pick up changes."
```

## Build Artifact Management

### What to .gitignore

| Pattern | What it catches |
|---------|----------------|
| `**/build/` | CMake build directories |
| `**/build_debug/` | Debug builds |
| `**/CMakeCache.txt` | CMake cache |
| `**/CMakeFiles/` | CMake generated files |
| `**/*.o` | Object files |
| `**/*.a` | Static libraries |
| `**/*.so` | Shared libraries |
| `**/__pycache__/` | Python bytecode |
| `**/*.pyc` | Python compiled files |

### Where to put .gitignore entries

- **Root `.gitignore`**: Catches repo-wide patterns (Python, IDE, OS files)
- **`serving/.gitignore`**: Catches build artifacts in vendored tools
- **`third_party/*/src/.gitignore`**: Catches build artifacts in our forks

### Disk cleanup (not in git)

Build artifacts on disk but not in git can waste space. Clean them:

```bash
# Find build artifacts
find serving -type d -name "build" -exec du -sh {} \;
find serving -type d -name "build_debug" -exec du -sh {} \;

# Remove them
find serving -type d -name "build_debug" -exec rm -rf {} +
find serving -type d -name "build" -exec rm -rf {} +
```

## Path Resolution

All tool paths are defined in `veritx_dse/paths.py`. This is the SINGLE source of truth.

### How it works

```python
# paths.py discovers repo root from package location:
# veritx_dse/ lives at: <repo>/tracks/t3-topology/dse/veritx_dse/
# So 4 levels up = repo root

_THIS_DIR = Path(__file__).resolve().parent          # veritx_dse/
_DSE_DIR = _THIS_DIR.parent                          # dse/
_T3_DIR = _DSE_DIR.parent                            # t3-topology/
_TRACKS_DIR = _T3_DIR.parent                         # tracks/
REPO = _TRACKS_DIR.parent                            # veritx-research/
```

### Adding a new path

1. Add the path constant to `paths.py`
2. Import it where needed: `from veritx_dse.paths import MY_TOOL_BIN`
3. Add a check in `_verify()` if it's critical

### Why not use relative paths in each module

Because every module would have its own fragile `parent.parent.parent` chain.
When you move a file, all those chains break. One place, one definition.

## Complete Example: Adding Noxim

Let's say you want to add Noxim (SystemC NoC simulator) as an alternative to BookSim2.

### 1. Directory structure

```
third_party/noxim/
  src/                    source code
    Makefile
    .gitignore
  METADATA.json
```

### 2. paths.py

```python
NOXIM_DIR = REPO / "third_party" / "noxim" / "src"
NOXIM_BIN = NOXIM_DIR / "noxim"
```

### 3. CLI command

```python
def cmd_evaluate_noxim(ctx: Ctx, args):
    """Evaluate topology using Noxim."""
    from veritx_dse.paths import NOXIM_BIN
    import subprocess, yaml

    # Generate Noxim config from trace
    config = _generate_noxim_config(args.trace)
    config_path = RUNS_DIR / "noxim" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.dump(config))

    # Run Noxim
    r = subprocess.run(
        [str(NOXIM_BIN), "-config", str(config_path)],
        capture_output=True, text=True, timeout=300
    )

    # Parse output
    latency = _parse_noxim_output(r.stdout)
    ok(ctx, f"Noxim latency: {latency}c")
```

### 4. Wire into CLI

In `cli.py`, add the subparser:

```python
p_noxim = subs.add_parser("noxim", help="Noxim evaluation")
p_noxim.add_argument("--trace", required=True)
p_noxim.add_argument("--config", help="Noxim YAML config")
p_noxim.set_defaults(func=cmd_evaluate_noxim)
```

### 5. .gitignore

```gitignore
# third_party/noxim/src/.gitignore
noxim
*.o
*.d
*.a
```

### 6. README section

```markdown
## N. Noxim Integration

Noxim is a cycle-accurate SystemC NoC simulator. We use it as an alternative
to BookSim2 for validation.

### Build
\`\`\`bash
cd third_party/noxim/src && make -j$(nproc)
\`\`\`

### Usage
\`\`\`bash
veritx evaluate noxim --trace runs/traces/my.trace
\`\`\`
```

## Common Pitfalls

### 1. Forgetting to rebuild after source changes

```bash
# Always rebuild after editing third_party/ source
cd third_party/booksim2/src && make -j$(nproc)
```

### 2. Using the wrong binary

The CLI uses `BOOKSIM_BIN` from `paths.py`. If you built in a different directory,
the CLI won't find it. Always build in `third_party/*/src/`.

### 3. Build artifacts in git

If you see `.o`, `.a`, `.so` files in `git status`, your `.gitignore` is missing
a pattern. Check `serving/.gitignore` and `third_party/*/src/.gitignore`.

### 4. Path resolution breaks when moving files

All paths go through `paths.py`. If you move `veritx_dse/`, update the number
of `.parent` calls in `paths.py`. Everything else stays the same.

### 5. Disk space exhaustion

Build artifacts can eat GBs. Check periodically:
```bash
du -sh serving/*/build* third_party/*/build* 2>/dev/null
```

## Checklist for New Tool Integration

- [ ] Directory created (`third_party/` or `serving/`)
- [ ] Source copied/cloned
- [ ] `METADATA.json` added with version pin
- [ ] `.gitignore` added for build artifacts
- [ ] `paths.py` updated with new path constants
- [ ] `_verify()` updated if path is critical
- [ ] CLI command added (if applicable)
- [ ] `serving/.gitignore` updated (if in serving/)
- [ ] `README.md` section added with build + usage instructions
- [ ] `serving/README.md` updated (if in serving/)
- [ ] Tests added for the new command
- [ ] Build verified: tool compiles and runs
- [ ] End-to-end test: CLI command produces correct output
