import json
import base64
import io
import os
import platform
import subprocess
import time

from lantern_chat.frame import send_msg
from lantern_chat.client.state import Message
from lantern_chat.client.net.image import _PIL_AVAILABLE, Image, _img_to_rows


class SendMixin:
    def _send(self, msg: str):
        # all sends go through here to avoid concurrent write races between threads
        # peak niche chat lol
        with self._send_lock:
            send_msg(self.sock, msg)

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
                self.state.messages.append(Message(text="[system] Pillow not installed — cannot send images", is_self=True, ts=0))
            return
        try:
            filename = os.path.basename(path)
            with Image.open(path) as img:
                img.load()  # force first frame for GIFs
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode()

            # large image fix - shouldnt kill client now
            if len(b64) > 8 * 1024 * 1024:
                with self.state.lock:
                    self.state.messages.append(Message(text="[system] Image too large to send (max ~8MB)", is_self=True, ts=0))
                return
            if dm_recipient:
                self._send(f"[DM_IMG]|{dm_recipient}|{filename}|{b64}")
            else:
                self._send(f"[IMG]|{filename}|{b64}")
        except Exception as e:
            with self.state.lock:
                self.state.messages.append(Message(text=f"[system] Failed to send image: {e}", is_self=True, ts=0))

    # this code is getting very long icl
    def send_img_bytes(self, data: bytes, filename: str, dm_recipient: str = None):
        if not _PIL_AVAILABLE:
            with self.state.lock:
                self.state.messages.append(Message(text="[system] Pillow not installed — cannot send images", is_self=True, ts=0))
            return
        try:
            with Image.open(io.BytesIO(data)) as img:
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode()
            if len(b64) > 8 * 1024 * 1024:
                with self.state.lock:
                    self.state.messages.append(Message(text="[system] Image too large to send (max ~8MB)", is_self=True, ts=0))
                return
            if dm_recipient:
                self._send(f"[DM_IMG]|{dm_recipient}|{filename}|{b64}")
            else:
                self._send(f"[IMG]|{filename}|{b64}")
        except Exception as e:
            with self.state.lock:
                self.state.messages.append(Message(text=f"[system] Failed to send image: {e}", is_self=True, ts=0))

    def request_dm_history(self, other_user: str):
        self._send(f"[REQ_DM_HISTORY]|{other_user}")
        self._send(f"[CLEAR_UNREAD]|{other_user}")

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
                    Message(text="[system] Cannot run admin command: no session token from server", is_self=True, ts=0)
                )
            return
        self._send(f"[ADMIN_CMD]|{command}|{self.config.USERNAME}|{self.state.session_token}|{payload}")

    def send_typing(self):
        now = time.time()
        if now - self.state.last_typing_sent < 2:  # debounce: only send every 2 seconds
            return
        self.state.last_typing_sent = now
        self._send(f"[TYPING]|{self.config.USERNAME}")

    def send_typing_stop(self):
        self._send(f"[TYPING_STOP]|{self.config.USERNAME}")

    def keepalive(self):
        while self.state.running:
            try:
                self.last_ping_sent = time.time()
                self._send("[ping]")
                time.sleep(5)
            except Exception:
                pass

    def system_fetch(self):
        return {
            "OS": f"{platform.system()} {platform.release()}",
            "Kernel": platform.version().split()[0],
            "Host": platform.node(),
            "Arch": platform.machine(),
        }
