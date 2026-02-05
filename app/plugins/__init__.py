"""Plugins module for external integrations."""

from app.plugins.base import StockImportData, StockPlugin
from app.plugins.flybase.client import (
    # Backward compatibility aliases
    BDSCPlugin,
    FlyBasePlugin,
    get_bdsc_plugin,
    get_flybase_plugin,
)

__all__ = [
    "StockPlugin",
    "StockImportData",
    "FlyBasePlugin",
    "get_flybase_plugin",
    # Backward compatibility
    "BDSCPlugin",
    "get_bdsc_plugin",
]
