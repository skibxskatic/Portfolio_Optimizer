"""
parsers/__init__.py — Broker Adapter Registry

ADAPTER_REGISTRY is an ordered list of all broker adapters.
Detection runs in order — the first adapter whose detect() returns True wins.
GenericAdapter is always last (guaranteed fallback).
"""

from parsers.fidelity import FidelityAdapter
from parsers.schwab import SchwabAdapter
from parsers.vanguard import VanguardAdapter
from parsers.troweprice import TRowePriceAdapter
from parsers.principal import PrincipalAdapter
from parsers.generic import GenericAdapter

ADAPTER_REGISTRY = [
    FidelityAdapter(),
    SchwabAdapter(),
    VanguardAdapter(),
    TRowePriceAdapter(),
    PrincipalAdapter(),
    GenericAdapter(),
]

__all__ = [
    'ADAPTER_REGISTRY',
    'FidelityAdapter',
    'SchwabAdapter',
    'VanguardAdapter',
    'TRowePriceAdapter',
    'PrincipalAdapter',
    'GenericAdapter',
]
