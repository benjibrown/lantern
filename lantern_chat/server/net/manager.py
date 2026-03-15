import socket
import time
import threading
import json
from rich import print
from lantern_chat.frame import send_msg, recv_msg

from lantern_chat.server.net.handlers import HandlerMixin, registry


class networkManager(HandlerMixin):
    def __init__(self, host, port, state):
        self.host = host
        self.port = port
        self.state = state
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.listen(50)

    def send(self, addr, msg: str):
        # send to a specific connected client by addr key
        client = self.state.clients.get(addr)
        if client:
            try:
                send_msg(client["conn"], msg)
            except Exception:
                self.state.clients.pop(addr, None)

    def sendConn(self, conn: socket.socket, msg: str):
        # send directly to a connection before it's been added to clients (e.g. during auth)
        try:
            send_msg(conn, msg)
        except Exception:
            pass

    def broadcast(self, msg, excludeAddr=None):
        for addr, info in list(self.state.clients.items()):
            if addr == excludeAddr:
                continue
            try:
                send_msg(info["conn"], msg)
            except Exception:
                self.state.clients.pop(addr, None)

    def sendToUser(self, username: str, msg: str) -> bool:
        for addr, info in list(self.state.clients.items()):
            if info.get("username") == username:
                try:
                    send_msg(info["conn"], msg)
                except Exception:
                    self.state.clients.pop(addr, None)
                return True
        return False

    def sendUserList(self, targetAddr=None):
        userList = ";".join(info["username"] for info in self.state.clients.values())
        msg = f"[USERS]|{userList}"
        if targetAddr:
            self.send(targetAddr, msg)
        else:
            self.broadcast(msg)

    def sendAdminList(self, targetAddr=None):
        admins = ";".join(sorted(self.state.admins))
        msg = f"[ADMINS]|{admins}"
        if targetAddr:
            self.send(targetAddr, msg)
        else:
            self.broadcast(msg)

    def sendMaxMessageLen(self, addr):
        self.send(addr, f"[MAX_MSG_LEN]|{self.state.max_msg_len}")

    def sendUserStats(self, addr, username: str):
        stats = self.state.get_user_stats(username)
        if not stats:
            return
        self.send(addr, f"[USER_STATS]|{json.dumps(stats)}")

    def sendUserListDetailed(self, addr, requestingUsername: str):
        online = set(info["username"] for info in self.state.clients.values())
        allRegistered = set(self.state.users.keys())
        allUsers = allRegistered | online
        entries = []
        for u in sorted(allUsers):
            if self.state.is_banned(u):
                continue
            status = "online" if u in online else "offline"
            lastDmMap = self.state.get_last_dm_time_for_user(requestingUsername)
            ts = lastDmMap.get(u, 0)
            entries.append(f"{u},{status},{ts}")
        self.send(addr, f"[USERS_DETAILED]|{';'.join(entries)}")

    def _handleClient(self, conn: socket.socket, addr):
        # per-client receive loop - each connection runs in its own thread
        try:
            while True:
                msg = recv_msg(conn)
                if msg is None:
                    break  # client disconnected cleanly

                if addr in self.state.clients:
                    self.state.clients[addr]["last_seen"] = time.time()

                if msg == "[ping]":
                    self.handlePing(addr)
                    continue

                ctx = {"addr": addr, "conn": conn}

                if msg.startswith("[REQ_USER_STATS]"):
                    parts = msg.split("|", 1)
                    username = parts[1].strip() if len(parts) > 1 else None
                    if not username:
                        username = self.state.clients.get(addr, {}).get("username")
                    if username:
                        self.sendUserStats(addr, username)
                    continue
                if msg.startswith("[REQ_MAX_MSG_LEN]"):
                    self.sendMaxMessageLen(addr)
                    continue

                result = registry.dispatch(msg, ctx, self)
                if result is not None:
                    continue

                self.handleMessage(msg, ctx)

        except Exception as e:
            print(f"[red][ERROR][/red] client {addr}: {e}")
        finally:
            # clean up if not already removed (e.g. from ban or explicit leave)
            if addr in self.state.clients:
                self.handleLeave({"addr": addr, "conn": None}, None)
            else:
                try:
                    conn.close()
                except Exception:
                    pass

    def handleMessage(self, msg, ctx):
        addr = ctx["addr"]
        clientInfo = self.state.clients.get(addr)
        if not clientInfo:
            return
        sender = clientInfo.get("username", str(addr))
        if self.state.is_muted(sender):
            self.send(addr, "[ADMIN_ERROR]|You are muted and cannot send to the main channel")
            return
        now = time.time()
        last = clientInfo.get("last_msg", 0)
        if self.state.msg_rate_limit > 0 and (now - last) < self.state.msg_rate_limit:
            wait = round(self.state.msg_rate_limit - (now - last), 1)
            self.send(addr, f"[RATE_LIMITED]|{wait}")
            return
        clientInfo["last_msg"] = now
        print(f"[purple][>][/purple] {sender} {msg}")
        self.state.add_channel_message(sender, msg)
        self.broadcast(msg, excludeAddr=addr)

    def cleanupLoop(self):
        while True:
            time.sleep(5)
            now = time.time()
            for addr, info in list(self.state.clients.items()):
                if now - info["last_seen"] > 60:
                    print(f"[yellow][TIMEOUT][/yellow] {info['username']} removed")
                    self.handleLeave({"addr": addr, "conn": info.get("conn")}, None)

    def run(self):
        print(f"[blue][*][/blue] TCP server listening on {self.host}:{self.port}")
        threading.Thread(target=self.cleanupLoop, daemon=True).start()
        while True:
            try:
                conn, addr = self.sock.accept()
                threading.Thread(target=self._handleClient, args=(conn, addr), daemon=True).start()
            except Exception as e:
                print(f"[red][ERROR][/red] accept: {e}")