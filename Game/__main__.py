"""游戏入口"""

from __future__ import annotations

from .ui import BattleGameApp


def Main() -> None:
    """启动游戏。"""
    app = BattleGameApp()
    app.mainloop()


if __name__ == "__main__":
    Main()
