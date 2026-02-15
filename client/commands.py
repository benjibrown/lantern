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

        if msg == "/logout":
            if self.ui.confirm_exit(stdscr):
                self.config.clear_session()
                self.state.running = False
                self.network.send_leave()
                self.network.close()
                sys.exit(0)
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

        if msg == "/channel" or msg == "/back":
            with self.state.lock:
                self.state.current_view = "channel"
                self.state.dm_target = None
            return True
        # TODO - /dm "user" - check if user exists and isnt just themselves. 
        # TODO - popup window when typing /.. to show available commands. autocompletion????? idk if this is possible in curses 
        if msg.startswith("/dm "):
            target = msg[4:].strip()
            if not target:
                return True
            with self.state.lock:
                self.state.dm_target = target
                self.state.current_view = "dm"
                self.state.ensure_dm_conversation(target)
            self.state.pending_dm_history = target
            self.network.request_dm_history(target)
            return True

        if msg == "/panel":
            self.ui.show_user_panel(stdscr)
            return True

        if msg == "/dnd":
            with self.state.lock:
                self.state.dnd = not self.state.dnd
                status = "on (notifications off)" if self.state.dnd else "off (notifications on)"
                self.state.messages.append((f"[system] Do not disturb {status}", True))
                self.state.messages[:] = self.state.messages[-self.config.MAX_MESSAGES:]
            return True

        return False

    def shutdown(self):
        self.state.running = False
        self.network.send_leave()
        self.network.close()
        sys.exit(0)
