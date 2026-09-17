"""veritx_dse.artifact — PRD §12, §14: Artifact signing and design manifests.

Signing mode honesty (verified-PRD Integrity PR B, §3.13 / §17.3): this
module implements HMAC-SHA256 **integrity checking** with a caller-supplied
shared secret. It is NOT public-verifiable signing (no PKI) and is NOT a
security boundary. There is deliberately NO default secret: passing no key
is a TypeError-class error, not an accidental signing with a hardcoded key.

Current signing mode: CHECKSUMMED / UNSIGNED-INTegrity (shared-secret HMAC).
Product signing (SIGNED_LOCAL / SIGNED_SROTA_SERVICE / SIGNED_CUSTOMER_ON_PREM)
is deferred until a real key-management requirement exists.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


class MissingSigningKey(TypeError):
    """No signing key supplied. There is no default key by design (PR B):
    signing with a source-embedded secret would silently present integrity
    as authenticity."""


def _require_key(secret_key: str | None) -> str:
    if not secret_key:
        raise MissingSigningKey(
            "sign_manifest() requires an explicit secret_key — there is "
            "deliberately no default (PR B: a source-embedded secret is not "
            "a security boundary and would misrepresent integrity as "
            "authenticity). Pass a key or use the CHECKSUMMED/UNSIGNED mode.")
    return secret_key


def sign_manifest(
    manifest: dict[str, Any],
    secret_key: str,
) -> str:
    """Sign a manifest dict using HMAC-SHA256.

    Args:
        manifest: The manifest dict to sign.
        secret_key: Shared secret for HMAC.

    Returns:
        Hex-encoded HMAC-SHA256 signature string.
    """
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    sig = hmac.new(
        secret_key.encode(), canonical.encode(), hashlib.sha256
    ).hexdigest()
    return sig


def verify_manifest(
    manifest: dict[str, Any],
    signature: str,
    secret_key: str,
) -> bool:
    """Verify a manifest's HMAC signature.

    Args:
        manifest: The manifest dict to verify.
        signature: The expected HMAC signature.
        secret_key: Shared secret for HMAC.

    Returns:
        True if signature matches, False otherwise.
    """
    expected = sign_manifest(manifest, secret_key)
    return hmac.compare_digest(expected, signature)


# ══════════════════════════════════════════════════════════════════════════════
# §12 — Design Manifest with Revision Chain
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class DesignManifest:
    """PRD §12: Immutable design revision with manifest hash and revision chain.

    Each design has a unique design_id. Revisions are numbered sequentially.
    Each revision carries the hash of the previous revision, forming a chain.

    Attributes:
        design_id: Unique identifier for this design (UUID4).
        revision: Sequential revision number (starts at 1).
        guardrail_hash: SHA-256 hash of the CompileRequest.
        manifest_hash: SHA-256 hash of THIS manifest (for chaining).
        parent_hash: Hash of the previous revision's manifest (empty for rev 1).
        timestamp: ISO 8601 creation timestamp.
        signature: HMAC-SHA256 signature of the manifest.
        metadata: Arbitrary metadata (engine version, user notes, etc.).
    """
    design_id: str
    revision: int
    guardrail_hash: str
    manifest_hash: str
    parent_hash: str
    timestamp: str
    signature: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        cr,
        secret_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DesignManifest:
        """Create the first revision of a design manifest.

        Args:
            cr: CompileRequest (extracts guardrail_hash).
            secret_key: HMAC signing key.
            metadata: Optional metadata dict.

        Returns:
            DesignManifest with revision=1.
        """
        design_id = str(uuid.uuid4())
        return cls._build(cr, secret_key=_require_key(secret_key),
                          metadata=metadata or {},
                          revision=1, design_id=design_id, parent_hash="")

    @classmethod
    def create_unsigned(
        cls,
        cr,
        metadata: dict[str, Any] | None = None,
    ) -> DesignManifest:
        """Create a revision-1 manifest in CHECKSUMMED/UNSIGNED mode.

        Same hash chain as create(); signature is empty and the signing
        mode is recorded in metadata. This is the honest research-mode
        default (PR B): integrity via checksums, no authenticity claim.
        """
        base = dict(metadata or {})
        base.setdefault("signing_mode", "CHECKSUMMED_UNSIGNED")
        return cls._build(cr, secret_key=None, metadata=base, revision=1,
                          design_id=None, parent_hash="")

    @staticmethod
    def _build(cr, secret_key: str | None, metadata: dict[str, Any],
               revision: int, design_id: str | None,
               parent_hash: str) -> DesignManifest:
        """Shared manifest construction for signed and unsigned modes."""
        did = design_id or str(uuid.uuid4())
        guardrail_hash = cr.guardrail_hash()
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        manifest_dict = {
            "design_id": did,
            "revision": revision,
            "guardrail_hash": guardrail_hash,
            "parent_hash": parent_hash,
            "timestamp": timestamp,
            "metadata": metadata or {},
        }
        manifest_hash = hashlib.sha256(
            json.dumps(manifest_dict, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        manifest_dict["manifest_hash"] = manifest_hash
        signature = sign_manifest(manifest_dict, secret_key) if secret_key else ""

        return DesignManifest(
            design_id=did,
            revision=revision,
            guardrail_hash=guardrail_hash,
            manifest_hash=manifest_hash,
            parent_hash=parent_hash,
            timestamp=timestamp,
            signature=signature,
            metadata=metadata or {},
        )

    def revise(
        self,
        cr,
        secret_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> DesignManifest:
        """Create a new revision from an existing manifest.

        Args:
            cr: Updated CompileRequest.
            secret_key: HMAC signing key.
            metadata: Optional metadata to merge.

        Returns:
            New DesignManifest with incremented revision.
        """
        new_metadata = {**self.metadata}
        if metadata:
            new_metadata.update(metadata)
        return self._build(cr, secret_key=_require_key(secret_key),
                           metadata=new_metadata,
                           revision=self.revision + 1,
                           design_id=self.design_id,
                           parent_hash=self.manifest_hash)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict."""
        return {
            "design_id": self.design_id,
            "revision": self.revision,
            "guardrail_hash": self.guardrail_hash,
            "manifest_hash": self.manifest_hash,
            "parent_hash": self.parent_hash,
            "timestamp": self.timestamp,
            "signature": self.signature,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DesignManifest:
        """Deserialize from dict."""
        return cls(
            design_id=d["design_id"],
            revision=d["revision"],
            guardrail_hash=d["guardrail_hash"],
            manifest_hash=d["manifest_hash"],
            parent_hash=d["parent_hash"],
            timestamp=d["timestamp"],
            signature=d["signature"],
            metadata=d.get("metadata", {}),
        )
