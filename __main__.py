from __future__ import annotations

import argparse

from . import launch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch the ManufacturingStudio desktop shell.")
    parser.add_argument("factory_xml", nargs="?", help="Optional path to a factory XML document.")
    args = parser.parse_args(argv)
    return launch(args.factory_xml)


if __name__ == "__main__":
    raise SystemExit(main())
