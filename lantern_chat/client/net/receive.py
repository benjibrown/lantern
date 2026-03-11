import json
import base64
import time
import platform
import subprocess

from lantern_chat.frame import recv_msg
from lantern_chat.client.state import Message
from lantern_chat.client.net.image import _img_to_rows


class ReceiveMixin:
    def receive(self):
        while self.state.running:
            try:
                msg = recv_msg(self.sock)
                if msg is None:
                    if self.state.banned:
                        break
                    # attempt reconnect
                    for attempt in range(1, 6):
                        wait = 2 ** (attempt - 1)  # 1, 2, 4, 8, 16
                        notice = Message(text=f"[system] disconnected — reconnecting in {wait}s (attempt {attempt}/5)...", is_self=True, ts=time.time())
                        with self.state.lock:
                            self.state.messages.append(notice)
                        time.sleep(wait)
                        try:
                            # create a fresh socket
                            import socket as _socket
                            self.sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
                            self.sock.connect((self.config.SERVER_HOST, self.config.SERVER_PORT))
                            # re-authenticate
                            self._send(f"[LOGIN]|{self.config.USERNAME}|{self.config.PASSWORD}")
                            with self.state.lock:
                                self.state.authenticated = False
                                self.state.channel_history_ready = False
                                self.state.channel_history_buffer = []
                            # wait for auth
                            deadline = time.time() + 10
                            while time.time() < deadline:
                                m = recv_msg(self.sock)
                                if m is None:
                                    break
                                with self.state.lock:
                                    self.state.last_received_from_server = time.time()
                                if m.startswith("[AUTH_OK]"):
                                    parts = m.split("|", 1)
                                    if len(parts) > 1:
                                        with self.state.lock:
                                            self.state.session_token = parts[1]
                                    self.send_join()
                                    break
                                elif m.startswith("[AUTH_FAIL]"):
                                    break
                            with self.state.lock:
                                reconnected = self.state.authenticated or self.state.channel_history_ready
                            if not reconnected:
                                # wait for history
                                deadline2 = time.time() + 10
                                while time.time() < deadline2:
                                    m = recv_msg(self.sock)
                                    if m is None:
                                        break
                                    with self.state.lock:
                                        self.state.last_received_from_server = time.time()
                                    # handle CHANNEL_HISTORY and CHANNEL_HISTORY_END inline
                                    if m.startswith("[CHANNEL_HISTORY]|"):
                                        parts = m.split("|", 2)
                                        if len(parts) == 3:
                                            try:
                                                idx = int(parts[1])
                                                chunk = parts[2]
                                                with self.state.lock:
                                                    while len(self.state.channel_history_buffer) <= idx:
                                                        self.state.channel_history_buffer.append("")
                                                    self.state.channel_history_buffer[idx] = chunk
                                            except Exception:
                                                pass
                                    elif m == "[CHANNEL_HISTORY_END]":
                                        with self.state.lock:
                                            self.state.channel_history_ready = True
                                            self.state.authenticated = True
                                        break
                                    elif m.startswith("[USERS]|"):
                                        with self.state.lock:
                                            self.state.authenticated = True
                                        break
                            with self.state.lock:
                                ok = self.state.authenticated
                            if ok:
                                notice2 = Message(text="[system] reconnected!", is_self=True, ts=time.time())
                                with self.state.lock:
                                    self.state.messages.append(notice2)
                                break  # break out of retry loop, back to main receive loop
                        except Exception:
                            pass
                    else:
                        # all retries failed
                        notice = Message(text="[system] could not reconnect to server. closing.", is_self=True, ts=time.time())
                        with self.state.lock:
                            self.state.messages.append(notice)
                            self.state.running = False
                    if not self.state.running:
                        break
                    continue  # continue the outer while loop with the new socket

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
                                    self.state.messages.append(Message(text=text, is_self=is_self, ts=ts))
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
                                self.state.messages.append(Message(text=line, is_self=True, ts=0))
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
                            self.state.messages.append(Message(text=notice, is_self=True, ts=0))
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
                            with self.state.lock:
                                if not (self.state.current_view == "dm" and self.state.dm_target == from_user):
                                    self.state.unread_dms[from_user] = self.state.unread_dms.get(from_user, 0) + 1

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
                            self.state.messages.append(Message(text=notice, is_self=True, ts=0))
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
                                        Message(text=f"[{sender}]: {text}", is_self=is_self, ts=ts)
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
                            self.state.messages.append(Message(text=notice, is_self=True, ts=0))
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
                            self.state.messages.append(Message(text=f"[system] {reason}", is_self=True, ts=0))
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
                            self.state.messages.append(Message(text=f"[system] {detail}", is_self=True, ts=0))
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
                            if not is_self:
                                with self.state.lock:
                                    if not (self.state.current_view == "dm" and self.state.dm_target == conv_key):
                                        self.state.unread_dms[conv_key] = self.state.unread_dms.get(conv_key, 0) + 1
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
                                entry = Message(text=label, is_self=is_self, ts=time.time(), img_rows=img_rows)
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
                                    self.state.messages.append(Message(text=display, is_self=is_self, ts=time.time(), msg_id=msg_id))
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
                        Message(text=msg[: self.config.MAX_MESSAGE_LEN], is_self=is_self, ts=time.time())
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
