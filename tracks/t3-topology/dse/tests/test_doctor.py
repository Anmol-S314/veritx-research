"""doctor: report assembly through the real seam.

run_checks(level, checks=[...]) is the deep interface — tiny injected check
functions build a real DoctorReport, and the tests assert the *decisions*
(verdict derivation, crash containment, LLM-degradation, rendering) with
zero IO and zero mocks of doctor internals. The LLM adapter is exercised
in its two honest modes: unconfigured (None) and unreachable (error dict,
never an exception) — hitting the network is neither needed nor allowed.
"""
import http.server
import json
import threading

import pytest

from veritx_dse.core import doctor
from veritx_dse.core.doctor import Observation, run_checks

# ── check functions used as injected seams ────────────────────────────────


def _ok(log):
    log.append("ok line")
    return [Observation(name="a", status="pass", observed="fine")]


def _warn(log):
    return [Observation(name="b", status="warn", expected="x", observed="y")]


def _boom(log):
    raise RuntimeError("check exploded")


# ── verdict derivation (the one decision that gates CI) ───────────────────


def test_verdict_fail_when_any_check_fails():
    rep = run_checks("quick", checks=[_ok, _warn])
    rep.checks.append(Observation(name="c", status="fail"))
    assert rep.verdict == "FAIL"


def test_verdict_warn_without_fail():
    rep = run_checks("quick", checks=[_ok, _warn])
    assert rep.verdict == "WARN"


def test_verdict_pass_when_all_clean():
    rep = run_checks("quick", checks=[_ok])
    assert rep.verdict == "PASS"


def test_counts_match_checks():
    rep = run_checks("quick", checks=[_ok, _ok, _warn])
    c = rep.counts()
    assert c["pass"] == 2 and c["warn"] == 1 and c["fail"] == 0


# ── crash containment: a broken check is a finding, not a crash ───────────


def test_crashing_check_becomes_fail_observation():
    rep = run_checks("quick", checks=[_ok, _boom])
    crashes = [c for c in rep.checks if c.name.startswith("crash.")]
    assert len(crashes) == 1
    assert crashes[0].status == "fail"
    assert "check exploded" in crashes[0].observed
    # and the healthy check's results survive alongside
    assert any(c.name == "a" and c.status == "pass" for c in rep.checks)
    assert rep.verdict == "FAIL"


def test_injected_check_receives_log_buffer():
    seen = []
    rep = run_checks("quick", checks=[lambda l: seen.append(l) or
                                      [Observation(name="z", status="pass")]])
    assert seen and seen[0] is rep.log_tail or rep.log_tail == []


def test_unknown_level_raises_loud():
    with pytest.raises(ValueError, match="unknown doctor level"):
        run_checks("nope")


# ── LLM adapter: advisory, never raises, never gates ──────────────────────


def _scrub_llm_env(monkeypatch):
    for k in ("VERITX_LLM_API_KEY", "VERITX_LLM_BASE_URL", "VERITX_LLM_MODEL",
              "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"):
        monkeypatch.delenv(k, raising=False)


def test_llm_unconfigured_returns_none(monkeypatch):
    _scrub_llm_env(monkeypatch)
    rep = run_checks("quick", checks=[_ok])
    assert doctor.review_with_llm(rep) is None


def test_llm_env_chain_veritx_wins_over_openai(monkeypatch):
    _scrub_llm_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://openai.example/v1")
    monkeypatch.setenv("VERITX_LLM_API_KEY", "sk-veritx")
    monkeypatch.setenv("VERITX_LLM_BASE_URL", "http://veritx.example/v1")
    monkeypatch.setenv("VERITX_LLM_MODEL", "m-veritx")
    base, key, model = doctor._llm_creds()
    assert (base, key, model) == ("http://veritx.example/v1", "sk-veritx",
                                  "m-veritx")


def test_llm_env_chain_openai_fallback(monkeypatch):
    """Only OPENAI_API_KEY set → default endpoint derived."""
    _scrub_llm_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-o")
    base, key, model = doctor._llm_creds()
    assert base == "https://api.openai.com/v1"
    assert key == "sk-o" and model == "gpt-4o-mini"


def test_llm_key_without_any_base_yields_none(monkeypatch):
    """VERITX_LLM_API_KEY alone is NOT enough — no endpoint to hit."""
    _scrub_llm_env(monkeypatch)
    monkeypatch.setenv("VERITX_LLM_API_KEY", "k")
    assert doctor.llm_configured() is False
    rep = run_checks("quick", checks=[_ok])
    assert doctor.review_with_llm(rep) is None


