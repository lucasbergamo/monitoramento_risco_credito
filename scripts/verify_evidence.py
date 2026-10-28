"""Entry point para verificar uma campanha pelo identificador explícito."""

import sys

from src.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["verify-evidence", *sys.argv[1:]]))
