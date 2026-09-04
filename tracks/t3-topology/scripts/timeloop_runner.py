"""Timeloop invocation + memoization cache (plan.md Section 6, step 5).

One operations/<shape_tag>/ folder per UNIQUE (op_template, M/N/K) --
NOT per OpAssignment. If N=72 has 72 attention_qk instances but only 2
distinct (k=2, k=3) head-group splits, exactly 2 real timeloop-mapper runs
happen and exactly 2 folders get created. Every OpAssignment that shares a
shape is recorded in that folder's used_by.json instead of getting its own
duplicate copy of the same stats.txt/map.txt/map+stats.xml.
"""
import subprocess
import shutil
import json
import yaml
from pathlib import Path

from timeloop_stats import dram_traffic_bytes


def shape_tag(op_template: str, shape: dict) -> str:
    """Deterministic folder name for a given (op_template, shape) pair.
    Shared with run_spatial_pipeline.py so execution.json can point at the
    same operations/<shape_tag>/ folders without re-running anything."""
    return op_template + "_" + "_".join(f"{k}{v}" for k, v in sorted(shape.items()))


class TimeloopRunner:
    def __init__(self, timeloop_dir, results_dir, problem_template: str = "gemm.yaml",
                 mapper_yaml: str = "mapper.yaml", arch_yaml: str = "arch.yaml"):
        self.timeloop_dir = Path(timeloop_dir)
        self.problem_template_path = self.timeloop_dir / "problem_library" / problem_template
        self.mapper_yaml = mapper_yaml
        self.arch_yaml = arch_yaml
        self.temp_problem = self.timeloop_dir / "problem.yaml"

        self.stats_file = self.timeloop_dir / "timeloop-mapper.stats.txt"
        self.map_file = self.timeloop_dir / "timeloop-mapper.map.txt"
        self.xml_file = self.timeloop_dir / "timeloop-mapper.map+stats.xml"

        self.results_dir = Path(results_dir)
        self.operations_dir = self.results_dir / "operations"

        self._cache = {}  # key -> (read_bytes, write_bytes, op_dir)
        self._usage = {}  # key -> [{"op_id":..., "tile_id":...}, ...]

    def _cache_key(self, op_template, shape):
        return (op_template, tuple(sorted(shape.items())))

    def get_dram_traffic(self, op_id: str, tile_id: int, op_template: str,
                          shape: dict, dtype_bytes: int):
        """Returns (dram_read_bytes, dram_write_bytes). Runs timeloop-mapper
        only on a genuine cache miss (new shape); every call -- hit or
        miss -- records (op_id, tile_id) against that shape's usage list
        for the manifest written by write_manifests()."""
        key = self._cache_key(op_template, shape)

        if key not in self._cache:
            self._generate_problem(shape)
            self._run_timeloop_mapper()

            op_dir = self.operations_dir / shape_tag(op_template, shape)
            op_dir.mkdir(parents=True, exist_ok=True)
            if self.stats_file.exists():
                shutil.copy(self.stats_file, op_dir / "stats.txt")
            if self.map_file.exists():
                shutil.copy(self.map_file, op_dir / "map.txt")
            if self.xml_file.exists():
                shutil.copy(self.xml_file, op_dir / "map+stats.xml")

            stats_text = (op_dir / "stats.txt").read_text()
            read_b, write_b = dram_traffic_bytes(stats_text, dtype_bytes)
            self._cache[key] = (read_b, write_b, op_dir)
            self._usage[key] = []

        self._usage[key].append({"op_id": op_id, "tile_id": tile_id})
        read_b, write_b, _op_dir = self._cache[key]
        return read_b, write_b

    def write_manifests(self):
        """Writes operations/<shape_tag>/used_by.json listing every
        OpAssignment (tile/head instance) that this one Timeloop run
        represents. Call once after all ops for a given N have been
        processed."""
        for key, usages in self._usage.items():
            op_template, shape_items = key
            _read_b, _write_b, op_dir = self._cache[key]
            manifest = {
                "op_template": op_template,
                "shape": dict(shape_items),
                "num_instances": len(usages),
                "used_by": usages,
            }
            with open(op_dir / "used_by.json", "w") as f:
                json.dump(manifest, f, indent=2)

    def _generate_problem(self, shape: dict):
        with open(self.problem_template_path) as f:
            problem = yaml.safe_load(f)
        instance = problem["problem"]["instance"]
        for key, value in shape.items():
            instance[key] = value
        with open(self.temp_problem, "w") as f:
            yaml.safe_dump(problem, f, sort_keys=False)

    def _run_timeloop_mapper(self):
        cmd = ["timeloop-mapper", self.mapper_yaml, self.arch_yaml, "problem.yaml"]
        result = subprocess.run(cmd, cwd=self.timeloop_dir)
        if result.returncode != 0:
            raise RuntimeError(
                f"timeloop-mapper failed for the problem written to {self.temp_problem}"
            )

    @property
    def num_unique_runs(self):
        return len(self._cache)
