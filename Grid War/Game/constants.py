"""全局常量与配色。"""

from __future__ import annotations

from typing import Final

from .models import Faction

GRID_SIZE: Final[int] = 16
CELL_SIZE: Final[int] = 38
MAX_STACK: Final[int] = 4
CITY_COST: Final[int] = 4
CITY_MAX: Final[int] = 20
CITY_DIS_MIN: Final[int] = 3
START_ZONE_RADIUS: Final[int] = 2
DEFAULT_PORT: Final[int] = 5555
POLL_INTERVAL_MS: Final[int] = 40

COLOR_PANEL: Final[str] = "#141922"
COLOR_CANVAS: Final[str] = "#0d1117"
COLOR_GRID: Final[str] = "#232b38"
COLOR_TEXT: Final[str] = "#e6ebf2"
COLOR_MUTED: Final[str] = "#8b93a7"
COLOR_ACCENT: Final[str] = "#ffd257"

FACTION_COLORS: Final[dict[Faction, str]] = {
    Faction.RED: "#e5534b",
    Faction.BLUE: "#4c8dff",
    Faction.NEUTRAL: "#9aa0aa",
}

TERRITORY_COLORS: Final[dict[Faction, str]] = {
    Faction.RED: "#2c1a20",
    Faction.BLUE: "#182338",
    Faction.NEUTRAL: "#20242c",
}
