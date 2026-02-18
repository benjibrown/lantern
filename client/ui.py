import curses
import time
import textwrap
import subprocess
import random

# ------ UI class ------
# next time im not using curses lmao
# TODO - make UI nicer, colors, improve menus, dnd color highlighting, icons etc


class UI:
    def __init__(self, config, state, network, command_handler):
        self.config = config
        self.state = state
        self.network = network
        self.command_handler = command_handler
        self.input_buf = ""
        self.input_cursor = 0
        self.scroll_offset = 0
        self.dm_scroll_offset = 0

    def draw_status_bar(self, stdscr, h, w, y):
        now = time.time()
        uptime = int(now - self.state.start_time)
        hrs = uptime // 3600
        mins = (uptime % 3600) // 60
        secs = uptime % 60
        uptime_str = (
            f"{hrs:02d}:{mins:02d}:{secs:02d}" if hrs else f"{mins:02d}:{secs:02d}"
        )
        clock = time.strftime("%H:%M:%S")
        ping_str = (
            f"{self.network.ping_ms}ms" if self.network.ping_ms is not None else "—"
        )

        with self.state.lock:
            user_count = len(self.state.users)
            view = self.state.current_view
            dm_target = self.state.dm_target

        if view == "dm" and dm_target:
            status = f" {clock} │ DM: {dm_target[:20]} │ ping: {ping_str} │ dnd {'on' if self.state.dnd else 'off'}  │ /back "
        else:
            status = f" {clock} │ users: {user_count} │ ping: {ping_str} │ up: {uptime_str} │ dnd: {'on' if self.state.dnd else 'off'}"
        stdscr.addstr(y, 0, status[: w - 1].ljust(w - 1), curses.A_DIM)

    def show_help(self, stdscr):
        h, w = stdscr.getmaxyx()
        if h >= 22 and w >= 70:
            art1 = [
                r" _          _                  ",
                r" | |__ _ _ _| |_ ___ _ _ _ _    ",
                r" | / _` | ' \  _/ -_) '_| ' \ _ ",
                r" |_\__,_|_||_\__\___|_| |_||_(_)",
                r"     lightweight terminal chat   ",
            ]
            art2 = [
                r"▄▄▌   ▄▄▄·  ▐ ▄ ▄▄▄▄▄▄▄▄ .▄▄▄   ▐ ▄    ",
                r"██•  ▐█ ▀█ •█▌▐█•██  ▀▄.▀·▀▄ █·•█▌▐█   ",
                r"██▪  ▄█▀▀█ ▐█▐▐▌ ▐█.▪▐▀▀▪▄▐▀▀▄ ▐█▐▐▌   ",
                r"▐█▌▐▌▐█ ▪▐▌██▐█▌ ▐█▌·▐█▄▄▌▐█•█▌██▐█▌   ",
                r".▀▀▀  ▀  ▀ ▀▀ █▪ ▀▀▀  ▀▀▀ .▀  ▀▀▀ █▪ ▀",
                r"     lightweight terminal chat  ",
            ]
            art3 = [
                r" _             _                    ",
                r"| | ___ ._ _ _| |_ ___  _ _ ._ _    ",
                r"| |<_> || ' | | | / ._>| '_>| ' | _ ",
                r"|_|<___||_|_| |_| \___.|_|  |_|_|<_>",
                r"       lightweight terminal chat      ",
            ]
            art4 = [
                r"  __             __                       ",
                r" |  .---.-.-----|  |_.-----.----.-----.   ",
                r" |  |  _  |     |   _|  -__|   _|     |__ ",
                r" |__|___._|__|__|____|_____|__| |__|__|__|",
                r"       lightweight terminal chat           ",
            ]
            art5 = [
                r"    __            __                 ",
                r"   / /___ _____  / /____  _________  ",
                r"  / / __ `/ __ \/ __/ _ \/ ___/ __ \ ",
                r" / / /_/ / / / / /_/  __/ /  / / / / ",
                r"/_/\__,_/_/ /_/\__/\___/_/  /_/ /_(_)",
                r"      lightweight terminal chat",
            ]
            art = random.choice([art1, art2, art3, art4, art5])
            art_lines = len(art)
            body = [
                "Commands:",
                "  /exit      Quit chat",
                "  /logout    Log out (next run: login again)",
                "  /channel   Back to main channel",
                "  /dm <user> Open DM with user",
                "  /panel     List users, pick one to DM",
                "  /fetch     Send system info (30s cooldown)",
                "  /dnd       Do not disturb (toggle notifications)",
                "",
                "Keybinds:",
                "  Ctrl+H     Help menu",
                "  Ctrl+/     Show keybinds",
                "  Ctrl+F     Fetch system info",
                "  Ctrl+C     Switch to channel view",
                "  Ctrl+P     Open user panel",
                "  Ctrl+D     Toggle DND",
                "  Ctrl+L     Logout",
                "  Ctrl+W     Exit (with confirm)",
                "  Esc Esc    Exit (immediate)",
                "",
                "Press any key to close",
            ]
            lines = art + body
        else:
            art_lines = 0
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
        try:
            title_attr = curses.color_pair(2) | curses.A_BOLD
            accent_attr = curses.color_pair(4) | curses.A_BOLD
            cmd_attr = curses.color_pair(4) | curses.A_BOLD
        except curses.error:
            title_attr = curses.A_BOLD
            accent_attr = curses.A_BOLD
            cmd_attr = curses.A_BOLD
        for i, line in enumerate(lines, 1):
            if art_lines and i <= art_lines:
                # Color the ASCII art header
                attr = title_attr
            elif art_lines and i == art_lines + 2:
                # "Commands:" header
                attr = accent_attr
            elif art_lines and i == art_lines + 2 + 10:
                # "Keybinds:" header (after ~10 body lines)
                attr = accent_attr
            elif line.startswith("  /") or line.startswith("  Ctrl"):
                # Highlight the command/key token in pastel purple
                try:
                    if line.startswith("  /") or line.startswith("  Ctrl"):
                        prefix = "  "
                        rest_line = line[2:]
                    else:
                        prefix = ""
                        rest_line = line
                    key, rest = rest_line.split(" ", 1)
                    win.addstr(i, 2, prefix)
                    win.addstr(i, 2 + len(prefix), key, cmd_attr)
                    win.addstr(i, 2 + len(prefix) + len(key) + 1, rest)
                    continue
                except ValueError:
                    attr = curses.A_NORMAL
            else:
                attr = curses.A_NORMAL
            win.addstr(i, 2, line[: win_w - 4], attr)
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
            "ctrl+h   Help menu",
            "ctrl+/   Show keybinds",
            "ctrl+f   Fetch system info",
            "ctrl+p   Open user panel (DM picker)",
            "ctrl+d   Toggle Do Not Disturb",
            "ctrl+l   Logout",
            "ctrl+w   Exit (with confirm)",
            "Esc x2   Exit (immediate)",
            "Press any key to close",
        ]
        win_h = len(lines) + 2
        win_w = max(len(l) for l in lines) + 4
        y = (h - win_h) // 2
        x = (w - win_w) // 2
        win = curses.newwin(win_h, win_w, y, x)
        win.border()
        try:
            header_attr = curses.color_pair(2) | curses.A_BOLD
            key_attr = curses.color_pair(4) | curses.A_BOLD
        except curses.error:
            header_attr = curses.A_BOLD
            key_attr = curses.A_BOLD
        for i, line in enumerate(lines, 1):
            if i == 1:
                attr = header_attr
            else:
                # highlight the "ctrl+X" part if present
                try:
                    key, rest = line.split(" ", 1)
                    win.addstr(i, 2, key, key_attr)
                    win.addstr(i, 2 + len(key) + 1, rest)
                    continue
                except ValueError:
                    attr = curses.A_NORMAL
            win.addstr(i, 2, line, attr)
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
        # filter out current user from the list
        ul = [u for u in ul if u[0] != self.config.USERNAME]
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
            header_attr = curses.color_pair(2) | curses.A_BOLD
            win.addstr(0, 3, " Select user to DM ", header_attr)
        except curses.error:
            pass
        # Column headers
        try:
            win.addstr(1, 2, "User              Status   Last seen", curses.A_DIM)
        except curses.error:
            pass
        sel = 0
        while True:
            for i, (u, status, ts) in enumerate(ul[: win_h - 4]):
                try:
                    # [admin] tag for users with admin privileges
                    display_name = f"{u} [ADMIN]" if u in self.state.admins else u
                    ts_str = (
                        time.strftime("%m/%d %H:%M", time.localtime(ts)) if ts else "—"
                    )
                    line = f" {display_name[:16]:16} {status:8} {ts_str}"
                    is_selected = i == sel
                    if is_selected:
                        attr = curses.color_pair(1) | curses.A_REVERSE
                    elif status.lower().startswith("off"):
                        attr = curses.A_DIM
                    else:
                        attr = curses.A_NORMAL
                    win.addstr(i + 2, 2, line[: win_w - 4], attr)
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
        self.input_cursor = 0
        self.network.request_max_msg_len()

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
                if (
                    is_self
                    and self.config.USERNAME
                    and text.startswith(f"[{self.config.USERNAME}]: ")
                ):
                    display_text = text[len(f"[{self.config.USERNAME}]: ") :]
                elif (
                    is_self
                    and self.config.USERNAME
                    and text.startswith(f"[{self.config.USERNAME}] ")
                ):
                    display_text = text[len(f"[{self.config.USERNAME}] ") :]
                prefix = "[you] " if is_self and not is_system else ""
                for l in textwrap.wrap(prefix + display_text, chat_w) or [""]:
                    lines.append((l, is_self, text, is_system))

            total_lines = len(lines)
            scroll = (
                self.dm_scroll_offset
                if (view == "dm" and dm_target)
                else self.scroll_offset
            )
            max_scroll = max(0, total_lines - chat_h)
            scroll = min(scroll, max_scroll)
            if view == "dm" and dm_target:
                self.dm_scroll_offset = scroll
            else:
                self.scroll_offset = scroll

            start = max(0, total_lines - chat_h - scroll)
            end = total_lines - scroll
            visible_lines = lines[start:end]

            for i, (line, is_self, original_text, is_system) in enumerate(
                visible_lines
            ):
                if is_system:
                    stdscr.addstr(i, 0, line, curses.color_pair(4))
                elif is_self:
                    stdscr.addstr(i, 0, line, curses.color_pair(1))
                elif original_text.startswith("[") and original_text.endswith(
                    " joined]"
                ):
                    stdscr.addstr(i, 0, line, curses.color_pair(2) | curses.A_DIM)
                elif original_text.startswith("[") and original_text.endswith(" left]"):
                    stdscr.addstr(i, 0, line, curses.color_pair(3) | curses.A_DIM)
                else:
                    stdscr.addstr(i, 0, line)

            stdscr.vline(0, chat_w, "|", chat_h)
            for i, u in enumerate(user_snapshot[:chat_h]):
                stdscr.addstr(i, chat_w + 2, u[: user_w - 2])
            label = u 
            if u in sef.state.admins:
                label = f"{u} [ADMIN]"
            stdscr.addstr(i, chat_w + 2, label[: user_w - 2])

            INPUT_Y = h - 3
            SEP_Y = h - 2
            STATUS_Y = h - 1
            prompt = "> "
            # visible = self.input_buf[-(chat_w - len(prompt) - 1) :] - old code, here until i can test the new scrolling input buffer code

            max_input_width = max(1, chat_w - len(prompt) - 1)

            # Determine which slice of the input buffer to show so that the cursor is visible
            if len(self.input_buf) <= max_input_width:
                start_idx = 0
            else:
                if self.input_cursor <= max_input_width:
                    start_idx = 0
                else:
                    start_idx = self.input_cursor - max_input_width
            end_idx = start_idx + max_input_width
            visible = self.input_buf[start_idx:end_idx]

            stdscr.move(INPUT_Y, 0)
            stdscr.clrtoeol()
            stdscr.addstr(INPUT_Y, 0, f"{prompt}{visible}")

            # draw cursor
            rel_idx = self.input_cursor - start_idx
            cursor_x = len(prompt) + max(0, rel_idx)
            cursor_x = max(len(prompt), min(chat_w - 1, cursor_x))
            try:
                cursor_attr = curses.color_pair(4) | curses.A_BOLD
            except curses.error:
                cursor_attr = curses.A_BOLD
            try:
                stdscr.addstr(INPUT_Y, cursor_x, "|", cursor_attr)
            except curses.error:
                pass
            stdscr.hline(SEP_Y, 0, curses.ACS_HLINE, w)
            self.draw_status_bar(stdscr, h, w, y=STATUS_Y)
            stdscr.refresh()
            try:
                ch = stdscr.getch()
                if ch == -1:
                    time.sleep(0.02)
                    continue
                # ---- double escape to quit immediately ----
                if ch == 27:
                    ch2 = stdscr.getch()
                    if ch2 == 27:
                        self.command_handler.shutdown()
                    else:
                        continue

                # ---- keybinds ----
                # - ord('a') - caps lock fix

                # help menu for ctrl + h
                if ch in (8, 127) and curses.keyname(ch) == b"^H":
                    self.show_help(stdscr)
                    continue
                # ctrl + / for keybinds
                if ch in (31, ord("_")):
                    self.show_keybinds(stdscr)
                    continue
                # ctrl + w for exit with confirm
                if ch in (23, ord("w") - ord("a") + 1):
                    if self.confirm_exit(stdscr):
                        self.command_handler.shutdown()
                    continue
                # ctrl + f for fetch
                if ch in (6, ord("f") - ord("a") + 1):
                    if self.command_handler.handle_command("/fetch", stdscr):
                        continue
                # ctrl + p for panel
                if ch == (ord("p") - ord("a") + 1):
                    if self.command_handler.handle_command("/panel", stdscr):
                        continue
                # ctrl + d for dnd toggle
                if ch == (ord("d") - ord("a") + 1):
                    if self.command_handler.handle_command("/dnd", stdscr):
                        continue
                # ctrl + b to return to main channel
                if ch == (ord("b") - ord("a") + 1):
                    if self.command_handler.handle_command("/back", stdscr):
                        continue

                scroll_off = (
                    self.dm_scroll_offset
                    if (view == "dm" and dm_target)
                    else self.scroll_offset
                )
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
                    self.input_cursor = 0
                    msg = self.input_buf.strip()
                    self.input_buf = ""
                    if not msg:
                        continue
                    if self.command_handler.handle_command(msg, stdscr):
                        continue

                    msg = msg[: self.config.MAX_MESSAGE_LEN]

                    if view == "dm" and dm_target:
                        out = f"[{self.config.USERNAME}]: {msg}"
                        self.network.send_dm(dm_target, msg)
                        with self.state.lock:
                            no_response = (
                                time.time() - self.state.last_received_from_server
                                > self.config.SERVER_RESPONSE_TIMEOUT
                            )
                            if self.state.send_failed or no_response:
                                self.state.send_failed = False
                                self.state.append_dm(
                                    dm_target,
                                    "[system] Failed to send (connection error)",
                                    True,
                                )
                            else:
                                self.state.append_dm(dm_target, out, True)
                    else:
                        out = f"[{self.config.USERNAME}]: {msg}"
                        self.network.send_message(out)
                        with self.state.lock:
                            no_response = (
                                time.time() - self.state.last_received_from_server
                                > self.config.SERVER_RESPONSE_TIMEOUT
                            )
                            if self.state.send_failed or no_response:
                                self.state.send_failed = False
                                self.state.messages.append(
                                    ("[system] Failed to send (connection error)", True)
                                )
                            else:
                                self.state.messages.append((out, True))
                            self.state.messages[:] = self.state.messages[
                                -self.config.MAX_MESSAGES :
                            ]

                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    if self.input_cursor > 0:
                        self.input_buf = (
                            self.input_buf[: self.input_cursor - 1]
                            + self.input_buf[self.input_cursor :]
                        )
                        self.input_cursor -= 1
                elif ch == curses.KEY_DC:
                    if self.input_cursor < len(self.input_buf):
                        self.input_buf = (
                            self.input_buf[: self.input_cursor]
                            + self.input_buf[self.input_cursor + 1 :]
                        )
                elif ch == curses.KEY_LEFT:
                    if self.input_cursor > 0:
                        self.input_cursor -= 1
                elif ch == curses.KEY_RIGHT:
                    if self.input_cursor < len(self.input_buf):
                        self.input_cursor += 1
                elif ch in (curses.KEY_HOME,):
                    self.input_cursor = 0
                elif ch in (curses.KEY_END,):
                    self.input_cursor = len(self.input_buf)
                elif ch == (ord("a") - ord("a") + 1):  # Ctrl+A -> Home
                    self.input_cursor = 0
                elif ch == (ord("e") - ord("a") + 1):  # Ctrl+E -> End
                    self.input_cursor = len(self.input_buf)
                elif (
                    32 <= ch <= 126 and len(self.input_buf) < self.config.MAX_INPUT_LEN
                ):
                    ch_val = chr(ch)
                    self.input_buf = (
                        self.input_buf[: self.input_cursor]
                        + ch_val
                        + self.input_buf[self.input_cursor :]
                    )
                    self.input_cursor += 1
            except Exception:
                pass
