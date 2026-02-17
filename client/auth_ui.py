import curses
import socket
import time
import json
import hashlib
import secrets


def _send_recv(host: str, port: int, msg: str, timeout=5.0):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(msg.encode(), (host, port))
        data, _ = sock.recvfrom(4096)
        return data.decode(errors="ignore").strip()
    finally:
        sock.close()

def run_auth_ui(stdscr, config):
    # the login/reigster form - this took way too long lol
    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(10, curses.COLOR_CYAN, -1)
    curses.init_pair(11, curses.COLOR_GREEN, -1)
    curses.init_pair(12, curses.COLOR_RED, -1)
    curses.init_pair(13, curses.COLOR_YELLOW, -1)

    h, w = stdscr.getmaxyx()
    is_register = False
    username = (config.USERNAME or "").strip()
    password = ""
    error = ""
    focus = 0  # 0=username, 1=password, 2=submit, 3=switch mode
    cursor_pos = 0

    def draw_box(win, title, y, x, box_h, box_w):
        win.border()
        win.addstr(0, 2, f" {title} ", curses.A_BOLD)
        win.refresh()

    def draw():
        stdscr.erase()
        th, tw = stdscr.getmaxyx()
        title = "  Lantern  "
        try:
            stdscr.addstr(0, max(0, (tw - len(title)) // 2), title, curses.color_pair(10) | curses.A_BOLD)
        except curses.error:
            pass

        tag = "Sign in to your account"
        if is_register:
            tag = "Create a new account"
        try:
            stdscr.addstr(2, max(0, (tw - len(tag)) // 2), tag, curses.A_DIM)
        except curses.error:
            pass

        box_w = 44
        box_h = 12
        y0 = max(2, (th - box_h) // 2 - 1)
        x0 = max(0, (tw - box_w) // 2)

        win = stdscr.subwin(box_h, box_w, y0, x0)
        win.erase()
        win.border()
        mode_title = " Register " if is_register else " Login "
        try:
            win.addstr(0, 2, mode_title, curses.color_pair(10) | curses.A_BOLD)
        except curses.error:
            pass

        row = 2
        win.addstr(row, 2, "Username:", curses.A_DIM)
        row += 1
        un_display = (username[: box_w - 6] if len(username) <= box_w - 6 else "..." + username[-(box_w - 9) :]).ljust(box_w - 6)
        un_display = un_display[: box_w - 4]
        try:
            if focus == 0:
                for i, c in enumerate(un_display):
                    attr = (curses.color_pair(11) | curses.A_REVERSE) if i == cursor_pos else curses.color_pair(11)
                    win.addstr(row, 2 + i, c, attr)
            else:
                win.addstr(row, 2, un_display, curses.A_NORMAL)
        except curses.error:
            pass
        row += 2

        win.addstr(row, 2, "Password:", curses.A_DIM)
        row += 1
        pw_display = "*" * len(password)
        pw_display = (pw_display[: box_w - 6] if len(pw_display) <= box_w - 6 else "*" * (box_w - 6)).ljust(box_w - 6)
        try:
            if focus == 1:
                for i, c in enumerate(pw_display[: box_w - 4]):
                    attr = (curses.color_pair(11) | curses.A_REVERSE) if i == len(password) else curses.color_pair(11)
                    win.addstr(row, 2 + i, c, attr)
            else:
                win.addstr(row, 2, pw_display[: box_w - 4], curses.color_pair(11) if focus == 1 else curses.A_NORMAL)
        except curses.error:
            pass
        row += 2

        submit_label = "  Register  " if is_register else "  Login  "
        try:
            win.addstr(row, (box_w - len(submit_label)) // 2, submit_label, curses.color_pair(10) | (curses.A_REVERSE if focus == 2 else curses.A_NORMAL))
        except curses.error:
            pass
        row += 1

        switch_label = "Already have an account? Login" if is_register else "Need an account? Register"
        try:
            win.addstr(row, max(0, (box_w - len(switch_label)) // 2), switch_label[: box_w - 2], curses.color_pair(13) if focus == 3 else curses.A_DIM)
        except curses.error:
            pass

        if error:
            try:
                stdscr.addstr(min(th - 2, y0 + box_h + 1), max(0, (tw - len(error)) // 2), error[: tw - 2], curses.color_pair(12))
            except curses.error:
                pass

        stdscr.refresh()

    while True:
        draw()

        ch = stdscr.getch()
        if ch == -1:
            continue

        if ch in (27, ord("q")) and focus != 0 and focus != 1:
            if focus == 2 or focus == 3:
                return None
            focus = 3
            continue
        if ch == 27:
            return None

        if ch in (curses.KEY_UP, curses.KEY_DOWN, 9):
            if ch == curses.KEY_UP or (ch == 9 and focus > 0):
                focus = (focus - 1) % 4
            else:
                focus = (focus + 1) % 4
            error = ""
            continue

        if ch in (10, 13):
            if focus == 2:
                username = username.strip()
                if not username:
                    error = "Username required"
                    continue
                if not password:
                    error = "Password required"
                    continue
                try:
                    if is_register:
                        out = _send_recv(config.SERVER_HOST, config.SERVER_PORT, f"[REGISTER]|{username}|{password}")
                        if out == "[REGISTER_OK]":
                            config.save_session(username, password)
                            return (username, password)
                        if out.startswith("[REGISTER_FAIL]|"):
                            error = out.split("|", 1)[1][:60]
                        else:
                            error = "Registration failed (server unreachable?)"
                    else:
                        out = _send_recv(config.SERVER_HOST, config.SERVER_PORT, f"[LOGIN]|{username}|{password}")
                        if out == "[AUTH_OK]":
                            config.save_session(username, password)
                            return (username, password)
                        if out.startswith("[AUTH_FAIL]|"):
                            error = out.split("|", 1)[1][:60]
                        else:
                            error = "Login failed (server unreachable?)"
                except (socket.timeout, OSError):
                    error = "Connection failed: cannot reach server"
                continue
            if focus == 3:
                is_register = not is_register
                error = ""
                continue
            if focus == 0:
                focus = 1
                continue
            if focus == 1:
                focus = 2
                continue

        if focus == 0:
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                if cursor_pos > 0:
                    username = username[: cursor_pos - 1] + username[cursor_pos :]
                    cursor_pos -= 1
            elif ch == curses.KEY_LEFT and cursor_pos > 0:
                cursor_pos -= 1
            elif ch == curses.KEY_RIGHT and cursor_pos < len(username):
                cursor_pos += 1
            elif 32 <= ch <= 126 and len(username) < 64:
                username = username[:cursor_pos] + chr(ch) + username[cursor_pos:]
                cursor_pos += 1
        elif focus == 1:
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                password = password[:-1]
            elif 32 <= ch <= 126 and len(password) < 128:
                password += chr(ch)
        error = ""
            # TODO - add option to show/hide password input - only visible during key press then masked after short delay - if ur reading this lmk if this is worth my time 
