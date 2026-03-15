import argparse
import json
import os

from lantern_chat.server.state import ServerState, HISTORY_FILE, USERS_FILE, CONFIG_FILE
from lantern_chat.server.net import networkManager

def fetch_version():
    # pull from package metadata if available
    try:
        import importlib.metadata
        return importlib.metadata.version("lantern-chat")
    except Exception:
        return "An error occurred while fetching the version. Please ensure the package is installed correctly."

def _load_server_config():
    if not os.path.exists(CONFIG_FILE):
        default = {
            "admins": [],
            "port": 6000,
            "fetch_cooldown": 30,
            "msg_rate_limit": 1.0,
            "max_msg_len": 400,
            "max_channel_messages": 2000,
            "max_dm_messages": 5000,
            "login_rate_limit_attempts": 5,
            "login_rate_limit_window": 300,
            "login_rate_limit_lockout": 900
        }
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(default, f, indent=2)
            print(f"Created default server config at {CONFIG_FILE}")
        except Exception:
            pass
        return default
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_server_config(data: dict):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def clear_db():
    confirm = input("Are you sure you want to clear all stored messages and users? This action cannot be undone. (y/N): ")
    if confirm.lower() != 'y':
        print("Aborting database reset.")
        return

    for path in (HISTORY_FILE, USERS_FILE):
        try:
            if os.path.exists(path):
                os.unlink(path)
                print(f"Removed {path}")
        except OSError as e:
            print(f"Failed to remove {path}: {e}")


def main():
    file_config = _load_server_config()

    parser = argparse.ArgumentParser(description="Lantern chat server")
    parser.add_argument("--reset-db", action="store_true", help="Clear all stored messages and users")
    parser.add_argument("--port", "-p", type=int, help="Port to listen on (default: 6000)")
    parser.add_argument("--version", "-v", help="Show version information", action="version", version=fetch_version())
    args = parser.parse_args()

    HOST = "0.0.0.0"
    PORT = args.port or file_config.get("port") or 6000

    # save port to config if explicitly passed via CLI
    if args.port and args.port != file_config.get("port"):
        file_config["port"] = args.port
        _save_server_config(file_config)

    if args.reset_db:
        clear_db()

    state = ServerState()
    network = networkManager(HOST, PORT, state)
    network.run()
