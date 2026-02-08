"""Command-line interface for FlyPrint agent."""

import logging
import sys
from pathlib import Path

import click
import requests

from flyprint import __version__
from flyprint.agent import get_agent
from flyprint.config import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_SERVER_URL,
    FlyPrintConfig,
    get_config,
)
from flyprint.printer import get_printer


def setup_logging(level: str) -> None:
    """Set up logging configuration.

    Args:
        level: Log level string.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )


@click.group()
@click.version_option(version=__version__)
def main():
    """FlyPrint - Local print agent for FlyPush.

    FlyPrint connects to your FlyPush server and prints labels
    automatically when print jobs are submitted.
    """
    pass


@main.command()
@click.option(
    "--server",
    "-s",
    prompt="FlyPush Server URL",
    help="URL of your FlyPush server (e.g., https://flypush.example.com)",
)
@click.option(
    "--key",
    "-k",
    prompt="API Key",
    hide_input=True,
    help="API key from FlyPush Settings > Print Agents",
)
def configure(server: str, key: str):
    """Configure the FlyPrint agent manually.

    Use this as a fallback if 'flyprint pair' doesn't work.
    Requires a server URL and API key from the web UI.
    """
    config = FlyPrintConfig(
        server_url=server.rstrip("/"),
        api_key=key,
    )

    config.save()
    click.echo(f"\nConfiguration saved to {DEFAULT_CONFIG_FILE}")
    click.echo("\nRun 'flyprint test' to verify the connection.")
    click.echo("Run 'flyprint start' to start the agent.")


@main.command()
@click.argument("code", required=False)
@click.option(
    "--server",
    "-s",
    default=DEFAULT_SERVER_URL,
    help=f"FlyPush server URL (default: {DEFAULT_SERVER_URL})",
)
def pair(code: str | None, server: str):
    """Pair this agent with your FlyPush server.

    Start pairing from the FlyPush web UI (Settings > Labels > Add Agent),
    then run this command. The server will match you automatically by IP.

    If automatic matching doesn't work, use the 6-character code shown
    in the web UI:

        flyprint pair AB3K9X
    """
    from flyprint.gui.pairing_dialog import do_pairing

    server_url = server.rstrip("/")

    click.echo(f"Pairing with {server_url}...")
    if code:
        click.echo(f"Using pairing code: {code}")
    else:
        click.echo("Attempting automatic IP-based pairing...")

    try:
        result = do_pairing(server_url, code)
        config = FlyPrintConfig(
            server_url=server_url,
            api_key=result["api_key"],
        )
        config.save()

        click.echo(f"\nPaired successfully as '{result['agent_name']}'!")
        click.echo(f"Configuration saved to {DEFAULT_CONFIG_FILE}")
        click.echo("\nRun 'flyprint start' to begin printing.")

    except requests.ConnectionError:
        click.echo(f"\nCould not connect to {server_url}")
        click.echo("Check the server URL and try again.")
        sys.exit(1)
    except ValueError as e:
        click.echo(f"\nPairing failed: {e}")
        if not code:
            click.echo(
                "\nTip: If you're on a different network, use the pairing code "
                "from the web UI:\n  flyprint pair <CODE>"
            )
        sys.exit(1)
    except Exception as e:
        click.echo(f"\nPairing error: {e}")
        sys.exit(1)


@main.command()
def status():
    """Show current configuration and status."""
    config = get_config()

    click.echo("\n=== FlyPrint Status ===\n")

    if not config.is_configured():
        click.echo("Status: NOT CONFIGURED")
        click.echo("\nRun 'flyprint pair' or 'flyprint configure' to set up the agent.")
        return

    click.echo(f"Server URL: {config.server_url}")
    click.echo(f"API Key: {'*' * 8}...{config.api_key[-4:] if len(config.api_key) > 4 else '****'}")
    click.echo(f"Printer: {config.printer_name or '(default)'}")
    click.echo(f"Poll Interval: {config.poll_interval}s")
    click.echo(f"Label Format: {config.label_format}")
    click.echo(f"Orientation: {config.orientation}")
    click.echo(f"Config Version: {config.config_version}")

    # Check printer status
    printer = get_printer(config.printer_name)
    click.echo("\n=== Printer Status ===\n")

    if printer.is_available:
        printers = printer.get_printers()
        if printers:
            click.echo("Available printers:")
            for p in printers:
                p_status = printer.get_printer_status(p["name"])
                marker = "*" if p.get("is_default") or p["name"] == config.printer_name else " "
                click.echo(f"  {marker} {p['name']} [{p_status}]")
        else:
            click.echo("No printers found")
    else:
        click.echo("CUPS not available")


@main.command()
def test():
    """Test connection to server and printer."""
    config = get_config()

    if not config.is_configured():
        click.echo("Error: Agent not configured. Run 'flyprint pair' first.")
        sys.exit(1)

    setup_logging("INFO")

    click.echo("\n=== Testing FlyPrint Connection ===\n")

    agent = get_agent(config)
    results = agent.test_connection()

    # Server status
    server = results["server"]
    server_icon = "+" if server["status"] == "ok" else "x"
    click.echo(f"{server_icon} Server: {server['message']}")

    # Printer status
    printer = results["printer"]
    printer_icon = (
        "+" if printer["status"] == "ok" else ("!" if printer["status"] == "warning" else "x")
    )
    click.echo(f"{printer_icon} Printer: {printer['message']}")

    if printer.get("printers"):
        click.echo(f"  Available: {', '.join(printer['printers'])}")

    click.echo("")

    if results["success"]:
        click.echo("All tests passed! You can now run 'flyprint start'.")
    else:
        click.echo("Some tests failed. Please check the configuration.")
        sys.exit(1)


@main.command()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def start(verbose: bool):
    """Start the FlyPrint agent.

    The agent will poll the server for print jobs and print them
    automatically. Press Ctrl+C to stop.
    """
    config = get_config()

    if not config.is_configured():
        click.echo("Error: Agent not configured. Run 'flyprint pair' first.")
        sys.exit(1)

    level = "DEBUG" if verbose else config.log_level
    setup_logging(level)

    click.echo("Starting FlyPrint agent... (Ctrl+C to stop)")

    agent = get_agent(config)
    agent.run()


@main.command()
def printers():
    """List available printers."""
    printer = get_printer()

    click.echo("\n=== Available Printers ===\n")

    if not printer.is_available:
        click.echo("CUPS not available. Is it installed and running?")
        sys.exit(1)

    printers_list = printer.get_printers()
    if not printers_list:
        click.echo("No printers found.")
        return

    default = printer.get_default_printer()

    for p in printers_list:
        p_status = printer.get_printer_status(p["name"])
        is_default = p["name"] == default
        marker = "* " if is_default else "  "
        click.echo(f"{marker}{p['name']} [{p_status}]")

    click.echo("\n(* = default printer)")


@main.command("install-service")
@click.option("--user", is_flag=True, help="Install as user service (no sudo required)")
def install_service(user: bool):
    """Install systemd service for auto-start.

    Creates a systemd service file so FlyPrint starts automatically
    on boot.
    """
    config = get_config()

    if not config.is_configured():
        click.echo("Error: Agent not configured. Run 'flyprint pair' first.")
        sys.exit(1)

    service_content = f"""[Unit]
