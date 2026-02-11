import socket
import threading
import time
import platform


class NetworkManager:
    def __init__(self, config, state):
        self.config = config
        self.state = state
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self.last_ping_sent = 0.0
        self.last_ping_recv = 0.0
        self.ping_ms = None

    def connect(self):
        """Send initial JOIN message"""
        self.sock.sendto(f"[JOIN]|{self.config.USERNAME}".encode(), 
                        (self.config.SERVER_HOST, self.config.SERVER_PORT))

    def send_message(self, msg):
        """Send a message to the server"""
        self.sock.sendto(msg.encode(), (self.config.SERVER_HOST, self.config.SERVER_PORT))

    def send_leave(self):
        """Send LEAVE message"""
        try:
            self.sock.sendto(f"[LEAVE]|{self.config.USERNAME}".encode(), 
                           (self.config.SERVER_HOST, self.config.SERVER_PORT))
        except:
            pass

    def request_user_list(self):
        """Request user list from server"""
        self.sock.sendto(f"[REQ_USERS]|{self.config.USERNAME}".encode(), 
                        (self.config.SERVER_HOST, self.config.SERVER_PORT))

    def keepalive(self):
        """Send periodic ping messages"""
        while self.state.running:
            try:
                self.last_ping_sent = time.time()
                self.sock.sendto(b"[ping]", (self.config.SERVER_HOST, self.config.SERVER_PORT))
                time.sleep(5)
            except:
                pass

    def receive(self):
        """Receive messages from server"""
        while self.state.running:
            try:
                data, _ = self.sock.recvfrom(4096)
                msg = data.decode(errors="ignore").strip()

                if not msg:
                    continue

                if msg == "[ping]":
                    self.last_ping_recv = time.time()
                    if self.last_ping_sent > 0:
                        self.ping_ms = int((self.last_ping_recv - self.last_ping_sent) * 1000)
                    continue

                with self.state.lock:
                    # user list sync
                    if msg.startswith("[USERS]|"):
                        self.state.users = set(msg.split("|", 1)[1].split(";"))
                        continue

                    is_self = msg.startswith(f"[{self.config.USERNAME}]:") or msg.startswith(f"[{self.config.USERNAME}] system")

                    self.state.messages.append((msg[:self.config.MAX_MSG_LEN], is_self))
                    self.state.messages[:] = self.state.messages[-self.config.MAX_MESSAGES:]

            except BlockingIOError:
                time.sleep(0.03)
            except:
                time.sleep(0.1)

    def start_threads(self):
        """Start receive and keepalive threads"""
        threading.Thread(target=self.receive, daemon=True).start()
        threading.Thread(target=self.keepalive, daemon=True).start()

    def close(self):
        """Close the socket"""
        try:
            self.sock.close()
        except:
            pass

    def system_fetch(self):
        """Get system information"""
        return {
            "OS": f"{platform.system()} {platform.release()}",
            "Kernel": platform.version().split()[0],
            "Host": platform.node(),
            "Arch": platform.machine(),
        }
