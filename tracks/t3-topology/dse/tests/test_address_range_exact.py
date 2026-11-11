import pytest

from veritx_dse.model.compile_model import AddressMap, AddressRange, CompileRequest

HIGH = (1 << 63) + 12345
MAX_U64 = (1 << 64) - 1
LOW = 0x1000_0000


def test_high_base_and_size_round_trip_exactly():
    mapping = AddressMap.from_dict({
        "ranges": [{
            "name": "HBM",
            "base": str(HIGH),
            "size": str(1 << 33),
            "target_agent_idx": 0,
        }],
    })
    assert mapping.ranges[0].base == HIGH
    assert mapping.ranges[0].size == (1 << 33)


def test_max_u64_round_trip_exactly():
    mapping = AddressMap.from_dict({
        "ranges": [{
            "name": "TOP",
            "base": str(MAX_U64),
            "size": "1",
            "target_agent_idx": 0,
        }],
    })
    assert mapping.ranges[0].base == MAX_U64


def test_wire_keeps_numbers_for_safe_values_and_strings_above():
    low = AddressRange(name="LOW", base=LOW, size=0x1000)
    high = AddressRange(name="HIGH", base=HIGH, size=0x1000)
    assert CompileRequest._address_dict(low)["base"] == LOW
    assert CompileRequest._address_dict(low)["size"] == 0x1000
    assert CompileRequest._address_dict(high)["base"] == str(HIGH)
    assert CompileRequest._address_dict(high)["size"] == 0x1000


def test_striped_interleave_above_safe_range_survives():
    low = AddressRange(name="S", base=0, size=1 << 32,
                       selection_policy="STRIPED",
                       interleave_bytes=str(1 << 53))
    assert low.interleave_bytes == (1 << 53)
    d = CompileRequest._address_dict(low)
    assert d["interleave_bytes"] == str(1 << 53)


@pytest.mark.parametrize("bad", ["9223372036854775808.0", "0x1000", "", "18446744073709551616", "-1", "1_000"])
def test_exact_int_rejects_ambiguous_text(bad):
    with pytest.raises(ValueError):
        AddressRange(name="X", base=bad, size=1)


def test_float_is_refused_not_rounded():
    with pytest.raises(ValueError):
        AddressRange(name="X", base=1.5, size=1)
    with pytest.raises(ValueError):
        AddressRange(name="X", base=MAX_U64 + 1, size=1)


def test_striped_alignment_uses_exact_arithmetic():
    base = ((HIGH // 4096) + 1) * 4096
    range_ = AddressRange(name="S", base=base, size=0x1000,
                          selection_policy="STRIPED",
                          interleave_bytes=4096)
    assert range_.base == base
    with pytest.raises(ValueError):
        AddressRange(name="S", base=base + 1, size=0x1000,
                     selection_policy="STRIPED",
                     interleave_bytes=4096)
