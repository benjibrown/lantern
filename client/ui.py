import curses
import time
import textwrap
import subprocess

# ------ UI class ------
# next time im not using curses lmao

class UI:
    def __init__(self, config, state, network, command_handler):
        self.config = config
        self.state = state
        self.network = network
        self.command_handler = command_handler
        self.input_buf = ""
        self.scroll_offset = 0
        self.dm_scroll_offset = 0

    def draw_status_bar(self, stdscr, h, w, y):
        now = time.time()
        uptime = int(now - self.state.start_time)
        hrs = uptime // 3600
        mins = (uptime % 3600) // 60
        secs = uptime % 60
        uptime_str = f"{hrs:02d}:{mins:02d}:{secs:02d}" if hrs else f"{mins:02d}:{secs:02d}"
        clock = time.strftime("%H:%M:%S")
        ping_str = f"{self.network.ping_ms}ms" if self.network.ping_ms is not None else "—"

        with self.state.lock:
            user_count = len(self.state.users)
            view = self.state.current_view
            dm_target = self.state.dm_target

        if view == "dm" and dm_target:
            status = f" {clock} │ DM: {dm_target[:20]} │ ping: {ping_str} │ /back "
        else:
            status = f" {clock} │ users: {user_count} │ ping: {ping_str} │ up: {uptime_str} "
        stdscr.addstr(y, 0, status[: w - 1].ljust(w - 1), curses.A_DIM)

    def show_help(self, stdscr):
        h, w = stdscr.getmaxyx()
        # might add some ascii art here so its not just a boring list of commands lol
        lines = [
            "Lantern Help",
            "",
            "/exit    Quit chat",
            "/logout  Log out (next run: login again)",
            "/help    Show this menu",
            "/channel  Back to main channel",
            "/dm <user>  Open DM with user",
            "/panel   List users, pick one to DM",
            "/fetch   Send system info (30s cooldown)",
            "/dnd     Do not disturb (toggle notifications)",
            "",
            "Press any key to close",
        ]
        win_h = len(lines) + 2
        win_w = min(w - 4, max(len(l) for l in lines) + 4)
        y = (h - win_h) // 2
        x = (w - win_w) // 2
        win = curses.newwin(win_h, win_w, y, x)
        win.border()
        for i, line in enumerate(lines, 1):
            win.addstr(i, 2, line[: win_w - 4])
        win.refresh()
        win.getch()
        win.clear()
        stdscr.touchwin()
        stdscr.refresh()

    def show_keybinds(self, stdscr):
        h, w = stdscr.getmaxyx()
        # TODO - add more keybinds to this list cos im adding some new ones later
        lines = [
            "Keybinds",
            "ctrl + h: help menu",
            "ctrl + w: exit",
            "double tap esc: exit",
            "ctrl + /: show keybinds",
            "ctrl + f: fetch system info",
            "Press any key to close",
        ]
        win_h = len(lines) + 2
        win_w = max(len(l) for l in lines) + 4
        y = (h - win_h) // 2
        x = (w - win_w) // 2
        win = curses.newwin(win_h, win_w, y, x)
        win.border()
        for i, line in enumerate(lines, 1):
            win.addstr(i, 2, line)
        win.refresh()
        win.getch()
        win.clear()
        stdscr.touchwin()
        stdscr.refresh()

    def show_user_panel(self, stdscr):
        self.network.request_users_detailed()
        time.sleep(0.15)
        for _ in range(20):
            with self.state.lock:
                ul = list(self.state.users_detailed)
            if ul:
                break
            time.sleep(0.1)
        with self.state.lock:
            ul = list(self.state.users_detailed)
        if not ul:
            ul = [(u, "?", 0) for u in sorted(self.state.users)]
        if not ul:
            return
        h, w = stdscr.getmaxyx()
        win_h = min(len(ul) + 4, h - 4)
        win_w = min(52, w - 4)
        y = (h - win_h) // 2
        x = (w - win_w) // 2
        win = curses.newwin(win_h, win_w, y, x)
        win.border()
        win.keypad(True)
        win.nodelay(False)
        try:
            win.addstr(0, 2, " Select user to DM ", curses.A_BOLD)
        except curses.error:
            pass
        sel = 0
        while True:
            for i, (u, status, ts) in enumerate(ul[: win_h - 3]):
                try:
                    ts_str = time.strftime("%m/%d %H:%M", time.localtime(ts)) if ts else "—"
                    line = f" {u[:18]:18} {status:8} {ts_str}"
                    attr = curses.A_REVERSE if i == sel else curses.A_NORMAL
                    win.addstr(i + 1, 2, line[: win_w - 4], attr)
                except curses.error:
                    pass
            try:
                win.addstr(win_h - 2, 2, "Enter: open DM  Esc: cancel", curses.A_DIM)
            except curses.error:
                pass
            win.refresh()
            ch = win.getch()
            if ch in (27, ord("q")):
                break
            if ch == curses.KEY_UP and sel > 0:
                sel -= 1
            if ch == curses.KEY_DOWN and sel < min(len(ul), win_h - 3) - 1:
                sel += 1
            if ch in (10, 13):
                target = ul[sel][0]
                if target == self.config.USERNAME:
                    break
                with self.state.lock:
                    self.state.dm_target = target
                    self.state.current_view = "dm"
                    self.state.ensure_dm_conversation(target)
                self.state.pending_dm_history = target
                self.network.request_dm_history(target)
                break
        win.clear()
        stdscr.touchwin()
        stdscr.refresh()

    def confirm_exit(self, stdscr):
        h, w = stdscr.getmaxyx()
        lines = [
            "Are you sure you want to exit?",
            "Press Enter to confirm, any other key to cancel.",
        ]
        win_h = len(lines) + 2
        win_w = max(len(l) for l in lines) + 4
        y = (h - win_h) // 2
        x = (w - win_w) // 2
        win = curses.newwin(win_h, win_w, y, x)
        win.border()
        win.keypad(True)
        win.nodelay(False)
        for i, line in enumerate(lines, start=1):
            win.addstr(i, 2, line)
        win.refresh()
        ch = win.getch()
        return ch in (10, 13)

    def run(self, stdscr):
        curses.cbreak()
        curses.curs_set(0)
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_CYAN, -1)
        curses.init_pair(3, curses.COLOR_RED, -1)
        try:
            curses.init_color(10, 800, 627, 1000)
            curses.init_pair(4, 10, -1)
        except Exception:
            curses.init_pair(4, curses.COLOR_MAGENTA, -1)

        stdscr.nodelay(True)
        stdscr.keypad(True)
        self.input_buf = ""
        self.network.request_user_list()

        while self.state.running:
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            user_w = 22
            chat_w = max(10, w - user_w - 1)
            chat_h = h - 3

            with self.state.lock:
                view = self.state.current_view
                dm_target = self.state.dm_target
                if view == "dm" and dm_target:
                    chat_snapshot = list(self.state.dm_conversations.get(dm_target, []))
                else:
                    chat_snapshot = list(self.state.messages)
                user_snapshot = sorted(self.state.users)

            lines = []
            for text, is_self in chat_snapshot:
                display_text = text
                is_system = text.startswith("[system]")
                if is_self and self.config.USERNAME and text.startswith(f"[{self.config.USERNAME}]: "):
                    display_text = text[len(f"[{self.config.USERNAME}]: ") :]
                elif is_self and self.config.USERNAME and text.startswith(f"[{self.config.USERNAME}] "):
                    display_text = text[len(f"[{self.config.USERNAME}] ") :]
                prefix = "[you] " if is_self and not is_system else ""
                for l in textwrap.wrap(prefix + display_text, chat_w) or [""]:
                    lines.append((l, is_self, text, is_system))

            total_lines = len(lines)
            scroll = self.dm_scroll_offset if (view == "dm" and dm_target) else self.scroll_offset
            max_scroll = max(0, total_lines - chat_h)
            scroll = min(scroll, max_scroll)
            if view == "dm" and dm_target:
                self.dm_scroll_offset = scroll
            else:
                self.scroll_offset = scroll

            start = max(0, total_lines - chat_h - scroll)
            end = total_lines - scroll
            visible_lines = lines[start:end]

            for i, (line, is_self, original_text, is_system) in enumerate(visible_lines):
                if is_system:
                    stdscr.addstr(i, 0, line, curses.color_pair(4))
                elif is_self:
                    stdscr.addstr(i, 0, line, curses.color_pair(1))
                elif original_text.startswith("[") and original_text.endswith(" joined]"):
                    stdscr.addstr(i, 0, line, curses.color_pair(2) | curses.A_DIM)
                elif original_text.startswith("[") and original_text.endswith(" left]"):
                    stdscr.addstr(i, 0, line, curses.color_pair(3) | curses.A_DIM)
                else:
                    stdscr.addstr(i, 0, line)



            stdscr.vline(0, chat_w, "|", chat_h)
            for i, u in enumerate(user_snapshot[:chat_h]):
                stdscr.addstr(i, chat_w + 2, u[: user_w - 2])

            INPUT_Y = h - 3
            SEP_Y = h - 2
            STATUS_Y = h - 1
            prompt = "> "
            visible = self.input_buf[-(chat_w - len(prompt) - 1) :]
            stdscr.move(INPUT_Y, 0)
            stdscr.clrtoeol()
            stdscr.addstr(INPUT_Y, 0, f"{prompt}{visible}")
            stdscr.hline(SEP_Y, 0, curses.ACS_HLINE, w)
            self.draw_status_bar(stdscr, h, w, y=STATUS_Y)
            stdscr.refresh()

            try:
                ch = stdscr.getch()
                if ch == -1:
                    time.sleep(0.02)
                    continue

                if ch == 27:
                    ch2 = stdscr.getch()
                    if ch2 == 27:
                        self.command_handler.shutdown()
                    else:
                        continue

                if ch in (8, 127) and curses.keyname(ch) == b"^H":
                    self.show_help(stdscr)
                    continue
                if ch in (31, ord("_")):
                    self.show_keybinds(stdscr)
                    continue
                if ch in (23, ord("w") - ord("a") + 1):
                    if self.confirm_exit(stdscr):
                        self.command_handler.shutdown()
                    continue
                if ch in (6, ord("f") - ord("a") + 1):
                    if self.command_handler.handle_command("/fetch", stdscr):
                        continue

                
                scroll_off = self.dm_scroll_offset if (view == "dm" and dm_target) else self.scroll_offset
                if ch == curses.KEY_UP:
                    if view == "dm" and dm_target:
                        self.dm_scroll_offset += 1
                    else:
                        self.scroll_offset += 1
                    continue
                if ch == curses.KEY_DOWN:
                    if view == "dm" and dm_target and self.dm_scroll_offset > 0:
                        self.dm_scroll_offset -= 1
                    elif not (view == "dm" and dm_target) and self.scroll_offset > 0:
                        self.scroll_offset -= 1
                    continue

                if ch in (10, 13):
                    msg = self.input_buf.strip()
                    self.input_buf = ""
                    if not msg:
                        continue
                    if self.command_handler.handle_command(msg, stdscr):
                        continue

                    msg = msg[: self.config.MAX_MSG_LEN]
                    if view == "dm" and dm_target:
                        out = f"[{self.config.USERNAME}]: {msg}"
                        self.network.send_dm(dm_target, msg)
                        with self.state.lock:
                            no_response = time.time() - self.state.last_received_from_server > self.config.SERVER_RESPONSE_TIMEOUT
                            if self.state.send_failed or no_response:
                                self.state.send_failed = False
                                self.state.append_dm(dm_target, "[system] Failed to send (connection error)", True)
                            else:
                                self.state.append_dm(dm_target, out, True)
                    else:
                        out = f"[{self.config.USERNAME}]: {msg}"
                        self.network.send_message(out)
                        with self.state.lock:
                            no_response = time.time() - self.state.last_received_from_server > self.config.SERVER_RESPONSE_TIMEOUT
                            if self.state.send_failed or no_response:
                                self.state.send_failed = False
                                self.state.messages.append(("[system] Failed to send (connection error)", True))
                            else:
                                self.state.messages.append((out, True))
                            self.state.messages[:] = self.state.messages[-self.config.MAX_MESSAGES :]

                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    self.input_buf = self.input_buf[:-1]
                elif 32 <= ch <= 126 and len(self.input_buf) < self.config.MAX_INPUT_LEN:
                    self.input_buf += chr(ch)

            except Exception:
                pass
