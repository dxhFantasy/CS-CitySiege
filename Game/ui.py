"""Tkinter 界面与交互。"""

from __future__ import annotations

import queue
import tkinter as tk
from tkinter import messagebox
from typing import Any, Protocol, cast

from .constants import (
    CELL_SIZE,
    CITY_COST,
    COLOR_ACCENT,
    COLOR_CANVAS,
    COLOR_GRID,
    COLOR_MUTED,
    COLOR_PANEL,
    COLOR_TEXT,
    DEFAULT_PORT,
    FACTION_COLORS,
    GRID_SIZE,
    # MAX_STACK,
    POLL_INTERVAL_MS,
    TERRITORY_COLORS,
    CITY_MAX,
    CITY_DIS_MIN
)
from .gameState import GameState
from .models import City, Faction, Order, Pos, Stack
from .network import GetLocalIp, LanClient, LanServer, MessageType, NetworkEvent


class ClickEvent(Protocol):
    """画布鼠标事件需要的字段。"""

    x: int
    y: int


class BattleGameApp(tk.Tk):
    """主窗口：绘制棋盘、处理输入、分发网络事件。"""

    def __init__(self) -> None:
        super().__init__()
        self.title("局域网战棋 · 城池争夺")
        self.resizable(False, False)
        self.configure(bg=COLOR_PANEL)

        self.game: GameState = GameState()
        self.mode: str = "menu"          # menu / host / client / local
        self.myFaction: Faction | None = None
        self.remoteFaction: Faction | None = None
        self.selected: Pos | None = None
        self.peerReady: bool = False
        self.busy: bool = False
        self.closing: bool = False
        self.winnerShown: bool = False
        self.boardVisible: bool = False
        self.server: LanServer | None = None
        self.client: LanClient | None = None
        self.eventQueue: "queue.Queue[NetworkEvent]" = queue.Queue()

        self.BuildUi()
        self.ShowMenuUi()
        self.RefreshUi()
        self.protocol("WM_DELETE_WINDOW", self.OnClose)
        self.after(POLL_INTERVAL_MS, self.ProcessEvents)

    # ---- 界面搭建 -------------------------------------------------------

    def BuildUi(self) -> None:
        """搭建棋盘与右侧面板。想改布局/配色从这里入手。"""
        boardPixels = GRID_SIZE * CELL_SIZE
        self.canvas = tk.Canvas(
            self,
            width=boardPixels,
            height=boardPixels,
            bg=COLOR_CANVAS,
            highlightthickness=0,
        )
        self.canvas.grid(row=0, column=0, padx=12, pady=12)
        self.canvas.bind("<Button-1>", self.OnCanvasClick)
        self.canvas.bind("<Button-3>", self.OnCanvasRightClick)

        self.sidebar = tk.Frame(self, bg=COLOR_PANEL)
        self.sidebar.grid(row=0, column=1, padx=(0, 12), pady=12, sticky="n")

        tk.Label(
            self.sidebar,
            text="城池争夺",
            font=("Microsoft YaHei", 18, "bold"),
            fg=COLOR_TEXT,
            bg=COLOR_PANEL,
        ).pack(anchor="w")

        self.statusLabel = tk.Label(
            self.sidebar,
            text="选择模式",
            font=("Microsoft YaHei", 9),
            fg=COLOR_MUTED,
            bg=COLOR_PANEL,
            justify="left",
            wraplength=250,
        )
        self.statusLabel.pack(anchor="w", pady=(2, 12))

        self.connectFrame = tk.Frame(self.sidebar, bg=COLOR_PANEL)
        self.gameFrame = tk.Frame(self.sidebar, bg=COLOR_PANEL)

        portRow = tk.Frame(self.connectFrame, bg=COLOR_PANEL)
        portRow.pack(fill="x", pady=2)
        tk.Label(
            portRow, text="端口", fg=COLOR_TEXT, bg=COLOR_PANEL
        ).pack(side="left")
        self.portEntry = tk.Entry(portRow, width=7)
        self.portEntry.insert(0, str(DEFAULT_PORT))
        self.portEntry.pack(side="left", padx=4)
        tk.Button(
            portRow, text="创建主机", command=self.StartHost, width=10
        ).pack(side="left")

        ipRow = tk.Frame(self.connectFrame, bg=COLOR_PANEL)
        ipRow.pack(fill="x", pady=2)
        tk.Label(
            ipRow, text="主机 IP", fg=COLOR_TEXT, bg=COLOR_PANEL
        ).pack(side="left")
        self.ipEntry = tk.Entry(ipRow, width=12)
        self.ipEntry.insert(0, "127.0.0.1")
        self.ipEntry.pack(side="left", padx=4)
        tk.Button(ipRow, text="加入", command=self.StartClient, width=7).pack(
            side="left"
        )

        tk.Button(
            self.connectFrame,
            text="本地双人（同一台电脑）",
            command=self.StartLocal,
        ).pack(fill="x", pady=(8, 0))

        tk.Label(
            self.connectFrame,
            text="提示：主机需允许防火墙访问；两台电脑连同一路由器/热点，加入方填主机的局域网 IP。",
            font=("Microsoft YaHei", 8),
            fg=COLOR_MUTED,
            bg=COLOR_PANEL,
            wraplength=240,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        self.turnLabel = tk.Label(
            self.gameFrame,
            text="",
            font=("Microsoft YaHei", 12, "bold"),
            fg=COLOR_TEXT,
            bg=COLOR_PANEL,
        )
        self.turnLabel.pack(anchor="w")

        self.scoreLabel = tk.Label(
            self.gameFrame,
            text="",
            font=("Microsoft YaHei", 9),
            fg=COLOR_MUTED,
            bg=COLOR_PANEL,
        )
        self.scoreLabel.pack(anchor="w", pady=(2, 8))

        actionRow = tk.Frame(self.gameFrame, bg=COLOR_PANEL)
        actionRow.pack(fill="x", pady=(0, 4))
        self.convertButton = tk.Button(
            actionRow, text="建城（4 士兵）", command=self.OnConvertClick
        )
        self.convertButton.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.undoButton = tk.Button(
            actionRow, text="撤回指令", command=self.OnUndoClick
        )
        self.undoButton.pack(side="left", expand=True, fill="x")

        self.endTurnButton = tk.Button(
            self.gameFrame,
            text="结束回合（结算指令）",
            command=self.OnEndTurnClick,
        )
        self.endTurnButton.pack(fill="x", pady=(0, 6))

        self.hintLabel = tk.Label(
            self.gameFrame,
            text="",
            font=("Microsoft YaHei", 9),
            fg=COLOR_MUTED,
            bg=COLOR_PANEL,
            wraplength=250,
            justify="left",
        )
        self.hintLabel.pack(anchor="w", pady=(4, 8))

        self.logBox = tk.Text(
            self.gameFrame,
            height=14,
            width=34,
            bg="#0d1117",
            fg="#c7d0dd",
            insertbackground="#c7d0dd",
            relief="flat",
            font=("Microsoft YaHei", 9),
            wrap="word",
        )
        self.logBox.pack(fill="both", expand=True)
        self.logBox.configure(state="disabled")

    def ShowMenuUi(self) -> None:
        """显示连接面板。"""
        self.boardVisible = False
        self.connectFrame.pack(fill="x")
        self.gameFrame.pack_forget()

    def ShowGameUi(self) -> None:
        """显示对局面板。"""
        self.boardVisible = True
        self.connectFrame.pack_forget()
        self.gameFrame.pack(fill="both", expand=True)

    # ---- 日志与状态 -----------------------------------------------------

    def Log(self, text: str) -> None:
        """追加一行日志。"""
        self.logBox.configure(state="normal")
        self.logBox.insert("end", text + "\n")
        lineCount = int(self.logBox.index("end-1c").split(".")[0])
        if lineCount > 400:
            self.logBox.delete("1.0", "50.0")
        self.logBox.see("end")
        self.logBox.configure(state="disabled")

    def SetStatus(self, text: str) -> None:
        """更新模式状态文字。"""
        self.statusLabel.configure(text=text)

    # ---- 模式入口 -------------------------------------------------------

    def StartHost(self) -> None:
        """创建主机，等待对手加入。"""
        if self.mode != "menu" or self.busy:
            return
        try:
            port = int(self.portEntry.get().strip())
        except ValueError:
            messagebox.showerror("端口错误", "请输入有效的端口号。") # type: ignore
            return
        try:
            self.server = LanServer(port, self.eventQueue)
        except OSError as exc:
            messagebox.showerror("无法创建主机", f"端口 {port} 监听失败：{exc}") # type: ignore
            return
        self.busy = True
        self.SetStatus(f"等待对手加入…\n本机 IP：{GetLocalIp()}\n端口：{port}")
        self.Log(f"已在端口 {port} 开启主机，等待对手加入。")

    def StartClient(self) -> None:
        """加入主机。"""
        if self.mode != "menu" or self.busy:
            return
        try:
            port = int(self.portEntry.get().strip())
        except ValueError:
            messagebox.showerror("端口错误", "请输入有效的端口号。") # type: ignore
            return
        host = self.ipEntry.get().strip() or "127.0.0.1"
        self.busy = True
        self.SetStatus(f"正在连接 {host}:{port} …")
        self.client = LanClient(host, port, self.eventQueue)

    def StartLocal(self) -> None:
        """本地双人（热座）模式。"""
        if self.mode != "menu":
            return
        self.mode = "local"
        self.myFaction = None
        self.peerReady = True
        self.ShowGameUi()
        self.RefreshUi()
        self.Log("本地双人模式：红方先行动。")

    # ---- 网络事件 -------------------------------------------------------

    def ProcessEvents(self) -> None:
        """主线程定时拉取网络事件，避免子线程操作 Tk 控件。"""
        if self.closing:
            return
        try:
            while True:
                kind, payload = self.eventQueue.get_nowait()
                try:
                    self.HandleEvent(kind, payload)
                except Exception as exc:  # 保证单个事件不会打断轮询
                    self.Log(f"处理网络事件失败：{exc}")
        except queue.Empty:
            pass
        if not self.closing:
            self.after(POLL_INTERVAL_MS, self.ProcessEvents)

    def HandleEvent(self, kind: str, payload: dict[str, Any]) -> None:
        """分发网络事件。"""
        if kind == "peer_connected":
            self.OnPeerConnected(payload)
        elif kind == "peer_message":
            self.HandleClientMessage(payload)
        elif kind == "connected":
            self.SetStatus("已连接，等待主机同步局面…")
        elif kind == "message":
            self.OnServerMessage(payload)
        elif kind in ("peer_disconnected", "disconnected"):
            self.OnDisconnected()
        elif kind == "error":
            self.busy = False
            text = str(payload.get("text", "连接失败"))
            self.SetStatus(text)
            messagebox.showerror("连接失败", text) # type: ignore

    def OnPeerConnected(self, payload: dict[str, Any]) -> None:
        """主机：客户端接入后分配阵营并发送初始状态。"""
        self.mode = "host"
        self.myFaction = Faction.RED
        self.remoteFaction = Faction.BLUE
        self.peerReady = True
        self.busy = False
        self.ShowGameUi()

        server = self.server
        if server is not None:
            server.Send(
                {"type": MessageType.WELCOME.value, "faction": Faction.BLUE.value}
            )
            server.Send(
                {"type": MessageType.STATE.value, "state": self.game.ToDict()}
            )

        address = str(payload.get("address", ""))
        self.SetStatus(f"对战进行中 · 你是红方\n对手：{address}")
        self.Log(f"对手已连接（{address}），你执红方，先手。")
        self.RefreshUi()

    def OnServerMessage(self, payload: dict[str, Any]) -> None:
        """客户端：处理主机发来的欢迎/状态/错误消息。"""
        msgType = payload.get("type")
        if msgType == MessageType.WELCOME.value:
            factionValue = payload.get("faction")
            if isinstance(factionValue, str):
                try:
                    self.myFaction = Faction(factionValue)
                except ValueError:
                    self.myFaction = Faction.BLUE
            self.peerReady = True
            self.busy = False
            self.SetStatus("对战进行中 · 你是蓝方")
            self.Log("已加入主机，你执蓝方。")
        elif msgType == MessageType.STATE.value:
            rawState = payload.get("state")
            if isinstance(rawState, dict):
                self.game = GameState.FromDict(cast(dict[str, Any], rawState))
                if self.mode == "menu":
                    self.mode = "client"
                if not self.boardVisible:
                    self.ShowGameUi()
                self.selected = None
                self.RefreshUi()
                self.MaybeShowWinner()
        elif msgType == MessageType.ERROR.value:
            self.Log(str(payload.get("text", "操作无效")))

    def HandleClientMessage(self, payload: dict[str, Any]) -> None:
        """主机：处理客户端指令，主机是权威状态。"""
        if self.mode != "host" or not self.peerReady or self.remoteFaction is None:
            return

        msgType = payload.get("type")
        if msgType == MessageType.ORDER.value:
            try:
                fromX = int(payload["fromX"])
                fromY = int(payload["fromY"])
                toX = int(payload["toX"])
                toY = int(payload["toY"])
            except (KeyError, TypeError, ValueError):
                self.SendError("指令格式错误")
                return
            if not self.game.ApplyOrder(
                self.remoteFaction, (fromX, fromY), (toX, toY)
            ):
                self.SendError("指令无效")
            self.AfterAction()
        elif msgType == MessageType.CANCEL.value:
            try:
                x = int(payload["x"])
                y = int(payload["y"])
            except (KeyError, TypeError, ValueError):
                self.SendError("撤回指令格式错误")
                return
            if not self.game.CancelOrder(self.remoteFaction, (x, y)):
                self.SendError("没有可撤回的指令")
            self.AfterAction()
        elif msgType == MessageType.CONVERT.value:
            try:
                x = int(payload["x"])
                y = int(payload["y"])
            except (KeyError, TypeError, ValueError):
                self.SendError("建城指令格式错误")
                return
            if not self.game.ApplyConvert(self.remoteFaction, (x, y)):
                self.SendError("建城无效")
            self.AfterAction()
        elif msgType == MessageType.END_TURN.value:
            if self.game.turn is self.remoteFaction:
                self.game.EndTurn()
                self.AfterAction()
            else:
                self.SendError("还没轮到你行动")
                self.AfterAction()

    def SendError(self, text: str) -> None:
        """主机：向客户端发送错误提示。"""
        server = self.server
        if server is not None:
            server.Send({"type": MessageType.ERROR.value, "text": text})

    def BroadcastState(self) -> None:
        """主机：广播完整状态。"""
        if self.mode != "host":
            return
        server = self.server
        if server is not None:
            server.Send(
                {"type": MessageType.STATE.value, "state": self.game.ToDict()}
            )

    def OnDisconnected(self) -> None:
        """连接断开处理。"""
        if self.closing:
            return
        self.peerReady = False
        self.SetStatus("连接已断开")
        self.Log("与对手的连接已断开。")
        self.RefreshUi()
        if self.mode in ("host", "client"):
            messagebox.showwarning("连接断开", "对手已离开，游戏结束。") # type: ignore # type: ignore

    # ---- 操作入口 -------------------------------------------------------

    def CanLocalAct(self) -> bool:
        """本机当前是否能操作。"""
        if self.mode == "menu" or self.closing:
            return False
        if self.game.winner is not None:
            return False
        if not self.peerReady:
            return False
        if self.mode == "local":
            return True
        return self.game.turn is self.myFaction

    def OnCanvasClick(self, event: ClickEvent) -> None:
        """左键：选中部队 / 下达指令。

        规则：已有选中部队时，只有再次点击它本身才会取消选中；
        点击其他格子一律视为给它下达指令，不会改选别的部队。
        """
        if not self.CanLocalAct():
            return
        x = event.x // CELL_SIZE
        y = event.y // CELL_SIZE
        if not (0 <= x < GRID_SIZE and 0 <= y < GRID_SIZE):
            return

        clicked: Pos = (x, y)
        stack = self.game.units[y][x]
        selection = self.selected

        if selection is None:
            if stack is not None and stack.faction is self.game.turn:
                if stack.moved:
                    if self.RequestCancel(clicked):
                        self.Log("已撤回该部队的指令。")
                        self.selected = clicked
                        self.RefreshBoard()
                else:
                    self.selected = clicked
                    self.RefreshBoard()
            return

        # 再点一次已选中的格子：取消选中
        if clicked == selection:
            self.selected = None
            self.RefreshBoard()
            return

        selectedStack = self.game.units[selection[1]][selection[0]]
        if selectedStack is None or selectedStack.faction is not self.game.turn:
            self.selected = None
            self.RefreshBoard()
            return

        # 关键改动：点击其他任何格子都只作为当前选中部队的目标，
        # 不再把点击到的己方部队改成新的选中对象。
        self.RequestOrder(selection, clicked)


    def OnCanvasRightClick(self, event: ClickEvent) -> None:
        """右键：撤回该格部队的指令。"""
        if not self.CanLocalAct():
            return
        x = event.x // CELL_SIZE
        y = event.y // CELL_SIZE
        if not (0 <= x < GRID_SIZE and 0 <= y < GRID_SIZE):
            return
        if self.RequestCancel((x, y)):
            self.Log("已撤回该部队的指令。")
            self.selected = None
            self.RefreshBoard()

    def RequestOrder(self, fromPos: Pos, toPos: Pos) -> None:
        """检查并下达移动/攻击指令。

        目标格有己方士兵也允许下单：如果目标格上的部队本回合会离开，
        结算时就能整合；如果没离开且已经满 4 个，这次移动原地不动。
        """
        if abs(fromPos[0] - toPos[0]) + abs(fromPos[1] - toPos[1]) != 1:
            self.Log("只能向上下左右相邻格下达指令。")
            return

        source = self.game.units[fromPos[1]][fromPos[0]]
        if source is None or source.moved:
            self.Log("这支部队本回合已经下过指令了。")
            return
        if source.faction is not self.game.turn:
            return

        if self.mode == "client":
            self.clientSend(
                {
                    "type": MessageType.ORDER.value,
                    "fromX": fromPos[0],
                    "fromY": fromPos[1],
                    "toX": toPos[0],
                    "toY": toPos[1],
                }
            )
            self.selected = None
            self.RefreshBoard()
            return

        # result: bool = self.game.ApplyOrder(source.faction, fromPos, toPos)
        # print(result)
        if self.game.ApplyOrder(source.faction, fromPos, toPos):
            self.AfterAction()
        else:
            self.Log("无法下达指令。")

    def RequestCancel(self, pos: Pos) -> bool:
        """撤回某格部队的指令，返回是否发出了撤回请求。"""
        x, y = pos
        stack = self.game.units[y][x]
        if (
            stack is None
            or stack.faction is not self.game.turn
            or not stack.moved
        ):
            return False
        if self.mode == "client":
            self.clientSend(
                {"type": MessageType.CANCEL.value, "x": x, "y": y}
            )
            return True
        if self.game.CancelOrder(self.game.turn, pos):
            self.selected = None
            self.AfterAction()
            return True
        return False

    def OnConvertClick(self) -> None:
        """建城（立即生效，需要该格没有指令）。"""
        if not self.CanLocalAct():
            return
        if self.selected is None:
            self.Log("请先选中一个己方部队格子。")
            return
        if len(self.game.cities) >= CITY_MAX:
            self.Log(f"场上最多存在{CITY_MAX}个城市")
            return 
        x, y = self.selected
        stack = self.game.units[y][x]
        if stack is None or stack.faction is not self.game.turn:
            self.Log("只能把己方部队变成城市。")
            return
        if stack.moved:
            self.Log("该部队已下达指令，请先撤回再建城。")
            return
        if stack.count < CITY_COST:
            self.Log(f"建城需要 {CITY_COST} 个士兵。")
            return
        if self.game.CityAt(x, y) is not None:
            self.Log("该格已经有城市了。")
            return
        if not self.game.CitySpacingOk(x, y):
            self.Log(f"每个城市之间的距离应至少为{CITY_DIS_MIN}。")
            return 

        if self.mode == "client":
            self.clientSend(
                {"type": MessageType.CONVERT.value, "x": x, "y": y}
            )
            self.selected = None
            self.RefreshBoard()
            return

        if self.game.ApplyConvert(self.game.turn, (x, y)):
            self.Log(f"{self.game.turn.DisplayName}在 ({x},{y}) 建立了一座城市。")
            self.AfterAction()
        else:
            self.Log("无法建城。")

    def OnUndoClick(self) -> None:
        """撤回当前选中部队的指令。"""
        if not self.CanLocalAct():
            return
        if self.selected is None:
            self.Log("请先选中一支部队。")
            return
        if not self.RequestCancel(self.selected):
            self.Log("该部队没有可撤回的指令。")

    def OnEndTurnClick(self) -> None:
        """结束回合：所有指令统一结算。"""
        if not self.CanLocalAct():
            return
        self.selected = None

        if self.mode == "client":
            self.clientSend({"type": MessageType.END_TURN.value})
            self.RefreshBoard()
            return

        orderCount = len(self.game.orders)
        self.game.EndTurn()
        self.AfterAction()
        if self.game.winner is None:
            self.Log(
                f"结算了 {orderCount} 条指令。第 {self.game.turnNumber} 回合 · "
                f"{self.game.turn.DisplayName}行动。"
            )

    def clientSend(self, message: dict[str, Any]) -> None:
        """客户端发送操作给主机。"""
        client = self.client
        if client is None or not self.peerReady:
            return
        client.Send(message)

    def AfterAction(self) -> None:
        """刷新界面、广播状态、检查胜负。"""
        self.selected = None
        self.RefreshUi()
        self.BroadcastState()
        self.MaybeShowWinner()

    def MaybeShowWinner(self) -> None:
        """记录一次胜负，并把弹窗放到事件循环顶层。"""
        winner = self.game.winner
        if winner is None or self.winnerShown:
            return
        self.winnerShown = True
        self.Log(
            f"{winner.DisplayName}占领了所有城市，并消灭了对方所有士兵，获得胜利！"
        )
        self.after_idle(self.ShowWinnerDialog)

    def ShowWinnerDialog(self) -> None:
        """在主事件循环顶层弹一次胜利提示。"""
        if self.closing:
            return
        winner = self.game.winner
        if winner is None:
            return
        messagebox.showinfo( # type: ignore
            "游戏结束",
            f"{winner.DisplayName}占领了所有城市并消灭了对方所有士兵，获得胜利！",
        )

    # ---- 绘制与刷新 -----------------------------------------------------

    def RefreshUi(self) -> None:
        """刷新棋盘、提示和按钮状态。"""
        self.RefreshBoard()
        game = self.game

        if game.winner is not None:
            self.turnLabel.configure(
                text=f"{game.winner.DisplayName} 获胜",
                fg=FACTION_COLORS[game.winner],
            )
        else:
            self.turnLabel.configure(
                text=f"第 {game.turnNumber} 回合 · {game.turn.DisplayName}行动",
                fg=FACTION_COLORS[game.turn],
            )

        redCount = game.CountSoldiers(Faction.RED)
        blueCount = game.CountSoldiers(Faction.BLUE)
        self.scoreLabel.configure(
            text=f"红 {redCount} · 蓝 {blueCount} · 待结算 {len(game.orders)}"
        )

        canAct = self.CanLocalAct()
        buttonState = "normal" if canAct else "disabled"
        self.convertButton.configure(state=buttonState)
        self.endTurnButton.configure(state=buttonState)

        hasOrder = False
        if self.selected is not None:
            selectedX, selectedY = self.selected
            selectedStack = game.units[selectedY][selectedX]
            if (
                selectedStack is not None
                and selectedStack.faction is game.turn
                and selectedStack.moved
            ):
                hasOrder = True
        self.undoButton.configure(
            state="normal" if canAct and hasOrder else "disabled"
        )

        if game.winner is not None:
            self.hintLabel.configure(text="游戏结束。")
        elif self.mode == "menu":
            self.hintLabel.configure(text="选择左侧模式后开始游戏。")
        elif canAct:
            self.hintLabel.configure(
                text="点击己方部队选中；已选中时再点它本身可取消选中，"
                "点其他格则给它下达移动/攻击指令。右键或“撤回指令”可撤销。"
                "所有指令在结束回合时统一结算。"
            )
        else:
            self.hintLabel.configure(text="等待对方行动…")

    def RefreshBoard(self) -> None:
        """按当前状态重绘棋盘。"""
        self.canvas.delete("all")
        game = self.game

        for y in range(GRID_SIZE):
            for x in range(GRID_SIZE):
                left = x * CELL_SIZE
                top = y * CELL_SIZE
                self.canvas.create_rectangle(
                    left,
                    top,
                    left + CELL_SIZE,
                    top + CELL_SIZE,
                    fill=TERRITORY_COLORS[game.territory[y][x]],
                    outline=COLOR_GRID,
                )

        for city in game.cities:
            self.DrawCity(city)

        for y in range(GRID_SIZE):
            for x in range(GRID_SIZE):
                stack = game.units[y][x]
                if stack is not None:
                    self.DrawStack(x, y, stack)

        for order in game.orders:
            self.DrawOrder(order)

        if self.selected is not None:
            selectedX, selectedY = self.selected
            self.canvas.create_rectangle(
                selectedX * CELL_SIZE + 2,
                selectedY * CELL_SIZE + 2,
                (selectedX + 1) * CELL_SIZE - 2,
                (selectedY + 1) * CELL_SIZE - 2,
                outline=COLOR_ACCENT,
                width=3,
            )

    def DrawCity(self, city: City) -> None:
        """画城市：菱形 + “城”字。"""
        x0 = city.x * CELL_SIZE
        y0 = city.y * CELL_SIZE
        centerX = x0 + CELL_SIZE / 2
        centerY = y0 + CELL_SIZE / 2
        size = CELL_SIZE / 2 - 3
        color = FACTION_COLORS[city.faction]
        points = [
            centerX,
            centerY - size,
            centerX + size,
            centerY,
            centerX,
            centerY + size,
            centerX - size,
            centerY,
        ]
        self.canvas.create_polygon(
            points, fill="#10141c", outline=color, width=2
        )
        self.canvas.create_text(
            x0 + 5,
            y0 + 3,
            text="城",
            anchor="nw",
            fill=color,
            font=("Microsoft YaHei", 8, "bold"),
        )

    def DrawStack(self, x: int, y: int, stack: Stack) -> None:
        """画部队；白色描边表示本回合已下指令。"""
        centerX = x * CELL_SIZE + CELL_SIZE // 2
        centerY = y * CELL_SIZE + CELL_SIZE // 2
        radius = 11 if self.game.CityAt(x, y) is not None else 13
        outline = (
            "#ffffff"
            if stack.moved and stack.faction is self.game.turn
            else COLOR_CANVAS
        )
        self.canvas.create_oval(
            centerX - radius,
            centerY - radius,
            centerX + radius,
            centerY + radius,
            fill=FACTION_COLORS[stack.faction],
            outline=outline,
            width=2,
        )
        self.canvas.create_text(
            centerX,
            centerY,
            text=str(stack.count),
            fill="#ffffff",
            font=("Microsoft YaHei", 10, "bold"),
        )

    def DrawOrder(self, order: Order) -> None:
        """画待结算指令：实线=攻击，虚线=移动/整合。"""
        startX = order.fromX * CELL_SIZE + CELL_SIZE // 2
        startY = order.fromY * CELL_SIZE + CELL_SIZE // 2
        endX = order.toX * CELL_SIZE + CELL_SIZE // 2
        endY = order.toY * CELL_SIZE + CELL_SIZE // 2
        target = self.game.units[order.toY][order.toX]
        isAttack = target is not None and target.faction is not order.faction
        self.canvas.create_line(
            startX,
            startY,
            endX,
            endY,
            fill=FACTION_COLORS[order.faction],
            width=3,
            arrow=tk.LAST,
            dash=() if isAttack else (5, 3),
        )

    # ---- 退出 -----------------------------------------------------------

    def OnClose(self) -> None:
        """关闭窗口：先断开网络，再结束主循环。"""
        if self.closing:
            return
        self.closing = True
        if self.server is not None:
            self.server.Close()
        if self.client is not None:
            self.client.Close()
        self.quit()
        self.destroy()
