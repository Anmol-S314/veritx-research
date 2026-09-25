"""Production workload corpus (C5): content-addressed manifests.

Every entry is built through the canonical pipeline; two builds of the same
entry must produce the same manifest id, and every entry must conserve its
packets/flits.
"""
from __future__ import annotations

from validation.corpus import ENTRIES, build_corpus, write_corpus


def test_corpus_is_content_addressed_and_stable():
    first = build_corpus()
    second = build_corpus()
    assert [m["manifest_id"] for m in first] \
        == [m["manifest_id"] for m in second]
    assert all(len(m["manifest_id"]) == 64 for m in first)


def test_corpus_covers_all_trust_levels():
    levels = {m["level"] for m in build_corpus()}
    assert {"W1", "W2", "W3"} <= levels


def test_corpus_entries_conserve_packets_and_flits():
    for manifest in build_corpus():
        cons = manifest["conservation"]
        assert cons["num_packets"] == manifest["expected_packets"]
        assert cons["flits_total"] == manifest["expected_flits"]
        assert manifest["expected_packets"] > 0
        assert manifest["expected_flits"] > 0


def test_write_corpus_emits_one_manifest_per_entry(tmp_path):
    written = write_corpus(tmp_path)
    assert len(written) == len(ENTRIES)
    assert all(p.is_file() for p in written)
