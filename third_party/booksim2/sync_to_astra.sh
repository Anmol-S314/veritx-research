#!/bin/bash
# sync_to_astra.sh — Copy canonical booksim2 source into ASTRA-sim's internal copy.
#
# ASTRA-sim has its own vendored copy of the booksim2 fork at:
#   serving/astra-sim/extern/network_backend/booksim2/booksim2/src/
#
# We maintain the canonical copy at:
#   third_party/booksim2/src/
#
# This script keeps them in sync. Run after editing any bookSim2 source file.
#
# Usage:
#   third_party/booksim2/sync_to_astra.sh          # sync + verify
#   third_party/booksim2/sync_to_astra.sh --check   # verify only (dry run)
#   third_party/booksim2/sync_to_astra.sh --force    # sync even if identical

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

SRC="${SCRIPT_DIR}/src"
DST="${REPO_ROOT}/serving/astra-sim/extern/network_backend/booksim2/booksim2/src"

# Files to sync (source code only — no binaries, no build artifacts)
SYNC_PATTERNS=(
    "*.cpp"
    "*.hpp"
    "*.h"
    "*.c"
    "Makefile"
)

# Files to SKIP (exist in third_party but shouldn't be in astra-sim)
SKIP_FILES=(
    "booksim"          # compiled binary
    "libveritx_embed.a" # compiled library
)

# Files that exist ONLY in astra-sim (don't delete them)
# snakeroute.cpp/hpp — kept in astra-sim only

CHECK_ONLY=false
FORCE=false
for arg in "$@"; do
    case "$arg" in
        --check) CHECK_ONLY=true ;;
        --force) FORCE=true ;;
        --help|-h)
            echo "Usage: $0 [--check] [--force]"
            echo "  --check   Dry run: show what would sync"
            echo "  --force   Sync even if files are identical"
            exit 0
            ;;
    esac
done

if [ ! -d "$SRC" ]; then
    echo "ERROR: Source directory not found: $SRC"
    exit 1
fi

if [ ! -d "$DST" ]; then
    echo "ERROR: Destination directory not found: $DST"
    echo "  Is ASTRA-sim vendored at serving/astra-sim/?"
    exit 1
fi

# Collect files to sync
FILES_TO_SYNC=()
for pattern in "${SYNC_PATTERNS[@]}"; do
    while IFS= read -r -d '' file; do
        rel="${file#$SRC/}"
        # Skip binaries and libraries
        skip=false
        for skip_name in "${SKIP_FILES[@]}"; do
            if [ "$rel" = "$skip_name" ]; then
                skip=true
                break
            fi
        done
        $skip && continue
        FILES_TO_SYNC+=("$rel")
    done < <(find "$SRC" -name "$pattern" -type f -print0 2>/dev/null)
done

# Check for differences
DIFFS=0
NEW_FILES=0
CHANGED_FILES=0

for rel in "${FILES_TO_SYNC[@]}"; do
    src_file="$SRC/$rel"
    dst_file="$DST/$rel"
    
    if [ ! -f "$dst_file" ]; then
        echo "  NEW:    $rel"
        NEW_FILES=$((NEW_FILES + 1))
        DIFFS=$((DIFFS + 1))
    elif ! diff -q "$src_file" "$dst_file" > /dev/null 2>&1; then
        echo "  CHANGED: $rel"
        CHANGED_FILES=$((CHANGED_FILES + 1))
        DIFFS=$((DIFFS + 1))
    fi
done

# Check for files only in astra-sim (informational)
for rel in "${FILES_TO_SYNC[@]}"; do
    if [ ! -f "$SRC/$rel" ] && [ -f "$DST/$rel" ]; then
        echo "  ASTRA-ONLY: $rel (not in third_party)"
    fi
done

if [ "$DIFFS" -eq 0 ]; then
    echo "✓ All ${#FILES_TO_SYNC[@]} files are in sync."
    exit 0
fi

echo ""
echo "Found $DIFFS differences ($NEW_FILES new, $CHANGED_FILES changed) across ${#FILES_TO_SYNC[@]} files."

if $CHECK_ONLY; then
    echo "Dry run — no files copied. Run without --check to sync."
    exit 0
fi

# Sync
echo ""
echo "Syncing $SRC → $DST ..."
COPIED=0
for rel in "${FILES_TO_SYNC[@]}"; do
    src_file="$SRC/$rel"
    dst_file="$DST/$rel"
    
    # Create subdirectory if needed
    dst_dir="$(dirname "$dst_file")"
    mkdir -p "$dst_dir"
    
    if [ ! -f "$dst_file" ] || ! diff -q "$src_file" "$dst_file" > /dev/null 2>&1; then
        cp "$src_file" "$dst_file"
        COPIED=$((COPIED + 1))
    fi
done

echo "✓ Synced $COPIED files."
echo ""
echo "Next: rebuild ASTRA-sim BookSim2Fabric:"
echo "  cd serving/astra-sim/extern/network_backend/booksim2/build"
echo "  cmake .. -DBOOKSIM2_SRC_DIR=${REPO_ROOT}/third_party/booksim2"
echo "  make -j\$(nproc)"
