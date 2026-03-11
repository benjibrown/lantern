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

        self.banned = False 
        self.ban_reason = ""

        # unread DM counts per user (cleared when that DM convo is opened)
        self.unread_dms = {}

        # user stats cache from /stats command
        self.user_stats = None

        # msg_id -> index in self.messages or (conv_key, index) for DMs
        self.disp_index = {}

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
                idx = len(self.dm_conversations[other_user]) - 1
                self.disp_index[msg_id] = ("dm", other_user, idx)

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
                idx = loc[1]
                if idx < len(self.messages):
                    msg = self.messages[idx]
                    self.messages[idx] = Message(text=self._redact_text(msg.text, redacted), is_self=msg.is_self, ts=msg.ts)
            elif loc[0] == "dm":
                conv_key, idx = loc[1], loc[2]
                conv = self.dm_conversations.get(conv_key, [])
                if idx < len(conv):
                    msg = conv[idx]
                    conv[idx] = Message(text=self._redact_text(msg.text, redacted), is_self=msg.is_self, ts=msg.ts)
