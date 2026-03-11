import socket
import threading

from lantern_chat.client.net.send import SendMixin
from lantern_chat.client.net.receive import ReceiveMixin


class NetworkManager(SendMixin, ReceiveMixin):
    def __init__(self, config, state):
        self.config = config
        self.state = state
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._send_lock = threading.Lock()  # guards all writes to self.sock
        self.last_ping_sent = 0.0
        self.last_ping_recv = 0.0
        self.ping_ms = None

    def connect(self):
        try:
            self.sock.connect((self.config.SERVER_HOST, self.config.SERVER_PORT))
            self._send(f"[LOGIN]|{self.config.USERNAME}|{self.config.PASSWORD}")
        except OSError:
            with self.state.lock:
                self.state.auth_failed = True

    def start_threads(self):
        threading.Thread(target=self.receive, daemon=True).start()
        threading.Thread(target=self.keepalive, daemon=True).start()

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass
