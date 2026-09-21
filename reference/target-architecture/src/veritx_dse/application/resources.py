from dataclasses import dataclass
from veritx_dse.core.errors import InvalidInput


@dataclass(frozen=True)
class ResourceCodec:
    kind:str
    verify:object


class ResourceRegistry:
    def __init__(self): self._codecs={}
    def register(self,codec):
        if codec.kind in self._codecs: raise InvalidInput("duplicate resource codec")
        self._codecs[codec.kind]=codec
    def codec(self,kind):
        try: return self._codecs[kind]
        except KeyError as exc: raise InvalidInput(f"unknown resource kind {kind}") from exc
