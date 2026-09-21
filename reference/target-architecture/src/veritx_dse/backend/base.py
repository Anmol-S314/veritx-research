from typing import Protocol


class BackendAdapter(Protocol):
    """A qualified backend process boundary.

    ``evaluate`` returns the backend's own output bytes, *unparsed*, so the
    evidence artifact can digest what the backend actually emitted. A
    backend cannot hand back counters that its own output does not contain.
    ``parse`` turns those exact bytes into counters plus the parser version
    that read them; it must refuse rather than guess.
    """

    name: str

    def evaluate(self, *, input_id: str, payload: bytes) -> bytes: ...

    def parse(self, raw: bytes) -> tuple[tuple[tuple[str, int], ...], str]: ...
