"""Parse Timeloop `*.stats.txt` output for DRAM read/write traffic.

Adapted from the parser in timeloop_to_matrix.py, with one important
change: the original placeholder summed reads/fills/updates into one
undifferentiated 'accesses' count. Pass 1 of the real pipeline needs reads
and writes as two separate matrix entries (bytes flowing tile->DRAM vs.
DRAM->tile), so this version keeps them apart.
"""
import re
from dataclasses import dataclass


@dataclass
class LevelStats:
    name: str
    instances: int
    reads: int
    fills: int
    updates: int

    @property
    def writes(self) -> int:
        # Writes *into* this level = fills (data pushed down from the level
        # above) + updates (partial-sum writebacks committed at this level).
        return self.fills + self.updates


def parse_levels(stats_text: str) -> list:
    levels, cur = [], None

    def flush():
        if cur and cur["name"] != "__ARITH__":
            levels.append(LevelStats(
                name=cur["name"], instances=cur["instances"],
                reads=cur["reads"], fills=cur["fills"], updates=cur["updates"],
            ))

    for line in stats_text.splitlines():
        m = re.match(r'\s*=== (.+?) ===', line)
        if m:
            flush()
            cur = {"name": m.group(1), "instances": 1, "reads": 0, "fills": 0, "updates": 0}
            continue
        if cur is None:
            continue
        mi = re.search(r'Utilized instances \(max\)\s*:\s*(\d+)', line)
        if mi:
            cur["instances"] = int(mi.group(1))
        for field_name, pattern in (
            ("reads", r'Actual scalar reads \(per-instance\)\s*:\s*(\d+)'),
            ("fills", r'Actual scalar fills \(per-instance\)\s*:\s*(\d+)'),
            ("updates", r'Actual scalar updates \(per-instance\)\s*:\s*(\d+)'),
        ):
            mm = re.search(pattern, line)
            if mm:
                cur[field_name] += int(mm.group(1))
    flush()
    return levels


def dram_traffic_bytes(stats_text: str, dtype_bytes: int) -> tuple:
    """Returns (dram_read_bytes, dram_write_bytes) for one Timeloop run.

    NOTE: Timeloop reports word/scalar counts, not bytes -- this multiplies
    by `dtype_bytes` (from ModelSpec) to get bytes. Sanity-check this
    against your arch.yaml datatype width; if your stats.txt already
    reports bytes, pass dtype_bytes=1.
    """
    levels = parse_levels(stats_text)
    dram = next((l for l in levels if "DRAM" in l.name.upper()), None)
    if dram is None:
        return 0, 0
    read_words = dram.reads * dram.instances
    write_words = dram.writes * dram.instances
    return read_words * dtype_bytes, write_words * dtype_bytes


def _selfcheck():
    sample = (
        "=== __ARITH__ ===\n  Actual scalar reads (per-instance) : 5\n"
        "=== DRAM ===\n  Utilized instances (max) : 2\n"
        "  Actual scalar reads (per-instance) : 100\n"
        "  Algorithmic scalar reads (per-instance) : 999\n"
        "  Actual scalar fills (per-instance) : 10\n"
        "  Actual scalar updates (per-instance) : 5\n"
        "  Actual scalar metadata reads (per-instance) : 7\n"
    )
    levels = parse_levels(sample)
    assert [l.name for l in levels] == ["DRAM"], levels
    assert levels[0].reads == 100 and levels[0].writes == 15, levels
    read_b, write_b = dram_traffic_bytes(sample, dtype_bytes=2)
    assert read_b == 100 * 2 * 2 and write_b == 15 * 2 * 2, (read_b, write_b)
    print("timeloop_stats.py selfcheck OK")


if __name__ == "__main__":
    _selfcheck()