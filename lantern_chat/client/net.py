import socket
import threading
import time
import platform
import subprocess
import json
import base64
import io
import os

from lantern_chat.frame import send_msg, recv_msg

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

IMG_MAX_WIDTH = 80
IMG_MAX_HEIGHT = 40


def _img_to_rows(data: bytes):
    # converts each img row into bytes :)
    # also works for gifs but will only take the first frame, which is probably fine for now lol
    if not _PIL_AVAILABLE:
        return None
    img = Image.open(io.BytesIO(data)).convert("RGB")
    # terminal chars are ~2x taller than wide so halve the height
    w = min(img.width, IMG_MAX_WIDTH)
    h = max(1, min(int(img.height * (w / img.width) * 0.45), IMG_MAX_HEIGHT))
    img = img.resize((w, h), Image.LANCZOS)
    rows = []
    for y in range(h):
        row = []
        for x in range(w):
            r, g, b = img.getpixel((x, y))
            row.append(("█", r, g, b))
        rows.append(row)
    return rows


class NetworkManager:
    def __init__(self, config, state):
        self.config = config
        self.state = state
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._send_lock = threading.Lock()  # guards all writes to self.sock
        self.last_ping_sent = 0.0
        self.last_ping_recv = 0.0
        self.ping_ms = None

    def _send(self, msg: str):
        # all sends go through here to avoid concurrent write races between threads
        # peak niche chat lol
        with self._send_lock:
            send_msg(self.sock, msg)

    def connect(self):
        try:
            self.sock.connect((self.config.SERVER_HOST, self.config.SERVER_PORT))
            self._send(f"[LOGIN]|{self.config.USERNAME}|{self.config.PASSWORD}")
        except OSError:
            with self.state.lock:
                self.state.auth_failed = True

    def send_join(self):
        self._send(f"[JOIN]|{self.config.USERNAME}")

    def send_message(self, msg):
        try:
            self._send(msg)
        except OSError:
            with self.state.lock:
                self.state.send_failed = True

    def send_leave(self):
        try:
            self._send(f"[LEAVE]|{self.config.USERNAME}")
        except Exception:
            pass

    def request_user_list(self):
        self._send(f"[REQ_USERS]|{self.config.USERNAME}")

    def request_users_detailed(self):
        self._send(f"[REQ_USERS_DETAILED]|{self.config.USERNAME}")

    def request_user_stats(self, username: str):
        self._send(f"[REQ_USER_STATS]|{username}")

    def send_dm(self, recipient: str, text: str):
        try:
            self._send(f"[DM]|{recipient}|{text}")
        except OSError:
            with self.state.lock:
                self.state.send_failed = True

    def send_disp(self, seconds: int, text: str):
        try:
            self._send(f"[DISP]|{seconds}|{text}")
        except OSError:
            with self.state.lock:
                self.state.send_failed = True

    def send_img(self, path: str, dm_recipient: str = None):
        if not _PIL_AVAILABLE:
            with self.state.lock:
                self.state.messages.append(("[system] Pillow not installed — cannot send images", True, 0))
            return
        try:
            filename = os.path.basename(path)
            with Image.open(path) as img:
                img.load()  # force first frame for GIFs
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode()
            if dm_recipient:
                self._send(f"[DM_IMG]|{dm_recipient}|{filename}|{b64}")
            else:
                self._send(f"[IMG]|{filename}|{b64}")
        except Exception as e:
            with self.state.lock:
                self.state.messages.append((f"[system] Failed to send image: {e}", True, 0))

    def request_dm_history(self, other_user: str):
        self._send(f"[REQ_DM_HISTORY]|{other_user}")

    def request_fetch(self):
        self._send(f"[REQ_FETCH]|{json.dumps(self.system_fetch())}")

    def request_max_msg_len(self):
        self._send(f"[REQ_MAX_MSG_LEN]|{self.config.USERNAME}")

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
                    ("[system] Cannot run admin command: no session token from server", True, 0)
                )
            return
        self._send(f"[ADMIN_CMD]|{command}|{self.config.USERNAME}|{self.state.session_token}|{payload}")

    def keepalive(self):
        while self.state.running:
            try:
                self.last_ping_sent = time.time()
                self._send("[ping]")
                time.sleep(5)
            except Exception:
                pass

    def receive(self):
        while self.state.running:
            try:
                msg = recv_msg(self.sock)
                if msg is None:
                    # server closed the connection
                    with self.state.lock:
                        self.state.running = False
                    break

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
                                    ts = m.get("timestamp", 0)
                                    self.state.messages.append((text, is_self, ts))
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
                                self.state.messages.append((line, True, 0))
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
                        # server broadcasts the fetch data; nothing more to send
                        continue

                    if msg.startswith("[FETCH_COOLDOWN]|"):
                        remaining = msg.split("|", 1)[1]
                        notice = f"[system] fetch cooldown ({remaining}s remaining)"
                        if self.state.current_view == "dm" and self.state.dm_target:
                            self.state.append_dm(self.state.dm_target, notice, True)
                        else:
                            self.state.messages.append((notice, True, 0))
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
                                from_user, f"[{from_user}]: {text}", False,
                                float(_ts) if _ts else time.time()
                            )
                            
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
                            
                        continue

                    if msg.startswith("[DM_FAIL]|"):
                        reason = msg.split("|", 1)[1] if "|" in msg else "DM failed"
                        notice = f"[system] {reason}"
                        self.state.pending_dm_history = None
                        if self.state.current_view == "dm" and self.state.dm_target:
                            self.state.append_dm(self.state.dm_target, notice, True)
                        else:
                            self.state.messages.append((notice, True, 0))
                            self.state.messages[:] = self.state.messages[-self.config.MAX_MESSAGES:]
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
                                    ts = m.get("timestamp", 0)
                                    self.state.dm_conversations[other].append(
                                        (f"[{sender}]: {text}", is_self, ts)
                                    )
                                self.state.dm_conversations[other][:] = (
                                    self.state.dm_conversations[other][
                                        -self.config.MAX_MESSAGES :
                                    ]
                                )
                                # only open the DM view now that we know the user exists
                                if self.state.pending_dm_history == other:
                                    self.state.dm_target = other
                                    self.state.current_view = "dm"
                                self.state.pending_dm_history = None
                            except Exception:
                                self.state.pending_dm_history = None
                        continue

                   
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
                    if msg.startswith("[RATE_LIMITED]|"):
                        wait = msg.split("|", 1)[1] if "|" in msg else "?"
                        notice = f"[system] slow down! try again in {wait}s"
                        if self.state.current_view == "dm" and self.state.dm_target:
                            self.state.append_dm(self.state.dm_target, notice, True)
                        else:
                            self.state.messages.append((notice, True, 0))
                            self.state.messages[:] = self.state.messages[-self.config.MAX_MESSAGES:]
                        continue

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
                            self.state.messages.append((f"[system] {reason}", True, 0))
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
                            self.state.messages.append((f"[system] {detail}", True, 0))
                            self.state.messages[:] = self.state.messages[
                                -self.config.MAX_MESSAGES :
                            ]
                        continue

                    if msg.startswith("[DM_IMG]|"):
                        # [DM_IMG]|<sender>|<other_user>|<filename>|<base64_data>
                        parts = msg.split("|", 4)
                        if len(parts) == 5:
                            sender, other_user, filename, b64 = parts[1], parts[2], parts[3], parts[4]
                            is_self = sender == self.config.USERNAME
                            conv_key = other_user if is_self else sender
                            label = f"[{sender}]: [image: {filename}]"
                            try:
                                img_rows = _img_to_rows(base64.b64decode(b64))
                            except Exception:
                                img_rows = None
                            self.state.append_dm(conv_key, label, is_self, time.time(), img_data=img_rows)
                        continue

                    if msg.startswith("[IMG]|"):
                        # [IMG]|<sender>|<filename>|<base64_data>
                        parts = msg.split("|", 3)
                        if len(parts) == 4:
                            sender, filename, b64 = parts[1], parts[2], parts[3]
                            is_self = sender == self.config.USERNAME
                            label = f"[{sender}]: [image: {filename}]"
                            try:
                                raw = base64.b64decode(b64)
                                img_rows = _img_to_rows(raw)
                            except Exception:
                                img_rows = None
                            with self.state.lock:
                                entry = (label, is_self, time.time(), None, img_rows)
                                if self.state.current_view == "dm" and self.state.dm_target:
                                    self.state.append_dm(self.state.dm_target, label, is_self, time.time(), img_data=img_rows)
                                else:
                                    self.state.messages.append(entry)
                                    self.state.messages[:] = self.state.messages[-self.config.MAX_MESSAGES:]
                        continue

                    if msg.startswith("[DISP]|"):
                        # [DISP]|<msg_id>|<sender>|<expires_at>|<text>
                        parts = msg.split("|", 4)
                        if len(parts) == 5:
                            msg_id, sender, expires_at, text = parts[1], parts[2], float(parts[3]), parts[4]
                            is_self = sender == self.config.USERNAME
                            display = f"[{sender}]: {text}"
                            with self.state.lock:
                                if self.state.current_view == "dm" and self.state.dm_target:
                                    self.state.append_dm(self.state.dm_target, display, is_self, time.time(), msg_id)
                                else:
                                    idx = len(self.state.messages)
                                    self.state.messages.append((display, is_self, time.time(), msg_id))
                                    self.state.messages[:] = self.state.messages[-self.config.MAX_MESSAGES:]
                                    self.state.disp_index[msg_id] = ("channel", idx)
                        continue

                    if msg.startswith("[DISP_EXPIRE]|"):
                        # [DISP_EXPIRE]|<msg_id>|<redacted>
                        parts = msg.split("|", 2)
                        if len(parts) == 3:
                            msg_id, redacted = parts[1], parts[2]
                            self.state.expire_disp(msg_id, redacted)
                        continue

                    is_self = msg.startswith(
                        f"[{self.config.USERNAME}]:"
                    ) or msg.startswith(f"[{self.config.USERNAME}] system")
                    self.state.messages.append(
                        (msg[: self.config.MAX_MESSAGE_LEN], is_self, time.time())
                    )
                    self.state.messages[:] = self.state.messages[
                        -self.config.MAX_MESSAGES :
                    ]
                    # notify on new messages unless dnd is on
                    if not is_self and not self.state.dnd:
                        try:
                            if platform.system() == "Darwin":
                                subprocess.Popen(
                                    ["osascript", "-e", f'display notification "{msg[:80]}" with title "Lantern"'],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                )
                            elif platform.system() == "Linux":
                                safe_msg = msg[:80].replace("\\", "")
                                subprocess.Popen(
                                    ["notify-send", "Lantern", safe_msg, "-t", "4000"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                )
                        except Exception:
                            pass

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