def test_llm_unreachable_returns_error_dict_not_exception(monkeypatch):
    _scrub_llm_env(monkeypatch)
    monkeypatch.setenv("VERITX_LLM_API_KEY", "k")
    monkeypatch.setenv("VERITX_LLM_BASE_URL", "http://127.0.0.1:1")  # closed port
    monkeypatch.setenv("VERITX_LLM_MODEL", "m")
    rep = run_checks("quick", checks=[_ok])
    out = doctor.review_with_llm(rep)
    assert out is not None and out["review"] is None
    assert "error" in out and out["model"] == "m"
    # verdict is untouched by the LLM layer — it is advisory by contract
    assert rep.verdict == "PASS"


class _MockOpenAIChat(http.server.BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible /chat/completions responder.

    Verifies the adapter's WIRE contract (POST path, bearer header,
    request JSON shape, response JSON shape) with a real HTTP round
    trip — no network, no API key.
    """

    def do_POST(self):  # noqa: N802 (http.server API)
        assert self.path == "/chat/completions"
        assert self.headers["Authorization"] == "Bearer test-key"
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        # request shape the adapter must emit
        assert body["model"] == "test-model"
        assert body["messages"][0]["role"] == "system"
        assert "funny" in body["messages"][0]["content"]
        user = json.loads(body["messages"][1]["content"])
        assert user["doctor_report"]["verdict"] in ("PASS", "WARN", "FAIL")
        resp = {"choices": [{"message": {"content":
            "All checks consistent; cycles match packet counts."}}]}
        payload = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):  # silence request logging
        pass


def test_llm_real_http_round_trip_against_mock_server(monkeypatch):
    """Full adapter path over real HTTP: endpoint + auth + request shape
    + response parsing. The mock stands in for the LLM; the adapter code
    under test is the real one."""
    _scrub_llm_env(monkeypatch)
    server = http.server.HTTPServer(("127.0.0.1", 0), _MockOpenAIChat)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("VERITX_LLM_BASE_URL",
                           f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("VERITX_LLM_API_KEY", "test-key")
        monkeypatch.setenv("VERITX_LLM_MODEL", "test-model")
        rep = run_checks("quick", checks=[_ok, _warn])
        out = doctor.review_with_llm(rep)
        assert out is not None
        assert out["review"] == ("All checks consistent; "
                                 "cycles match packet counts.")
        assert out["model"] == "test-model"
        assert out["latency_s"] >= 0
        assert rep.verdict == "WARN"  # advisory layer did not gate
    finally:
        server.shutdown()
        server.server_close()


# ── rendering: every status mark + LLM section reachable ──────────────────


def test_render_shows_all_verdict_marks_and_summary():
    rep = run_checks("quick", checks=[_ok, _warn])
    rep.checks.append(Observation(name="f", status="fail"))
    rep.checks.append(Observation(name="s", status="skip"))
    text = doctor.render(rep)
    for mark in ("✓", "⚠", "✗", "-"):
        assert mark in text
    assert "verdict=FAIL" in text


def test_render_includes_llm_review_when_present():
    rep = run_checks("quick", checks=[_ok])
    rep.llm = {"model": "m", "review": "numbers look consistent",
               "latency_s": 1.2}
    assert "LLM second opinion" in doctor.render(rep)
    assert "numbers look consistent" in doctor.render(rep)


def test_to_dict_is_json_round_trippable():
    rep = run_checks("quick", checks=[_ok, _warn])
    rep.llm = {"model": "m", "review": None, "error": "x"}
    doc = json.loads(json.dumps(rep.to_dict()))
    assert doc["verdict"] == "WARN" and doc["llm"]["model"] == "m"
    assert {c["name"] for c in doc["checks"]} == {"a", "b"}


# ── the real registry: quick checks must exist and be runnable-safe ───────


def test_registry_has_both_levels_and_deep_is_superset():
    assert set(doctor.CHECKS) == {"quick", "deep"}
    assert len(doctor.CHECKS["deep"]) >= len(doctor.CHECKS["quick"])
    assert doctor.CHECKS["deep"][:len(doctor.CHECKS["quick"])] == \
        doctor.CHECKS["quick"]


def test_real_quick_battery_runs_offline_and_fast():
    """The genuine quick level must pass in this checkout: binaries exist,
    the two BookSim default dicts match, calibration doc carries the anchor.
    This is the honest end-to-end: real checks, real repo, no network."""
    import time
    t0 = time.time()
    rep = run_checks("quick")
    took = time.time() - t0
    assert rep.verdict in ("PASS", "WARN")   # FAIL means repo is broken
    assert took < 30
    names = {c.name for c in rep.checks}
    assert {"bin.booksim", "seam.booksim_defaults_match",
            "docs.calibration"} <= names
