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
            self.sock.sendto(
                msg.encode(), (self.config.SERVER_HOST, self.config.SERVER_PORT)
            )
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

    def request_user_stats(self, username: str):
        self.sock.sendto(
            f"[REQ_USER_STATS]|{username}".encode(),
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
    # two ways i can send stuff 
    # b"...." - convert to bytes client side 
    # .encode() - same thing lol
    def request_fetch(self):
        self.sock.sendto(
            b"[REQ_FETCH]",
            (self.config.SERVER_HOST, self.config.SERVER_PORT),
        )

    def request_max_msg_len(self):
        self.sock.sendto(
            f"[REQ_MAX_MSG_LEN]|{self.config.USERNAME}".encode(),
            (self.config.SERVER_HOST, self.config.SERVER_PORT),
        )
    
    def send_admin_command(self, command: str, payload: str):
        if not self.state.session_token:
            # if we do not have a token yet, the server will not accept admin commands
            with self.state.lock:
                # append to messages if on main chat, append to dm if in dms 
                if self.state.in_dm:
                    self.state.append_dm(
                        self.state.dm_conversation_partner,
                        "[system] Cannot run admin command: no session token from server",
                        True,
                    )
                else:
                    self.state.messages.append(
                    ("[system] Cannot run admin command: no session token from server", True)
                )
            return
        full = f"[ADMIN_CMD]|{command}|{self.config.USERNAME}|{self.state.session_token}|{payload}"
        self.send_message(full)

    def keepalive(self):
        while self.state.running:
            try:
                self.last_ping_sent = time.time()
                self.sock.sendto(
                    b"[ping]", (self.config.SERVER_HOST, self.config.SERVER_PORT)
                )
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
                        self.ping_ms = int(
                            (self.last_ping_recv - self.last_ping_sent) * 1000
                        )
                    continue

                if msg.startswith("[AUTH_OK]"):
                    # capture session token if provided
                    parts = msg.split("|", 1)
                    if len(parts) > 1:
                        self.state.session_token = parts[1]
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
                                self.state.messages[:] = self.state.messages[
                                    -self.config.MAX_MESSAGES :
                                ]
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

                    if msg.startswith("[ADMINS]|"):
                        raw = msg.split("|", 1)[1]
                        self.state.admins = set(u for u in raw.split(";") if u)
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

                    # TODO - output in a window instead of sending a message to main chat, show last online time etc 
                    if msg.startswith("[USER_STATS]|"):
                        raw = msg.split("|", 1)[1]
                        try:
                            stats = json.loads(raw)
                        except Exception:
                            stats = None

                        
                        
                        self.state.user_stats = stats
                        
                        # format a human-readable stats message
                        if not stats:
                            lines = ["[system] No stats available for that user."]
                        else:
                            username = stats.get("username", "?")
                            is_admin = "yes" if stats.get("is_admin") else "no"
                            is_banned = "yes" if stats.get("is_banned") else "no"
                            is_muted = "yes" if stats.get("is_muted") else "no"
                            total_msgs = stats.get("total_channel_messages", 0)
                            lines = [
                                f"[system] Stats for '{username}':",
                                f"  Admin: {is_admin}",
                                f"  Banned: {is_banned}",
                                f"  Muted: {is_muted}",
                                f"  Channel messages: {total_msgs}",
                            ]

                        if self.state.current_view == "dm" and self.state.dm_target:
                            for line in lines:
                                self.state.append_dm(self.state.dm_target, line, True)
                        else:
                            for line in lines:
                                self.state.messages.append((line, True))
                            self.state.messages[:] = self.state.messages[
                                -self.config.MAX_MESSAGES :
                            ]
                        continue
                        
                    # fetch max message length from server
                    if msg.startswith("[MAX_MSG_LEN]|"):
                        try:
                            self.config.MAX_MESSAGE_LEN = int(msg.split("|", 1)[1])
                        except Exception:
                            pass
                        continue
                    
                    if msg == "[FETCH_OK]":
                        info = self.system_fetch()
                        if self.state.current_view == "dm" and self.state.dm_target:
                            self.state.append_dm(self.state.dm_target, "system", True)
                            for k, v in info.items():
                                self.state.append_dm(self.state.dm_target, f"  {k}: {v}", True)
                        else:
                            self.state.messages.append(("system", True))
                            for k, v in info.items():
                                self.state.messages.append((f"  {k}: {v}", True))
                        if self.state.current_view == "dm" and self.state.dm_target:
                            self.send_dm(self.state.dm_target, "system")
                            for k, v in info.items():
                                self.send_dm(self.state.dm_target, f"  {k}: {v}")
                        else:
                            self.send_message(f"[{self.config.USERNAME}] system")
                            for k, v in info.items():
                                self.send_message(f"  {k}: {v}")
                        continue

                    if msg.startswith("[FETCH_COOLDOWN]|"):
                        remaining = msg.split("|", 1)[1]
                        notice = f"[system] fetch cooldown ({remaining}s remaining)"
                        if self.state.current_view == "dm" and self.state.dm_target:
                            self.state.append_dm(self.state.dm_target, notice, True)
                        else:
                            self.state.messages.append((notice, True))
                        continue

                    if msg.startswith("[DM]|"):
                        parts = msg.split("|", 3)
                        if len(parts) >= 4:
                            _, from_user, _ts, text = (
                                parts[0],
                                parts[1],
                                parts[2],
                                parts[3],
                            )
                            is_self = from_user == self.config.USERNAME
                            if is_self:
                                continue
                            self.state.append_dm(
                                from_user, f"[{from_user}]: {text}", False
                            )
                            '''
                            if not self.state.dnd:
                                try:
                                    if platform.system() == "Darwin":
                                        subprocess.run(
                                            [
                                                "osascript",
                                                "-e",
                                                f'display notification "DM from {from_user}" with title "Lantern"',
                                            ]
                                        )
                                    elif platform.system() == "Linux":
                                        subprocess.run(
                                            [
                                                "notify-send",
                                                "Lantern",
                                                f"DM from {from_user}",
                                            ]
                                        )
                                except Exception:
                                    pass
                            '''
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
                                    self.state.dm_conversations[other].append(
                                        (f"[{sender}]: {text}", is_self)
                                    )
                                self.state.dm_conversations[other][:] = (
                                    self.state.dm_conversations[other][
                                        -self.config.MAX_MESSAGES :
                                    ]
                                )
                                self.state.pending_dm_history = None
                            except Exception:
                                self.state.pending_dm_history = None
                        continue
                    # TODO - ban reasons, implemented server side and here but need to allow for it in the client.
                    # client could technically delete this code but they would still be banned server side 
                    if msg.startswith("[BANNED]|"):
                        reason = msg.split("|", 1)[1] if "|" in msg else "You have been banned from this server"

                        with self.state.lock:
                                # always send ban messages to main chat, even if in dm, since user is banned from server not just dm 

                                self.state.banned = True 
                                self.state.ban_reason = reason

                        self.state.running = False
                        # TODO - before qutting, show a message with ban reason for 10s and like ascii art just for the fun of it
                        try:
                            self.close()
                        except Exception:
                            pass
                        continue

                    # admin command feedback from the server 
                    if msg.startswith("[ADMIN_ERROR]|"):
                        reason = msg.split("|", 1)[1] if "|" in msg else "Admin error"
                        # route system message
                        if self.state.current_view == "dm" and self.state.dm_target:
                            self.state.append_dm(
                                self.state.dm_target,
                                f"[system] {reason}",
                                True,
                            )
                        else:
                            self.state.messages.append((f"[system] {reason}", True))
                            self.state.messages[:] = self.state.messages[
                                -self.config.MAX_MESSAGES :
                            ]
                        continue

                    if msg.startswith("[ADMIN_OK]|"):
                        detail = msg.split("|", 1)[1] if "|" in msg else "Admin command applied"
                        if self.state.current_view == "dm" and self.state.dm_target:
                            self.state.append_dm(
                                self.state.dm_target,
                                f"[system] {detail}",
                                True,
                            )
                        else:
                            self.state.messages.append((f"[system] {detail}", True))
                            self.state.messages[:] = self.state.messages[
                                -self.config.MAX_MESSAGES :
                            ]
                        continue

                    is_self = msg.startswith(
                        f"[{self.config.USERNAME}]:"
                    ) or msg.startswith(f"[{self.config.USERNAME}] system")
                    self.state.messages.append(
                        (msg[: self.config.MAX_MESSAGE_LEN], is_self)
                    )
                    self.state.messages[:] = self.state.messages[
                        -self.config.MAX_MESSAGES :
                    ]
                    # TODO - ANSII detection for focus - only show noti if window not focused, this is fine for now, if u hate notis run /dnd or ctrl+d
                   '''
                   if not is_self and not self.state.dnd:
                        try:
                            if platform.system() == "Darwin":
                                subprocess.run(
                                    [
                                        "osascript",
                                        "-e",
                                        f'display notification "{msg[:50]}" with title "New Message"',
                                    ]
                                )
                            elif platform.system() == "Linux":
                                subprocess.run(["notify-send", "New Message", msg[:50]])
                        except Exception:
                            pass
                    '''

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
