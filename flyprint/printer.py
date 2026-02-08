"""Backward-compatible printer module.

Re-exports from flyprint.printing for code that imports from flyprint.printer directly.
"""

from flyprint.printing import PrinterError, get_printer
from flyprint.printing.cups_printer import CupsPrinter

__all__ = [
    "CupsPrinter",
    "PrinterError",
    "get_printer",
]
