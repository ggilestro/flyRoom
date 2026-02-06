"""Configuration management for FlyPrint agent."""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

# Default configuration directory
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "flyprint"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"


@dataclass
class FlyPrintConfig:
    """Configuration for the FlyPrint agent.

    Attributes:
        server_url: Base URL of the FlyPush server.
        api_key: API key for agent authentication.
        printer_name: CUPS printer name to use (None = default).
        poll_interval: Seconds between polling for jobs.
        label_format: Default label format.
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR).
        orientation: Print orientation (0=portrait, 90=landscape, 180/270=reversed).
    """

    server_url: str = ""
    api_key: str = ""
    printer_name: str | None = None
    poll_interval: int = 5
    label_format: str = "dymo_11352"
    log_level: str = "INFO"
    orientation: int = 0  # 0, 90, 180, or 270 degrees

    def is_configured(self) -> bool:
        """Check if the agent has been configured.

        Returns:
            bool: True if server_url and api_key are set.
        """
        return bool(self.server_url and self.api_key)

    def save(self, config_path: Path | None = None) -> None:
        """Save configuration to file.

        Args:
            config_path: Path to config file (default: ~/.config/flyprint/config.json).
        """
        path = config_path or DEFAULT_CONFIG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)

        # Secure the config file (contains API key)
        os.chmod(path, 0o600)

    @classmethod
    def load(cls, config_path: Path | None = None) -> "FlyPrintConfig":
        """Load configuration from file.

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
            return cls(**data)
        except (json.JSONDecodeError, TypeError) as e:
            print(f"Warning: Error loading config: {e}")
            return cls()


def get_config(config_path: Path | None = None) -> FlyPrintConfig:
    """Get the current configuration.

    Args:
        config_path: Optional custom config path.

    Returns:
        FlyPrintConfig: Current configuration.
    """
    return FlyPrintConfig.load(config_path)
