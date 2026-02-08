"""Windows printing backend using win32print and ShellExecute."""

import logging
import tempfile
from pathlib import Path

from flyprint.printing.base import PrinterError

logger = logging.getLogger(__name__)

# Try to import win32 modules
try:
    import win32api
    import win32print

    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False
    logger.debug("pywin32 not available - Windows printing disabled")


class Win32Printer:
    """Windows printing backend using win32print API."""

    def __init__(self, printer_name: str | None = None):
        """Initialize Windows printer.

        Args:
            printer_name: Printer name (None = default printer).
        """
        self.printer_name = printer_name

    @property
    def is_available(self) -> bool:
        """Check if Windows printing is available.

        Returns:
            bool: True if win32print is importable.
        """
        return WIN32_AVAILABLE

    def get_printers(self) -> list[dict]:
        """Get list of available printers.

        Returns:
            list[dict]: List of printer info dicts.
        """
        if not WIN32_AVAILABLE:
            return []

        try:
            default = self.get_default_printer()
            # Reason: Flag 2 = PRINTER_ENUM_LOCAL, Flag 4 = PRINTER_ENUM_CONNECTIONS
            printers = win32print.EnumPrinters(
                win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            )
            result = []
            for _flags, _description, name, comment in printers:
                result.append(
                    {
                        "name": name,
                        "state": 3,  # Map to CUPS-like idle state
                        "state_message": comment or "",
                        "is_default": name == default,
                    }
                )
            return result
        except Exception as e:
            logger.error(f"Error enumerating printers: {e}")
            return []

    def get_default_printer(self) -> str | None:
        """Get the default printer name.

        Returns:
            str | None: Default printer name or None.
        """
        if not WIN32_AVAILABLE:
            return None

        try:
            return win32print.GetDefaultPrinter()
        except Exception as e:
            logger.error(f"Error getting default printer: {e}")
            return None

    def get_printer_status(self, printer_name: str | None = None) -> str:
        """Get status of a specific printer.

        Args:
            printer_name: Printer name (None = configured or default).

        Returns:
            str: Status string ('ready', 'offline', 'busy', 'unknown').
        """
        if not WIN32_AVAILABLE:
            return "unknown"

        name = printer_name or self.printer_name or self.get_default_printer()
        if not name:
            return "unknown"

        try:
            handle = win32print.OpenPrinter(name)
            try:
                info = win32print.GetPrinter(handle, 2)
                status = info["Status"]
                if status == 0:
                    return "ready"
                # Reason: Common win32print status bits
                elif status & 0x00000400:  # PRINTER_STATUS_OFFLINE
                    return "offline"
                elif status & 0x00000004:  # PRINTER_STATUS_PRINTING
                    return "busy"
                return "unknown"
            finally:
                win32print.ClosePrinter(handle)
        except Exception as e:
            logger.error(f"Error getting printer status: {e}")
            return "unknown"

    def print_pdf(
        self,
        pdf_data: bytes,
        title: str = "FlyPrint Label",
        copies: int = 1,
        printer_name: str | None = None,
        orientation: int = 0,
    ) -> bool:
        """Print a PDF document using ShellExecute.

        Delegates to the system's default PDF handler (e.g., Adobe Reader,
        SumatraPDF) for actual rendering and printing.

        Args:
            pdf_data: PDF file contents as bytes.
            title: Print job title.
            copies: Number of copies.
            printer_name: Override printer name.
            orientation: Rotation in degrees (ignored on Windows - handled by driver).

        Returns:
            bool: True if print job was submitted successfully.

        Raises:
            PrinterError: If printing fails.
        """
        if not WIN32_AVAILABLE:
            raise PrinterError("pywin32 is not installed")

        name = printer_name or self.printer_name or self.get_default_printer()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf_data)
            temp_path = f.name

        try:
            for _ in range(copies):
                if name:
                    # Print to specific printer via ShellExecute
                    win32api.ShellExecute(
                        0,
                        "printto",
                        temp_path,
                        f'"{name}"',
                        ".",
                        0,  # SW_HIDE
                    )
                else:
                    # Print to default printer
                    win32api.ShellExecute(
                        0,
                        "print",
                        temp_path,
                        None,
                        ".",
                        0,
                    )
            logger.info(f"Print job submitted to {name or 'default'} ({copies} copies)")
            return True
        except Exception as e:
            raise PrinterError(f"Windows print failed: {e}") from e
        finally:
            # Reason: Small delay to let the print spooler read the file
            import time

            time.sleep(2)
            Path(temp_path).unlink(missing_ok=True)

    def print_png(
        self,
        png_data: bytes,
        title: str = "FlyPrint Label",
        copies: int = 1,
        printer_name: str | None = None,
        page_size: str = "w72h154",
        dpi: int = 300,
    ) -> bool:
        """Print a PNG image using ShellExecute.

        Args:
            png_data: PNG file contents as bytes.
            title: Print job title.
            copies: Number of copies.
            printer_name: Override printer name.
            page_size: Page size (informational on Windows).
            dpi: Image DPI (informational on Windows).

        Returns:
            bool: True if print job was submitted successfully.

        Raises:
            PrinterError: If printing fails.
        """
        if not WIN32_AVAILABLE:
            raise PrinterError("pywin32 is not installed")

        name = printer_name or self.printer_name or self.get_default_printer()

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(png_data)
            temp_path = f.name

        try:
            for _ in range(copies):
                if name:
                    win32api.ShellExecute(
                        0,
                        "printto",
                        temp_path,
                        f'"{name}"',
                        ".",
                        0,
                    )
                else:
                    win32api.ShellExecute(
                        0,
                        "print",
                        temp_path,
                        None,
                        ".",
                        0,
                    )
            logger.info(f"PNG print job submitted to {name or 'default'} ({copies} copies)")
            return True
        except Exception as e:
            raise PrinterError(f"Windows PNG print failed: {e}") from e
        finally:
            import time

            time.sleep(2)
            Path(temp_path).unlink(missing_ok=True)
