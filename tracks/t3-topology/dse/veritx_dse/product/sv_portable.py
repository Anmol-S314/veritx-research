"""Emit the common SystemVerilog subset every tool can read.

The product emits readable SystemVerilog: functions with early ``return``s,
``automatic`` function-local declarations, and ``initial``-block
parameter-contract ``$fatal`` checks. Verilator accepts all three. Yosys does
not: it parses ``return`` as a task call (``Can't resolve task name 'return'``),
rejects ``automatic`` in a declaration (``unexpected TOK_AUTOMATIC``), and has
no ``$fatal``.

None of that is semantics, so the emitter passes every synthesizable module
through :func:`portable_sv` on the way out:

* ``return e;`` in a case item becomes ``fname = e;``;
* ``return e;`` in tail position becomes ``fname = e;``;
* ``automatic <type> x;`` inside a *function* loses the redundant keyword (the
  enclosing function is already automatic). The same keyword is kept inside a
  procedural block: a block-scope variable is static there, so ``automatic``
  is what stops a synthesis tool from carrying an undefined initial value for
  it as stored state;
* an ``initial`` block holding ``$fatal`` is wrapped in ``ifndef SYNTHESIS``.

The rewrite refuses anything it cannot prove safe: a ``return`` that is not the
last action on its path, or a ``return`` outside a function, raises instead of
guessing. Testbenches are never ported — they are simulation-only, and Yosys
never reads them.
"""
from __future__ import annotations

import re

FUNC_OPEN = re.compile(r"^\s*function\b.*?\b(\w+)\s*\(")
CASE_RETURN = re.compile(r"^(\s*)((?:default|[\w']+)\s*:\s*)return\b(.*)$")
PLAIN_RETURN = re.compile(r"^(\s*)return\b(.*)$")
AUTOMATIC_LOCAL = re.compile(
    r"^(\s*)automatic\s+([A-Za-z_]\w*(?:::\w+)?)\b(.*)$")


def strip_comments(text: str) -> str:
    """Remove // and /* */ comments so keyword searches only see code."""
    out = []
    i = 0
    in_block = False
    while i < len(text):
        if in_block:
            j = text.find("*/", i)
            if j < 0:
                return "".join(out)
            i = j + 2
            in_block = False
            continue
        j = text.find("/*", i)
        k = text.find("//", i)
        if k >= 0 and (j < 0 or k < j):
            out.append(text[i:k])
            nl = text.find("\n", k)
            if nl < 0:
                return "".join(out)
            out.append("\n")
            i = nl + 1
            continue
        if j >= 0:
            out.append(text[i:j])
            i = j + 2
            in_block = True
            continue
        out.append(text[i:])
        break
    return "".join(out)



