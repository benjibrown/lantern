import json 
import socket
import time
import threading
from rich import print
from frame import send_msg, recv_msg

# i should add more comments to this code ig

TIMEOUT = 15
# set of banned characters - only _ and - are allowed as special characters, no spaces allowed 
# this is checked server side and client side so users cannot just modify client code to bypass
BANNED_CHARS = set(" !\"#$%&'()*+,./:;<=>?@[\\]^`{|}~<>")


class NetworkManager:
    def __init__(self, host, port, state):
        self.host = host
        self.port = port
        self.state = state
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.listen(50)

    def _send(self, addr, msg: str):
        # send to a specific connected client by addr key
        client = self.state.clients.get(addr)
        if client:
            try:
                send_msg(client["conn"], msg)
            except Exception:
                self.state.clients.pop(addr, None)

    def _send_conn(self, conn: socket.socket, msg: str):
        # send directly to a connection before it's been added to clients (e.g. during auth)
        try:
            send_msg(conn, msg)
        except Exception:
            pass

    def broadcast(self, msg, exclude_addr=None):
        for addr, info in list(self.state.clients.items()):
            if addr == exclude_addr:
                continue
            try:
                send_msg(info["conn"], msg)
            except Exception:
                self.state.clients.pop(addr, None)

    def send_to_user(self, username: str, msg: str) -> bool:
        for addr, info in list(self.state.clients.items()):
            if info.get("username") == username:
                try:
                    send_msg(info["conn"], msg)
                except Exception:
                    self.state.clients.pop(addr, None)
                return True
        return False

    def send_user_list(self, target_addr=None):
        user_list = ";".join(info["username"] for info in self.state.clients.values())
        msg = f"[USERS]|{user_list}"
        if target_addr:
            self._send(target_addr, msg)
        else:
            self.broadcast(msg)

    def send_admin_list(self, target_addr=None):
        admins = ";".join(sorted(self.state.admins))
        msg = f"[ADMINS]|{admins}"
        if target_addr:
            self._send(target_addr, msg)
        else:
            self.broadcast(msg)

    def send_max_message_len(self, addr):
        self._send(addr, f"[MAX_MSG_LEN]|{self.state.MAX_MSG_LEN}")

    def send_user_stats(self, addr, username: str):
        stats = self.state.get_user_stats(username)
        if not stats:
            return
        self._send(addr, f"[USER_STATS]|{json.dumps(stats)}")

    def send_user_list_detailed(self, addr, requesting_username: str):
        online = set(info["username"] for info in self.state.clients.values())
        last_dm = self.state.get_last_dm_time_for_user(requesting_username)
        all_users = set(online) | set(last_dm)
        entries = []
        for u in sorted(all_users):
            if self.state.is_banned(u):
                continue
            status = "online" if u in online else "offline"
            ts = last_dm.get(u, 0)
            entries.append(f"{u},{status},{ts}")
        self._send(addr, f"[USERS_DETAILED]|{';'.join(entries)}")

    def handle_ping(self, addr):
        self._send(addr, "[ping]")
        if addr in self.state.clients:
            self.state.clients[addr]["last_seen"] = time.time()

    def handle_register(self, msg, addr, conn):
        parts = msg.split("|", 2)
        if len(parts) < 3:
            self._send_conn(conn, "[REGISTER_FAIL]|Invalid format")
            return
        _, username, password = parts
        username = username.strip()
        if not username:
            self._send_conn(conn, "[REGISTER_FAIL]|Username required")
            return
        if self.state.user_exists(username):
            self._send_conn(conn, "[REGISTER_FAIL]|Username taken")
            return
        if any(c in BANNED_CHARS for c in username):
            self._send_conn(conn, "[REGISTER_FAIL]|Username contains illegal characters")
            return
        if len(username) > 16:
            self._send_conn(conn, "[REGISTER_FAIL]|Username too long (max 16 characters)")
            return

        if self.state.register_user(username, password):
            self._send_conn(conn, "[REGISTER_OK]")
            print(f"[green][+][/green] New user registered: {username}")
        else:
            self._send_conn(conn, "[REGISTER_FAIL]|Registration failed")

    def handle_login(self, msg, addr, conn):
        parts = msg.split("|", 2)
        if len(parts) < 3:
            self._send_conn(conn, "[AUTH_FAIL]|Invalid format")
            return
        _, username, password = parts
        username = username.strip()
        if not username:
            self._send_conn(conn, "[AUTH_FAIL]|Username required")
            return
        if self.state.is_banned(username):
            reason = self.state.get_ban_reason(username)
            out = f"You are banned: {reason}" if reason else "You are banned from this server"
            self._send_conn(conn, f"[AUTH_FAIL]|{out}")
            return
        if not self.state.validate_user(username, password):
            self._send_conn(conn, "[AUTH_FAIL]|Bad username or password")
            return
        # i love tokens 
        token = self.state.create_session(username)
        self.state.set_pending_auth(addr, username)
        self._send_conn(conn, f"[AUTH_OK]|{token}")
        print(f"[cyan][~][/cyan] User authenticated: {username} from {addr}")

    def handle_join(self, msg, addr, conn):
        parts = msg.split("|", 1)
        if len(parts) < 2:
            return
        _, username = parts
        username = username.strip()
        pending = self.state.pop_pending_auth(addr)
        if pending != username:
            self._send_conn(conn, "[AUTH_FAIL]|Please login first")
            return
        now = time.time()
        self.state.clients[addr] = {"username": username, "last_seen": now, "conn": conn}
        print(f"[green][+][/green] {username} joined from {addr}")
        self.broadcast(f"[{username} joined]", exclude_addr=addr)
        self.send_user_list()
        self.send_user_list(addr)
        self.send_admin_list(addr)
        # send recent channel history so new joiners have some context
        # with TCP this is a single reliable stream so chunking is just for protocol consistency
        history = self.state.get_channel_history()
        payload = json.dumps(history)
        chunk_size = 4000
        for i in range(0, max(1, len(payload)), chunk_size):
            chunk = payload[i : i + chunk_size]
            self._send(addr, f"[CHANNEL_HISTORY]|{i // chunk_size}|{chunk}")
        self._send(addr, "[CHANNEL_HISTORY_END]")

    def handle_leave(self, addr):
        info = self.state.clients.pop(addr, {})
        username = info.get("username", "unknown")
        conn = info.get("conn")
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        print(f"[red][-][/red] {username} left")
        self.broadcast(f"[{username} left]")
        self.send_user_list()

    def handle_req_users(self, addr):
        self.send_user_list(addr)

    def handle_req_users_detailed(self, msg, addr):
        parts = msg.split("|", 1)
        username = parts[1].strip() if len(parts) > 1 else None
        if not username:
            username = self.state.clients.get(addr, {}).get("username", "")
        self.send_user_list_detailed(addr, username)

    def handle_message(self, msg, addr):
        client_info = self.state.clients.get(addr)
        if not client_info:
            return
        sender = client_info.get("username", str(addr))
        if self.state.is_muted(sender):
            self._send(addr, "[ADMIN_ERROR]|You are muted and cannot send to the main channel")
            return
        print(f"[purple][>][/purple] {sender} {msg}")
        self.state.add_channel_message(sender, msg)
        self.broadcast(msg, exclude_addr=addr)

    def handle_dm(self, msg, addr):
        sender = self.state.clients.get(addr, {}).get("username")
        if not sender:
            return
        parts = msg.split("|", 2)
        if len(parts) < 3:
            return
        _, recipient, text = parts
        recipient = recipient.strip()
        if not recipient or recipient == sender:
            return
        if not self.state.user_exists(recipient):
            self._send(addr, f"[DM_FAIL]|User {recipient} not found")
            return
        self.state.add_dm(sender, recipient, text)
        ts = int(time.time())
        payload = f"[DM]|{sender}|{ts}|{text}"
        self.send_to_user(recipient, payload)
        self._send(addr, payload)

    def handle_req_dm_history(self, msg, addr):
        sender = self.state.clients.get(addr, {}).get("username")
        if not sender:
            return
        parts = msg.split("|", 1)
        other = parts[1].strip() if len(parts) > 1 else None
        if not other:
            return
        history = self.state.get_dm_history(sender, other)
        self._send(addr, f"[DM_HISTORY]|{other}|{json.dumps(history)}")

    def handle_admin_cmd(self, msg, addr):
        parts = msg.split("|", 4)
        if len(parts) < 4:
            self._send(addr, "[ADMIN_ERROR]|Invalid admin command format")
            return

        _, command, actor, token = parts[:4]
        rest = parts[4] if len(parts) > 4 else ""
        actor = actor.strip()

        current = self.state.clients.get(addr, {})
        if current.get("username") != actor:
            self._send(addr, "[ADMIN_ERROR]|Actor mismatch for this connection")
            return

        expected_token = self.state.get_session_token(actor)
        if not expected_token or token != expected_token:
            self._send(addr, "[ADMIN_ERROR]|Invalid or missing session token")
            return

        if not self.state.is_admin(actor):
            self._send(addr, "[ADMIN_ERROR]|You are not an admin on this server")
            return

        command = command.lower().strip()

        if command in ("mute", "unmute", "ban", "unban"):
            raw = (rest or "").strip()
            target = raw 
            ban_reason = None 
            if command == "ban" and "|" in raw:
                t, r = raw.split("|", 1) 
                target = t.strip() 
                ban_reason = r.strip() or None
            if not target:
                self._send(addr, f"[ADMIN_ERROR]|/{command} requires a target username")
                return
            if not self.state.user_exists(target):
                self._send(addr, f"[ADMIN_ERROR]|User '{target}' not found")
                return

            if command == "mute":
                self.state.set_muted(target, True)
                info = f"[system] {actor} muted {target}"
            elif command == "unmute":
                self.state.set_muted(target, False)
                info = f"[system] {actor} unmuted {target}"
            elif command == "unban":
                if not self.state.is_banned(target):
                    self._send(addr, f"[ADMIN_ERROR]|User '{target}' is not banned")
                    return
                self.state.set_banned(target, False)
                info = f"[system] {actor} unbanned {target}"
            else:  # ban
                self.state.set_banned(target, True, reason=ban_reason)
                kicked_addrs = [a for a, d in list(self.state.clients.items()) if d.get("username") == target]
                # construct a stable ban message that includes the optional reason
                banned_text = ban_reason or self.state.get_ban_reason(target) or "None"
                for a in kicked_addrs:
                    self._send(a, f"[BANNED]|{banned_text}")
                    self.handle_leave(a)
                info = f"[system] {actor} banned {target}"

            self._send(addr, "[ADMIN_OK]|Command applied")
            # announce to channel
            self.broadcast(info)
            self.state.add_channel_message("system", info)
            return

        if command == "changeusername":
            # rest: "<old_name>|<new_name>"
            if "|" not in rest:
                self._send(addr, "[ADMIN_ERROR]|/changeusername requires 'old_name|new_name'")
                return
            old_name, new_name = [p.strip() for p in rest.split("|", 1)]
            if not old_name or not new_name:
                self._send(addr, "[ADMIN_ERROR]|Both old and new usernames are required")
                return
            if not self.state.user_exists(old_name):
                self._send(addr, f"[ADMIN_ERROR]|User '{old_name}' not found")
                return
            if self.state.user_exists(new_name):
                self._send(addr, f"[ADMIN_ERROR]|Username '{new_name}' is already taken")
                return
            if not self.state.rename_user(old_name, new_name):
                self._send(addr, "[ADMIN_ERROR]|Failed to rename user (validation or storage error)")
                return

            info = f"[system] {actor} renamed user {old_name} to {new_name}"
            self._send(addr, "[ADMIN_OK]|Username changed")
            for info_dict in self.state.clients.values():
                if info_dict.get("username") == old_name:
                    info_dict["username"] = new_name
            self.broadcast(info)
            self.state.add_channel_message("system", info)
            # refresh admin list for all, in case an admin was renamed
            self.send_admin_list()
            # refresh user list so panels don't show the old name
            self.send_user_list()
            return

        self._send(addr, f"[ADMIN_ERROR]|Unknown admin command '{command}'")

    def handle_req_fetch(self, addr):
        client_info = self.state.clients.get(addr)
        if not client_info:
            return 
        username = client_info.get("username")
        if not username:
            return 
        cooldown = self.state.fetch_cooldown 
        if cooldown > 0:
            now = time.time() 
            last = self.state.fetch_last.get(username, 0)
            remaining = cooldown - (now - last)
            if remaining > 0:
                self._send(addr, f"[FETCH_COOLDOWN]|{int(remaining)}")
                return
            self.state.fetch_last[username] = now
        self._send(addr, "[FETCH_OK]")

    def _handle_client(self, conn: socket.socket, addr):
        # per-client receive loop - each connection runs in its own thread
        try:
            while True:
                msg = recv_msg(conn)
                if msg is None:
                    break  # client disconnected cleanly

                if addr in self.state.clients:
                    self.state.clients[addr]["last_seen"] = time.time()

                if msg == "[ping]":
                    self.handle_ping(addr)
                    continue
                if msg.startswith("[REQ_USER_STATS]"):
                    parts = msg.split("|", 1)
                    username = parts[1].strip() if len(parts) > 1 else None
                    if not username:
                        username = self.state.clients.get(addr, {}).get("username")
                    if username:
                        self.send_user_stats(addr, username)
                    continue
                if msg.startswith("[REQ_MAX_MSG_LEN]"):
                    self.send_max_message_len(addr)
                    continue
                if msg.startswith("[REGISTER]|"):
                    self.handle_register(msg, addr, conn)
                    continue
                if msg.startswith("[LOGIN]|"):
                    self.handle_login(msg, addr, conn)
                    continue
                if msg.startswith("[JOIN]|"):
                    self.handle_join(msg, addr, conn)
                    continue
                if msg.startswith("[LEAVE]|"):
                    self.handle_leave(addr)
                    break
                if msg.startswith("[REQ_USERS]|"):
                    self.handle_req_users(addr)
                    continue
                if msg.startswith("[REQ_USERS_DETAILED]|"):
                    self.handle_req_users_detailed(msg, addr)
                    continue
                if msg.startswith("[DM]|"):
                    self.handle_dm(msg, addr)
                    continue
                if msg.startswith("[REQ_DM_HISTORY]|"):
                    self.handle_req_dm_history(msg, addr)
                    continue
                if msg.startswith("[ADMIN_CMD]|"):
                    self.handle_admin_cmd(msg, addr)
                    continue
                if msg.startswith("[REQ_FETCH]"):
                    self.handle_req_fetch(addr)
                    continue
                self.handle_message(msg, addr)

        except Exception as e:
            print(f"[red][ERROR][/red] client {addr}: {e}")
        finally:
            # clean up if not already removed (e.g. from ban or explicit leave)
            if addr in self.state.clients:
                self.handle_leave(addr)
            else:
                try:
                    conn.close()
                except Exception:
                    pass

    def cleanup_loop(self):
        while True:
            time.sleep(5)
            now = time.time()
            for addr, info in list(self.state.clients.items()):
                if now - info["last_seen"] > TIMEOUT:
                    print(f"[yellow][TIMEOUT][/yellow] {info['username']} removed")
                    self.handle_leave(addr)

    def run(self):
        print(f"[blue][*][/blue] TCP server listening on {self.host}:{self.port}")
        threading.Thread(target=self.cleanup_loop, daemon=True).start()
        while True:
            try:
                conn, addr = self.sock.accept()
                threading.Thread(target=self._handle_client, args=(conn, addr), daemon=True).start()
            except Exception as e:
                print(f"[red][ERROR][/red] accept: {e}")

