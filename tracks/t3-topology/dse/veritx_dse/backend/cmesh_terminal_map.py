"""Backend addressing bijection; canonical endpoints are never renumbered.

Native CMesh builds a global terminal grid, not router-major endpoint IDs.
Only full occupancy of the source-derived 1x2 (c=2) or 2x2 (c=4) split is
supported here. Local port order is addressing, not physical seat geometry.
"""
from dataclasses import dataclass

from veritx_dse.core.artifact import content_hash
from veritx_dse.core.errors import SemanticError
from veritx_dse.model.attachment import AgentAttachmentArtifact


class CMeshTerminalMapError(ValueError, SemanticError):
    pass


@dataclass(frozen=True)
class CMeshTerminalMap:
    k: int
    concentration: int
    # (canonical endpoint, native terminal, router, local port)
    bindings: tuple[tuple[int, int, int, int], ...]

    def __post_init__(self) -> None:
        if (type(self.k) is not int or self.k < 1
                or type(self.concentration) is not int
                or self.concentration not in (2, 4)):
            raise CMeshTerminalMapError("cmesh requires k >= 1 and c in {2,4}")
        count = self.k * self.k * self.concentration
        if (not isinstance(self.bindings, tuple) or len(self.bindings) != count
                or any(not isinstance(row, tuple) or len(row) != 4
                       or any(type(v) is not int for v in row)
                       for row in self.bindings)):
            raise CMeshTerminalMapError("cmesh requires full immutable terminal bindings")
        if sorted(e for e, _, _, _ in self.bindings) != list(range(count)):
            raise CMeshTerminalMapError("canonical endpoints must cover 0..E-1 exactly")
        if sorted(n for _, n, _, _ in self.bindings) != list(range(count)):
            raise CMeshTerminalMapError("native terminals must cover 0..E-1 exactly")
        if {(r, p) for _, _, r, p in self.bindings} != {
                (r, p) for r in range(self.k * self.k)
                for p in range(self.concentration)}:
            raise CMeshTerminalMapError("router/local-port seats must cover the native universe")
        for _, node, router, port in self.bindings:
            if self.node_to_seat(node) != (router, port):
                raise CMeshTerminalMapError("native terminal does not roundtrip to canonical router/local port")

    @property
    def cx(self) -> int:
        return self.concentration // 2

    @property
    def cy(self) -> int:
        return self.concentration // self.cx

    def node_to_seat(self, node: int) -> tuple[int, int]:
        if type(node) is not int or not 0 <= node < self.k * self.k * self.concentration:
            raise CMeshTerminalMapError("native terminal is out of range")
        x, y = node % (self.k * self.cx), node // (self.k * self.cx)
        return (y // self.cy) * self.k + x // self.cx, (y % self.cy) * self.cx + x % self.cx

    def endpoint_to_node(self) -> dict[int, int]:
        return {endpoint: node for endpoint, node, _, _ in self.bindings}

    def mapping_hash(self) -> str:
        return content_hash("srota/CMeshTerminalMap", 1, {
            "k": self.k, "c": self.concentration, "cx": self.cx, "cy": self.cy,
            "bindings": [list(row) for row in sorted(self.bindings)]})


def cmesh_terminal_map(attachment: AgentAttachmentArtifact, *, k: int,
                       concentration: int) -> CMeshTerminalMap:
    if (type(k) is not int or k < 1 or type(concentration) is not int
            or concentration not in (2, 4)):
        raise CMeshTerminalMapError("cmesh requires k >= 1 and c in {2,4}")
    cx, cy = concentration // 2, 2
    rows = []
    for endpoint in attachment.endpoints:
        router, port = endpoint.router_id, endpoint.port_id
        node = (k * cx) * (cy * (router // k) + port // cx) + cx * (router % k) + port % cx
        rows.append((endpoint.endpoint_id, node, router, port))
    return CMeshTerminalMap(k, concentration, tuple(sorted(rows)))
