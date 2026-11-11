import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'srota_events', Path(__file__).resolve().parents[4] / 'scripts/check_srota_packet_events.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

STIMULUS = '1 0 63 200 1\n1 2 3 4\n'
EVENTS = 'A 201 1 0 63 0 0 1 1 1 2 3 4\nD 1000 1 0 63 0 1 1 1 1 2 3 4\n'


def test_multiflit_packets_interleave_without_losing_each_packets_order():
    stimulus = '1 0 63 0 2\n1 2 3 4\n5 6 7 8\n2 1 63 0 1\n9 10 11 12\n'
    events = ('A 0 1 0 63 0 0 1 0 1 2 3 4\n'
              'A 0 2 1 63 0 0 1 1 9 10 11 12\n'
              'A 1 1 0 63 1 0 0 1 5 6 7 8\n'
              'D 2 1 0 63 0 1 1 0 1 2 3 4\n'
              'D 3 1 0 63 1 1 0 1 5 6 7 8\n'
              'D 4 2 1 63 0 0 1 1 9 10 11 12\n')
    assert module.check_events(stimulus, events)['delivered_flits'] == 3
    with pytest.raises(ValueError, match='unstable route tag'):
        module.check_events(stimulus, events.replace('D 3 1 0 63 1 1', 'D 3 1 0 63 1 0'))


def test_replay_events_preserve_payload_and_allow_legal_route_selection():
    assert module.check_events(STIMULUS, EVENTS) == {
        'packets': 1, 'accepted_flits': 1, 'delivered_flits': 1, 'ordered_pairs': 1}


@pytest.mark.parametrize('events', [
    EVENTS.replace('D 1000', 'D 199'),
    EVENTS.replace('1 2 3 4\n', '1 2 3 5\n'),
    EVENTS.splitlines()[1] + '\n',
    EVENTS + EVENTS.splitlines()[1] + '\n',
    EVENTS.splitlines()[0] + '\n',
])
def test_corruption_premature_phantom_duplicate_or_missing_events_refuse(events):
    with pytest.raises(ValueError):
        module.check_events(STIMULUS, events)
