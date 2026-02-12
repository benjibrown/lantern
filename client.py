#!/usr/bin/env python3
import curses
import sys

from client.config import Config
from client.state import ClientState
from client.net import NetworkManager
from client.commands import CommandHandler
from client.ui import UI


def main():
    config = Config()
    state = ClientState(config.USERNAME)
    network = NetworkManager(config, state)
    ui = UI(config, state, network, None)  # do stuff 
    command_handler = CommandHandler(config, state, network, ui)
    ui.command_handler = command_handler # circular 

    network.connect()
    network.start_threads()

    try:
        curses.wrapper(ui.run)
    except KeyboardInterrupt:
        command_handler.shutdown()
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
