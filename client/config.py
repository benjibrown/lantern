import getpass
import platform
import argparse


class Config:
    def __init__(self):
        parser = argparse.ArgumentParser(description="Lantern Chat Client")
        parser.add_argument("-s", "--server", default="0.0.0.0", help="Server address")
        parser.add_argument("-p", "--port", type=int, default=6273, help="Server port")
        parser.add_argument("-u", "--username", default=getpass.getuser(), help="Username")

        args = parser.parse_args()

        self.SERVER_HOST = args.server
        self.SERVER_PORT = args.port

        raw_name = args.username.strip()
        self.USERNAME = f"{raw_name}@{platform.node()}" if raw_name else f"{getpass.getuser()}@{platform.node()}"

        # Constants
        self.MAX_MSG_LEN = 400
        self.MAX_INPUT_LEN = 300
        self.MAX_MESSAGES = 500
        self.FETCH_COOLDOWN = 30
