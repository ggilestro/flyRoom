"""Label generation for thermal printers.

Generates properly sized labels for direct thermal printing on label printers
like Dymo LabelWriter and Brother QL series.

For Dymo printers, PNG images work better than PDF due to CUPS scaling issues.
"""

import io
from datetime import date
from typing import Literal

import code128 as code128_pil  # Simple barcode library for PIL
import qrcode
from PIL import Image, ImageDraw, ImageFont
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import code128, qr  # reportlab barcode for PDFs
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

# Label format specifications
# For Dymo: use PNG output - CUPS treats images as 72 DPI by default
# width_mm/height_mm are physical label dimensions
# dpi should be 72 to match CUPS default interpretation
# left_margin_px: pixels to add on left to account for printer's non-printable area
# output_format: "png" for Dymo (avoids CUPS PDF scaling issues), "pdf" for others
LABEL_FORMATS = {
    # Dymo 11352: 25.4mm x 54mm label (physical dimensions)
    # Content is drawn in landscape (54mm wide x 25.4mm tall) because that's
    # how it appears when printed - the long edge is horizontal.
    "dymo_11352": {
        "width_mm": 25.4,
        "height_mm": 54,
        "output_format": "png",
        "cups_page": "w72h154",
        "left_margin_mm": 3,  # Leading edge margin (becomes left when label is read)
        "right_margin_mm": 2,  # Trailing edge margin (becomes right when label is read)
        "landscape_content": True,  # Draw content rotated 90° (54mm wide x 25.4mm tall)
    },
    "dymo_99010": {"width": 89, "height": 28, "rotation": 0, "output_format": "pdf"},
    "dymo_99012": {"width": 89, "height": 36, "rotation": 0, "output_format": "pdf"},
    "brother_29mm": {"width": 90, "height": 29, "rotation": 0, "output_format": "pdf"},
    "brother_62mm": {"width": 100, "height": 62, "rotation": 0, "output_format": "pdf"},
}


# Legacy compatibility - get size in mm
def _get_size_mm(fmt):
    if "width_mm" in fmt:
        return (fmt["width_mm"], fmt["height_mm"])
    if "width_pt" in fmt:
        return (fmt["width_pt"] / 2.834645, fmt["height_pt"] / 2.834645)
    return (fmt["width"], fmt["height"])


LABEL_SIZES = {k: _get_size_mm(v) for k, v in LABEL_FORMATS.items()}


