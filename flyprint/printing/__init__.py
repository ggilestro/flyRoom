"""Cross-platform printing abstraction.

Provides a unified printer interface across Linux/macOS (CUPS) and Windows (win32print).
Use get_printer() factory to get the appropriate backend for the current platform.
"""

import logging
import platform

from flyprint.printing.base import PrinterBackend, PrinterError

logger = logging.getLogger(__name__)


def get_printer(printer_name: str | None = None) -> PrinterBackend:
    """Factory function that returns the appropriate printer backend.

    Args:
        printer_name: Optional printer name.

    Returns:
        PrinterBackend: Platform-specific printer instance.
    """
    system = platform.system()

    if system == "Windows":
        from flyprint.printing.win32_printer import Win32Printer

        return Win32Printer(printer_name)
    else:
        # Linux and macOS both use CUPS
        from flyprint.printing.cups_printer import CupsPrinter

        return CupsPrinter(printer_name)


__all__ = [
    "PrinterBackend",
    "PrinterError",
    "get_printer",
]
