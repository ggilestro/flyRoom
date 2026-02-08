"""Configuration management for FlyPrint agent."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

# Default configuration directory
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "flyprint"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"
DEFAULT_CACHED_CONFIG_FILE = DEFAULT_CONFIG_DIR / "cached_config.json"

# Default server URL for pairing
DEFAULT_SERVER_URL = "https://flypush.gilest.ro"


@dataclass
class FlyPrintConfig:
    """Configuration for the FlyPrint agent.

    Core settings (saved to config.json):
        server_url: Base URL of the FlyPush server.
        api_key: API key for agent authentication.

    Operational settings (managed by server, cached locally):
        printer_name: CUPS printer name to use (None = default).
        poll_interval: Seconds between polling for jobs.
        label_format: Default label format.
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR).
        orientation: Print orientation (0=portrait, 90=landscape, 180/270=reversed).
        code_type: Code type for labels ('qr' or 'barcode').
        copies: Default copies per label.
        config_version: Server config version for sync tracking.
    """

    server_url: str = ""
    api_key: str = ""
    printer_name: str | None = None
    poll_interval: int = 5
    label_format: str = "dymo_11352"
    log_level: str = "INFO"
    orientation: int = 0
    code_type: str = "qr"
    copies: int = 1
    config_version: int = 0

    def is_configured(self) -> bool:
        """Check if the agent has been configured.

        Returns:
            bool: True if server_url and api_key are set.
        """
        return bool(self.server_url and self.api_key)

    def save(self, config_path: Path | None = None) -> None:
        """Save core config (server_url + api_key) to file.

        Args:
            config_path: Path to config file (default: ~/.config/flyprint/config.json).
        """
        path = config_path or DEFAULT_CONFIG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)

        core_data = {
            "server_url": self.server_url,
            "api_key": self.api_key,
        }

        with open(path, "w") as f:
            json.dump(core_data, f, indent=2)

        # Secure the config file (contains API key)
        os.chmod(path, 0o600)

    def save_cached_config(self, cache_path: Path | None = None) -> None:
        """Save operational config to cached_config.json.

        Args:
            cache_path: Path to cache file.
        """
        path = cache_path or DEFAULT_CACHED_CONFIG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)

        cached_data = {
            "printer_name": self.printer_name,
            "poll_interval": self.poll_interval,
            "label_format": self.label_format,
            "log_level": self.log_level,
            "orientation": self.orientation,
            "code_type": self.code_type,
            "copies": self.copies,
            "config_version": self.config_version,
        }

        with open(path, "w") as f:
            json.dump(cached_data, f, indent=2)

    def apply_server_config(self, data: dict) -> None:
        """Apply config received from server and save cache.

        Args:
            data: Config dict from server's /agent/config endpoint.
        """
        if "printer_name" in data:
            self.printer_name = data["printer_name"]
        if "poll_interval" in data:
            self.poll_interval = data["poll_interval"]
        if "label_format" in data:
            self.label_format = data["label_format"]
        if "log_level" in data:
            self.log_level = data["log_level"]
        if "orientation" in data:
            self.orientation = data["orientation"]
        if "code_type" in data:
            self.code_type = data["code_type"]
        if "copies" in data:
            self.copies = data["copies"]
        if "config_version" in data:
            self.config_version = data["config_version"]

        self.save_cached_config()

    @classmethod
    def load(cls, config_path: Path | None = None) -> "FlyPrintConfig":
        """Load configuration from file(s).

        Supports both old all-in-one format and new split format.
        Loads core config from config.json, then overlays cached_config.json.

        Args:
            config_path: Path to config file.

        Returns:
            FlyPrintConfig: Loaded configuration or default.
        """
        path = config_path or DEFAULT_CONFIG_FILE

        if not path.exists():
            return cls()

        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, TypeError) as e:
            print(f"Warning: Error loading config: {e}")
            return cls()

        # Backward compatibility: old format has all fields in one file
        config = cls(
            server_url=data.get("server_url", ""),
            api_key=data.get("api_key", ""),
            printer_name=data.get("printer_name"),
            poll_interval=data.get("poll_interval", 5),
            label_format=data.get("label_format", "dymo_11352"),
            log_level=data.get("log_level", "INFO"),
            orientation=data.get("orientation", 0),
            code_type=data.get("code_type", "qr"),
            copies=data.get("copies", 1),
            config_version=data.get("config_version", 0),
        )

        # Overlay cached config if it exists (new format)
        cache_path = path.parent / "cached_config.json"
        if cache_path.exists():
            try:
                with open(cache_path) as f:
                    cached = json.load(f)
                if "printer_name" in cached:
                    config.printer_name = cached["printer_name"]
                if "poll_interval" in cached:
                    config.poll_interval = cached["poll_interval"]
                if "label_format" in cached:
                    config.label_format = cached["label_format"]
                if "log_level" in cached:
                    config.log_level = cached["log_level"]
                if "orientation" in cached:
                    config.orientation = cached["orientation"]
                if "code_type" in cached:
                    config.code_type = cached["code_type"]
                if "copies" in cached:
                    config.copies = cached["copies"]
                if "config_version" in cached:
                    config.config_version = cached["config_version"]
            except (json.JSONDecodeError, TypeError):
                pass  # Ignore corrupted cache

        return config


def get_config(config_path: Path | None = None) -> FlyPrintConfig:
    """Get the current configuration.

    Args:
        config_path: Optional custom config path.

    Returns:
        FlyPrintConfig: Current configuration.
    """
    return FlyPrintConfig.load(config_path)
