import threading
import time
from dataclasses import dataclass, field


@dataclass
class Message:
    text: str
    is_self: bool
    ts: float = 0.0
    msg_id: str = None
    img_rows: list = None


class ClientState:
    def __init__(self, username, max_messages=500):
        self.messages = []
        self.username = username
        self.users = set()
        self.session_token = None 
        self.admins = set()
        self.lock = threading.RLock()
        self.running = True
        self.start_time = time.time()
        self.max_messages = max_messages

        self.authenticated = False
        self.auth_failed = False

        self.channel_history_buffer = []
        self.channel_history_ready = False

        self.users_detailed = []
        self.dm_conversations = {}
        self.current_view = "channel"
        self.dm_target = None
        self.pending_dm_history = None
        self.notifications = False
        self.last_notification_time = 0
        self.send_failed = False
        self.last_received_from_server = 0.0
        self.dnd = True
        self.last_ui_activity = time.time()
        self.typing_users = {}  # {username: expiry_time} - who's typing and when indicator expires

        self.banned = False 
        self.ban_reason = ""

        # unread DM counts per user (cleared when that DM convo is opened)
        self.unread_dms = {}

        # user stats cache from /stats command
        self.user_stats = None

        # msg_id -> index in self.messages or (conv_key, index) for DMs
        self.disp_index = {}
        
        # typing state
        self.last_typing_sent = 0  # track when we last sent typing notification
        self.is_typing = False  # whether we've notified server we're typing

    def ensure_dm_conversation(self, other_user):
        with self.lock:
            if other_user not in self.dm_conversations:
                self.dm_conversations[other_user] = []
            return self.dm_conversations[other_user]

    def append_dm(self, other_user, text, is_self, ts=0, msg_id=None, img_data=None):
        with self.lock:
            self.ensure_dm_conversation(other_user)
            self.dm_conversations[other_user].append(Message(text=text, is_self=is_self, ts=ts, msg_id=msg_id, img_rows=img_data))
            self.dm_conversations[other_user][:] = self.dm_conversations[other_user][-self.max_messages:]
            if msg_id:
                self.disp_index[msg_id] = ("dm", other_user)

    def _redact_text(self, existing, redacted):
        # preserve "[sender]: " prefix so the author is still visible after hiding
        if "]: " in existing:
            prefix = existing[: existing.index("]: ") + 3]
            return prefix + redacted
        return redacted

    def expire_disp(self, msg_id, redacted):
        with self.lock:
            loc = self.disp_index.pop(msg_id, None)
            if loc is None:
                return
            if loc[0] == "channel":
                for i, msg in enumerate(self.messages):
                    if msg.msg_id == msg_id:
                        self.messages[i] = Message(text=self._redact_text(msg.text, redacted), is_self=msg.is_self, ts=msg.ts)
                        break
            elif loc[0] == "dm":
                conv_key = loc[1]
                conv = self.dm_conversations.get(conv_key, [])
                for i, msg in enumerate(conv):
                    if msg.msg_id == msg_id:
                        conv[i] = Message(text=self._redact_text(msg.text, redacted), is_self=msg.is_self, ts=msg.ts)
                        break

    def clear_unread(self, other_user):
        with self.lock:
            self.unread_dms.pop(other_user, None)

    def update_ui_activity(self):
        with self.lock:
            self.last_ui_activity = time.time()

    def is_window_focused(self, idle_threshold_seconds=5):
        with self.lock:
            idle_time = time.time() - self.last_ui_activity
        return idle_time < idle_threshold_seconds

    def mark_user_typing(self, username, duration_seconds=5):
        with self.lock:
            self.typing_users[username] = time.time() + duration_seconds

    def clear_user_typing(self, username):
        with self.lock:
            self.typing_users.pop(username, None)

    def get_typing_users(self):
        with self.lock:
            now = time.time()
            expired = [u for u, exp in self.typing_users.items() if exp < now]
            for u in expired:
                self.typing_users.pop(u, None)
            return list(self.typing_users.keys())
