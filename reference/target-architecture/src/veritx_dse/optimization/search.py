from itertools import product
from veritx_dse.core.artifact import canonical_json


def canonical_assignments(defn):
    params=sorted(defn.parameters,key=lambda p:p.name)
    domains=[tuple(sorted(p.values,key=canonical_json)) for p in params]
    for vals in product(*domains):
        yield dict(zip((p.name for p in params),vals))
