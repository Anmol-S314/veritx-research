"""veritx_dse.config — Configuration management.

Single source of truth for all paths and settings.
Overridable via environment variables.
"""
from __future__ import annotations
import os
from pathlib import Path
from veritx_dse.paths import REPO, DSE_DIR, RUNS_DIR


class Config:
    """Centralized configuration with env var overrides."""
    
    def __init__(self):
        self._repo = REPO
        self._dse = DSE_DIR
        self._runs = RUNS_DIR
        self._experiments = self._runs / "experiments"
    
    @property
    def repo_root(self) -> Path:
        return Path(os.environ.get("VERITX_REPO", self._repo))
    
    @property
    def dse_dir(self) -> Path:
        return Path(os.environ.get("VERITX_DSE_DIR", self._dse))
    
    @property
    def runs_dir(self) -> Path:
        return Path(os.environ.get("VERITX_RUNS_DIR", self._runs))
    
    @property
    def experiments_dir(self) -> Path:
        return Path(os.environ.get("VERITX_EXPERIMENTS_DIR", self._experiments))
    
    @property
    def booksim_bin(self) -> Path:
        return Path(os.environ.get("VERITX_BOOKSIM_BIN", 
                                   self.repo_root / "third_party" / "booksim2" / "src" / "booksim"))
    
    @property
    def certify_sh(self) -> Path:
        return Path(os.environ.get("VERITX_CERTIFY_SH",
                                   self.dse_dir.parent / "scripts" / "certify.sh"))
    
    @property
    def timeout(self) -> int:
        return int(os.environ.get("VERITX_TIMEOUT", 60))
    
    @property
    def default_seed(self) -> int:
        return int(os.environ.get("VERITX_SEED", 0))
    
    @property
    def default_nodes(self) -> int:
        return int(os.environ.get("VERITX_NODES", 64))


# Global singleton
config = Config()
