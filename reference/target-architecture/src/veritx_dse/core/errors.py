class VeriTXError(Exception):
    """Base class for declared VeriTX refusals."""


class InvalidInput(VeriTXError):
    pass


class EvidenceInvalid(VeriTXError):
    pass


class UnsupportedSemantic(VeriTXError):
    pass


class UnsupportedSchedule(VeriTXError):
    pass


class MappingInvalid(VeriTXError):
    pass


class ConservationFailed(VeriTXError):
    pass


class BackendUnavailable(VeriTXError):
    pass


class BackendFailure(VeriTXError):
    pass
