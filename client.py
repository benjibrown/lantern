#!/usr/bin/env python3
# TODO - strip new lines from chat box input so you cant just paste the whole bee movie script 
import curses
import sys
import time

from client.config import Config
from client.state import ClientState
from client.net import NetworkManager
from client.commands import CommandHandler
from client.ui import UI, show_ban_screen
from client.auth_ui import run_auth_ui


def main():
    config = Config()

    if not config.has_session():
        def auth_wrapper(stdscr):
            result = run_auth_ui(stdscr, config)
            if result is None:
                sys.exit(0)
            config.USERNAME, config.PASSWORD = result

        curses.wrapper(auth_wrapper)

    state = ClientState(config.USERNAME)
    network = NetworkManager(config, state)
    ui = UI(config, state, network, None)
    command_handler = CommandHandler(config, state, network, ui)
    ui.command_handler = command_handler

    network.connect()
    network.start_threads()

    connect_timeout = 10.0
    deadline = time.monotonic() + connect_timeout
    while not state.authenticated and not state.auth_failed and time.monotonic() < deadline:
        time.sleep(0.05)
    if state.auth_failed:
        config.clear_session()
        print("Authentication failed. Please run again to log in.", file=sys.stderr)
        sys.exit(1)

    if not state.authenticated:
        print("Could not connect to server. Check address and that the server is running.", file=sys.stderr)
        sys.exit(1)

    config.save_session(config.USERNAME, config.PASSWORD)

    try:
        curses.wrapper(ui.run)
    except KeyboardInterrupt:
        command_handler.shutdown()
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)

    if state.banned:
        def banned_wrapper(stdscr):
           show_ban_screen(stdscr, state.ban_reason) 

        curses.wrapper(banned_wrapper)
        sys.exit(0)


if __name__ == "__main__":
    main()


