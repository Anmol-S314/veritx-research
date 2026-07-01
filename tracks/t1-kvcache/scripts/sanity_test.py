#!/usr/bin/env python3
"""T1 KVCache — sanity check: verify gem5 binary exists (deferred build)."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "configs"))
import sanity_config
sanity_config.main()
