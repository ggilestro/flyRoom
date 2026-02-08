"""Tkinter pairing dialog for first-run setup."""

import logging
import platform
import threading
import tkinter as tk
from tkinter import messagebox

import requests

from flyprint.config import DEFAULT_SERVER_URL, FlyPrintConfig
from flyprint.printing import get_printer

logger = logging.getLogger(__name__)


def do_pairing(
    server_url: str,
    code: str | None = None,
) -> dict | None:
    """Execute pairing request against server.

    Shared between CLI and GUI. Gathers printer info and sends
    pairing request to the server.

    Args:
        server_url: FlyPush server URL.
        code: Optional 6-char pairing code.

    Returns:
        dict | None: Pairing result with api_key/agent_name/agent_id, or None on failure.

    Raises:
        requests.ConnectionError: If server is unreachable.
        requests.RequestException: On other HTTP errors.
    """
    hostname = platform.node()
    server_url = server_url.rstrip("/")

    # Gather available printers
    available_printers = []
    try:
        printer = get_printer()
        if printer.is_available:
            for p in printer.get_printers():
                available_printers.append(
                    {"name": p["name"], "is_default": p.get("is_default", False)}
                )
    except Exception:
        pass

    response = requests.post(
        f"{server_url}/api/labels/agent/pair",
        json={
            "code": code or None,
            "hostname": hostname,
            "available_printers": available_printers,
        },
        timeout=15,
    )

    if response.status_code == 200:
        return response.json()
    elif response.status_code == 404:
        detail = response.json().get("detail", "No matching pairing session found")
        raise ValueError(detail)
    else:
        detail = response.json().get("detail", f"HTTP {response.status_code}")
        raise RuntimeError(f"Pairing failed: {detail}")


class PairingDialog:
    """Tkinter dialog for first-run pairing.

    Shows server URL field, pairing code field, and pair button.
    On success, saves config and closes.
    """

    def __init__(self, default_server_url: str = DEFAULT_SERVER_URL):
        """Initialize pairing dialog.

        Args:
            default_server_url: Pre-filled server URL.
        """
        self.result: FlyPrintConfig | None = None
        self.default_server_url = default_server_url

    def show(self) -> FlyPrintConfig | None:
        """Show the pairing dialog and block until closed.

        Returns:
            FlyPrintConfig | None: Config if pairing succeeded, None if cancelled.
        """
        self.root = tk.Tk()
        self.root.title("FlyPrint Setup")
        self.root.resizable(False, False)

        # Center window
        w, h = 420, 300
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        self._build_ui()
        self.root.mainloop()
        return self.result

    def _build_ui(self):
        """Build the dialog UI."""
        frame = tk.Frame(self.root, padx=20, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)

        # Title
        title = tk.Label(frame, text="FlyPrint Setup", font=("", 16, "bold"))
        title.pack(pady=(0, 5))

        subtitle = tk.Label(
            frame,
            text="Connect this agent to your FlyPush server.",
            font=("", 10),
            fg="gray",
        )
        subtitle.pack(pady=(0, 15))

        # Server URL
        tk.Label(frame, text="Server URL:", anchor="w").pack(fill=tk.X)
        self.server_var = tk.StringVar(value=self.default_server_url)
        server_entry = tk.Entry(frame, textvariable=self.server_var, width=45)
        server_entry.pack(fill=tk.X, pady=(2, 10))

        # Pairing code
        tk.Label(
            frame,
            text="Pairing Code (leave empty for auto-pairing):",
            anchor="w",
        ).pack(fill=tk.X)
        self.code_var = tk.StringVar()
        code_entry = tk.Entry(frame, textvariable=self.code_var, width=20, font=("Courier", 14))
        code_entry.pack(fill=tk.X, pady=(2, 15))

        # Status label
        self.status_var = tk.StringVar(value="")
        self.status_label = tk.Label(frame, textvariable=self.status_var, fg="gray")
        self.status_label.pack(pady=(0, 10))

        # Buttons
        btn_frame = tk.Frame(frame)
        btn_frame.pack(fill=tk.X)

        self.pair_btn = tk.Button(
            btn_frame,
            text="Pair",
            command=self._on_pair,
            width=15,
            bg="#2563eb",
            fg="white",
        )
        self.pair_btn.pack(side=tk.RIGHT, padx=(5, 0))

        cancel_btn = tk.Button(
            btn_frame,
            text="Cancel",
            command=self._on_cancel,
            width=10,
        )
        cancel_btn.pack(side=tk.RIGHT)

    def _on_pair(self):
        """Handle pair button click."""
        server_url = self.server_var.get().strip()
        code = self.code_var.get().strip() or None

        if not server_url:
            messagebox.showerror("Error", "Please enter a server URL.")
            return

        self.pair_btn.config(state=tk.DISABLED)
        self.status_var.set("Connecting...")
        self.status_label.config(fg="gray")

        # Run pairing in background thread to avoid blocking UI
        thread = threading.Thread(target=self._do_pair, args=(server_url, code), daemon=True)
        thread.start()

    def _do_pair(self, server_url: str, code: str | None):
        """Execute pairing in background thread.

        Args:
            server_url: Server URL.
            code: Optional pairing code.
        """
        try:
            result = do_pairing(server_url, code)
            if result:
                config = FlyPrintConfig(
                    server_url=server_url.rstrip("/"),
                    api_key=result["api_key"],
                )
                config.save()
                self.result = config

                self.root.after(0, self._on_success, result["agent_name"])
            else:
                self.root.after(0, self._on_error, "Pairing returned no result")
        except requests.ConnectionError:
            self.root.after(0, self._on_error, f"Could not connect to {server_url}")
        except ValueError as e:
            self.root.after(0, self._on_error, str(e))
        except Exception as e:
            self.root.after(0, self._on_error, str(e))

    def _on_success(self, agent_name: str):
        """Handle successful pairing.

        Args:
            agent_name: Name assigned to the agent.
        """
        self.status_var.set(f"Paired as '{agent_name}'!")
        self.status_label.config(fg="green")
        messagebox.showinfo("Success", f"Paired successfully as '{agent_name}'!")
        self.root.destroy()

    def _on_error(self, message: str):
        """Handle pairing error.

        Args:
            message: Error message to display.
        """
        self.status_var.set(message)
        self.status_label.config(fg="red")
        self.pair_btn.config(state=tk.NORMAL)

    def _on_cancel(self):
        """Handle cancel button."""
        self.root.destroy()
