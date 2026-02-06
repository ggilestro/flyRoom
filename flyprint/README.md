# FlyPrint

Local print agent for FlyPush label printing.

FlyPrint is a lightweight agent that runs on local machines (Raspberry Pi, desktop, etc.) and polls your FlyPush server for print jobs. When a job is available, it downloads the label PDF and prints via local CUPS.

## Installation

### Prerequisites

- Python 3.10+
- CUPS (Common Unix Printing System)
- A configured printer in CUPS

### Install from source

```bash
cd flyprint
pip install .

# Include CUPS support (recommended)
pip install ".[cups]"
```

### Install CUPS (if needed)

**Debian/Ubuntu/Raspberry Pi:**
```bash
sudo apt update
sudo apt install cups python3-cups
```

**Arch Linux:**
```bash
sudo pacman -S cups python-pycups
```

## Quick Start

### 1. Configure the agent

Get your API key from FlyPush: Settings > Print Agents > Add Agent

```bash
flyprint configure \
  --server https://your-flypush-server.com \
  --key YOUR_API_KEY \
  --printer "Your_Printer_Name"
```

### 2. Test the connection

```bash
flyprint test
```

### 3. Start the agent

```bash
flyprint start
```

## Commands

| Command | Description |
|---------|-------------|
| `flyprint configure` | Set up server URL, API key, and printer |
| `flyprint test` | Test connection to server and printer |
| `flyprint start` | Start the print agent |
| `flyprint status` | Show current configuration |
| `flyprint printers` | List available CUPS printers |
| `flyprint install-service` | Install systemd service for auto-start |

## Running as a Service

For always-on printing (e.g., on a Raspberry Pi), install as a systemd service:

### User service (no root required)

```bash
flyprint install-service --user

# Enable and start
systemctl --user daemon-reload
systemctl --user enable flyprint
systemctl --user start flyprint

# View logs
journalctl --user -u flyprint -f
```

### System service (requires root)

```bash
flyprint install-service
# Follow the printed instructions to copy the service file
```

## Printer Setup

### Dymo LabelWriter 400

1. Install Dymo drivers:
   ```bash
   sudo apt install printer-driver-dymo
   ```

2. Connect the printer via USB

3. Add to CUPS:
   ```bash
   sudo lpadmin -p dymo400 -E -v usb://DYMO/LabelWriter%20400 \
     -P /usr/share/ppd/dymo/lw400.ppd
   ```

4. Set as default (optional):
   ```bash
   sudo lpoptions -d dymo400
   ```

### Brother QL Series

Brother QL printers are also supported via CUPS with the `brother-ql` drivers.

## Configuration File

Configuration is stored in `~/.config/flyprint/config.json`:

```json
{
  "server_url": "https://your-flypush-server.com",
  "api_key": "your_api_key",
  "printer_name": "dymo400",
  "poll_interval": 5,
  "label_format": "dymo_11352",
  "log_level": "INFO"
}
```

## Troubleshooting

### "CUPS not available"

Make sure CUPS is installed and running:
```bash
sudo systemctl status cups
```

### "No printers found"

Check CUPS printer list:
```bash
lpstat -p
```

### "Server rejected heartbeat"

- Verify your API key is correct
- Check that the server URL is accessible
- Ensure the agent is active in FlyPush settings

### Verbose logging

Run with verbose flag to see more details:
```bash
flyprint start --verbose
```

## License

MIT License - see LICENSE file.
