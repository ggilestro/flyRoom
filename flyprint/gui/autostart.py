"""Platform-specific auto-start on login management."""

import logging
import platform
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_executable_path() -> str:
    """Get the path to the current executable.

    Returns:
        str: Path to flyprint executable or python interpreter.
    """
    # Reason: When running as PyInstaller bundle, sys.executable points to the bundle
    if getattr(sys, "frozen", False):
        return sys.executable
    return f"{sys.executable} -m flyprint gui"


# ============================================================================
# Linux: XDG autostart .desktop file
# ============================================================================

_LINUX_DESKTOP_DIR = Path.home() / ".config" / "autostart"
_LINUX_DESKTOP_FILE = _LINUX_DESKTOP_DIR / "flyprint.desktop"


def _linux_is_enabled() -> bool:
    """Check if Linux autostart is enabled."""
    return _LINUX_DESKTOP_FILE.exists()


def _linux_enable():
    """Enable Linux autostart via .desktop file."""
    exe_path = _get_executable_path()
    content = f"""[Desktop Entry]
Type=Application
Name=FlyPrint
Comment=FlyPush label printing agent
Exec={exe_path}
Icon=flyprint
Terminal=false
Categories=Utility;
StartupNotify=false
X-GNOME-Autostart-enabled=true
"""
    _LINUX_DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    _LINUX_DESKTOP_FILE.write_text(content)
    logger.info(f"Autostart enabled: {_LINUX_DESKTOP_FILE}")


def _linux_disable():
    """Disable Linux autostart."""
    if _LINUX_DESKTOP_FILE.exists():
        _LINUX_DESKTOP_FILE.unlink()
        logger.info("Autostart disabled")


# ============================================================================
# macOS: LaunchAgent plist
# ============================================================================

_MACOS_LAUNCH_DIR = Path.home() / "Library" / "LaunchAgents"
_MACOS_PLIST_FILE = _MACOS_LAUNCH_DIR / "ro.gilest.flyprint.plist"


def _macos_is_enabled() -> bool:
    """Check if macOS LaunchAgent is enabled."""
    return _MACOS_PLIST_FILE.exists()


def _macos_enable():
    """Enable macOS autostart via LaunchAgent plist."""
    exe_path = _get_executable_path()

    # Reason: Split command into ProgramArguments for launchd
    if getattr(sys, "frozen", False):
        program_args = f"    <string>{exe_path}</string>"
    else:
        program_args = (
            f"    <string>{sys.executable}</string>\n"
            f"    <string>-m</string>\n"
            f"    <string>flyprint</string>\n"
            f"    <string>gui</string>"
        )

    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>ro.gilest.flyprint</string>
    <key>ProgramArguments</key>
    <array>
{program_args}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
"""
    _MACOS_LAUNCH_DIR.mkdir(parents=True, exist_ok=True)
    _MACOS_PLIST_FILE.write_text(content)
    logger.info(f"LaunchAgent enabled: {_MACOS_PLIST_FILE}")


def _macos_disable():
    """Disable macOS autostart."""
    if _MACOS_PLIST_FILE.exists():
        _MACOS_PLIST_FILE.unlink()
        logger.info("LaunchAgent disabled")


# ============================================================================
# Windows: Registry Run key
# ============================================================================

_WIN_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_WIN_REG_NAME = "FlyPrint"


def _windows_is_enabled() -> bool:
    """Check if Windows autostart registry key exists."""
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_REG_KEY, 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, _WIN_REG_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except ImportError:
        return False
    except OSError:
        return False


def _windows_enable():
    """Enable Windows autostart via registry."""
    try:
        import winreg

        exe_path = _get_executable_path()
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_REG_KEY, 0, winreg.KEY_WRITE)
        winreg.SetValueEx(key, _WIN_REG_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
        winreg.CloseKey(key)
        logger.info("Windows autostart enabled via registry")
    except ImportError:
        logger.error("winreg not available")
    except OSError as e:
        logger.error(f"Failed to set registry key: {e}")


def _windows_disable():
    """Disable Windows autostart via registry."""
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_REG_KEY, 0, winreg.KEY_WRITE)
        try:
            winreg.DeleteValue(key, _WIN_REG_NAME)
        except FileNotFoundError:
            pass
        winreg.CloseKey(key)
        logger.info("Windows autostart disabled")
    except ImportError:
        pass
    except OSError as e:
        logger.error(f"Failed to remove registry key: {e}")


# ============================================================================
# Public API
# ============================================================================


def is_autostart_enabled() -> bool:
    """Check if autostart on login is enabled.

    Returns:
        bool: True if autostart is enabled for the current platform.
    """
    system = platform.system()
    if system == "Linux":
        return _linux_is_enabled()
    elif system == "Darwin":
        return _macos_is_enabled()
    elif system == "Windows":
        return _windows_is_enabled()
    return False


def enable_autostart():
    """Enable autostart on login for the current platform."""
    system = platform.system()
    if system == "Linux":
        _linux_enable()
    elif system == "Darwin":
        _macos_enable()
    elif system == "Windows":
        _windows_enable()
    else:
        logger.warning(f"Autostart not supported on {system}")


def disable_autostart():
    """Disable autostart on login for the current platform."""
    system = platform.system()
    if system == "Linux":
        _linux_disable()
    elif system == "Darwin":
        _macos_disable()
    elif system == "Windows":
        _windows_disable()


def toggle_autostart():
    """Toggle autostart on login."""
    if is_autostart_enabled():
        disable_autostart()
    else:
        enable_autostart()
