# Backward compatibility shim — delegates to FidelityAdapter
# portfolio_analyzer.py calls these functions directly; they now route through the adapter layer.
import sys
from pathlib import Path

_src_dir = Path(__file__).parent
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from parsers.fidelity import FidelityAdapter as _FidelityAdapter
from parsers.fidelity import unroll_tax_lots  # re-export for any direct callers

_adapter = _FidelityAdapter()


def load_fidelity_positions(path):
    return _adapter.parse_positions(path)


def load_fidelity_history(path):
    return _adapter.parse_history(path)
