import getpass
import platform
import argparse
import json 
import os

DEFAULT_CONFIG = {
    "server": "0.0.0.0",
    "port": 6000,
    "username": None
}


class Config:
    def __init__(self):
        parser = argparse.ArgumentParser(description="Lantern Chat Client")
        parser.add_argument("-s", "--server", help="Server address")
        parser.add_argument("-p", "--port", type=int, help="Server port")
        parser.add_argument("-u", "--username", help="Username")
        parser.add_argument("-c", "--config", default="config.json", help="Config file path")

        args = parser.parse_args()

        # ----- load from config file -----
        file_config = self.load_config(args.config)

        # ----- priority chain -----
        self.SERVER_HOST = (
            args.server
            or file_config.get("server")
            or DEFAULT_CONFIG["server"]
        )

        self.SERVER_PORT = (
            args.port
            or file_config.get("port")
            or DEFAULT_CONFIG["port"]
        )

        raw_name = (
            args.username
            or file_config.get("username")
            or DEFAULT_CONFIG["username"]
        )

        if not raw_name:
            raw_name = getpass.getuser()

        self.USERNAME = f"{raw_name}@{platform.node()}"

        # Constants
        self.MAX_MSG_LEN = 400
        self.MAX_INPUT_LEN = 300
        self.MAX_MESSAGES = 500
        self.FETCH_COOLDOWN = 30


    def load_config(self, path):
        if not path:
            return {}

        if not os.path.exists(path):
            return {}

        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return {}

