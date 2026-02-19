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
                    if self.state.current_view == "dm" and self.state.dm_target:
                        self.state.append_dm(self.state.dm_target, f"[system] fetch cooldown ({int(self.config.FETCH_COOLDOWN - (now - self.last_fetch))}s remaining)", True)
                    else:
                        self.state.messages.append((f"[system] fetch cooldown ({int(self.config.FETCH_COOLDOWN - (now - self.last_fetch))}s remaining)", True))
                return True
                                

            self.last_fetch = now
            info = self.network.system_fetch()

            with self.state.lock:
                if self.state.current_view == "dm" and self.state.dm_target:
                    self.state.append_dm(self.state.dm_target, "system", True)
                    for k, v in info.items():
                        self.state.append_dm(self.state.dm_target, f"  {k}: {v}", True)
                else:
                    self.state.messages.append(("system", True))
                    for k, v in info.items():
                        self.state.messages.append((f"  {k}: {v}", True))
            if self.state.current_view == "dm" and self.state.dm_target:
                self.network.send_dm(self.state.dm_target, "system")
                for k, v in info.items():
                    self.network.send_dm(self.state.dm_target, f"  {k}: {v}")
            else:
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
            # TODO - validate target username (exists, not self), also dm cmd doesnt work in the dm view - idk why
            
            if not target:
                return True

            if target == self.config.USERNAME:
                with self.state.lock:
                    if self.state.current_view == "dm" and self.state.dm_target:
                        self.state.append_dm(self.state.dm_target, "[system] cannot DM yourself", True)
                    else:
                        self.state.messages.append(("[system] cannot DM yourself", True))
                return True
            if target not in self.state.users:
                with self.state.lock:
                    if self.state.current_view == "dm" and self.state.dm_target:
                        self.state.append_dm(self.state.dm_target, f"[system] user '{target}' not found", True)
                    else:
                        self.state.messages.append((f"[system] user '{target}' not found", True))
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
                if self.state.current_view == "dm" and self.state.dm_target:
                    self.state.append_dm(self.state.dm_target, f"[system] Do not disturb {status}", True)
                else:
                    self.state.messages.append((f"[system] Do not disturb {status}", True))
                    self.state.messages[:] = self.state.messages[-self.config.MAX_MESSAGES:]
            return True
        # fetch user stats for the given user - if none, fetch self.
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
                    self.state.messages.append((notice, True))
                    self.state.messages[:] = self.state.messages[-self.config.MAX_MESSAGES:]
            return True

        #admin / moderation commands - handled in one block as all req token 
        if msg.startswith("/mute ") or msg.startswith("/unmute ") or msg.startswith("/ban "):
            parts = msg.split(maxsplit=1)
            if len(parts) != 2 or not parts[1].strip():
                with self.state.lock:
                    if self.state.current_view == "dm" and self.state.dm_target:
                        self.state.append_dm(self.state.dm_target, "[system] Usage: /mute <user>, /unmute <user>, /ban <user>", True)
                    else:
                        self.state.messages.append(
                        ("[system] Usage: /mute <user>, /unmute <user>, /ban <user>", True)
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
                        ("[system] Usage: /changeusername <old_username> <new_username>", True)
                    )
                        self.state.messages[:] = self.state.messages[-self.config.MAX_MESSAGES:]
                return True
            _, old_name, new_name = parts
            payload = f"{old_name}|{new_name}"
            self.network.send_admin_command("changeusername", payload)
            return True
        
        return False

    def shutdown(self):
        self.state.running = False
        self.network.send_leave()
        self.network.close()
        sys.exit(0)

