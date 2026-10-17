"""网络层：原始 socket + 自维护缓冲区的按行 JSON 收发。"""

from __future__ import annotations

import json
import socket
import queue
import threading
from enum import Enum
from typing import Any, cast


class MessageType(Enum):
    """网络消息类型。"""

    WELCOME = "welcome"
    STATE = "state"
    ORDER = "order"
    CANCEL = "cancel"
    CONVERT = "convert"
    END_TURN = "end_turn"
    ERROR = "error"


NetworkEvent = tuple[str, dict[str, Any]]


class LanPeer:
    """一条 TCP 连接上的按行 JSON 收发。"""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.sock.settimeout(1.0)
        self.buffer: bytes = b""
        self.sendLock = threading.Lock()
        self.closed = False

    def Send(self, message: dict[str, Any]) -> None:
        """发送一条 JSON 消息。"""
        if self.closed:
            return
        payload = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        with self.sendLock:
            try:
                self.sock.sendall(payload)
            except OSError:
                self.closed = True

    def Read(self) -> dict[str, Any] | None:
        """阻塞读取一条 JSON 消息；连接断开返回 None。"""
        while not self.closed:
            newlineIndex = self.buffer.find(b"\n")
            if newlineIndex >= 0:
                line = self.buffer[:newlineIndex]
                self.buffer = self.buffer[newlineIndex + 1 :]
                try:
                    data = json.loads(line.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if isinstance(data, dict):
                    return cast(dict[str, Any], data)
                continue
            try:
                chunk = self.sock.recv(65536)
            except TimeoutError:
                continue
            except OSError:
                return None
            if not chunk:
                return None
            self.buffer += chunk
        return None

    def Close(self) -> None:
        """关闭连接；shutdown 会让阻塞中的 recv 立刻返回。"""
        self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class LanServer:
    """主机侧：监听端口、接受一个客户端、在子线程里读取消息。"""

    def __init__(self, port: int, eventQueue: queue.Queue[NetworkEvent]) -> None:
        self.eventQueue = eventQueue
        self.peer: LanPeer | None = None
        self.closed = False
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("", port))
        self.listener.listen(1)
        self.listener.settimeout(1.0)
        self.thread = threading.Thread(target=self.AcceptLoop, daemon=True)
        self.thread.start()

    def AcceptLoop(self) -> None:
        """等待客户端接入，然后持续读取客户端消息。"""
        while not self.closed:
            try:
                clientSock, address = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            if self.closed:
                try:
                    clientSock.close()
                except OSError:
                    pass
                return

            peer = LanPeer(clientSock)
            self.peer = peer
            self.eventQueue.put(
                ("peer_connected", {"address": f"{address[0]}:{address[1]}"})
            )
            while not self.closed:
                message = peer.Read()
                if message is None:
                    break
                self.eventQueue.put(("peer_message", message))
            self.eventQueue.put(("peer_disconnected", {}))
            return

    def Send(self, message: dict[str, Any]) -> None:
        """向客户端发送消息。"""
        peer = self.peer
        if peer is not None:
            peer.Send(message)

    def Close(self) -> None:
        """关闭监听与连接。"""
        self.closed = True
        peer = self.peer
        if peer is not None:
            peer.Close()
        try:
            self.listener.close()
        except OSError:
            pass


class LanClient:
    """客户端：在子线程里连接主机并读取消息。"""

    def __init__(
        self, host: str, port: int, eventQueue: "queue.Queue[NetworkEvent]"
    ) -> None:
        self.eventQueue = eventQueue
        self.peer: LanPeer | None = None
        self.closed = False
        self.thread = threading.Thread(
            target=self.ConnectLoop, args=(host, port), daemon=True
        )
        self.thread.start()

    def ConnectLoop(self, host: str, port: int) -> None:
        """连接主机，成功后进入消息读取循环。"""
        try:
            sock = socket.create_connection((host, port), timeout=5.0)
            sock.settimeout(None)
        except OSError as exc:
            self.eventQueue.put(("error", {"text": f"连接失败：{exc}"}))
            return

        peer = LanPeer(sock)
        self.peer = peer
        self.eventQueue.put(("connected", {"address": f"{host}:{port}"}))
        while not self.closed:
            message = peer.Read()
            if message is None:
                break
            self.eventQueue.put(("message", message))
        self.eventQueue.put(("disconnected", {}))

    def Send(self, message: dict[str, Any]) -> None:
        """向主机发送消息。"""
        peer = self.peer
        if peer is not None:
            peer.Send(message)

    def Close(self) -> None:
        """关闭连接。"""
        self.closed = True
        peer = self.peer
        if peer is not None:
            peer.Close()


def GetLocalIp() -> str:
    """获取本机局域网 IP，用于提示主机地址。"""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return cast(str, probe.getsockname()[0])
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        probe.close()
