"""Engineering tools that live beside the engine (sweepers, generators).

This is a REGULAR package, not a namespace portion, and that is deliberate:
`scripts/tools.py` is a standalone vendored-tool manager that is only ever
run as a script (`python3 scripts/tools.py`), but several test modules put
`scripts/` on `sys.path`. A regular package wins import resolution by path
order, whereas a namespace package loses to any regular module anywhere on
the path — so without this file `import tools.<module>` resolves to
`scripts/tools.py` and fails with "'tools' is not a package".
"""