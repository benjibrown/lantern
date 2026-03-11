import sys
import threading

from lantern_chat.client.state import Message


class CommandHandler:
    def __init__(self, config, state, network, ui):
        self.config = config
        self.state = state
        self.network = network
        self.ui = ui

    def handle_command(self, msg, stdscr):
        if msg == "/exit":
            if self.ui.confirm_exit(stdscr):
                self.shutdown()
            return True

        if msg == "/clear":
            with self.state.lock:
                self.state.messages.clear()
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
            self.network.request_fetch()
            return True

        if msg == "/channel" or msg == "/back":
            with self.state.lock:
                self.state.current_view = "channel"
                self.state.dm_target = None
            return True
        if msg.startswith("/dm "):
            target = msg[4:].strip()
            
            if not target:
                return True

            if target == self.config.USERNAME:
                with self.state.lock:
                    if self.state.current_view == "dm" and self.state.dm_target:
                        self.state.append_dm(self.state.dm_target, "[system] cannot DM yourself", True)
                    else:
                        self.state.messages.append(Message(text="[system] cannot DM yourself", is_self=True, ts=0))
                return True
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
                if self.state.current_view == "dm" and self.state.dm_target:
                    self.state.append_dm(self.state.dm_target, f"[system] Do not disturb {status}", True)
                else:
                    self.state.messages.append(Message(text=f"[system] Do not disturb {status}", is_self=True, ts=0))
                    self.state.messages[:] = self.state.messages[-self.config.MAX_MESSAGES:]
            return True
        if msg.startswith("/stats"):
            parts = msg.split(maxsplit=1)
            target = parts[1].strip() if len(parts) > 1 else self.config.USERNAME
            self.network.request_user_stats(target)

            # let the user know we're requesting stats; the actual stats
            # will be displayed when the server responds.
            with self.state.lock:
                notice = f"[system] Requesting stats for '{target}'..."
                if self.state.current_view == "dm" and self.state.dm_target:
                    self.state.append_dm(self.state.dm_target, notice, True)
                else:
                    self.state.messages.append(Message(text=notice, is_self=True, ts=0))
                    self.state.messages[:] = self.state.messages[-self.config.MAX_MESSAGES:]
            return True

        #admin / moderation commands - handled in one block as all req token 
        if msg.startswith("/mute ") or msg.startswith("/unmute ") or msg.startswith("/ban ") or msg.startswith("/unban "):
            parts = msg.split(maxsplit=1)
            if len(parts) != 2 or not parts[1].strip():
                with self.state.lock:
                    if self.state.current_view == "dm" and self.state.dm_target:
                        self.state.append_dm(self.state.dm_target, "[system] Usage: /mute <user>, /unmute <user>, /ban <user>, /unban <user>", True)
                    else:
                        self.state.messages.append(
                        Message(text="[system] Usage: /mute <user>, /unmute <user>, /ban <user>, /unban <user>", is_self=True, ts=0)
                    )
                        self.state.messages[:] = self.state.messages[-self.config.MAX_MESSAGES:]
                return True
            target = parts[1].strip()
            cmd = parts[0][1:]  # strip leading '/'

            payload = target 
            if cmd == "ban":
                reason = self.ui.prompt_ban_reason(stdscr, target)
                if reason is None:  # User cancelled the ban
                    return True 
                payload = f"{target}|{reason}"

            self.network.send_admin_command(cmd, payload)
            return True

        if msg.startswith("/changeusername"):
            parts = msg.split()
            if len(parts) != 3:
                with self.state.lock:
                    if self.state.current_view == "dm" and self.state.dm_target:
                        self.state.append_dm(self.state.dm_target, "[system] Usage: /changeusername <old_username> <new_username>", True)
                    else:
                        self.state.messages.append(
                        Message(text="[system] Usage: /changeusername <old_username> <new_username>", is_self=True, ts=0)
                    )
                        self.state.messages[:] = self.state.messages[-self.config.MAX_MESSAGES:]
                return True
            _, old_name, new_name = parts
            payload = f"{old_name}|{new_name}"
            self.network.send_admin_command("changeusername", payload)
            return True
        # img cmd handling - might make keybind
        if msg == "/img":
            path = self.ui.show_file_picker(stdscr)
            if path:
                with self.state.lock:
                    dm_target = self.state.dm_target if self.state.current_view == "dm" else None
                threading.Thread(target=self.network.send_img, args=(path, dm_target), daemon=True).start()
            return True

        if msg.startswith("/disp "):
            with self.state.lock:
                in_dm = self.state.current_view == "dm" and bool(self.state.dm_target)
                dm_target = self.state.dm_target
            if in_dm:
                self.state.append_dm(dm_target, "[system] /disp is not supported in DMs", True)
                return True
            parts = msg.split(None, 2)
            if len(parts) < 3 or not parts[1].isdigit():
                with self.state.lock:
                    self.state.messages.append(Message(text="[system] Usage: /disp <seconds> <message>", is_self=True, ts=0))
                    self.state.messages[:] = self.state.messages[-self.config.MAX_MESSAGES:]
                return True
            seconds, text = int(parts[1]), parts[2]
            self.network.send_disp(seconds, text)
            return True

        return False

    def shutdown(self):
        self.state.running = False
        self.network.send_leave()
        self.network.close()
        sys.exit(0)

