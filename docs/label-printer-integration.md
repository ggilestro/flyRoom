# Label Printer Integration Guide

This document captures lessons learned from integrating the Dymo LabelWriter 400 with the flyPrint system. Use this as a reference when adding support for new label printer models.

## Dymo LabelWriter 400 - What Worked

### Use PNG Images, Not PDF

**The most critical lesson**: For Dymo LabelWriter printers on Linux/CUPS, **use PNG images instead of PDF**.

PDF files cause unpredictable scaling issues with CUPS. The `pdftopdf` filter applies scaling that's difficult to control, often resulting in labels printing at 2x or 4x the expected size.

PNG images go directly to the raster driver and produce consistent results.

### Use 72 DPI (Not 300 DPI)

Even though the Dymo LabelWriter 400 is a 300 DPI printer, **create PNG images at 72 DPI**.

CUPS interprets image dimensions at 72 DPI by default (1 point = 1 pixel at 72 DPI). The `-o ppi=300` option is **not reliably respected** by CUPS filters.

For a Dymo 11352 label (25.4mm × 54mm):
- CUPS page size: `w72h154` (72 points × 154 points)
- Image dimensions: **72 × 154 pixels** (at 72 DPI)

This 1:1 mapping between pixels and points ensures correct sizing.

### Print Command That Works

```bash
lpr -P LabelWriter-400 -# 1 \
    -o PageSize=w72h154 \
    -o scaling=100 \
    -o fit-to-page=false \
    -o PrintQuality=Graphics \
    label.png
```

Key options:
- `PageSize=w72h154` - Must match the label type
- `scaling=100` - Prevent CUPS from scaling the image
- `fit-to-page=false` - Disable auto-fit behavior
- `PrintQuality=Graphics` - Use graphics mode for images

### Account for Printer Margins

The PPD file defines the `ImageableArea` - the actual printable region:

```
*ImageableArea w72h154: "4.08 4.32 69.12 146.64"
```

This means:
- Left margin: 4.08 points (~1.4mm)
- Bottom margin: 4.32 points (~1.5mm)
- Right margin: 72 - 69.12 = 2.88 points (~1mm)
- Top margin: 154 - 146.64 = 7.36 points (~2.6mm)

Add a `left_margin_px` offset (approximately 5 pixels at 72 DPI) to shift content right and prevent it from being cut off by the printer's physical margin.

## What Did NOT Work

### PDF Output

PDF files caused consistent 2x scaling issues regardless of:
- Exact page dimensions matching CUPS
- `fit-to-page=false` option
- `scaling=100` option
- `print-scaling=none` option

**Avoid PDF for Dymo printers.**

### The `-o ppi=300` Option

This option is documented but **does not work reliably** with the Dymo CUPS driver. Images are still interpreted at the default 72 DPI regardless of this setting.

### Canvas Rotation in PDF

ReportLab canvas rotation with `c.rotate()` and `c.translate()` for label orientation was problematic. The coordinate transformations often positioned content outside the visible page area.

**Instead**: Create the image in the correct orientation from the start, matching how the label feeds through the printer.

### High-Resolution Images

Creating 300 DPI images (300 × 638 pixels for the 11352 label) resulted in labels spanning 4 labels (2×2 grid) because CUPS interpreted them at 72 DPI, making them appear ~4× larger.

## CUPS Page Sizes for Common Dymo Labels

| Label Model | Dimensions (mm) | CUPS PageSize | Image Size (72 DPI) |
|-------------|-----------------|---------------|---------------------|
| 11352       | 25.4 × 54       | w72h154       | 72 × 154 px         |
| 99010       | 28 × 89         | w79h252       | 79 × 252 px         |
| 99012       | 36 × 89         | w102h252      | 102 × 252 px        |
| 11354       | 57 × 32         | w162h90       | 162 × 90 px         |

Find available page sizes with:
```bash
lpoptions -p LabelWriter-400 -l | grep PageSize
```

## PPD File Information

The PPD file contains critical printer configuration:

```bash
# Location
/etc/cups/ppd/LabelWriter-400.ppd

# View page sizes and margins
sudo grep -E "(PageSize|ImageableArea|Resolution)" /etc/cups/ppd/LabelWriter-400.ppd
```

Key sections:
- `*PageSize` - Available label sizes
- `*ImageableArea` - Printable area (accounts for physical margins)
- `*PaperDimension` - Full page dimensions
- `*Resolution` - Supported DPI values

## Adding a New Printer Model

1. **Install the printer and CUPS drivers**

2. **Find the PPD and available page sizes**:
   ```bash
   lpstat -l -p PrinterName
   lpoptions -p PrinterName -l
   ```

3. **Identify the correct page size** for your label type

4. **Check the ImageableArea** to determine margin offsets

5. **Start with PNG at 72 DPI** matching the CUPS page dimensions

6. **Test with a simple rectangle** before adding complex content

7. **Add the format to `LABEL_FORMATS`**:
   ```python
   "new_label": {
       "width_mm": 25.4,      # Physical label width
       "height_mm": 54,       # Physical label height
       "dpi": 72,             # Use 72 for CUPS compatibility
       "output_format": "png", # PNG for thermal printers
       "cups_page": "w72h154", # CUPS page size name
       "left_margin_px": 5,   # Offset for printer margins
   }
   ```

8. **Test iteratively** - thermal printers can waste labels, so verify sizing before printing many copies

## Debugging Tips

### Check what CUPS is doing
```bash
# Enable CUPS debug logging
cupsctl --debug-logging

# View CUPS error log
tail -f /var/log/cups/error_log
```

### Test print command manually
```bash
# Save a test image
python -c "from PIL import Image; img = Image.new('RGB', (72, 154), 'white'); img.save('/tmp/test.png')"

# Print with verbose output
lpr -P LabelWriter-400 -o PageSize=w72h154 /tmp/test.png
```

### Inspect the print queue
```bash
lpstat -o  # Show pending jobs
lpstat -t  # Show all status info
cancel -a  # Cancel all jobs (if stuck)
```

## References

- [Dymo CUPS Drivers (GitHub)](https://github.com/matthiasbock/dymo-cups-drivers)
- [Dymo CUPS Driver Samples](https://github.com/kfprimm/dymo-cups-drivers/blob/master/docs/SAMPLES)
- [CUPS Command-Line Printing](https://www.cups.org/doc/options.html)
- [Daniel Lange's Dymo Linux Guide](https://daniel-lange.com/archives/190-Printing-labels-with-the-DYMO-LabelWriter-Wireless-and-LabelWriter-5xx-on-Debian-Linux.html)
