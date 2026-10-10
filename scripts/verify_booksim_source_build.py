#!/usr/bin/env python3
"""Two external builds of actual BookSim worktree inputs. NEVER qualification.

This is deliberately NOT a BuildManifest: a content snapshot cannot establish
clean revision provenance. No binary, pin, registry or git index is modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys

REPO = Path(__file__).resolve().parent.parent
RECIPE = "booksim-source-snapshot-debug-prefix-map/v1"
GENERATED_NAMES = {"booksim", "booksim.build-manifest.json", "lex.yy.c", "y.tab.c", "y.tab.h"}
GENERATED_SUFFIXES = {".o", ".d", ".a", ".pyc"}
CACHE_DIRS = {".git", "__pycache__", ".pytest_cache"}
FLAGS = "-Wall -I. -Iarbiters -Iallocators -Irouters -Inetworks -Ipower -O3 -g"
TEST = "tracks/t3-topology/dse/tests/test_booksim_source_build_verification.py"


class VerificationError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_fact(path):
    data = Path(path).read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
            "executable": bool(Path(path).stat().st_mode & 0o111)}


def inventory(root):
    """Include ALL non-generated files, including ignored/untracked build inputs.

    Refuse all symlinks (even internal ones) and special files. The explicit
    product exclusions are the only omissions; no gitignore/glob source filter.
    """
    root = Path(root).resolve()
    rows, excluded = [], []
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise VerificationError(f"source symlink refused: {relative}")
            if stat.S_ISDIR(mode):
                if name in CACHE_DIRS:
                    dirs.remove(name)
                    excluded.append(relative + "/")
                continue
            if not stat.S_ISREG(mode):
                raise VerificationError(f"special source input refused: {relative}")
            if name in GENERATED_NAMES or path.suffix in GENERATED_SUFFIXES:
                excluded.append(relative)
            else:
                rows.append({"path": relative, **file_fact(path)})
    rows.sort(key=lambda row: row["path"])
    names = {row["path"] for row in rows}
    if not {"Makefile", "config.l", "config.y"} <= names:
        raise VerificationError("missing standalone Makefile/config.l/config.y")
    return {"files": rows, "content_sha256": digest(rows), "excluded": sorted(excluded)}


def source_identity(value):
    # Excluded products change during builds; only actual source rows are inputs.
    return value["files"]


def git_facts(repo, source):
    def git(*args):
        try:
            proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                                  text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return proc.stdout.rstrip("\n") if proc.returncode == 0 else None
    try:
        scope = str(Path(source).resolve().relative_to(Path(repo).resolve()))
    except ValueError:
        scope = None
    whole = git("status", "--porcelain", "--untracked-files=all")
    scoped = git("status", "--porcelain", "--untracked-files=all", "--", scope) if scope else None
    return {"revision": git("rev-parse", "HEAD"), "repository_status": whole,
            "repository_dirty": bool(whole) if whole is not None else None,
            "source_scope": scope, "source_status": scoped,
            "source_dirty": bool(scoped) if scoped is not None else None,
            "pinned": False, "qualification": False}


def tool_fact(command):
    path = shutil.which(command)
    if path is None:
        raise VerificationError(f"required tool absent: {command}")
    path = str(Path(path).resolve())
    proc = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise VerificationError(f"tool version unavailable: {command}")
    return {"path": path, "version": proc.stdout, **file_fact(path)}


def run_logged(command, cwd, log, env, timeout):
    status = None
    error = None
    with Path(log).open("wb") as stream:
        try:
            proc = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    start_new_session=True)
            try:
                status = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Kill make/compiler or pytest/native descendants, not just the
                # wrapper; no background build may outlive a failed report.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                raise
        except (OSError, subprocess.TimeoutExpired) as exc:
            error = str(exc)
            stream.write(("\nVERIFICATION_FAILURE: " + error + "\n").encode())
    return {"command": command, "returncode": status, "error": error,
            "log": str(Path(log).name), "log_fact": file_fact(log)}


def require_same(root, before):
    after = inventory(root)
    if source_identity(after) != source_identity(before):
        raise VerificationError(f"source inventory drift: {root}")
    return after


def copy_snapshot(source, target, before):
    target.mkdir()
    for row in before["files"]:
        relative = Path(row["path"])
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(source) / relative, destination)
    require_same(source, before)
    return require_same(target, before)


def verification_inputs(repo):
    """Bind the Python implementation/fixtures actually used by diagnostics."""
    repo = Path(repo)
    paths = {Path(__file__).resolve()}
    paths.update((repo / "tracks/t3-topology/dse").rglob("*.py"))
    paths.add(repo / "tracks/t3-topology/examples/dense_4b_32tiles_conc4-v3.json")
    return {str(path.resolve()): file_fact(path) for path in sorted(paths)}


def retained_artifacts(output):
    facts = {}
    for path in sorted(Path(output).rglob("*")):
        relative = path.relative_to(output)
        if path.is_file() and path.name != "verification.json" and (
                len(relative.parts) == 1 or relative.parts[0].startswith("native-") or path.name == "booksim"):
            if path.is_symlink() or not path.resolve().is_relative_to(Path(output).resolve()):
                raise VerificationError("escaping retained artifact")
            facts[relative.as_posix()] = file_fact(path)
    return facts


def verify_report(path):
    """Rehash retained source, binaries, logs and native evidence; not attestation.

    Hashes detect drift, not an adversary rewriting an entire report and artifacts.
    They do not establish source-to-binary provenance or validate release claims.
    """
    path = Path(path).resolve()
    doc = json.loads(path.read_text())
    if not isinstance(doc, dict) or doc.get("report_sha256") != digest(
            {key: value for key, value in doc.items() if key != "report_sha256"}):
        raise VerificationError("report digest mismatch")
    fields = {"schema", "recipe", "state", "pinned", "qualification", "success", "source_root", "repo_root", "provenance",
              "input_inventory", "container_digest_supplied_not_attested", "native_diagnostics", "require_byte_identical",
              "byte_identical", "builds", "diagnostics", "tools", "artifacts", "limitations", "verification_inputs",
              "failure", "build_environment", "report_sha256"}
    if set(doc) != fields or any(type(doc.get(key)) is not bool for key in
                                ("success", "native_diagnostics", "require_byte_identical", "byte_identical")):
        raise VerificationError("invalid diagnostic report fields/types")
    if doc.get("schema") != "BOOKSIM_SOURCE_BUILD_VERIFICATION_V1" or \
            doc.get("state") != "DIAGNOSTIC_UNQUALIFIED" or \
            doc.get("qualification") is not False or doc.get("pinned") is not False:
        raise VerificationError("not a successful unqualified diagnostic report")
    if not doc.get("success") or len(doc.get("builds", [])) != 2:
        raise VerificationError("two successful builds required")
    if doc["recipe"] != RECIPE or [row["directory"] for row in doc["builds"]] != ["build-1", "build-2"]:
        raise VerificationError("unknown recipe/build directories")
    current = git_facts(Path(doc["repo_root"]), Path(doc["source_root"]))
    if any(current[key] != doc["provenance"][key] for key in
           ("revision", "source_scope", "source_status", "source_dirty", "pinned", "qualification")):
        raise VerificationError("source git provenance drift/mismatch")
    require_same(Path(doc["source_root"]), doc["input_inventory"])
    if doc["input_inventory"]["content_sha256"] != digest(doc["input_inventory"]["files"]):
        raise VerificationError("source digest mismatch")
    for name, fact in doc["verification_inputs"].items():
        if file_fact(name) != fact:
            raise VerificationError("verification implementation/fixture drift")
    for build in doc["builds"]:
        require_same(path.parent / build["directory"], doc["input_inventory"])
        if build["execution"]["returncode"] != 0 or build["execution"]["error"] is not None:
            raise VerificationError("build failure in report")
        if file_fact(path.parent / build["execution"]["log"]) != build["execution"]["log_fact"]:
            raise VerificationError("build log drift")
    if retained_artifacts(path.parent) != doc["artifacts"]:
        raise VerificationError("artifact coverage/digest mismatch")
    for name, fact in doc["artifacts"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise VerificationError("escaping report artifact")
        artifact = path.parent / relative
        if artifact.is_symlink() or not artifact.resolve().is_relative_to(path.parent):
            raise VerificationError("escaping report artifact")
        if file_fact(artifact) != fact:
            raise VerificationError(f"artifact drift: {name}")
    binaries = [file_fact(path.parent / row["directory"] / "booksim") for row in doc["builds"]]
    if binaries != [row["binary"] for row in doc["builds"]]:
        raise VerificationError("binary identity mismatch")
    equal = binaries[0] == binaries[1]
    if doc["byte_identical"] is not equal or (doc["require_byte_identical"] and not equal):
        raise VerificationError("binary comparison mismatch")
    for tool in doc["tools"].values():
        if file_fact(tool["path"]) != {key: tool[key] for key in ("sha256", "size", "executable")}:
            raise VerificationError("tool executable drift")
    if doc["native_diagnostics"]:
        if len(doc["diagnostics"]) != 2 or any(row["returncode"] != 0 or row["error"] is not None for row in doc["diagnostics"]):
            raise VerificationError("native diagnostics incomplete")
        for index, build in enumerate(doc["builds"]):
            for name in ("cmesh-2", "cmesh-4", "class-vc"):
                summary = json.loads((path.parent / f"native-{index + 1}" / name / "summary.json").read_text())
                if summary["binary_sha256"] != build["binary"]["sha256"] or summary["qualification"] is not False:
                    raise VerificationError("native summary identity mismatch")
    elif doc["diagnostics"]:
        raise VerificationError("undeclared native diagnostics")
    return doc


def verify_builds(*, repo_root, source_root, output_root, cxx="g++", cc="gcc",
                  container_digest=None, native_diagnostics=True,
                  require_byte_identical=True, timeout=900):
    repo, source, output = map(lambda p: Path(p).resolve(), (repo_root, source_root, output_root))
    if output.is_relative_to(repo) or output.is_relative_to(source) or repo.is_relative_to(output) or source.is_relative_to(output):
        raise VerificationError("output must be external, not an ancestor of repository/source")
    if output.exists():
        raise VerificationError("output directory must be fresh")
    if not re.fullmatch(r"[A-Za-z0-9_./+\-]+", str(output)):
        raise VerificationError("output path contains unsafe make/shell characters")
    if type(timeout) is not int or not 1 <= timeout <= 3600:
        raise VerificationError("timeout must be integer 1..3600")
    if container_digest is not None and not re.fullmatch(r"\S+@sha256:[0-9a-f]{64}", container_digest):
        raise VerificationError("container must be digest-pinned; supplied identity is not attested")
    before = inventory(source)
    output.mkdir(parents=True)
    report = {"schema": "BOOKSIM_SOURCE_BUILD_VERIFICATION_V1", "recipe": RECIPE,
              "state": "DIAGNOSTIC_UNQUALIFIED", "pinned": False, "qualification": False,
              "success": False, "source_root": str(source), "repo_root": str(repo), "provenance": git_facts(repo, source),
              "input_inventory": before, "container_digest_supplied_not_attested": container_digest,
              "native_diagnostics": native_diagnostics, "require_byte_identical": require_byte_identical,
              "byte_identical": None, "builds": [], "diagnostics": [], "tools": {}, "artifacts": {},
              "limitations": ["Content snapshot, NOT a reviewed clean checkout or BuildManifest",
                              "Tool hashes/versions do not pin linked libraries or host/container",
                              "Repeated bytes/behaviors are diagnostics, NOT native/hardware equivalence"],
              "verification_inputs": verification_inputs(repo) if native_diagnostics else {},
              "failure": None}
    env = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C", "LANG": "C", "SOURCE_DATE_EPOCH": "0"}
    report["build_environment"] = env
    try:
        report["tools"] = {name: tool_fact(command) for name, command in
                           (("cxx", cxx), ("cc", cc), ("make", "make"), ("flex", "flex"), ("bison", "bison"), ("python", sys.executable))}
        if any(not re.fullmatch(r"[A-Za-z0-9_./+\-]+", tool["path"]) for tool in report["tools"].values()):
            raise VerificationError("tool path contains unsafe make/shell characters")
        for index in range(2):
            name = f"build-{index + 1}"
            build = output / name
            copied = copy_snapshot(source, build, before)
            flags = FLAGS + f" -ffile-prefix-map={build}=/veritx/booksim-src -fdebug-prefix-map={build}=/veritx/booksim-src"
            tools = report["tools"]
            command = [tools["make"]["path"], "-j2", "booksim", f"CXX={tools['cxx']['path']}",
                       f"CC={tools['cc']['path']}", f"LEX={tools['flex']['path']}",
                       f"YACC={tools['bison']['path']} -y", f"CPPFLAGS={flags}", "LFLAGS="]
            execution = run_logged(command, build, output / f"{name}.log", env, timeout)
            row = {"directory": name, "copied_inventory": copied, "execution": execution,
                   "flags": flags, "binary": None}
            report["builds"].append(row)
            require_same(source, before)
            row["post_build_inventory"] = require_same(build, before)
            if execution["returncode"] != 0 or not (build / "booksim").is_file():
                raise VerificationError(f"build failed: {name}; inspect retained log")
            row["binary"] = file_fact(build / "booksim")
        report["byte_identical"] = report["builds"][0]["binary"] == report["builds"][1]["binary"]
        # Still run behavioral checks on both binaries on byte mismatch.
        if native_diagnostics:
            for index, build in enumerate(report["builds"]):
                evidence = output / f"native-{index + 1}"
                evidence.mkdir()
                test_env = {**env, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(repo / "tracks/t3-topology/dse"),
                            "VERITX_SOURCE_VERIFICATION_BINARY": str(output / build["directory"] / "booksim"),
                            "VERITX_SOURCE_VERIFICATION_SHA256": build["binary"]["sha256"],
                            "VERITX_SOURCE_VERIFICATION_EVIDENCE": str(evidence),
                            "VERITX_SROTA_DIAGNOSTIC_BINARY": str(output / build["directory"] / "booksim")}
                regulator_test = repo / "tracks/t3-topology/dse/tests/test_native_srota_regulator.py"
                command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(repo / TEST),
                           str(regulator_test) + "::test_live_native_throttle_bypass_refund_sidebuffer_and_conservation",
                           "-k", "native_diagnostic or live_native", "--basetemp", str(evidence / "pytest"), "-rs"]
                record = run_logged(command, repo, output / f"native-{index + 1}.log", test_env, timeout)
                report["diagnostics"].append(record)
                if record["returncode"] != 0:
                    raise VerificationError("native diagnostic tests failed; inspect retained logs")
                summaries = list(evidence.glob("*/summary.json"))
                if len(summaries) != 3:
                    raise VerificationError("native diagnostic coverage incomplete")
                if {summary.parent.name for summary in summaries} != {"cmesh-2", "cmesh-4", "class-vc"}:
                    raise VerificationError("native diagnostic profiles incomplete")
                for summary in summaries:
                    value = json.loads(summary.read_text())
                    if value["binary_sha256"] != build["binary"]["sha256"] or value["qualification"] is not False:
                        raise VerificationError("foreign/qualified native evidence")
                require_same(source, before)
                require_same(output / build["directory"], before)
                if file_fact(output / build["directory"] / "booksim") != build["binary"]:
                    raise VerificationError("binary drift during native diagnostics")
        if require_byte_identical and not report["byte_identical"]:
            raise VerificationError("byte mismatch; no reproducibility claim")
        for tool in report["tools"].values():
            if file_fact(tool["path"])["sha256"] != tool["sha256"]:
                raise VerificationError("tool executable drift during build")
        if native_diagnostics and verification_inputs(repo) != report["verification_inputs"]:
            raise VerificationError("verification implementation/fixture drift during diagnostics")
        report["success"] = True
    except (VerificationError, OSError, subprocess.SubprocessError) as exc:
        report["failure"] = str(exc)
    # Bind every retained native config/trace/dump/log/evidence and both binaries.
    report["artifacts"] = retained_artifacts(output)
    report["report_sha256"] = digest(report)
    (output / "verification.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--source-root", type=Path, default=REPO / "third_party/booksim2/src")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--cxx", default="g++")
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--container-digest")
    parser.add_argument("--build-only", action="store_true", help="explicitly omit native diagnostic tests")
    parser.add_argument("--allow-byte-mismatch", action="store_true", help="retain honest mismatch, NOT reproducibility")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--verify-report", type=Path)
    args = parser.parse_args()
    try:
        if args.verify_report:
            verify_report(args.verify_report)
            print("retained diagnostic artifacts verified; NOT qualification")
            return 0
        if args.output_root is None:
            parser.error("--output-root is required for builds")
        report = verify_builds(repo_root=args.repo_root, source_root=args.source_root, output_root=args.output_root,
                               cxx=args.cxx, cc=args.cc, container_digest=args.container_digest,
                               native_diagnostics=not args.build_only, require_byte_identical=not args.allow_byte_mismatch,
                               timeout=args.timeout)
        print(f"DIAGNOSTIC_UNQUALIFIED success={report['success']} byte_identical={report['byte_identical']}")
        if report["failure"]:
            print(report["failure"], file=sys.stderr)
        return 0 if report["success"] else 1
    except (VerificationError, OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
