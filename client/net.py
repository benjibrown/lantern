import socket
import threading
import time
import platform
import subprocess
import json

class NetworkManager:
    def __init__(self, config, state):
        self.config = config
        self.state = state
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self.last_ping_sent = 0.0
        self.last_ping_recv = 0.0
        self.ping_ms = None

    def connect(self):
        self.sock.sendto(
            f"[LOGIN]|{self.config.USERNAME}|{self.config.PASSWORD}".encode(),
            (self.config.SERVER_HOST, self.config.SERVER_PORT),
        )

    def send_join(self):
        self.sock.sendto(
            f"[JOIN]|{self.config.USERNAME}".encode(),
            (self.config.SERVER_HOST, self.config.SERVER_PORT),
        )

    def send_message(self, msg):
        try:
            self.sock.sendto(msg.encode(), (self.config.SERVER_HOST, self.config.SERVER_PORT))
        except OSError:
            with self.state.lock:
                self.state.send_failed = True

    def send_leave(self):
        try:
            self.sock.sendto(
                f"[LEAVE]|{self.config.USERNAME}".encode(),
                (self.config.SERVER_HOST, self.config.SERVER_PORT),
            )
        except Exception:
            pass

    def request_user_list(self):
        self.sock.sendto(
            f"[REQ_USERS]|{self.config.USERNAME}".encode(),
            (self.config.SERVER_HOST, self.config.SERVER_PORT),
        )

    def request_users_detailed(self):
        self.sock.sendto(
            f"[REQ_USERS_DETAILED]|{self.config.USERNAME}".encode(),
            (self.config.SERVER_HOST, self.config.SERVER_PORT),
        )

    def send_dm(self, recipient: str, text: str):
        try:
            self.sock.sendto(
                f"[DM]|{recipient}|{text}".encode(),
                (self.config.SERVER_HOST, self.config.SERVER_PORT),
            )
        except OSError:
            with self.state.lock:
                self.state.send_failed = True

    def request_dm_history(self, other_user: str):
        self.sock.sendto(
            f"[REQ_DM_HISTORY]|{other_user}".encode(),
            (self.config.SERVER_HOST, self.config.SERVER_PORT),
        )

    def keepalive(self):
        while self.state.running:
            try:
                self.last_ping_sent = time.time()
                self.sock.sendto(b"[ping]", (self.config.SERVER_HOST, self.config.SERVER_PORT))
                time.sleep(5)
            except Exception:
                pass

    def receive(self):
        while self.state.running:
            try:
                data, _ = self.sock.recvfrom(4096)
                msg = data.decode(errors="ignore").strip()

                if not msg:
                    continue

                with self.state.lock:
                    self.state.last_received_from_server = time.time()

                if msg == "[ping]":
                    self.last_ping_recv = time.time()
                    if self.last_ping_sent > 0:
                        self.ping_ms = int((self.last_ping_recv - self.last_ping_sent) * 1000)
                    continue

                if msg == "[AUTH_OK]":
                    self.send_join()
                    continue

                if msg.startswith("[AUTH_FAIL]|"):
                    with self.state.lock:
                        self.state.auth_failed = True
                    continue

                if msg.startswith("[CHANNEL_HISTORY]|"):
                    parts = msg.split("|", 2)
                    if len(parts) >= 3:
                        idx, chunk = int(parts[1]), parts[2]
                        with self.state.lock:
                            while len(self.state.channel_history_buffer) <= idx:
                                self.state.channel_history_buffer.append("")
                            self.state.channel_history_buffer[idx] = chunk
                    continue

                if msg == "[CHANNEL_HISTORY_END]":
                    with self.state.lock:
                        try:
                            full = "".join(self.state.channel_history_buffer)
                            if full:
                                history = json.loads(full)
                                for m in history:
                                    text = m.get("text", "")
                                    sender = m.get("sender", "")
                                    is_self = sender == self.config.USERNAME
                                    self.state.messages.append((text, is_self))
                                self.state.messages[:] = self.state.messages[-self.config.MAX_MESSAGES:]
                            self.state.channel_history_buffer = []
                            self.state.channel_history_ready = True
                            self.state.authenticated = True
                        except Exception:
                            self.state.channel_history_buffer = []
                            self.state.channel_history_ready = True
                            self.state.authenticated = True
                    continue

                with self.state.lock:
                    if msg.startswith("[USERS]|"):
                        self.state.users = set(msg.split("|", 1)[1].split(";"))
                        if not self.state.channel_history_ready:
                            self.state.authenticated = True
                        continue

                    if msg.startswith("[USERS_DETAILED]|"):
                        raw = msg.split("|", 1)[1]
                        self.state.users_detailed = []
                        for part in raw.split(";"):
                            if not part:
                                continue
                            bits = part.split(",", 2)
                            u = bits[0] if bits else ""
                            status = bits[1] if len(bits) > 1 else "offline"
                            ts = float(bits[2]) if len(bits) > 2 else 0
                            self.state.users_detailed.append((u, status, ts))
                        self.state.users_detailed.sort(key=lambda x: -x[2])
                        continue

                    if msg.startswith("[DM]|"):
                        parts = msg.split("|", 3)
                        if len(parts) >= 4:
                            _, from_user, _ts, text = parts[0], parts[1], parts[2], parts[3]
                            is_self = from_user == self.config.USERNAME
                            if is_self:
                                continue
                            self.state.append_dm(from_user, f"[{from_user}]: {text}", False)
                            if not self.state.dnd:
                                try:
                                    if platform.system() == "Darwin":
                                        subprocess.run(["osascript", "-e", f'display notification "DM from {from_user}" with title "Lantern"'])
                                    elif platform.system() == "Linux":
                                        subprocess.run(["notify-send", "Lantern", f"DM from {from_user}"])
                                except Exception:
                                    pass
                        continue

                    if msg.startswith("[DM_FAIL]|"):
                        continue

                    if msg.startswith("[DM_HISTORY]|"):
                        parts = msg.split("|", 2)
                        if len(parts) >= 3:
                            other, payload = parts[1], parts[2]
                            try:
                                history = json.loads(payload)
                                self.state.ensure_dm_conversation(other)
                                self.state.dm_conversations[other] = []
                                for m in history:
                                    sender = m.get("sender", "")
                                    text = m.get("text", "")
                                    is_self = sender == self.config.USERNAME
                                    self.state.dm_conversations[other].append((f"[{sender}]: {text}", is_self))
                                self.state.dm_conversations[other][:] = self.state.dm_conversations[other][-self.config.MAX_MESSAGES:]
                                self.state.pending_dm_history = None
                            except Exception:
                                self.state.pending_dm_history = None
                        continue

                    is_self = msg.startswith(f"[{self.config.USERNAME}]:") or msg.startswith(f"[{self.config.USERNAME}] system")
                    self.state.messages.append((msg[: self.config.MAX_MSG_LEN], is_self))
                    self.state.messages[:] = self.state.messages[-self.config.MAX_MESSAGES:]
                    # TODO - ANSII detection for focus - only show noti if window not focused, this is fine for now, if u hate notis run /dnd
                    if not is_self and not self.state.dnd:
                        try:
                            if platform.system() == "Darwin":
                                subprocess.run(["osascript", "-e", f'display notification "{msg[:50]}" with title "New Message"'])
                            elif platform.system() == "Linux":
                                subprocess.run(["notify-send", "New Message", msg[:50]])
                        except Exception:
                            pass

            except BlockingIOError:
                time.sleep(0.03)
            except Exception:
                time.sleep(0.1)

    def start_threads(self):
        threading.Thread(target=self.receive, daemon=True).start()
        threading.Thread(target=self.keepalive, daemon=True).start()

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass

    def system_fetch(self):
        return {
            "OS": f"{platform.system()} {platform.release()}",
            "Kernel": platform.version().split()[0],
            "Host": platform.node(),
            "Arch": platform.machine(),
        }