def guard_fatal_blocks(text: str, stats: dict) -> str:
    """Wrap `initial begin ... end` blocks containing $fatal in ifndef SYNTHESIS."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    wrapped = 0
    while i < len(lines):
        if re.match(r"^\s*initial\s+begin\s*$", lines[i]):
            depth = 0
            j = i
            while j < len(lines):
                depth += len(re.findall(r"\bbegin\b", lines[j])) - len(re.findall(r"\bend\b", lines[j]))
                if depth <= 0 and j > i:
                    break
                j += 1
            block = "".join(lines[i:j + 1])
            already_guarded = any(l.strip() == "`ifndef SYNTHESIS"
                                  for l in out[-1:] if l.strip())
            if "$fatal" in block and not already_guarded:
                out.append("`ifndef SYNTHESIS\n")
                out.append(block)
                out.append("`endif\n")
                wrapped += 1
            else:
                out.append(block)
            i = j + 1
            continue
        out.append(lines[i])
        i += 1
    stats["fatal_blocks_guarded"] = wrapped
    return "".join(out)

_BLOCK_OPEN = re.compile(r"\bbegin\b\s*(?::\s*\w+)?\s*$")
_DECLARATION = re.compile(
    r"^(\s*)(automatic\s+)?([A-Za-z_]\w*(?:::\w+)?(?:\s*\[[^\]]*\])*)\s+"
    r"([A-Za-z_]\w*)\s*(?:=\s*(.+?))?;\s*$")
_NOT_A_TYPE = {
    # A net declaration is not a variable: `wire x = e;` is a continuous
    # assignment, so splitting it into `wire x;` plus `x = e;` inside a
    # procedural block is a syntax error.
    "wire", "tri", "tri0", "tri1", "triand", "trior", "wand", "wor",
    "supply0", "supply1", "uwire",
    "assign", "if", "else", "for", "while", "repeat", "case", "casez", "casex",
    "begin", "end", "return", "endcase", "default", "else", "assert", "wait",
    "function", "task", "initial", "always", "always_ff", "always_comb",
    "always_latch", "endfunction", "endtask", "unique", "priority", "do",
}


_END_KEYWORDS = ("endcase", "endgenerate", "endfunction", "endtask", "endmodule",
                 "endpackage", "endinterface", "endprogram", "endclass")


def _without_comment(line: str) -> str:
    position = line.find("//")
    return (line if position < 0 else line[:position]).strip()


def _block_kind(line: str) -> str:
    """`open`, `close`, `close_open`, `statement` or `skip` for one source line."""
    stripped = _without_comment(line)
    if not stripped:
        return "skip"
    opens = bool(_BLOCK_OPEN.search(stripped))
    if stripped.startswith(_END_KEYWORDS):
        return "statement"
    closes = stripped == "end" or stripped.startswith("end ") or stripped.startswith("end;")
    if closes and opens:
        return "close_open"
    if closes:
        return "close"
    if opens:
        return "open"
    return "statement"


def _declaration_of(line: str):
    """(indent, type, name, value, automatic) for a declaration, else None."""
    match = _DECLARATION.match(line)
    if match is None:
        return None
    automatic = "automatic " if match.group(2) else ""
    type_text = " ".join(match.group(3).split())
    if type_text.split(" ")[0] in _NOT_A_TYPE:
        return None
    return (match.group(1), type_text, match.group(4), match.group(5), automatic)


def hoist_block_locals(text: str, stats: dict) -> str:
    """Declare a block-local at the top of its block, assign where it stood.

    SystemVerilog requires a block's declarations to precede its first
    statement, and Yosys rejects an initialised declaration inside an
    ``always`` block outright, so an initialised local that appears after a
    statement is declared at the block top and assigned in place.  The
    assignment keeps the per-execution initialisation the declaration had.
    """
    lines = text.split("\n")
    output: list[str] = []
    frames: list[dict] = []
    stack: list[dict] = []
    hoisted = 0
    for line in lines:
        kind = _block_kind(line)
        if kind == "open":
            frame = {"index": len(output), "locals": [], "seen_statement": False}
            frames.append(frame)
            stack.append(frame)
            output.append(line)
            continue
        if kind == "close":
            if not stack:
                raise SystemExit(f"unbalanced 'end' while hoisting: {line.strip()!r}")
            stack.pop()
            output.append(line)
            continue
        if kind == "close_open":
            if not stack:
                raise SystemExit(f"unbalanced 'end' while hoisting: {line.strip()!r}")
            stack.pop()
            frame = {"index": len(output), "locals": [], "seen_statement": False}
            frames.append(frame)
            stack.append(frame)
            output.append(line)
            continue
        declaration = _declaration_of(line)
        if declaration is not None and stack:
            indent, type_text, name, value, automatic = declaration
            frame = stack[-1]
            # `automatic` is kept: a block-scope variable is static without
            # it, and a static one hands synthesis an undefined initial value
            # to carry as stored state.
            frame["locals"].append(f"{indent}{automatic}{type_text} {name};")
            # The initialiser becomes a plain assignment in place: inside a
            # block it is a per-execution assignment, and Yosys refuses the
            # initialised declaration form outright.
            if value is not None:
                output.append(f"{indent}{name} = {value.strip()};")
            hoisted += 1
            continue
        if kind == "statement" and stack:
            stack[-1]["seen_statement"] = True
        output.append(line)
    if stack:
        raise SystemExit("unbalanced 'begin' while hoisting block locals")
    for frame in sorted(frames, key=lambda item: item["index"], reverse=True):
        locals_ = list(dict.fromkeys(frame["locals"]))
        if locals_:
            output[frame["index"] + 1:frame["index"] + 1] = locals_
    stats["block_locals_hoisted"] = hoisted
    return "\n".join(output)


def transform(text: str) -> tuple[str, dict]:
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    fn: str | None = None
    stats = {"case_returns": 0, "tail_returns": 0, "automatic_locals": 0,
             "fatal_blocks_guarded": 0, "block_locals_hoisted": 0, "functions": []}
    i = 0

    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        m_open = FUNC_OPEN.match(raw)
        if m_open and not stripped.startswith("endfunction"):
            fn = m_open.group(1)
            stats["functions"].append(fn)
            out.append(raw)
            i += 1
            continue
        if stripped == "endfunction":
            fn = None
            out.append(raw)
            i += 1
            continue

        m_loc = AUTOMATIC_LOCAL.match(raw) if fn is not None else None
        if m_loc:
            indent, kind, rest = m_loc.groups()
            tail = rest if rest.endswith("\n") else rest + "\n"
            out.append(f"{indent}{kind}{tail}")
            stats["automatic_locals"] += 1
            i += 1
            continue

        for pattern, kind in ((CASE_RETURN, "case"), (PLAIN_RETURN, "tail")):
            m = pattern.match(raw)
            if not m:
                continue
            if fn is None:
                raise SystemExit(f"line {i+1}: return outside a function")
            # Gather the whole statement, which may span lines.
            stmt = raw
            consumed = 1
            while ";" not in stmt.rstrip().split("//")[0]:
                if i + consumed >= len(lines):
                    raise SystemExit(f"line {i+1}: unterminated return")
                stmt += lines[i + consumed]
                consumed += 1
            indent = re.match(r"^(\s*)", stmt).group(1)
            body = " ".join(stmt.split())  # already whitespace-collapsed and stripped
            if kind == "case":
                m2 = re.match(r"^((?:default|[\w']+)\s*:\s*)return\b(.*);$", body)
                if not m2:
                    raise SystemExit(f"line {i+1}: cannot parse case return: {body!r}")
                label, expr = m2.groups()
                out.append(f"{indent}{label}{fn} = {expr};\n")
                stats["case_returns"] += 1
            else:
                m2 = re.match(r"^return\b(.*);$", body)
                if not m2:
                    raise SystemExit(f"line {i+1}: cannot parse return: {body!r}")
                expr = m2.group(1)
                nxt = next((l.strip() for l in lines[i + consumed:] if l.strip()), "")
                if nxt != "endfunction":
                    raise SystemExit(
                        f"line {i+1}: return is not in tail position (next statement is {nxt!r}); "
                        "refusing to rewrite")
                out.append(f"{indent}{fn} = {expr};\n")
                stats["tail_returns"] += 1
            i += consumed
            break
        else:
            out.append(raw)
            i += 1

    result = "".join(out)
    result = guard_fatal_blocks(result, stats)
    result = hoist_block_locals(result, stats)
    code = strip_comments(result)
    leftovers = [f"{n}: {l.strip()}" for n, l in enumerate(code.splitlines(), 1)
                 if re.search(r"\breturn\b", l)]
    if leftovers:
        raise SystemExit("return statements survived:\n" + "\n".join(leftovers[:10]))
    return result, stats



__all__ = ["portable_sv", "transform", "strip_comments", "guard_fatal_blocks",
           "hoist_block_locals"]


def portable_sv(text: str) -> str:
    """The ported source, for an emitter to write instead of its raw text."""
    ported, _stats = transform(text)
    return ported
