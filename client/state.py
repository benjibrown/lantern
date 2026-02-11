import threading
import time
from client.history import ChatHistory


class ClientState:
    def __init__(self, username, max_messages=500):
        self.messages = []  # list of (text, is_self)
        self.username = username
        self.users = set([username])
        self.lock = threading.Lock()
        self.running = True
        self.start_time = time.time()
        self.history = ChatHistory(max_messages=max_messages, username=username)        
        # Load chat history on startup, recalculating is_self based on current username
        self.messages = self.history.load(self.username)
