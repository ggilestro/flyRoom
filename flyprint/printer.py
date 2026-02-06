"""CUPS printing functionality for FlyPrint agent."""

import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Try to import cups, but make it optional
try:
    import cups

    CUPS_AVAILABLE = True
except ImportError:
    CUPS_AVAILABLE = False
    logger.warning("pycups not available - using lp command fallback")


class PrinterError(Exception):
    """Error during printing operation."""

    pass


class CupsPrinter:
    """Wrapper for CUPS printing operations."""

    def __init__(self, printer_name: str | None = None):
        """Initialize CUPS printer connection.

        Args:
            printer_name: CUPS printer name (None = default printer).
        """
        self.printer_name = printer_name
        self._connection = None

        if CUPS_AVAILABLE:
            try:
                self._connection = cups.Connection()
            except RuntimeError as e:
                logger.error(f"Could not connect to CUPS: {e}")

    @property
    def is_available(self) -> bool:
        """Check if CUPS is available and connected.

        Returns:
            bool: True if CUPS is available.
        """
        return self._connection is not None or self._check_lp_available()

    def _check_lp_available(self) -> bool:
        """Check if lp command is available (fallback).

        Returns:
            bool: True if lp command exists.
        """
        try:
            result = subprocess.run(["which", "lp"], capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def get_printers(self) -> list[dict]:
        """Get list of available printers.

        Returns:
            list[dict]: List of printer info dicts with 'name' and 'state'.
        """
        if self._connection:
            try:
                printers = self._connection.getPrinters()
                return [
                    {
                        "name": name,
                        "state": info.get("printer-state", 0),
                        "state_message": info.get("printer-state-message", ""),
                        "is_default": info.get("printer-is-default", False),
                    }
                    for name, info in printers.items()
                ]
            except Exception as e:
                logger.error(f"Error getting printers: {e}")
                return []
        else:
            # Fallback: use lpstat
            try:
                result = subprocess.run(
                    ["lpstat", "-p"], capture_output=True, text=True, timeout=10
                )
                printers = []
                for line in result.stdout.strip().split("\n"):
                    if line.startswith("printer "):
                        parts = line.split()
                        if len(parts) >= 2:
                            printers.append(
                                {
                                    "name": parts[1],
                                    "state": 3,  # Assume idle
                                    "state_message": "",
                                    "is_default": False,
                                }
                            )
                return printers
            except (subprocess.TimeoutExpired, FileNotFoundError):
                return []

    def get_default_printer(self) -> str | None:
        """Get the default printer name.

        Returns:
            str | None: Default printer name or None.
        """
        if self._connection:
            try:
                return self._connection.getDefault()
            except Exception as e:
                logger.error(f"Error getting default printer: {e}")
                return None
        else:
            # Fallback: use lpstat -d
            try:
                result = subprocess.run(["lpstat", "-d"], capture_output=True, text=True, timeout=5)
                if "system default destination:" in result.stdout:
                    return result.stdout.split(":")[-1].strip()
                return None
            except (subprocess.TimeoutExpired, FileNotFoundError):
                return None

    def get_printer_status(self, printer_name: str | None = None) -> str:
        """Get status of a specific printer.

        Args:
            printer_name: Printer name (None = configured or default).

        Returns:
            str: Status string ('ready', 'offline', 'busy', 'unknown').
        """
        name = printer_name or self.printer_name or self.get_default_printer()
        if not name:
            return "unknown"

        if self._connection:
            try:
                printers = self._connection.getPrinters()
                if name not in printers:
                    return "offline"

                state = printers[name].get("printer-state", 0)
                # CUPS states: 3=idle, 4=processing, 5=stopped
                if state == 3:
                    return "ready"
                elif state == 4:
                    return "busy"
                elif state == 5:
                    return "offline"
                return "unknown"
            except Exception as e:
                logger.error(f"Error getting printer status: {e}")
                return "unknown"
        else:
            return "unknown"

    def print_pdf(
        self,
        pdf_data: bytes,
        title: str = "FlyPrint Label",
        copies: int = 1,
        printer_name: str | None = None,
        orientation: int = 0,
    ) -> bool:
        """Print a PDF document.

        Args:
            pdf_data: PDF file contents as bytes.
            title: Print job title.
            copies: Number of copies.
            printer_name: Override printer name.
            orientation: Rotation in degrees (0, 90, 180, 270).

        Returns:
            bool: True if print job was submitted successfully.

        Raises:
            PrinterError: If printing fails.
        """
        name = printer_name or self.printer_name or self.get_default_printer()
        if not name and self._connection:
            # If no specific printer and using pycups, get default
            name = self.get_default_printer()

        # Map orientation degrees to CUPS orientation-requested values
        # 3=portrait, 4=landscape, 5=reverse-landscape, 6=reverse-portrait
        orientation_map = {0: 3, 90: 4, 180: 6, 270: 5}
        cups_orientation = orientation_map.get(orientation, 3)

        # Write PDF to temp file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf_data)
            temp_path = f.name

        try:
            if self._connection and name:
                # Use pycups
                job_id = self._connection.printFile(
                    name,
                    temp_path,
                    title,
                    {"copies": str(copies), "orientation-requested": str(cups_orientation)},
                )
                logger.info(f"Print job {job_id} submitted to {name}")
                return True
            else:
                # Fallback to lp command
                cmd = ["lp", "-t", title, "-n", str(copies)]
                if name:
                    cmd.extend(["-d", name])
                # Set page size for Dymo 11352 labels - w72h154 (portrait: ~25mm x 54mm)
                cmd.extend(["-o", "PageSize=w72h154"])
                # Force 100% scaling (no resize)
                cmd.extend(["-o", "scaling=100"])
                cmd.extend(["-o", "fit-to-page=false"])
                # Additional orientation if specified (0=portrait/3, 90=landscape/4, etc.)
                if orientation != 0:
                    cmd.extend(["-o", f"orientation-requested={cups_orientation}"])
                cmd.append(temp_path)

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if result.returncode != 0:
                    raise PrinterError(f"lp command failed: {result.stderr}")

                logger.info(f"Print job submitted via lp: {result.stdout.strip()}")
                return True

        except subprocess.TimeoutExpired as err:
            raise PrinterError("Print command timed out") from err
        except FileNotFoundError as err:
            raise PrinterError("lp command not found - is CUPS installed?") from err
        finally:
            # Clean up temp file
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
        """Print a PNG image (optimized for Dymo printers).

        Uses lpr with ppi option for correct sizing on thermal printers.

        Args:
            png_data: PNG file contents as bytes.
            title: Print job title.
            copies: Number of copies.
            printer_name: Override printer name.
            page_size: CUPS page size (e.g., 'w72h154' for Dymo 11352).
            dpi: Image DPI (should match image resolution).

        Returns:
            bool: True if print job was submitted successfully.

        Raises:
            PrinterError: If printing fails.
        """
        name = printer_name or self.printer_name or self.get_default_printer()

        # Write PNG to temp file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(png_data)
            temp_path = f.name

        try:
            # Use lpr command - image at 72 DPI matches CUPS default
            cmd = ["lpr"]
            if name:
                cmd.extend(["-P", name])
            cmd.extend(["-#", str(copies)])
            # Set page size to match label
            cmd.extend(["-o", f"PageSize={page_size}"])
            # Don't scale the image
            cmd.extend(["-o", "scaling=100"])
            cmd.extend(["-o", "fit-to-page=false"])
            cmd.extend(["-o", "PrintQuality=Graphics"])
            cmd.append(temp_path)

            logger.info(f"Print command: {' '.join(cmd)}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                raise PrinterError(f"lpr command failed: {result.stderr}")

            logger.info("Print job submitted via lpr")
            return True

        except subprocess.TimeoutExpired as err:
            raise PrinterError("Print command timed out") from err
        except FileNotFoundError as err:
            raise PrinterError("lpr command not found - is CUPS installed?") from err
        finally:
            # Clean up temp file
            Path(temp_path).unlink(missing_ok=True)


def get_printer(printer_name: str | None = None) -> CupsPrinter:
    """Factory function for CupsPrinter.

    Args:
        printer_name: Optional printer name.

    Returns:
        CupsPrinter: Printer instance.
    """
    return CupsPrinter(printer_name)