Description=FlyPrint Label Printing Agent
After=network.target cups.service

[Service]
Type=simple
ExecStart={sys.executable} -m flyprint start
Restart=on-failure
RestartSec=10
Environment=HOME={Path.home()}

[Install]
WantedBy={"default.target" if user else "multi-user.target"}
"""

    if user:
        service_dir = Path.home() / ".config" / "systemd" / "user"
        service_path = service_dir / "flyprint.service"
    else:
        service_path = Path("/etc/systemd/system/flyprint.service")

    click.echo("\nService file content:\n")
    click.echo(service_content)

    if user:
        service_dir.mkdir(parents=True, exist_ok=True)
        with open(service_path, "w") as f:
            f.write(service_content)

        click.echo(f"\nService installed to {service_path}")
        click.echo("\nTo enable and start the service:")
        click.echo("  systemctl --user daemon-reload")
        click.echo("  systemctl --user enable flyprint")
        click.echo("  systemctl --user start flyprint")
        click.echo("\nTo view logs:")
        click.echo("  journalctl --user -u flyprint -f")
    else:
        click.echo("\nTo install as system service, run:")
        click.echo(f"  sudo tee {service_path} << 'EOF'")
        click.echo(service_content)
        click.echo("EOF")
        click.echo("\nThen enable and start:")
        click.echo("  sudo systemctl daemon-reload")
        click.echo("  sudo systemctl enable flyprint")
        click.echo("  sudo systemctl start flyprint")


@main.command()
def gui():
    """Launch FlyPrint with system tray GUI.

    Opens a system tray icon with status display and controls.
    Shows pairing dialog if not yet configured.
    """
    from flyprint.app_entry import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
