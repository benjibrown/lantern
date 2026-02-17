import argparse
import getpass
import json
import os
import platform

DEFAULT_CONFIG = {
    "server": "0.0.0.0",
    "port": 6000,
    "username": None,
}


def _session_path(config_path: str) -> str:
    base = os.path.dirname(os.path.abspath(config_path))
    return os.path.join(base, ".lantern_session")


class Config:
    def __init__(self):
        parser = argparse.ArgumentParser(description="Lantern Chat Client")
        parser.add_argument("-s", "--server", help="Server address")
        parser.add_argument("-p", "--port", type=int, help="Server port")
        parser.add_argument("-u", "--username", help="Username (overrides session)")
        parser.add_argument("-c", "--config", default="config.json", help="Config file path")

        args = parser.parse_args()
        self.config_path = args.config
        self.SESSION_PATH = _session_path(args.config)

        file_config = self.load_config(args.config)

        self.SERVER_HOST = (
            args.server
            or file_config.get("server")
            or os.environ.get("LANTERN_SERVER")
            or DEFAULT_CONFIG["server"]
        )

        self.SERVER_PORT = (
            args.port
            or file_config.get("port")
            or DEFAULT_CONFIG["port"]
        )

        self.USERNAME = args.username or file_config.get("username") or DEFAULT_CONFIG["username"]
        self.PASSWORD = None

        session = self.load_session()
        if session:
            self.USERNAME = self.USERNAME or session.get("username")
            self.PASSWORD = session.get("password")
        else:
            self.USERNAME = self.USERNAME or None
            self.PASSWORD = None
        # default max until fetched from server
        self.MAX_MESSAGE_LEN = 400
        self.MAX_INPUT_LEN = 300
        self.MAX_MESSAGES = 500
        self.FETCH_COOLDOWN = 30
        self.SERVER_RESPONSE_TIMEOUT = 15

    def load_config(self, path):
        if not path or not os.path.exists(path):
            return {}
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def load_session(self):
        if not os.path.exists(self.SESSION_PATH):
            return None
        try:
            with open(self.SESSION_PATH, "r") as f:
                return json.load(f)
        except Exception:
            return None

    def has_session(self):
        return bool(self.USERNAME and self.PASSWORD is not None)

    def save_session(self, username: str, password: str):
        try:
            with open(self.SESSION_PATH, "w") as f:
                json.dump({"username": username, "password": password}, f)
        except Exception:
            pass

    def clear_session(self):
        try:
            if os.path.exists(self.SESSION_PATH):
                os.unlink(self.SESSION_PATH)
        except Exception:
            pass
