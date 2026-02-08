"""GUI entry point for FlyPrint desktop application.

Launches the system tray icon with agent running in background thread.
Shows pairing dialog on first run.
"""

import json
import logging
import sys
import threading
from pathlib import Path

from flyprint import __version__
from flyprint.config import DEFAULT_SERVER_URL, get_config

logger = logging.getLogger(__name__)


def _get_bundled_server_url() -> str:
    """Check for a bundled config.json next to the executable.

    When distributed with a pre-seeded server URL, the config is placed
    next to the binary so users don't need to type it manually.

    Returns:
        str: Server URL from bundled config, or DEFAULT_SERVER_URL.
    """
    if getattr(sys, "frozen", False):
        # PyInstaller bundle: look next to the executable
        exe_dir = Path(sys.executable).parent
    else:
        # Running from source: look next to this file
        exe_dir = Path(__file__).parent

    bundled_config = exe_dir / "config.json"
    if bundled_config.exists():
        try:
            with open(bundled_config) as f:
                data = json.load(f)
            return data.get("server_url", DEFAULT_SERVER_URL)
        except (json.JSONDecodeError, KeyError):
            pass
    return DEFAULT_SERVER_URL


def _setup_logging():
    """Set up logging for the GUI application."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )


def main():
    """Main entry point for the FlyPrint GUI application.

    Flow:
    1. Load config from ~/.config/flyprint/
    2. Check for bundled config next to executable
    3. If not configured: show pairing dialog
    4. Start agent in background thread
    5. Run tray icon on main thread (required by macOS)
    """
    _setup_logging()
    logger.info(f"FlyPrint GUI v{__version__} starting")

    # Load existing config
    config = get_config()

    # If not configured, show pairing dialog
    if not config.is_configured():
        default_url = _get_bundled_server_url()

        from flyprint.gui.pairing_dialog import PairingDialog

        dialog = PairingDialog(default_server_url=default_url)
        config = dialog.show()

        if config is None:
            logger.info("Pairing cancelled, exiting")
            sys.exit(0)

    # Verify config is valid
    if not config.is_configured():
        logger.error("Configuration is incomplete")
        sys.exit(1)

    # Import here to avoid circular imports and allow GUI-less usage
    from flyprint.agent import FlyPrintAgent
    from flyprint.gui.tray import TrayApp

    # Create agent instance
    agent = FlyPrintAgent(config)

    # Agent control functions
    agent_thread: threading.Thread | None = None

    def start_agent():
        nonlocal agent_thread
        if agent_thread and agent_thread.is_alive():
            return

        def _run():
            try:
                agent.run()
            except Exception as e:
                logger.exception(f"Agent error: {e}")
                tray.connected = False
                tray.agent_running = False

        agent_thread = threading.Thread(target=_run, daemon=True, name="flyprint-agent")
        agent_thread.start()
        tray.agent_running = True

    def stop_agent():
        agent.running = False
        tray.agent_running = False
        tray.connected = False

    def quit_app():
        agent.running = False
        tray.stop()

    # Create tray app
    tray = TrayApp(
        config=config,
        on_start=start_agent,
        on_stop=stop_agent,
        on_quit=quit_app,
    )

    # Patch agent to update tray status on heartbeat
    _original_send_heartbeat = agent.send_heartbeat

    def _patched_heartbeat():
        result = _original_send_heartbeat()
        tray.connected = result is not None

        # Check for update notification
        if result and "latest_agent_version" in result:
            try:
                latest_str = result["latest_agent_version"]
                current = tuple(int(x) for x in __version__.split("."))
                latest = tuple(int(x) for x in latest_str.split("."))
                if latest > current:
                    tray.notify_update_available(latest_str)
            except (ValueError, AttributeError):
                pass

        return result

    agent.send_heartbeat = _patched_heartbeat

    # Start agent in background
    start_agent()

    # Run tray on main thread (blocks until quit)
    logger.info("Starting system tray")
    tray.run()

    logger.info("FlyPrint GUI exiting")


if __name__ == "__main__":
    main()
