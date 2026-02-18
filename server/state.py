import hashlib
import json
import os
import secrets
import time

HISTORY_FILE = "server/messages.json"
USERS_FILE = "server/users.json"
CONFIG_FILE = "server/config.json"
MAX_CHANNEL_MESSAGES = 2000
MAX_DM_MESSAGES_PER_CONV = 5000


def _hash_password(password: str, salt: str) -> str:
    # super duper hashing that only leet haxxors could break .....
    return hashlib.sha256((salt + password).encode()).hexdigest()


class ServerState:
    def __init__(self):
        self.clients = {}  # addr -> {"username": str, "last_seen": float}
        self.pending_auth = {}  # addr -> username (after LOGIN/REGISTER success, until JOIN)
        self.sessions = {}  # username -> current session token

        self.users = self._load_users()  # username -> dict/legacy password
        self.channel_messages = self._load_channel_messages()
        self.dm_conversations = self._load_dm_conversations()  # (u1,u2) normalized -> [{"sender", "text", "timestamp"}]
        self._dm_key = lambda a, b: tuple(sorted([a, b]))

        self.admins = self._load_admins()  # set of usernames

        # DEFAULT CONFIG
        self.MAX_MSG_LEN = 400 # shared with client during runtime, TODO - put in config file 

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

    def _load_admins(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                admins = data.get("admins", [])
                if isinstance(admins, list):
                    return set(str(a) for a in admins if a)
            except Exception:
                pass
        return set()

    def save_admins(self):
        data = {"admins": sorted(self.admins)}
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)

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

        if isinstance(entry, dict):
            if entry.get("banned"):
                return False
            salt = entry.get("salt") or ""
            stored_hash = entry.get("hash") or ""
            legacy_pw = entry.get("legacy_password")

            if salt and stored_hash:
                return stored_hash == _hash_password(password, salt)
            if legacy_pw is not None:
                return legacy_pw == password
            return False

        # legacy plain-text storage
        return entry == password

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
        self.users[username] = {
            "salt": salt,
            "hash": h,
            "banned": False,
            "muted": False,
        }
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

    def create_session(self, username: str) -> str:
        token = secrets.token_hex(32)
        self.sessions[username] = token
        return token

    def get_session_token(self, username: str) -> str | None:
        return self.sessions.get(username)

    def clear_session(self, username: str):
        self.sessions.pop(username, None)

    def is_admin(self, username: str) -> bool:
        return username in self.admins

    def is_banned(self, username: str) -> bool:
        entry = self.users.get(username)
        if isinstance(entry, dict):
            return bool(entry.get("banned"))
        return False

    def is_muted(self, username: str) -> bool:
        entry = self.users.get(username)
        if isinstance(entry, dict):
            return bool(entry.get("muted"))
        return False

    def _ensure_user_dict(self, username: str):
        entry = self.users.get(username)
        if entry is None:
            return
        if isinstance(entry, dict):
            return
        # upgrade legacy plain-text entry to a structured dict, preserving password
        self.users[username] = {"legacy_password": entry, "banned": False, "muted": False}

    def set_banned(self, username: str, banned: bool):
        if username not in self.users:
            return
        self._ensure_user_dict(username)
        entry = self.users[username]
        if isinstance(entry, dict):
            entry["banned"] = banned
        self.save_all()

    def set_muted(self, username: str, muted: bool):
        if username not in self.users:
            return
        self._ensure_user_dict(username)
        entry = self.users[username]
        if isinstance(entry, dict):
            entry["muted"] = muted
        self.save_all()

    def rename_user(self, old_username: str, new_username: str) -> bool:
        # if a user is renamed in dms then you must reopen dms for msgs to send 
        old_username = (old_username or "").strip()
        new_username = (new_username or "").strip()
        if not old_username or not new_username:
            return False
        if old_username not in self.users or new_username in self.users:
            return False

        # move user entry
        self.users[new_username] = self.users.pop(old_username)

        # move session token if present
        if old_username in self.sessions:
            self.sessions[new_username] = self.sessions.pop(old_username)

        new_dm_conversations = {}
        for key, msgs in self.dm_conversations.items():
            u1, u2 = key.split(",", 1)
            if u1 == old_username:
                u1 = new_username
            if u2 == old_username:
                u2 = new_username
            new_key = self._dm_key_str(u1, u2)
            new_dm_conversations[new_key] = msgs
        self.dm_conversations = new_dm_conversations

        # update admin set if needed
        if old_username in self.admins:
            self.admins.discard(old_username)
            self.admins.add(new_username)
            self.save_admins()

        self.save_all()
        return True
