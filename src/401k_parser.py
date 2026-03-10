# Backward compatibility shim — delegates to parsers.fidelity
# Any legacy code that imports 401k_parser directly still works unchanged.
import sys
from pathlib import Path

_src_dir = Path(__file__).parent
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from parsers.fidelity import (
    extract_plan_menu,
    extract_current_holdings,
    get_plan_menu_tickers,
    parse_401k_options_file,
    find_401k_options_file,
)

__all__ = [
    'extract_plan_menu',
    'extract_current_holdings',
    'get_plan_menu_tickers',
    'parse_401k_options_file',
    'find_401k_options_file',
]
