from veritx_dse.core.errors import BackendUnavailable
class TimeloopBackend:
    name="TIMELOOP"
    def evaluate(self,*,input_id,payload):
        raise BackendUnavailable("Timeloop area/energy integration is not fabricated")
    def parse(self,raw):
        raise BackendUnavailable("Timeloop area/energy integration is not fabricated")
