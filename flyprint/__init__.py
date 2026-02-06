"""FlyPrint - Local print agent for FlyPush label printing.

FlyPrint is a lightweight agent that runs on local machines (Raspberry Pi,
desktop, etc.) and polls FlyPush for print jobs. When a job is available,
it downloads the label PDF and prints via local CUPS.

Usage:
    flyprint configure --server https://your-server.com --key YOUR_API_KEY
    flyprint start
    flyprint status
    flyprint test

For systemd service installation:
    flyprint install-service
"""

__version__ = "0.1.0"
__author__ = "Giorgio Gilestro"
