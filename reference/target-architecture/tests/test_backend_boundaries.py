import pytest
from veritx_dse.backend.astra import AstraBackend
from veritx_dse.backend.ramulator import RamulatorBackend
from veritx_dse.backend.timeloop import TimeloopBackend
from veritx_dse.core.errors import BackendUnavailable


@pytest.mark.parametrize("backend",[AstraBackend(),RamulatorBackend(),TimeloopBackend()])
def test_unqualified_backends_refuse_instead_of_faking_evidence(backend):
    with pytest.raises(BackendUnavailable):
        backend.evaluate(input_id="x",payload=b"x")