def create_label_png(
    stock_id: str,
    genotype: str,
    label_format: str = "dymo_11352",
    source_info: str | None = None,
    location_info: str | None = None,
    code_type: Literal["qr", "barcode"] = "qr",
    print_date: str | None = None,
    for_print: bool = False,
) -> bytes:
    """Generate a PNG label image.

    Creates a high-quality raster image. For preview, outputs at 300 DPI.
    For print, can output at lower resolution suitable for CUPS/Dymo.

    Args:
        stock_id: Stock ID to display and encode in QR.
        genotype: Genotype string.
        label_format: Label format key.
        source_info: Optional source info.
        location_info: Optional location info.
        code_type: Type of code to render ("qr" or "barcode").
        print_date: Print date string (defaults to today if None).
        for_print: If True, output at 72 DPI for CUPS. If False, 300 DPI for preview.

    Returns:
        bytes: PNG image contents.
    """
    # Default print_date to today
    if print_date is None:
        print_date = date.today().isoformat()
    if label_format not in LABEL_FORMATS:
        raise ValueError(f"Unknown label format: {label_format}")

    fmt = LABEL_FORMATS[label_format]
    width_mm = fmt.get("width_mm", fmt.get("width", 25.4))
    height_mm = fmt.get("height_mm", fmt.get("height", 54))
    landscape_content = fmt.get("landscape_content", False)

    # DPI settings
    # Always render at 300 DPI for quality. For print output, supersample:
    # render at 300 DPI then LANCZOS downsample to 72 DPI.
    # Reason: CUPS treats 1 pixel = 1 point (1/72 inch) with scaling=100,
    # so output must be 72 DPI for correct physical size. Supersampling
    # gives sharp text/QR while maintaining correct dimensions.
    render_dpi = 300
    output_dpi = 72 if for_print else 300

    # Calculate pixel dimensions at render DPI
    # For landscape_content, we draw in landscape orientation (width/height swapped)
    if landscape_content:
        # Draw with long edge horizontal: 54mm wide x 25.4mm tall
        draw_width_mm = height_mm  # 54mm
        draw_height_mm = width_mm  # 25.4mm
    else:
        draw_width_mm = width_mm
        draw_height_mm = height_mm

    width_px = int(draw_width_mm / 25.4 * render_dpi)
    height_px = int(draw_height_mm / 25.4 * render_dpi)

    # Create white background image
    img = Image.new("RGB", (width_px, height_px), "white")
    draw = ImageDraw.Draw(img)

    # Pixels per mm at render DPI
    px_per_mm = render_dpi / 25.4

    # Margins in pixels — account for Dymo's non-printable area at label edges
    # After -90° rotation, left→top (leading edge), right→bottom (trailing edge)
    left_margin_mm = fmt.get("left_margin_mm", 3)
    right_margin_mm = fmt.get("right_margin_mm", 2)
    margin = int(left_margin_mm * px_per_mm)
    right_margin = int(right_margin_mm * px_per_mm)

    # Font sizes in mm, converted to pixels
    # - Large (title): 3mm
    # - Medium (genotype): 2.25mm
    # - Small (info): 1.9mm
    font_size_large = int(3 * px_per_mm)
    font_size_medium = int(2.25 * px_per_mm)
    font_size_small = int(1.9 * px_per_mm)

    # Try to load fonts from various locations
    font_paths = [
        # System fonts (Linux)
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        # Bundled with reportlab
        "/usr/local/lib/python3.11/site-packages/reportlab/fonts/VeraBd.ttf",
        "/usr/local/lib/python3.11/site-packages/reportlab/fonts/Vera.ttf",
        # Bundled with barcode
        "/usr/local/lib/python3.11/site-packages/barcode/fonts/DejaVuSansMono.ttf",
    ]

    font_large = None
    font_medium = None
    font_small = None

    for path in font_paths:
        try:
            font_large = ImageFont.truetype(path, font_size_large)
            font_medium = ImageFont.truetype(path, font_size_medium)
            font_small = ImageFont.truetype(path, font_size_small)
            break  # Found a working font
        except OSError:
            continue

    # Final fallback to default (tiny) font
    if font_large is None:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()

    if code_type == "qr":
        # Wide label: QR on left, text stacked vertically on right
        # QR should be about 20mm (fits in 25mm height with margins)
        qr_size = int(20 * px_per_mm)

        # Generate QR code
        qr_data = f"flypush://{stock_id}"
        qr_img = qrcode.make(qr_data, box_size=max(1, qr_size // 21), border=1)
        qr_img = qr_img.resize((qr_size, qr_size), Image.Resampling.NEAREST)

        # Paste QR code on left, vertically centered
        qr_x = margin
        qr_y = (height_px - qr_size) // 2
        img.paste(qr_img, (qr_x, qr_y))

        # Text area to the right of QR - all text on separate rows
        text_x = qr_x + qr_size + int(2 * px_per_mm)  # 2mm gap
        text_y = margin
        max_width = width_px - text_x - right_margin
        line_height_large = int(3.5 * px_per_mm)
        line_height_small = int(2.5 * px_per_mm)

        # Row 1: stock ID (large)
        draw.text((text_x, text_y), stock_id, fill="black", font=font_large)
        text_y += line_height_large

        # Row 2: source info (small)
        if source_info:
            draw.text((text_x, text_y), source_info, fill="black", font=font_small)
            text_y += line_height_small

        # Row 3: date (large)
        if print_date:
            draw.text((text_x, text_y), print_date, fill="black", font=font_large)
            text_y += line_height_large

        # Row 4: location (small)
        if location_info:
            draw.text((text_x, text_y), location_info, fill="black", font=font_small)
            text_y += line_height_small

        # Row 5+: genotype (may need wrapping)
        text_y += int(1 * px_per_mm)  # Small gap before genotype
        genotype_lines = _wrap_text_pil(genotype, font_medium, max_width, draw)
        line_spacing = int(2.5 * px_per_mm)
        for line in genotype_lines[:3]:  # Max 3 lines
            if text_y < height_px - margin:
                draw.text((text_x, text_y), line, fill="black", font=font_medium)
                text_y += line_spacing

    else:
        # Barcode layout: text on top, barcode at bottom
        # Allocate ~9mm for barcode area (8mm bars + small margin)
        barcode_area_height = int(9 * px_per_mm)

        text_x = margin
        text_y = margin
        max_width = width_px - 2 * margin
        line_height = int(3.5 * px_per_mm)

        # Left side: stock ID on top (large), source info below (small)
        draw.text((text_x, text_y), stock_id, fill="black", font=font_large)
        if source_info:
            draw.text((text_x, text_y + line_height), source_info, fill="black", font=font_small)

        # Right side: date on top (large), location below (small)
        top_right_y = text_y
        if print_date:
            bbox = draw.textbbox((0, 0), print_date, font=font_large)
            text_width_px = bbox[2] - bbox[0]
            draw.text(
                (width_px - right_margin - text_width_px, top_right_y),
                print_date,
                fill="black",
                font=font_large,
            )
            top_right_y += line_height
        if location_info:
            bbox = draw.textbbox((0, 0), location_info, font=font_small)
            text_width_px = bbox[2] - bbox[0]
            draw.text(
                (width_px - right_margin - text_width_px, top_right_y),
                location_info,
                fill="black",
                font=font_small,
            )

        text_y += int(8 * px_per_mm)  # Move down ~8mm before genotype

        # Draw genotype (may need wrapping)
        genotype_lines = _wrap_text_pil(genotype, font_medium, max_width, draw)
        line_spacing = int(2 * px_per_mm)
        for line in genotype_lines[:3]:  # Max 3 lines with smaller font
            if text_y < height_px - barcode_area_height - margin:
                draw.text((text_x, text_y), line, fill="black", font=font_medium)
                text_y += line_spacing

        # Generate barcode using code128 library (no text, clean output)
        # Target: ~50mm wide, 8mm tall at current DPI
        target_barcode_width_px = int(50 / 25.4 * render_dpi)
        target_barcode_height_px = int(8 / 25.4 * render_dpi)

        # Calculate thickness to achieve target width
        # First generate with thickness=1 to measure module count
        test_barcode = code128_pil.image(stock_id, thickness=1, height=10)
        num_modules = test_barcode.size[0]  # width in pixels = number of modules at thickness=1

        # Calculate optimal thickness (may be fractional, so we'll resize slightly)
        optimal_thickness = target_barcode_width_px / num_modules
        thickness = max(1, int(optimal_thickness))

        # Generate barcode at calculated dimensions
        barcode_img = code128_pil.image(
            stock_id, thickness=thickness, height=target_barcode_height_px
        )

        # Fine-tune width if needed (resize to exact target)
        if barcode_img.size[0] != target_barcode_width_px:
            barcode_img = barcode_img.resize(
                (target_barcode_width_px, target_barcode_height_px), Image.Resampling.NEAREST
            )

        # Convert from mode '1' (1-bit) to RGB for pasting
        barcode_img = barcode_img.convert("RGB")

        # Paste barcode at bottom, centered horizontally
        barcode_x = (width_px - target_barcode_width_px) // 2
        barcode_y = height_px - target_barcode_height_px - int(0.5 * px_per_mm)
        img.paste(barcode_img, (barcode_x, barcode_y))

    # For landscape_content labels, rotate 90° clockwise to get portrait orientation
    # for the physical label (printer feeds narrow edge first)
    if landscape_content:
        img = img.rotate(-90, expand=True)

    # Supersample: downsample to output DPI if needed (for print)
    if output_dpi < render_dpi:
        # Reason: LANCZOS resampling from 300->72 DPI gives sharp text/QR
        # at the correct pixel dimensions for CUPS (1px = 1pt = 1/72 inch)
        out_w = int(img.width * output_dpi / render_dpi)
        out_h = int(img.height * output_dpi / render_dpi)
        img = img.resize((out_w, out_h), Image.Resampling.LANCZOS)

    # Save to bytes
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", dpi=(output_dpi, output_dpi))
    buffer.seek(0)
    return buffer.getvalue()


def _wrap_text_pil(text: str, font, max_width: int, draw: ImageDraw.Draw) -> list[str]:
    """Wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]

    if current_line:
        lines.append(" ".join(current_line))

    return lines


def create_test_label_png(label_format: str = "dymo_11352") -> bytes:
    """Generate a test label PNG with alignment markers.

    Args:
        label_format: Label format key.

    Returns:
        bytes: PNG image contents.
    """
    if label_format not in LABEL_FORMATS:
        raise ValueError(f"Unknown label format: {label_format}")

    fmt = LABEL_FORMATS[label_format]
    width_mm = fmt.get("width_mm", fmt.get("width", 25.4))
    height_mm = fmt.get("height_mm", fmt.get("height", 54))
    dpi = fmt.get("dpi", 300)
    left_margin_px = fmt.get("left_margin_px", 0)

    # Calculate pixel dimensions
    width_px = int(width_mm / 25.4 * dpi)
    height_px = int(height_mm / 25.4 * dpi)

    # Create white background image
    img = Image.new("RGB", (width_px, height_px), "white")
    draw = ImageDraw.Draw(img)

    # Margins adjusted for printer's non-printable area
    left_margin = int(dpi * 0.04) + left_margin_px
    right_margin = int(dpi * 0.02)
    top_margin = int(dpi * 0.04)
    bottom_margin = int(dpi * 0.04)
    corner_size = int(dpi * 0.1)

    # Draw border rectangle (asymmetric to show actual printable area)
    draw.rectangle(
        [left_margin, top_margin, width_px - right_margin, height_px - bottom_margin],
        outline="black",
        width=2,
    )

    # Try to load font
    try:
        font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", int(dpi * 0.08))
    except OSError:
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(dpi * 0.08)
            )
        except OSError:
            font = ImageFont.load_default()

    # Corner markers (using asymmetric margins)
    # TL
    draw.line(
        [(left_margin, top_margin), (left_margin + corner_size, top_margin)], fill="black", width=2
    )
    draw.line(
        [(left_margin, top_margin), (left_margin, top_margin + corner_size)], fill="black", width=2
    )
    draw.text((left_margin + 5, top_margin + 5), "TL", fill="black", font=font)

    # TR
    draw.line(
        [
            (width_px - right_margin, top_margin),
            (width_px - right_margin - corner_size, top_margin),
        ],
        fill="black",
        width=2,
    )
    draw.line(
        [
            (width_px - right_margin, top_margin),
            (width_px - right_margin, top_margin + corner_size),
        ],
        fill="black",
        width=2,
    )
    draw.text((width_px - right_margin - 35, top_margin + 5), "TR", fill="black", font=font)

    # BL
    draw.line(
        [
            (left_margin, height_px - bottom_margin),
            (left_margin + corner_size, height_px - bottom_margin),
        ],
        fill="black",
        width=2,
    )
    draw.line(
        [
            (left_margin, height_px - bottom_margin),
            (left_margin, height_px - bottom_margin - corner_size),
        ],
        fill="black",
        width=2,
    )
    draw.text((left_margin + 5, height_px - bottom_margin - 25), "BL", fill="black", font=font)

    # BR
    draw.line(
        [
            (width_px - right_margin, height_px - bottom_margin),
            (width_px - right_margin - corner_size, height_px - bottom_margin),
        ],
        fill="black",
        width=2,
    )
    draw.line(
        [
            (width_px - right_margin, height_px - bottom_margin),
            (width_px - right_margin, height_px - bottom_margin - corner_size),
        ],
        fill="black",
        width=2,
    )
    draw.text(
        (width_px - right_margin - 35, height_px - bottom_margin - 25),
        "BR",
        fill="black",
        font=font,
    )

    # Center crosshairs
    cx, cy = width_px // 2, height_px // 2
    cross_size = int(dpi * 0.15)
    draw.line([(cx - cross_size, cy), (cx + cross_size, cy)], fill="black", width=1)
    draw.line([(cx, cy - cross_size), (cx, cy + cross_size)], fill="black", width=1)
    draw.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], outline="black", width=1)

    # Dimension labels
    try:
        font_small = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans.ttf", int(dpi * 0.06))
    except OSError:
        try:
            font_small = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", int(dpi * 0.06)
            )
        except OSError:
            font_small = ImageFont.load_default()

    draw.text(
        (cx - 40, cy + cross_size + 5),
        f"{width_mm:.1f}x{height_mm:.1f}mm",
        fill="black",
        font=font_small,
    )
    draw.text(
        (cx - 30, cy - cross_size - 20), f"{width_px}x{height_px}px", fill="black", font=font_small
    )

    # Save to bytes
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", dpi=(dpi, dpi))
    buffer.seek(0)
    return buffer.getvalue()


def _apply_rotation(
    c: canvas.Canvas, width_pt: float, height_pt: float, rotation: int
) -> tuple[float, float]:
    """Apply rotation transformation to canvas.

    Args:
        c: ReportLab canvas.
        width_pt: Page width in points.
        height_pt: Page height in points.
        rotation: Rotation in degrees (0, 90, 180, -90/270).

    Returns:
        tuple[float, float]: Drawing width and height after rotation.
    """
    if rotation == -90 or rotation == 270:
        # 90 degrees clockwise: content drawn in original dimensions gets rotated to fit page
        # translate(-width_pt, 0) shifts content into view after rotation
        c.rotate(-90)
        c.translate(-width_pt, 0)
        return width_pt, height_pt  # Return original content dimensions
    elif rotation == 90:
        # 90 degrees counter-clockwise: content drawn in original dimensions gets rotated
        c.rotate(90)
        c.translate(0, -height_pt)
        return width_pt, height_pt  # Return original content dimensions
    elif rotation == 180:
        # 180 degrees: flip upside down, same dimensions
        c.rotate(180)
        c.translate(-width_pt, -height_pt)
        return width_pt, height_pt
    else:
        # No rotation (0)
        return width_pt, height_pt


def create_label_pdf(
    stock_id: str,
    genotype: str,
    label_format: str = "dymo_11352",
    source_info: str | None = None,
    location_info: str | None = None,
    code_type: Literal["qr", "barcode"] = "qr",
    print_date: str | None = None,
) -> bytes:
    """Generate a PDF label for a single stock.

    Creates the label as PNG (same as print output) and embeds it in a PDF
    for preview. This ensures the preview matches exactly what will be printed.

    Args:
        stock_id: Stock ID to display and encode in QR.
        genotype: Genotype string (will be truncated if too long).
        label_format: Label format key from LABEL_SIZES.
        source_info: Optional source info (e.g., "BDSC #3605").
        location_info: Optional location info (e.g., "Tray A - 15").
        code_type: Type of code to render ("qr" or "barcode").
        print_date: Print date string (defaults to today if None).

    Returns:
        bytes: PDF file contents.

    Raises:
        ValueError: If label_format is not recognized.
    """
    if label_format not in LABEL_FORMATS:
        raise ValueError(f"Unknown label format: {label_format}")

    # Generate high-quality PNG for preview
    png_data = create_label_png(
        stock_id=stock_id,
        genotype=genotype,
        label_format=label_format,
        source_info=source_info,
        location_info=location_info,
        code_type=code_type,
        print_date=print_date,
        for_print=False,  # High-quality for preview
    )

    # Get page dimensions for PDF
    fmt = LABEL_FORMATS[label_format]
    if "width_mm" in fmt:
        width_pt = fmt["width_mm"] * mm
        height_pt = fmt["height_mm"] * mm
    else:
        width_pt = fmt.get("width", 25.4) * mm
        height_pt = fmt.get("height", 54) * mm
    landscape_content = fmt.get("landscape_content", False)

    # For landscape_content, swap page dimensions for preview
    if landscape_content:
        page_width, page_height = height_pt, width_pt
    else:
        page_width, page_height = width_pt, height_pt

    # Create PDF with PNG embedded
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(page_width, page_height))

    # Load PNG and draw it to fill the page
    png_buffer = io.BytesIO(png_data)
    png_img = Image.open(png_buffer)

    # For landscape_content, the PNG is portrait (rotated for printer)
    # We need to rotate it back for the landscape PDF preview
    if landscape_content:
        png_img = png_img.rotate(90, expand=True)

    # Save rotated image to buffer for reportlab
    img_buffer = io.BytesIO()
    png_img.save(img_buffer, format="PNG")
    img_buffer.seek(0)

    # Draw image to fill page
    from reportlab.lib.utils import ImageReader

    img_reader = ImageReader(img_buffer)
    c.drawImage(img_reader, 0, 0, width=page_width, height=page_height)

    c.save()
    buffer.seek(0)
    return buffer.getvalue()


def create_batch_label_pdf(
    labels: list[dict],
    label_format: str = "dymo_11352",
    labels_per_page: int = 1,
    code_type: Literal["qr", "barcode"] = "qr",
    for_print: bool = False,
) -> bytes:
    """Generate a PDF with multiple labels.

    Creates each label as PNG and embeds them in a PDF.
    For preview (for_print=False): landscape orientation for web display.
    For print (for_print=True): portrait orientation at 300 DPI for CUPS.

    Args:
        labels: List of label dicts with stock_id, genotype, source_info, location_info, print_date.
        label_format: Label format key from LABEL_SIZES.
        labels_per_page: Number of labels per page (1 for thermal printers).
        code_type: Type of code to render ("qr" or "barcode").
        for_print: If True, generate portrait PDF for printing via CUPS.

    Returns:
        bytes: PDF file contents.

    Raises:
        ValueError: If label_format is not recognized.
    """
    if label_format not in LABEL_FORMATS:
        raise ValueError(f"Unknown label format: {label_format}")

    from reportlab.lib.utils import ImageReader

    fmt = LABEL_FORMATS[label_format]
    if "width_mm" in fmt:
        width_pt = fmt["width_mm"] * mm
        height_pt = fmt["height_mm"] * mm
    else:
        width_pt = fmt.get("width", 25.4) * mm
        height_pt = fmt.get("height", 54) * mm
    landscape_content = fmt.get("landscape_content", False)

    if for_print:
        # Reason: For printing, use portrait (narrow x tall) to match CUPS PageSize
        # (e.g., w72h154). The PNG from create_label_png is already portrait
        # (rotated for the printer). PDF embeds it at correct physical dimensions;
        # CUPS rasterizes at printer's native 300 DPI for full quality.
        page_width, page_height = width_pt, height_pt
    elif landscape_content:
        # For preview, swap to landscape for web display
        page_width, page_height = height_pt, width_pt
    else:
        page_width, page_height = width_pt, height_pt

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(page_width, page_height))

    for i, label_data in enumerate(labels):
        if i > 0:
            c.showPage()

        # Generate 300 DPI PNG (no downsampling)
        png_data = create_label_png(
            stock_id=label_data["stock_id"],
            genotype=label_data["genotype"],
            label_format=label_format,
            source_info=label_data.get("source_info"),
            location_info=label_data.get("location_info"),
            code_type=code_type,
            print_date=label_data.get("print_date"),
            for_print=False,  # Always 300 DPI PNG source
        )

        # Load PNG
        png_buffer = io.BytesIO(png_data)
        png_img = Image.open(png_buffer)

        # For preview with landscape_content, rotate PNG back to landscape
        # For print, PNG is already portrait (correct for printer)
        if not for_print and landscape_content:
            png_img = png_img.rotate(90, expand=True)

        # Save to buffer for reportlab
        img_buffer = io.BytesIO()
        png_img.save(img_buffer, format="PNG")
        img_buffer.seek(0)

        # Draw image to fill page
        img_reader = ImageReader(img_buffer)
        c.drawImage(img_reader, 0, 0, width=page_width, height=page_height)

    c.save()
    buffer.seek(0)
    return buffer.getvalue()


def _draw_label_content(
    c: canvas.Canvas,
    stock_id: str,
    genotype: str,
    source_info: str | None,
    location_info: str | None,
    width_pt: float,
    height_pt: float,
    rotation: int = -90,
    code_type: Literal["qr", "barcode"] = "qr",
    print_date: str | None = None,
) -> None:
    """Draw label content on canvas at current position.

    Args:
        c: ReportLab canvas.
        stock_id: Stock ID.
        genotype: Genotype string.
        source_info: Optional source info.
        location_info: Optional location info.
        width_pt: Label width in points.
        height_pt: Label height in points.
        rotation: Rotation in degrees (-90 for clockwise, 0 for none).
        code_type: Type of code to render ("qr" or "barcode").
        print_date: Print date string.
    """
    # Default print_date to today if not provided
    if print_date is None:
        print_date = date.today().isoformat()

    # Apply rotation based on configuration
    draw_width, draw_height = _apply_rotation(c, width_pt, height_pt, rotation)

    margin = 2 * mm
    line_height = 3 * mm

    # Determine if label is narrow (portrait-ish) - QR on top layout needed
    is_narrow_label = draw_width < 35 * mm

    if code_type == "qr":
        if is_narrow_label:
            # Narrow label: QR at top, text below
            qr_size = min(draw_width - 2 * margin, 15 * mm)
            qr_x = (draw_width - qr_size) / 2  # Center horizontally
            qr_y = draw_height - margin - qr_size  # At top

            # QR code
            qr_data = f"flypush://{stock_id}"
            qr_code = qr.QrCodeWidget(qr_data)
            qr_code.barWidth = qr_size
            qr_code.barHeight = qr_size

            d = Drawing(qr_size, qr_size)
            d.add(qr_code)
            renderPDF.draw(d, c, qr_x, qr_y)

            # Text below QR
            text_x = margin
            text_width = draw_width - 2 * margin
            current_y = qr_y - 2 * mm

            # Stock ID
            c.setFont("Helvetica-Bold", 8)
            c.drawString(text_x, current_y, stock_id)
            current_y -= line_height

            # Genotype
            c.setFont("Helvetica", 5)
            max_chars = int(text_width / (2 * mm))
            genotype_lines = _wrap_text(genotype, max_chars, max_lines=3)
            for line in genotype_lines:
                if current_y > margin:
                    c.drawString(text_x, current_y, line)
                    current_y -= line_height * 0.8

            # Source info
            if source_info and current_y > margin + line_height:
                c.setFont("Helvetica-Oblique", 4)
                c.drawString(text_x, current_y, source_info)
                current_y -= line_height * 0.8

            # Location and date
            if location_info and current_y > margin:
                c.setFont("Helvetica", 4)
                c.drawString(text_x, current_y, location_info)
                current_y -= line_height * 0.8

            if print_date and current_y > margin:
                c.setFont("Helvetica", 4)
                c.drawString(text_x, current_y, print_date)
        else:
            # Wide label: QR on left, text on right
            qr_size = min(draw_height - 2 * margin, 18 * mm)
            qr_x = margin
            qr_y = (draw_height - qr_size) / 2

            text_x = qr_x + qr_size + 2 * mm
            text_width = draw_width - text_x - margin

            # QR code
            qr_data = f"flypush://{stock_id}"
            qr_code = qr.QrCodeWidget(qr_data)
            qr_code.barWidth = qr_size
            qr_code.barHeight = qr_size

            d = Drawing(qr_size, qr_size)
            d.add(qr_code)
            renderPDF.draw(d, c, qr_x, qr_y)

            # Text content
            current_y = draw_height - margin - line_height

            # Stock ID
            c.setFont("Helvetica-Bold", 9)
            c.drawString(text_x, current_y, stock_id)
            current_y -= line_height + 1 * mm

            # Genotype
            c.setFont("Helvetica", 6)
            max_chars = int(text_width / (2.5 * mm))
            genotype_lines = _wrap_text(genotype, max_chars, max_lines=2)
            for line in genotype_lines:
                if current_y > margin:
                    c.drawString(text_x, current_y, line)
                    current_y -= line_height

            # Source info
            if source_info and current_y > margin + line_height:
                current_y -= 0.5 * mm
                c.setFont("Helvetica-Oblique", 5)
                c.drawString(text_x, current_y, source_info)
                current_y -= line_height

            # Location and date on same line
            bottom_line = ""
            if location_info:
                bottom_line = location_info
            if print_date:
                if bottom_line:
                    bottom_line += "    " + print_date
                else:
                    bottom_line = print_date
            if bottom_line and current_y > margin:
                c.setFont("Helvetica", 5)
                c.drawString(text_x, current_y, bottom_line)

    else:
        # Barcode layout: text on top, barcode at bottom
        text_x = margin
        text_width = draw_width - 2 * margin

        # Adjust sizes for narrow labels
        if is_narrow_label:
            barcode_height = 10 * mm
            font_size_title = 7
            font_size_text = 5
            font_size_small = 4
        else:
            barcode_height = 8 * mm
            font_size_title = 9
            font_size_text = 6
            font_size_small = 5

        text_area_top = draw_height - margin
        current_y = text_area_top - line_height

        # Stock ID
        c.setFont("Helvetica-Bold", font_size_title)
        c.drawString(text_x, current_y, stock_id)
        current_y -= line_height

        # Genotype
        c.setFont("Helvetica", font_size_text)
        max_chars = int(text_width / (2 * mm))
        genotype_lines = _wrap_text(genotype, max_chars, max_lines=3)
        for line in genotype_lines:
            if current_y > barcode_height + margin + line_height:
                c.drawString(text_x, current_y, line)
                current_y -= line_height * 0.8

        # Source info
        if source_info and current_y > barcode_height + margin + line_height:
            c.setFont("Helvetica-Oblique", font_size_small)
            c.drawString(text_x, current_y, source_info)
            current_y -= line_height * 0.8

        # Location
        if location_info and current_y > barcode_height + margin + line_height:
            c.setFont("Helvetica", font_size_small)
            c.drawString(text_x, current_y, location_info)
            current_y -= line_height * 0.8

        # Print date
        if print_date and current_y > barcode_height + margin:
            c.setFont("Helvetica", font_size_small)
            c.drawString(text_x, current_y, print_date)

        # Draw barcode at bottom using reportlab's code128
        # Adjust barWidth based on available space
        available_width = draw_width - 2 * margin
        # Start with a reasonable barWidth and adjust if needed
        bar_width = 0.4 if is_narrow_label else 0.5
        barcode_obj = code128.Code128(stock_id, barHeight=6 * mm, barWidth=bar_width)

        # If barcode is too wide, scale it down
        if barcode_obj.width > available_width:
            scale_factor = available_width / barcode_obj.width
            bar_width = bar_width * scale_factor * 0.95  # 95% to leave some margin
            barcode_obj = code128.Code128(stock_id, barHeight=6 * mm, barWidth=bar_width)

        barcode_actual_width = barcode_obj.width

        # Center the barcode horizontally
        barcode_x = (draw_width - barcode_actual_width) / 2
        barcode_y = margin

        # Draw barcode directly on canvas (not via Drawing - Code128 is not a Shape)
        barcode_obj.drawOn(c, barcode_x, barcode_y)


def _wrap_text(text: str, max_chars: int, max_lines: int = 3) -> list[str]:
    """Wrap text to fit within width, respecting max lines.

    Args:
        text: Text to wrap.
        max_chars: Maximum characters per line.
        max_lines: Maximum number of lines.

    Returns:
        list[str]: Lines of wrapped text.
    """
    if len(text) <= max_chars:
        return [text]

    lines = []
    remaining = text

    while remaining and len(lines) < max_lines:
        if len(remaining) <= max_chars:
            lines.append(remaining)
            break

        # Find break point
        break_point = max_chars
        # Try to break at semicolon, space, or slash
        for sep in ["; ", " ", "/", "-"]:
            pos = remaining[:max_chars].rfind(sep)
            if pos > max_chars // 2:
                break_point = pos + len(sep)
                break

        line = remaining[:break_point].rstrip()
        remaining = remaining[break_point:].lstrip()

        # Add ellipsis if this is the last line and there's more text
        if len(lines) == max_lines - 1 and remaining:
            if len(line) > max_chars - 3:
                line = line[: max_chars - 3]
            line = line.rstrip() + "..."

        lines.append(line)

    return lines


def create_label_image(
    stock_id: str,
    genotype: str,
    label_format: str = "dymo_11352",
    source_info: str | None = None,
    location_info: str | None = None,
    dpi: int = 300,
    output_format: Literal["png", "jpeg"] = "png",
    code_type: Literal["qr", "barcode"] = "qr",
    print_date: str | None = None,
) -> bytes:
    """Generate a label as an image (PNG/JPEG).

    Creates the label as a PDF first, then converts to image.
    Useful for preview or printers that don't accept PDF.

    Args:
        stock_id: Stock ID.
        genotype: Genotype string.
        label_format: Label format key.
        source_info: Optional source info.
        location_info: Optional location info.
        dpi: Image resolution.
        output_format: Output image format.
        code_type: Type of code to render ("qr" or "barcode").
        print_date: Print date string.

    Returns:
        bytes: Image file contents.
    """
    # For now, return the PDF - image conversion requires additional dependencies
    # In production, use pdf2image or similar to convert
    # This is a placeholder that could be extended with Pillow/pdf2image
    return create_label_pdf(
        stock_id=stock_id,
        genotype=genotype,
        label_format=label_format,
        source_info=source_info,
        location_info=location_info,
        code_type=code_type,
        print_date=print_date,
    )


def create_test_label_pdf(label_format: str = "dymo_11352") -> bytes:
    """Generate a test label PDF with alignment markers.

    This helps verify label alignment, rotation, and margins on the printer.
    Shows corner markers, center crosshairs, and orientation indicators.

    Args:
        label_format: Label format key from LABEL_FORMATS.

    Returns:
        bytes: PDF file contents.

    Raises:
        ValueError: If label_format is not recognized.
    """
    if label_format not in LABEL_FORMATS:
        raise ValueError(f"Unknown label format: {label_format}")

    fmt = LABEL_FORMATS[label_format]
    # Support both mm dimensions (width/height) and point dimensions (width_pt/height_pt)
    if "width_pt" in fmt:
        width_pt = fmt["width_pt"]
        height_pt = fmt["height_pt"]
        width_mm = width_pt / mm
        height_mm = height_pt / mm
    else:
        width_mm = fmt["width"]
        height_mm = fmt["height"]
        width_pt = width_mm * mm
        height_pt = height_mm * mm
    rotation = fmt.get("rotation", 0)
    swap_page = fmt.get("swap_page", False)
    scale = fmt.get("scale", 1.0)

    # For printers like Dymo with narrow print heads, swap page dimensions
    if swap_page and rotation in (-90, 90, 270):
        page_width, page_height = height_pt, width_pt
    else:
        page_width, page_height = width_pt, height_pt

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(page_width, page_height))

    # Apply scale factor if needed (to compensate for printer scaling)
    if scale != 1.0:
        c.scale(scale, scale)
        width_pt = width_pt / scale
        height_pt = height_pt / scale
        width_mm = width_pt / mm
        height_mm = height_pt / mm

    # Apply rotation based on format configuration
    draw_width, draw_height = _apply_rotation(c, width_pt, height_pt, rotation)

    # Scale margins and corner size for small labels
    margin = min(1.5 * mm, width_pt * 0.05)
    corner_size = min(3 * mm, width_pt * 0.1)

    # Draw border rectangle
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.3 * mm)
    c.rect(margin, margin, draw_width - 2 * margin, draw_height - 2 * margin)

    # Draw corner markers with labels
    c.setFont("Helvetica-Bold", 5)

    # Bottom-left corner: "BL"
    c.line(margin, margin, margin + corner_size, margin)
    c.line(margin, margin, margin, margin + corner_size)
    c.drawString(margin + 1 * mm, margin + 1 * mm, "BL")

    # Bottom-right corner: "BR"
    c.line(draw_width - margin, margin, draw_width - margin - corner_size, margin)
    c.line(draw_width - margin, margin, draw_width - margin, margin + corner_size)
    c.drawRightString(draw_width - margin - 1 * mm, margin + 1 * mm, "BR")

    # Top-left corner: "TL"
    c.line(margin, draw_height - margin, margin + corner_size, draw_height - margin)
    c.line(margin, draw_height - margin, margin, draw_height - margin - corner_size)
    c.drawString(margin + 1 * mm, draw_height - margin - 4 * mm, "TL")

    # Top-right corner: "TR"
    c.line(
        draw_width - margin,
        draw_height - margin,
        draw_width - margin - corner_size,
        draw_height - margin,
    )
    c.line(
        draw_width - margin,
        draw_height - margin,
        draw_width - margin,
        draw_height - margin - corner_size,
    )
    c.drawRightString(draw_width - margin - 1 * mm, draw_height - margin - 4 * mm, "TR")

    # Draw center crosshairs
    center_x = draw_width / 2
    center_y = draw_height / 2
    crosshair_size = 4 * mm
    c.setLineWidth(0.2 * mm)
    c.line(center_x - crosshair_size, center_y, center_x + crosshair_size, center_y)
    c.line(center_x, center_y - crosshair_size, center_x, center_y + crosshair_size)
    # Small circle at center
    c.circle(center_x, center_y, 1 * mm)

    # Add orientation info
    c.setFont("Helvetica", 5)
    # Arrow pointing to "long side" with label
    if draw_width > draw_height:
        # Horizontal is longer
        c.drawCentredString(center_x, center_y + 6 * mm, f"<-- LONG ({draw_width/mm:.0f}mm) -->")
        c.drawCentredString(center_x, center_y - 7 * mm, f"SHORT ({draw_height/mm:.0f}mm)")
    else:
        # Vertical is longer
        c.drawCentredString(center_x, center_y + 8 * mm, f"SHORT ({draw_width/mm:.0f}mm)")
        c.saveState()
        c.translate(center_x - 8 * mm, center_y)
        c.rotate(90)
        c.drawCentredString(0, 0, f"LONG ({draw_height/mm:.0f}mm)")
        c.restoreState()

    # Add format and rotation info at bottom
    c.setFont("Helvetica", 4)
    c.drawCentredString(center_x, margin + 5 * mm, f"{label_format} rot={rotation}")

    c.save()
    buffer.seek(0)
    return buffer.getvalue()


def get_available_formats() -> list[dict]:
    """Get list of available label formats with dimensions.

    Returns:
        list[dict]: Label format specifications.
    """
    formats = []
    for key, fmt in LABEL_FORMATS.items():
        name = key.replace("_", " ").title()
        # Support different dimension keys
        if "width_mm" in fmt:
            width = fmt["width_mm"]
            height = fmt["height_mm"]
        else:
            width = fmt["width"]
            height = fmt["height"]
        rotation = fmt.get("rotation", 0)
        formats.append(
            {
                "id": key,
                "name": name,
                "width_mm": width,
                "height_mm": height,
                "rotation": rotation,
                "description": f"{width}mm x {height}mm",
            }
        )
    return formats
