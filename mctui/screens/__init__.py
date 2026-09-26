from .backups import backups
from .config_editor import config_editor
from .create_server import create_server
from .dashboard import dashboard
from .diagnostics import diagnostics
from .instances import instances
from .logs import logs
from .players import players
from .server_control import server_control
from .settings import settings

__all__ = [
    "dashboard",
    "server_control",
    "create_server",
    "instances",
    "players",
    "logs",
    "backups",
    "diagnostics",
    "config_editor",
    "settings",
]
