import argparse
import json
import os

_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "lantern")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "config.json")
_SESSION_FILE = os.path.join(_CONFIG_DIR, "session")
_STATE_FILE = os.path.join(_CONFIG_DIR, "state.json")
os.makedirs(_CONFIG_DIR, exist_ok=True)

DEFAULT_PORT = 6000


class Config:
    def __init__(self):
        parser = argparse.ArgumentParser(description="Lantern Chat Client")
        parser.add_argument("-s", "--server", help="Server address")
        parser.add_argument("-p", "--port", type=int, help="Server port")
        parser.add_argument("-u", "--username", help="Username (overrides session)")

        args = parser.parse_args()

        file_config = self._load_config()

        server = (
            args.server
            or file_config.get("server")
            or os.environ.get("LANTERN_SERVER")
        )

        # first-run: no server configured anywhere — prompt and save
        if not server:
            server = input("Enter server address [leave blank for localhost]: ").strip() or "localhost"
            file_config["server"] = server
            file_config.setdefault("port", DEFAULT_PORT)
            self._save_config(file_config)
            print(f"Config saved to {_CONFIG_FILE}")

        self.SERVER_HOST = server
        self.SERVER_PORT = args.port or file_config.get("port") or DEFAULT_PORT
        self.USERNAME = args.username or file_config.get("username") or None
        self.PASSWORD = None

        session = self._load_session()
        if session:
            self.USERNAME = self.USERNAME or session.get("username")
            self.PASSWORD = session.get("password")

        # defaults until fetched from server
        self.MAX_MESSAGE_LEN = 400
        self.MAX_INPUT_LEN = 300
        self.MAX_MESSAGES = 500
        self.SERVER_RESPONSE_TIMEOUT = 15

    def _load_config(self):
        if not os.path.exists(_CONFIG_FILE):
            return {}
        try:
            with open(_CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_config(self, data: dict):
        try:
            with open(_CONFIG_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _load_session(self):
        if not os.path.exists(_SESSION_FILE):
            return None
        try:
            with open(_SESSION_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return None

    def has_session(self):
        return bool(self.USERNAME and self.PASSWORD is not None)

    def save_session(self, username: str, password: str):
        try:
            with open(_SESSION_FILE, "w") as f:
                json.dump({"username": username, "password": password}, f)
        except Exception:
            pass

    def clear_session(self):
        try:
            if os.path.exists(_SESSION_FILE):
                os.unlink(_SESSION_FILE)
        except Exception:
            pass

    def _load_state(self):
        if not os.path.exists(_STATE_FILE):
            return {}
        try:
            with open(_STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_state(self, data: dict):
        try:
            with open(_STATE_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def load_dnd(self):
        data = self._load_config()
        return bool(data.get("dnd", True))

    def save_dnd(self, enabled):
        data = self._load_config()
        data["dnd"] = bool(enabled)
        self._save_config(data)

    def load_last_view(self):
        data = self._load_state()
        view = data.get("last_view")
        return view if view in ("channel", "dm") else "channel"

    def save_last_view(self, view):
        data = self._load_state()
        data["last_view"] = "dm" if view == "dm" else "channel"
        self._save_state(data)

    def load_last_dm(self):
        data = self._load_state()
        value = data.get("last_dm")
        return value if isinstance(value, str) and value.strip() else None

    def save_last_dm(self, username):
        data = self._load_state()
        if username:
            data["last_dm"] = str(username).strip()
        else:
            data.pop("last_dm", None)
        self._save_state(data)


