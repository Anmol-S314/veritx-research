from veritx_dse.core.errors import BackendUnavailable
class AstraBackend:
    name="ASTRA"
    def evaluate(self,*,input_id,payload):
        raise BackendUnavailable("ASTRA requires the qualified Chakra/schema/feeder integration")
    def parse(self,raw):
        raise BackendUnavailable("ASTRA requires the qualified Chakra/schema/feeder integration")
