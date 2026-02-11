import time
import sys


class CommandHandler:
    def __init__(self, config, state, network, ui):
        self.config = config
        self.state = state
        self.network = network
        self.ui = ui
        self.last_fetch = 0

    def handle_command(self, msg, stdscr):
        if msg == "/exit":
            if self.ui.confirm_exit(stdscr):
                self.shutdown()
            return True

        if msg == "/help":
            self.ui.show_help(stdscr)
            return True

        if msg == "/fetch":
            now = time.time()
            if now - self.last_fetch < self.config.FETCH_COOLDOWN:
                with self.state.lock:
                    self.state.messages.append(("[system] fetch cooldown", True))
                return True

            self.last_fetch = now
            info = self.network.system_fetch()

            with self.state.lock:
                self.state.messages.append(("system", True))
                for k, v in info.items():
                    self.state.messages.append((f"  {k}: {v}", True))

            self.network.send_message(f"[{self.config.USERNAME}] system")
            for k, v in info.items():
                self.network.send_message(f"  {k}: {v}")
            return True

        return False

    def shutdown(self):
        self.state.running = False
        self.network.send_leave()
        self.network.close()
        sys.exit(0)
