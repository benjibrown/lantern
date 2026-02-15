import hashlib
import json
import os
import secrets
import time

HISTORY_FILE = "server/messages.json"
USERS_FILE = "server/users.json"
MAX_CHANNEL_MESSAGES = 2000
MAX_DM_MESSAGES_PER_CONV = 5000


def _hash_password(password: str, salt: str) -> str:
    # super duper hashing that only leet haxxors could break .....
    return hashlib.sha256((salt + password).encode()).hexdigest()


class ServerState:
    def __init__(self):
        self.clients = {}  # addr -> {"username": str, "last_seen": float}
        self.pending_auth = {}  # addr -> username (after LOGIN/REGISTER success, until JOIN)
        self.users = self._load_users()  # username -> {"hash": str, "salt": str}
        self.channel_messages = self._load_channel_messages()
        self.dm_conversations = self._load_dm_conversations()  # (u1,u2) normalized -> [{"sender", "text", "timestamp"}]
        self._dm_key = lambda a, b: tuple(sorted([a, b]))

    def _load_users(self):
        if os.path.exists(USERS_FILE):
            try:
                with open(USERS_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _load_channel_messages(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f:
                    data = json.load(f)
                    return data.get("channel", [])[-MAX_CHANNEL_MESSAGES:]
            except Exception:
                pass
        return []

    def _load_dm_conversations(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f:
                    data = json.load(f)
                    return data.get("dm", {})
            except Exception:
                pass
        return {}

    def save_all(self):
        data = {
            "channel": self.channel_messages[-MAX_CHANNEL_MESSAGES:],
            "dm": self.dm_conversations,
        }
        with open(HISTORY_FILE, "w") as f:
            json.dump(data, f)
        with open(USERS_FILE, "w") as f:
            json.dump(self.users, f)

    def validate_user(self, username: str, password: str) -> bool:
        if username not in self.users:
            return False
        entry = self.users[username]
        if isinstance(entry, str):
            return entry == password  # legacy plain storage
        salt = entry.get("salt", "")
        h = entry.get("hash", "")
        return h == _hash_password(password, salt)

    def user_exists(self, username: str) -> bool:
        return username in self.users

    def register_user(self, username: str, password: str) -> bool:
        if not username or not username.strip():
            return False
        username = username.strip()
        if username in self.users:
            return False
        salt = secrets.token_hex(16)
        h = _hash_password(password, salt)
        self.users[username] = {"salt": salt, "hash": h}
        self.save_all()
        return True

    def add_channel_message(self, sender: str, text: str):
        msg = {"sender": sender, "text": text, "timestamp": time.time()}
        self.channel_messages.append(msg)
        self.channel_messages[:] = self.channel_messages[-MAX_CHANNEL_MESSAGES:]
        self.save_all()
        return msg

    def get_channel_history(self, limit=500):
        return self.channel_messages[-limit:]

    def _dm_key_str(self, u1: str, u2: str) -> str:
        return ",".join(sorted([u1, u2]))

    def add_dm(self, sender: str, recipient: str, text: str):
        key = self._dm_key_str(sender, recipient)
        if key not in self.dm_conversations:
            self.dm_conversations[key] = []
        msg = {"sender": sender, "text": text, "timestamp": time.time()}
        self.dm_conversations[key].append(msg)
        self.dm_conversations[key] = self.dm_conversations[key][-MAX_DM_MESSAGES_PER_CONV:]
        self.save_all()
        return msg

    def get_dm_history(self, user1: str, user2: str, limit=500):
        key = self._dm_key_str(user1, user2)
        msgs = self.dm_conversations.get(key, [])
        return msgs[-limit:]

    def get_last_dm_time_for_user(self, username: str) -> dict:

        out = {}
        for key, msgs in self.dm_conversations.items():
            u1, u2 = key.split(",", 1)
            if not msgs:
                continue
            ts = msgs[-1]["timestamp"]
            other = u2 if u1 == username else u1
            out[other] = max(out.get(other, 0), ts)
        return out

    def set_pending_auth(self, addr, username: str):
        self.pending_auth[addr] = username

    def pop_pending_auth(self, addr):
        return self.pending_auth.pop(addr, None)
