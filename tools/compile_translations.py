"""Compile gettext .po catalogs to .mo files for BlindRSS builds.

The parser/writer live in core/po_compile.py so the frozen app can reuse them
for over-the-air translation updates (only .mo files are bundled, so downloaded
catalogs are compiled on the user's machine). This module stays the build's
entry point and re-exports the same names it always exposed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Run as a script ("python tools/compile_translations.py") sys.path[0] is tools/,
# so the repo root has to be added before core can be imported.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.po_compile import (  # noqa: E402,F401  (re-exported for the build and tests)
    DOMAIN,
    compile_catalog,
    iter_catalogs,
    parse_po_text,
    read_po,
    write_mo,
)


DEFAULT_LOCALE_ROOT = ROOT / "locale"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile BlindRSS gettext catalogs.")
    parser.add_argument("--locale-root", default=str(DEFAULT_LOCALE_ROOT))
    args = parser.parse_args()

    locale_root = Path(args.locale_root)
    catalogs = iter_catalogs(locale_root)
    if not catalogs:
        print(f"No {DOMAIN}.po catalogs found under {locale_root}.")
        return 0

    for po_path in catalogs:
        mo_path = compile_catalog(po_path)
        print(f"Compiled {po_path} -> {mo_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
