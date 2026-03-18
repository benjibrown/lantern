import hashlib
import json
import os
import secrets
import threading
import time

_DATA_DIR = os.path.join(os.path.expanduser("~"), ".local", "share", "lantern")
_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "lantern")
os.makedirs(_DATA_DIR, exist_ok=True)
os.makedirs(_CONFIG_DIR, exist_ok=True)
HISTORY_FILE = os.path.join(_DATA_DIR, "messages.json")
USERS_FILE = os.path.join(_DATA_DIR, "users.json")
CONFIG_FILE = os.path.join(_CONFIG_DIR, "server.json")


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
        
        # load config values
        self.fetch_cooldown = self._load_config_int("fetch_cooldown", 30)
        self.msg_rate_limit = self._load_config_float("msg_rate_limit", 1.0)
        self.max_msg_len = self._load_config_int("max_msg_len", 400)
        self.max_channel_messages = self._load_config_int("max_channel_messages", 2000)
        self.max_dm_messages = self._load_config_int("max_dm_messages", 5000)
        self.login_rate_limit_attempts = self._load_config_int("login_rate_limit_attempts", 5)
        self.login_rate_limit_window = self._load_config_int("login_rate_limit_window", 300)
        self.login_rate_limit_lockout = self._load_config_int("login_rate_limit_lockout", 900)

        self.fetch_last = {}
        self.failed_logins = {}
        self.unreadMessages = self._loadUnreadMessages()  # username -> {sender: count}
        self.usersWithUnread = self._loadUsersWithUnread()  # username -> set(senders)
        self._save_lock = threading.Lock()
        

    def _loadUnreadMessages(self):
        # load unread message counts from history file
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f:
                    data = json.load(f)
                    return data.get("unread", {})
            except Exception:
                pass
        return {}

    def _loadUsersWithUnread(self):
        # build reverse index: username -> {users who sent unread msgs}
        result = {}
        for username, unreadMap in self.unreadMessages.items():
            result[username] = set(k for k, v in unreadMap.items() if v > 0)
        return result

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
                    # use a large sentinel since max_channel_messages isn't loaded yet
                    return data.get("channel", [])[-99999:]
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
       
    def _load_config_int(self, key, default):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    return int(data.get(key, default))
            except Exception:
                pass
        return default

    def _load_config_float(self, key, default):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    return float(data.get(key, default))
            except Exception:
                pass
        return default

    def _load_fetch_cooldown(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    return int(data.get("fetch_cooldown"))
            except Exception:
                pass
        return 30 # default cooldown if fetch_cooldown missing

    def _load_msg_rate_limit(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    return float(data.get("msg_rate_limit", 1.0))
            except Exception:
                pass
        return 1.0  # default: 1 message per second

    def save_admins(self):
        data = {"admins": sorted(self.admins)}
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)

    def save_all(self):
        data = {
            "channel": self.channel_messages[-self.max_channel_messages:],
            "dm": self.dm_conversations,
            "unread": self.unreadMessages,
        }
        with self._save_lock:
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
        self.channel_messages[:] = self.channel_messages[-self.max_channel_messages:]
        self.save_all()
        return msg

    def purge_channel_messages(self, count: int):
        # purge last n messages from chat - only main channel
        removed = min(count, len(self.channel_messages))
        self.channel_messages = self.channel_messages[:-removed] if removed else self.channel_messages
        self.save_all()
        return removed

    def get_channel_history(self, limit=500):
        return self.channel_messages[-limit:]

    def _dm_key_str(self, u1: str, u2: str):
        return ",".join(sorted([u1, u2]))

    def add_dm(self, sender: str, recipient: str, text: str):
        key = self._dm_key_str(sender, recipient)
        if key not in self.dm_conversations:
            self.dm_conversations[key] = []
        msg = {"sender": sender, "text": text, "timestamp": time.time()}
        self.dm_conversations[key].append(msg)
        self.dm_conversations[key] = self.dm_conversations[key][-self.max_dm_messages:]
        self.save_all() 
        return msg

    def get_dm_history(self, user1: str, user2: str, limit=500):
        key = self._dm_key_str(user1, user2)
        msgs = self.dm_conversations.get(key, [])
        return msgs[-limit:]

    def get_last_dm_time_for_user(self, username: str): # chat is this peak

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

    def create_session(self, username: str):
        token = secrets.token_hex(32)
        self.sessions[username] = token
        return token

    def get_session_token(self, username: str):
        return self.sessions.get(username)

    def clear_session(self, username: str):
        self.sessions.pop(username, None)

    def is_admin(self, username: str):
        return username in self.admins

    def is_banned(self, username: str):
        entry = self.users.get(username)
        if isinstance(entry, dict):
            return bool(entry.get("banned"))
        return False
    
    def get_ban_reason(self, username: str):

        entry = self.users.get(username)
        if isinstance(entry, dict):
            reason = entry.get("ban_reason") 

            if isinstance(reason, str) and reason.strip():
                return reason.strip()
        return None


    def is_muted(self, username: str):
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

    def set_banned(self, username: str, banned: bool, reason: str = ""):
        if username not in self.users:
            return
        self._ensure_user_dict(username)
        entry = self.users[username]
        if isinstance(entry, dict):
            entry["banned"] = banned
            if banned:
                if reason is not None:
                    entry["ban_reason"] = reason.strip()[:256]
                else:
                    entry.pop("ban_reason", None)
        self.save_all()

    def set_muted(self, username: str, muted: bool):
        if username not in self.users:
            return
        self._ensure_user_dict(username)
        entry = self.users[username]
        if isinstance(entry, dict):
            entry["muted"] = muted
        self.save_all()

    def rename_user(self, old_username: str, new_username: str):
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
    
    def get_user_stats(self, username: str):
        # return dict with stats for a given user (not necessarily one requesting) - send their username, admin or not, banned?, muted?, total number of channel messages sent 
        entry = self.users.get(username)
        if entry is None:
            return None
        if isinstance(entry, dict):
            return {
                "username": username,
                "is_admin": self.is_admin(username),
                "is_banned": self.is_banned(username),
                "is_muted": self.is_muted(username),
                "total_channel_messages": sum(1 for msg in self.channel_messages if msg["sender"] == username),
            }
        # if hasnt met any of these if statements then return None 
        return None
    # camel case better ??
    def isLoginRateLimited(self, ip):
        # check if ip is ratelimited
        now = time.time()
        if ip not in self.failed_logins:
            return False
        record = self.failed_logins[ip]
        # remove old attempts outside the window
        self.failed_logins[ip] = [
            r for r in record
            if now - r["timestamp"] <= self.login_rate_limit_window
        ]
        # if still have 5+ recent failures, we're locked out for the lockout period
        if len(self.failed_logins[ip]) >= self.login_rate_limit_attempts:
            first_attempt = self.failed_logins[ip][0]["timestamp"]
            if now - first_attempt <= self.login_rate_limit_lockout:
                return True
        # no record or lockout expired
        if not self.failed_logins[ip]:
            del self.failed_logins[ip]
        return False

    def recordFailedLogin(self, ip):
        # record a failed login 
        now = time.time()
        if ip not in self.failed_logins:
            self.failed_logins[ip] = []
        # remove old attempts outside the window
        self.failed_logins[ip] = [
            r for r in self.failed_logins[ip]
            if now - r["timestamp"] <= self.login_rate_limit_window
        ]
        # add this attempt
        self.failed_logins[ip].append({"timestamp": now, "count": len(self.failed_logins[ip]) + 1})
        # if we've hit the limit, return seconds until unlock
        if len(self.failed_logins[ip]) >= self.login_rate_limit_attempts:
            first_attempt = self.failed_logins[ip][0]["timestamp"]
            unlock_time = first_attempt + self.login_rate_limit_lockout
            return max(1, int(unlock_time - now))
        return 0

    def clearLoginAttempts(self, ip):
        # clear attempts for an ip if login success
        if ip in self.failed_logins:
            del self.failed_logins[ip]

    def addUnreadMessage(self, recipient: str, sender: str):
        # increment unread count for recipient from sender
        if recipient not in self.unreadMessages:
            self.unreadMessages[recipient] = {}
        if sender not in self.unreadMessages[recipient]:
            self.unreadMessages[recipient][sender] = 0
        self.unreadMessages[recipient][sender] += 1
        # update the set of users with unread msgs
        if recipient not in self.usersWithUnread:
            self.usersWithUnread[recipient] = set()
        self.usersWithUnread[recipient].add(sender)
        self.save_all()

    def clearUnread(self, username: str, sender: str):
        # mark conversation as read
        if username in self.unreadMessages and sender in self.unreadMessages[username]:
            self.unreadMessages[username][sender] = 0
            # remove from the set
            if username in self.usersWithUnread:
                self.usersWithUnread[username].discard(sender)
            self.save_all()

    def getUnreadCounts(self, username: str):
        # return unread counts for a user {sender: count}
        if username not in self.unreadMessages:
            return {}
        return {k: v for k, v in self.unreadMessages[username].items() if v > 0}

    def getUsersWithUnread(self, username: str):
        # return set of users who sent unread messages
        return self.usersWithUnread.get(username, set())

    def reload_config(self):
        # reload all config values from disk - admin only
        # 2nd value passed is default 
        self.admins = self._load_admins()
        self.fetch_cooldown = self._load_config_int("fetch_cooldown", 30) 
        self.msg_rate_limit = self._load_config_float("msg_rate_limit", 1.0)
        self.max_msg_len = self._load_config_int("max_msg_len", 400)
        self.max_channel_messages = self._load_config_int("max_channel_messages", 2000)
        self.max_dm_messages = self._load_config_int("max_dm_messages", 5000)
        self.login_rate_limit_attempts = self._load_config_int("login_rate_limit_attempts", 5)
        self.login_rate_limit_window = self._load_config_int("login_rate_limit_window", 300)
        self.login_rate_limit_lockout = self._load_config_int("login_rate_limit_lockout", 900)


