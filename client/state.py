import threading
import time


class ClientState:
    def __init__(self, username, max_messages=500):
        self.messages = []
        self.username = username
        self.users = set()
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
        self.dnd = False

    def ensure_dm_conversation(self, other_user: str):
        with self.lock:
            if other_user not in self.dm_conversations:
                self.dm_conversations[other_user] = []
            return self.dm_conversations[other_user]

    def append_dm(self, other_user: str, text: str, is_self: bool):
        with self.lock:
            self.ensure_dm_conversation(other_user)
            self.dm_conversations[other_user].append((text, is_self))
            self.dm_conversations[other_user][:] = self.dm_conversations[other_user][-self.max_messages:]
