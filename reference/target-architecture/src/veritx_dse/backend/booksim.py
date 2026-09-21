from pathlib import Path
from veritx_dse.core.errors import BackendUnavailable


def render_trace(traffic):
    lines=[f"{p.src_endpoint} {p.dst_endpoint} {p.payload_bytes} {p.flits} {p.packet_id}"
           for p in traffic.packets]
    return ("\n".join(lines)+("\n" if lines else "")).encode()


class BookSimBackend:
    name="BOOKSIM"
    def __init__(self,binary=None): self.binary=None if binary is None else Path(binary)
    def evaluate(self,*,input_id,payload):
        if self.binary is None or not self.binary.exists():
            raise BackendUnavailable("qualified BookSim binary was not supplied")
        raise BackendUnavailable(
            "reference target renders canonical BookSim input but does not guess "
            "the repository-specific qualified process/counter contract"
        )
    def parse(self,raw):
        raise BackendUnavailable(
            "reference target renders canonical BookSim input but does not guess "
            "the repository-specific qualified process/counter contract"
        )
