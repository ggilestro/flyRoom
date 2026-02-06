"""Label generation utilities for QR codes and barcodes."""

import io
from typing import Literal

import qrcode
from barcode import Code128
from barcode.writer import ImageWriter
from qrcode.constants import ERROR_CORRECT_M


def generate_qr_code(data: str, size: int = 200, box_size: int = 10) -> bytes:
    """Generate a QR code as PNG bytes.

    Args:
        data: Data to encode in QR code.
        size: Output image size in pixels.
        box_size: Size of each box in pixels.

    Returns:
        bytes: PNG image data.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=ERROR_CORRECT_M,
        box_size=box_size,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    # Resize if needed
    if img.size[0] != size:
        img = img.resize((size, size))

    # Convert to bytes
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def generate_barcode(data: str, barcode_type: Literal["code128"] = "code128") -> bytes:
    """Generate a barcode as PNG bytes.

    Args:
        data: Data to encode in barcode.
        barcode_type: Type of barcode (currently only code128 supported).

    Returns:
        bytes: PNG image data.
    """
    # Create barcode
    buffer = io.BytesIO()
    writer = ImageWriter()

    # Configure writer options
    writer.set_options(
        {
            "module_width": 0.3,
            "module_height": 10,
            "font_size": 8,
            "text_distance": 3,
            "quiet_zone": 2,
        }
    )

    code = Code128(data, writer=writer)
    code.write(buffer)

    return buffer.getvalue()


def generate_label_content(
    stock_id: str,
    genotype: str,
    include_qr: bool = True,
    include_barcode: bool = True,
    max_genotype_length: int = 50,
) -> dict:
    """Generate label content including codes.

    Args:
        stock_id: Stock ID for encoding.
        genotype: Genotype string.
        include_qr: Whether to include QR code.
        include_barcode: Whether to include barcode.
        max_genotype_length: Maximum genotype display length.

    Returns:
        dict: Label content with optional encoded images.
    """
    # Truncate genotype if too long
    display_genotype = genotype
    if len(genotype) > max_genotype_length:
        display_genotype = genotype[: max_genotype_length - 3] + "..."

    content = {
        "stock_id": stock_id,
        "genotype": genotype,
        "display_genotype": display_genotype,
    }

    if include_qr:
        # QR code contains full stock info URL
        qr_data = f"flypush://{stock_id}"
        content["qr_code"] = generate_qr_code(qr_data, size=150)

    if include_barcode:
        # Barcode contains just stock ID
        content["barcode"] = generate_barcode(stock_id)

    return content


# Label format presets
LABEL_FORMATS = {
    "dymo_11352": {
        "name": "Dymo 11352 Address Label",
        "width_mm": 54,
        "height_mm": 24,
        "orientation": "landscape",
        "font_size": 8,
        "qr_size": 50,
        "supports_pdf": True,
    },
    "dymo_99010": {
        "name": "Dymo 99010 Standard Address",
        "width_mm": 89,
        "height_mm": 28,
        "orientation": "landscape",
        "font_size": 9,
        "qr_size": 60,
        "supports_pdf": True,
    },
    "dymo_99012": {
        "name": "Dymo 99012 Large Address",
        "width_mm": 89,
        "height_mm": 36,
        "orientation": "landscape",
        "font_size": 10,
        "qr_size": 70,
        "supports_pdf": True,
    },
    "brother_29mm": {
        "name": "Brother 29mm",
        "width_mm": 29,
        "height_mm": 90,
        "orientation": "portrait",
        "font_size": 8,
        "qr_size": 80,
        "supports_pdf": True,
    },
    "brother_62mm": {
        "name": "Brother 62mm",
        "width_mm": 62,
        "height_mm": 100,
        "orientation": "landscape",
        "font_size": 10,
        "qr_size": 100,
        "supports_pdf": True,
    },
    "standard_1x2": {
        "name": "Standard 1x2 inch",
        "width_mm": 50.8,
        "height_mm": 25.4,
        "orientation": "landscape",
        "font_size": 8,
        "qr_size": 60,
        "supports_pdf": True,
    },
}


def get_label_format(format_name: str) -> dict:
    """Get label format configuration.

    Args:
        format_name: Name of the label format.

    Returns:
        dict: Label format configuration.

    Raises:
        ValueError: If format not found.
    """
    if format_name not in LABEL_FORMATS:
        raise ValueError(f"Unknown label format: {format_name}")
    return LABEL_FORMATS[format_name]


def list_label_formats() -> list[dict]:
    """List all available label formats.

    Returns:
        list[dict]: List of label format configurations.
    """
    return [{"id": k, **v} for k, v in LABEL_FORMATS.items()]
