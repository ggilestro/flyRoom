"""System tray icon and menu using pystray."""

import logging
import threading
import webbrowser

from flyprint.config import FlyPrintConfig

logger = logging.getLogger(__name__)


def _create_icon_image(connected: bool = False):
    """Create a simple tray icon image.

    Args:
        connected: If True, use green color; otherwise gray.

    Returns:
        PIL.Image: 64x64 icon image.
    """
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw a filled circle as the icon
    color = (34, 197, 94, 255) if connected else (156, 163, 175, 255)
    margin = 4
    draw.ellipse([margin, margin, size - margin, size - margin], fill=color)

    # Draw a "P" in white in the center
    try:
        from PIL import ImageFont

        font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 32)
    except (OSError, ImportError):
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), "P", font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = (size - text_w) // 2
    text_y = (size - text_h) // 2 - 2
    draw.text((text_x, text_y), "P", fill=(255, 255, 255, 255), font=font)

    return img


class TrayApp:
    """System tray application for FlyPrint.

    Displays agent status, provides menu for start/stop, test connection,
    open web UI, autostart toggle, and quit.
    """

    def __init__(
        self,
        config: FlyPrintConfig,
        agent_thread: threading.Thread | None = None,
        on_start: callable = None,
        on_stop: callable = None,
        on_quit: callable = None,
    ):
        """Initialize tray app.

        Args:
            config: FlyPrint configuration.
            agent_thread: Reference to the agent background thread.
            on_start: Callback to start the agent.
            on_stop: Callback to stop the agent.
            on_quit: Callback to quit the application.
        """
        self.config = config
        self.agent_thread = agent_thread
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_quit = on_quit
        self._connected = False
        self._agent_running = False
        self._icon = None
        self._update_available = False
        self._latest_version: str | None = None

    @property
    def connected(self) -> bool:
        """Whether the agent is connected to the server."""
        return self._connected

    @connected.setter
    def connected(self, value: bool):
        """Update connected status and refresh icon.

        Args:
            value: New connection status.
        """
        self._connected = value
        if self._icon:
            self._icon.icon = _create_icon_image(value)

    @property
    def agent_running(self) -> bool:
        """Whether the agent is currently running."""
        return self._agent_running

    @agent_running.setter
    def agent_running(self, value: bool):
        """Update agent running status and refresh menu.

        Args:
            value: New running status.
        """
        self._agent_running = value
        if self._icon:
            self._icon.update_menu()

    def notify_update_available(self, latest_version: str):
        """Show a notification that an update is available.

        Args:
            latest_version: The latest available version string.
        """
        self._update_available = True
        self._latest_version = latest_version
        if self._icon:
            self._icon.notify(
                f"FlyPrint update available: v{latest_version}",
                "Click to download the latest version.",
            )

    def _build_menu(self):
        """Build the system tray menu.

        Returns:
            pystray.Menu: The tray menu.
        """
        import pystray

        from flyprint.gui.autostart import is_autostart_enabled

        status_text = "Connected" if self._connected else "Disconnected"
        printer_text = self.config.printer_name or "(default)"
        server_text = self.config.server_url or "(not configured)"

        items = [
            pystray.MenuItem(f"Status: {status_text}", None, enabled=False),
            pystray.MenuItem(f"Printer: {printer_text}", None, enabled=False),
            pystray.MenuItem(f"Server: {server_text}", None, enabled=False),
            pystray.Menu.SEPARATOR,
        ]

        if self._agent_running:
            items.append(pystray.MenuItem("Stop Agent", self._on_stop))
        else:
            items.append(pystray.MenuItem("Start Agent", self._on_start))

        items.extend(
            [
                pystray.MenuItem("Test Connection", self._on_test),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Open Web UI", self._on_open_web),
                pystray.MenuItem(
                    "Start on Login",
                    self._on_toggle_autostart,
                    checked=lambda _: is_autostart_enabled(),
                ),
            ]
        )

        if self._update_available and self._latest_version:
            items.append(
                pystray.MenuItem(
                    f"Update Available (v{self._latest_version})",
                    self._on_update,
                )
            )

        items.extend(
            [
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._on_quit),
            ]
        )

        return pystray.Menu(*items)

    def run(self):
        """Run the system tray icon (blocks on main thread).

        Must be called from the main thread on macOS.
        """
        import pystray

        icon_image = _create_icon_image(self._connected)

        self._icon = pystray.Icon(
            "flyprint",
            icon_image,
            "FlyPrint",
            menu=self._build_menu(),
        )

        self._icon.run()

    def stop(self):
        """Stop the system tray icon."""
        if self._icon:
            self._icon.stop()

    def _on_start(self, icon=None, item=None):
        """Handle 'Start Agent' menu click."""
        if self.on_start:
            self.on_start()
        self.agent_running = True

    def _on_stop(self, icon=None, item=None):
        """Handle 'Stop Agent' menu click."""
        if self.on_stop:
            self.on_stop()
        self.agent_running = False

    def _on_test(self, icon=None, item=None):
        """Handle 'Test Connection' menu click."""
        from flyprint.agent import get_agent

        try:
            agent = get_agent(self.config)
            results = agent.test_connection()

            server_ok = results["server"]["status"] == "ok"
            printer_ok = results["printer"]["status"] in ("ok", "warning")

            msg = f"Server: {'OK' if server_ok else 'FAILED'}\n"
            msg += f"Printer: {'OK' if printer_ok else 'FAILED'}"

            if self._icon:
                self._icon.notify("FlyPrint Connection Test", msg)
        except Exception as e:
            if self._icon:
                self._icon.notify("Connection Test Failed", str(e))

    def _on_open_web(self, icon=None, item=None):
        """Handle 'Open Web UI' menu click."""
        if self.config.server_url:
            webbrowser.open(f"{self.config.server_url}/settings")

    def _on_toggle_autostart(self, icon=None, item=None):
        """Handle 'Start on Login' toggle."""
        from flyprint.gui.autostart import toggle_autostart

        toggle_autostart()
        if self._icon:
            self._icon.update_menu()

    def _on_update(self, icon=None, item=None):
        """Handle 'Update Available' click - open download page."""
        if self.config.server_url:
            webbrowser.open(f"{self.config.server_url}/settings#print-agents")

    def _on_quit(self, icon=None, item=None):
        """Handle 'Quit' menu click."""
        if self.on_quit:
            self.on_quit()
        self.stop()
