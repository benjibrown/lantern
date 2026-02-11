import socket
import time
from rich import print


class NetworkManager:
    def __init__(self, host, port, state):
        self.host = host
        self.port = port
        self.state = state
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, port))

    def broadcast(self, msg, exclude_addr=None):

        for addr in list(self.state.clients):
            if addr == exclude_addr:
                continue
            try:
                self.sock.sendto(msg.encode(), addr)
            except Exception:
                self.state.clients.pop(addr, None)

    def send_user_list(self, target_addr=None):
        user_list = ";".join(info["username"] for info in self.state.clients.values())

        msg = f"[USERS]|{user_list}"

        if target_addr:
            try:
                self.sock.sendto(msg.encode(), target_addr)
            except:
                pass
        else:
            self.broadcast(msg)

    def handle_ping(self, addr):
        self.sock.sendto(b"[ping]", addr)
        if addr in self.state.clients:
            self.state.clients[addr]["last_seen"] = time.time()

    def handle_join(self, msg, addr):
        username = msg.split("|", 1)[1]
        now = time.time()
        self.state.clients[addr] = {
            "username": username,
            "last_seen": now
        }

        print(f"[green][+][/green] {username} joined from {addr}")

        # notify others
        self.broadcast(f"[{username} joined]", exclude_addr=addr)

        # sync user lists
        self.send_user_list()  # everyone
        self.send_user_list(addr)  # just in case

    def handle_leave(self, msg, addr):
        username = self.state.clients.get(addr, {}).get("username", "unknown")
        self.state.clients.pop(addr, None)

        print(f"[red][-][/red] {username} left")

        self.broadcast(f"[{username} left]")
        self.send_user_list()

    def handle_req_users(self, addr):
        self.send_user_list(addr)

    def handle_message(self, msg, addr):
        sender = self.state.clients.get(addr, {}).get("username", str(addr))
        print(f"[purple][>][/purple] {sender}: {msg}")

        self.broadcast(msg, exclude_addr=addr)

    def run(self):
        print(f"[blue][*][/blue] UDP server listening on {self.host}:{self.port}")

        while True:
            try:
                data, addr = self.sock.recvfrom(4096)
                msg = data.decode(errors="ignore").strip()
                now = time.time()

                # update heartbeat
                if addr in self.state.clients:
                    self.state.clients[addr]["last_seen"] = now

                # ---- ping ----
                if msg == "[ping]":
                    self.handle_ping(addr)
                    continue

                # ---- join ----
                if msg.startswith("[JOIN]|"):
                    self.handle_join(msg, addr)
                    continue

                # ---- leave ----
                if msg.startswith("[LEAVE]|"):
                    self.handle_leave(msg, addr)
                    continue

                # ---- request user list ----
                if msg.startswith("[REQ_USERS]|"):
                    self.handle_req_users(addr)
                    continue

                # ---- normal messages ----
                self.handle_message(msg, addr)

            except Exception as e:
                print("[red][ERROR][/red]", e)
