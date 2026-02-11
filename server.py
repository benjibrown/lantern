#!/usr/bin/env python3
from server.state import ServerState
from server.net import NetworkManager


def main():
    HOST = "0.0.0.0"
    PORT = 6000

    state = ServerState()
    network = NetworkManager(HOST, PORT, state)
    network.run()


if __name__ == "__main__":
    main()
