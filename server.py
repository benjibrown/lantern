#!/usr/bin/env python3
import argparse
import os

from server.state import ServerState, HISTORY_FILE, USERS_FILE
from server.net import NetworkManager


def clear_db():
    # ask user for confirmation before deleting files 
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

    parser = argparse.ArgumentParser(description="Lantern chat server")
    parser.add_argument(
        "--reset-db",
        action="store_true",
        help="Clear all stored messages and users, then start the server",
    )
    args = parser.parse_args()
    # TODO - add option to specify host and port. config file???? 
    HOST = "0.0.0.0"
    PORT = 6000

    if args.reset_db:
        clear_db()

    state = ServerState()
    network = NetworkManager(HOST, PORT, state)
    network.run()


if __name__ == "__main__":
    main()
