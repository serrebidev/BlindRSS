"""Pull Caster's casting engine into this repository.

Caster (github.com/serrebidev/Caster) is where casting is developed and
measured against real receivers. This app does not re-implement any of it: it
takes Caster's protocol clients and streaming engine unchanged, so every fix
made there arrives here by running this script, not by porting it again.

    python tools/sync_caster.py                 # from ../Caster
    python tools/sync_caster.py --caster PATH   # from another checkout

What it writes, all at the repository root so both PyInstaller and the Debian
package pick them up like any other module:

* caster_extras.py, caster_devices.py, caster_config.py - copied verbatim.
  They import nothing but the standard library (soco is optional and lazy).
* caster_engine.py - the GUI-free top half of Caster's caster.py (media
  probing, the HLS relay, TsSource, the Device model, the asyncio loop
  thread), extracted verbatim. Everything from ``class MainFrame`` down is
  wx GUI and is left behind; core/casting.py is this app's replacement for it.

Never edit the generated files by hand: fix Caster and sync again.
"""

from __future__ import annotations

import argparse
import ast
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERBATIM = ("caster_extras.py", "caster_devices.py", "caster_config.py")
ENGINE = "caster_engine.py"
# Module-level coroutines defined after MainFrame that the engine needs.
TRAILING_HELPERS = ("_cancel", "_close_atv", "_set_atv_volume")


def _header(commit: str, version: str, what: str) -> str:
    return (
        f"# Vendored from Caster {version} ({commit}) by tools/sync_caster.py.\n"
        f"# {what}\n"
        "# Do not edit: fix it in Caster and run tools/sync_caster.py again.\n"
    )


def _caster_version(tree: ast.Module) -> str:
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and getattr(node.targets[0], "id", "") == "APP_VERSION"):
            return str(ast.literal_eval(node.value))
    raise SystemExit("caster.py: APP_VERSION not found")


def _used_names(source: str) -> set:
    return {node.id for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Name)} | {
        node.value.id for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)}


def extract_engine(source: str) -> tuple[str, str]:
    """(engine module body, Caster version) from caster.py's source."""
    tree = ast.parse(source)
    lines = source.splitlines()
    version = _caster_version(tree)
    start = end = None
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and getattr(node.targets[0], "id", "") == "APP_VERSION"):
            start = node.end_lineno          # everything after this line
        if isinstance(node, ast.ClassDef) and node.name == "MainFrame":
            end = node.lineno - 1            # up to the GUI
            if node.decorator_list:
                end = node.decorator_list[0].lineno - 1
    if start is None or end is None:
        raise SystemExit("caster.py: could not find the engine section")
    body = "\n".join(lines[start:end]).strip("\n") + "\n"
    helpers = []
    for node in tree.body:
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) \
                and node.name in TRAILING_HELPERS:
            helpers.append(ast.get_source_segment(source, node))
    missing = set(TRAILING_HELPERS) - {h.split("(")[0].split()[-1] for h in helpers}
    if missing:
        raise SystemExit(f"caster.py: helpers not found: {sorted(missing)}")
    body += "\n\n" + "\n\n\n".join(helpers) + "\n"

    # Caster's own imports, keeping the standard library and, from anything
    # else, only the names the engine section actually uses. That drops wx,
    # the GUI modules, pychromecast and pyatv: the engine needs none of them.
    used = _used_names(body)
    imports = ["from __future__ import annotations", ""]
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                bound = alias.asname or root
                if root in sys.stdlib_module_names and bound in used:
                    imports.append(ast.unparse(ast.Import(names=[alias])))
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            names = [a for a in node.names if (a.asname or a.name) in used]
            if names:
                imports.append(ast.unparse(ast.ImportFrom(
                    module=node.module, names=names, level=node.level)))
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.Assign)):
            break
    doc = ('"""Caster\'s streaming engine: probing, HLS relay, live TS reader, device model.\n\n'
           "Extracted verbatim from Caster's caster.py; see tools/sync_caster.py.\n"
           '"""\n')
    return doc + "\n" + "\n".join(imports) + "\n\n\n" + body, version


def _commit(caster_dir: str) -> str:
    try:
        return subprocess.run(["git", "-C", caster_dir, "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _write(path: str, text: str) -> None:
    # The repository's Python sources use LF.
    text = text.replace("\r\n", "\n")
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--caster", default=os.path.join(os.path.dirname(REPO_ROOT), "Caster"),
                        help="Caster checkout (default: ../Caster)")
    args = parser.parse_args(argv)
    caster_dir = os.path.abspath(args.caster)
    with open(os.path.join(caster_dir, "caster.py"), encoding="utf-8") as handle:
        caster_source = handle.read()
    commit = _commit(caster_dir)
    engine, version = extract_engine(caster_source)
    _write(os.path.join(REPO_ROOT, ENGINE),
           _header(commit, version, "GUI-free engine section of caster.py.") + engine)
    for name in VERBATIM:
        with open(os.path.join(caster_dir, name), encoding="utf-8") as handle:
            text = handle.read()
        _write(os.path.join(REPO_ROOT, name), _header(commit, version, f"Verbatim copy of {name}.") + text)
    print(f"Synced Caster {version} ({commit}): {ENGINE}, {', '.join(VERBATIM)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
