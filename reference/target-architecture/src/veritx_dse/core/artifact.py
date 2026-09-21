from __future__ import annotations
import hashlib, json, math
from collections.abc import Mapping
from dataclasses import is_dataclass, asdict
from typing import Any, Iterable
from .errors import InvalidInput, EvidenceInvalid


def _plain(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _plain(value.to_dict())
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise InvalidInput("non-finite floats are outside canonical JSON")
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def content_id(domain: str, value: Any) -> str:
    payload = (domain + "\0" + canonical_json(value)).encode()
    return hashlib.sha256(payload).hexdigest()


def require_exact_fields(doc: Any, fields: Iterable[str], where: str) -> None:
    if not isinstance(doc, dict):
        raise InvalidInput(f"{where} must be an object")
    expected, actual = set(fields), set(doc)
    if expected != actual:
        raise InvalidInput(
            f"{where} field set mismatch; missing={sorted(expected-actual)}, "
            f"extra={sorted(actual-expected)}"
        )


def require_embedded_id(doc: dict[str, Any], field: str, expected: str, where: str) -> None:
    if doc.get(field) != expected:
        raise EvidenceInvalid(f"{where}.{field} does not match recomputed identity")
