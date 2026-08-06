#!/usr/bin/env python3
"""Backward-compat entry point. The original minimax_max_prices.py is now
a package (`minimax_max_prices/`); this file preserves the old
`python minimax_max_prices.py` invocation by delegating to the
package's __main__."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from minimax_max_prices import _translate_args
from cli import main as cli_main
sys.exit(cli_main(_translate_args(sys.argv[1:])))
