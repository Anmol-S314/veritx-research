"""Pinned, bounded native diagnostic inputs. No release qualification implied."""
from dataclasses import dataclass
from fractions import Fraction
import hashlib
from pathlib import Path

from veritx_dse.core.artifact import FrozenMap, ImmutableError, canonical_bytes, content_id, thaw
from veritx_dse.core.errors import InvalidInput, EvidenceInvalid
from veritx_dse.model.resource_graph import exact_int

PROFILE = "NATIVE_COUPLED_TENSOR_DIAGNOSTIC_V1"
PIN_NAMES = frozenset({"booksim_executable", "booksim_library", "booksim_source_manifest",
                      "ramulator_extension", "ramulator_library", "ramulator_source_manifest"})


def file_sha256(path):
    p = Path(path)
    if p.is_symlink() or not p.is_file():
        raise InvalidInput("native input must be a regular file, not a symlink")
    h = hashlib.sha256()
    with p.open('rb') as src:
        for block in iter(lambda: src.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _pin_fields(pin):
    if not isinstance(pin, (dict, FrozenMap)) or len(pin) != 2 or set(pin) != {"path", "sha256"}:
        raise InvalidInput("native file pin requires exactly path and sha256")
    if not isinstance(pin['path'], str) or '\x00' in pin['path'] or not Path(pin['path']).is_absolute():
        raise InvalidInput("native file pin requires an absolute local path")
    sha = pin['sha256']
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
        raise InvalidInput("native file pin requires lowercase SHA-256")


def verify_pin(pin):
    _pin_fields(pin)
    if file_sha256(pin['path']) != pin['sha256']:
        raise EvidenceInvalid("native pinned input changed: " + pin['path'])


@dataclass(frozen=True)
class NativeCoupledConfig:
    files: FrozenMap
    ramulator_config: FrozenMap
    booksim_period_ps_num: int
    booksim_period_ps_den: int
    memory_tck_ps: int
    owner_endpoint: int
    window_start: int
    window_end: int
    tx_bytes: int
    host_reservation_slots: int
    max_memory_outstanding: int
    host_flit_limit: int
    max_engine_steps: int

    def __post_init__(self):
        if not isinstance(self.files, FrozenMap) or len(self.files) != len(PIN_NAMES) or set(self.files) != PIN_NAMES:
            raise InvalidInput("native files require the complete pinned input set")
        for pin in self.files.values():
            _pin_fields(pin)
        if not isinstance(self.ramulator_config, FrozenMap) or len(canonical_bytes(self.ramulator_config)) > 256 * 1024:
            raise InvalidInput("Ramulator config must be immutable and at most 256 KiB")
        for name in self.__dataclass_fields__:
            if name not in ('files', 'ramulator_config'):
                exact_int(name, getattr(self, name), 0 if name in ('owner_endpoint', 'window_start') else 1)
        if self.window_start >= self.window_end or self.window_end > 2**28:
            raise InvalidInput("memory window must fit the single HBM2_1Gb channel")
        if self.tx_bytes != 32 or self.window_start % 32 or self.window_end % 32:
            raise InvalidInput("HBM2 window requires aligned 32-byte transactions")
        if self.period_ps.denominator != self.booksim_period_ps_den:
            raise InvalidInput("BookSim period must be reduced")
        if (self.host_reservation_slots > 1024 or self.max_memory_outstanding > 1024
                or self.host_flit_limit > 65536 or self.max_engine_steps > 1_000_000):
            raise InvalidInput("native resource bound exceeded")

    @property
    def period_ps(self):
        return Fraction(self.booksim_period_ps_num, self.booksim_period_ps_den)

    def to_dict(self):
        return {k: thaw(getattr(self, k)) for k in self.__dataclass_fields__}

    def config_id(self):
        return content_id('veritx/NativeCoupledConfig/v1', self.to_dict())

    @classmethod
    def from_dict(cls, doc):
        if not isinstance(doc, dict) or set(doc) != set(cls.__dataclass_fields__):
            raise InvalidInput('native config requires exactly its closed fields')
        if not isinstance(doc['files'], dict) or not isinstance(doc['ramulator_config'], dict):
            raise InvalidInput('native files and Ramulator config must be objects')
        try:
            return cls(**{**doc, 'files': FrozenMap(doc['files']),
                          'ramulator_config': FrozenMap(doc['ramulator_config'])})
        except ImmutableError as exc:
            raise InvalidInput('native config contains a noncanonical value') from exc
