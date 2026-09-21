import json
from pathlib import Path
from veritx_dse.core.artifact import canonical_json
from veritx_dse.core.errors import EvidenceInvalid


class ResourceStore:
    def __init__(self,root): self.root=Path(root)
    def put(self,kind,resource_id,document):
        path=self.root/kind/f"{resource_id}.json"; path.parent.mkdir(parents=True,exist_ok=True)
        body=canonical_json(document)
        if path.exists() and path.read_text()!=body:
            raise EvidenceInvalid("immutable id exists with different content")
        path.write_text(body)
    def get(self,kind,resource_id):
        path=self.root/kind/f"{resource_id}.json"
        if not path.exists(): raise EvidenceInvalid(f"missing {kind}/{resource_id}")
        return json.loads(path.read_text())
