"""The embedded fabric's host flit limit must not throttle real traffic.

The HEAD BookSim EmbeddedTM refuses host injection until a positive host flit
limit is set, and it refuses again whenever the limit has no room for a stream.
The producer this machine replaced injected with no host-side cap at all, so the
limit is set explicitly and uncapped; these tests pin that decision and the
regression that motivated it (a fabric-capacity bound smaller than one
maximum-size stream aborted real presets instead of simulating them).
"""
import re

from veritx_dse.backend.astra_machine import (
    HOST_FLIT_LIMIT_DERIVATION,
    UNBOUNDED_HOST_FLITS,
    host_flit_limit_for,
)
from veritx_dse.core.paths import REPO


class _Prepared:
    def __init__(self, config_text: str = "", num_vcs: int = 4,
                 endpoint_count: int = 16):
        self.config_text = config_text
        self.num_vcs = num_vcs
        self.endpoint_count = endpoint_count


def _parser_default(name: str) -> int:
    text = (REPO / "third_party/booksim2/src/booksim_config.cpp").read_text()
    match = re.search(rf'_int_map\["{name}"\]\s*=\s*(\d+)\s*;', text)
    assert match, f"parser does not declare a default for {name}"
    return int(match.group(1))


def test_limit_is_positive_and_uncapped():
    assert host_flit_limit_for(_Prepared()) == UNBOUNDED_HOST_FLITS
    assert UNBOUNDED_HOST_FLITS > 0


def test_limit_admits_a_stream_larger_than_the_whole_fabric_buffering():
    """The bound that was rejected: endpoints x VCs x vc_buf_size. On a
    16-endpoint, 4-VC, 8-flit fabric that is 512 flits, while a real preset
    injects 8192-flit streams — so that bound refused injection and three
    shipped presets failed instead of completing."""
    vc_buf_size = _parser_default("vc_buf_size")
    capacity = 16 * 4 * vc_buf_size
    observed_stream = 8192
    assert host_flit_limit_for(_Prepared()) > observed_stream > capacity


def test_derivation_is_documented_for_the_run_bundle():
    assert "uncapped" in HOST_FLIT_LIMIT_DERIVATION
    assert "injection window, not a fabric buffer" in HOST_FLIT_LIMIT_DERIVATION
