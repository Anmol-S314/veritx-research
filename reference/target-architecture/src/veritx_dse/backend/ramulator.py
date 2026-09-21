from veritx_dse.core.errors import BackendUnavailable
class RamulatorBackend:
    name="RAMULATOR"
    def evaluate(self,*,input_id,payload):
        raise BackendUnavailable("Ramulator requires the qualified repository adapter")
    def parse(self,raw):
        raise BackendUnavailable("Ramulator requires the qualified repository adapter")
