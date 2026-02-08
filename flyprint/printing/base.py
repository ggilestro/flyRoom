"""Abstract printer backend interface."""

from typing import Protocol, runtime_checkable


class PrinterError(Exception):
    """Error during printing operation."""

    pass


@runtime_checkable
class PrinterBackend(Protocol):
    """Protocol defining the printer backend interface.

    All platform-specific printer implementations must satisfy this protocol.
    """

    @property
    def is_available(self) -> bool:
        """Check if the printing system is available.

        Returns:
            bool: True if printing is available.
        """
        ...

    def get_printers(self) -> list[dict]:
        """Get list of available printers.

        Returns:
            list[dict]: List of printer info dicts with 'name', 'state',
                        'state_message', and 'is_default' keys.
        """
        ...

    def get_default_printer(self) -> str | None:
        """Get the default printer name.

        Returns:
            str | None: Default printer name or None.
        """
        ...

    def get_printer_status(self, printer_name: str | None = None) -> str:
        """Get status of a specific printer.

        Args:
            printer_name: Printer name (None = configured or default).

        Returns:
            str: Status string ('ready', 'offline', 'busy', 'unknown').
        """
        ...

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
        ...

    def print_png(
        self,
        png_data: bytes,
        title: str = "FlyPrint Label",
        copies: int = 1,
        printer_name: str | None = None,
        page_size: str = "w72h154",
        dpi: int = 300,
    ) -> bool:
        """Print a PNG image.

        Args:
            png_data: PNG file contents as bytes.
            title: Print job title.
            copies: Number of copies.
            printer_name: Override printer name.
            page_size: Page size string.
            dpi: Image DPI.

        Returns:
            bool: True if print job was submitted successfully.

        Raises:
            PrinterError: If printing fails.
        """
        ...
