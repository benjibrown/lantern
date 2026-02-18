import json
import socket
import time
import threading
from rich import print

TIMEOUT = 15

class NetworkManager:
    def __init__(self, host, port, state):
        self.host = host
        self.port = port
        self.state = state
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, port))
        self.sock.setblocking(False)

    def broadcast(self, msg, exclude_addr=None):
        for addr in list(self.state.clients):
            if addr == exclude_addr:
                continue
            try:
                self.sock.sendto(msg.encode(), addr)
            except Exception:
                self.state.clients.pop(addr, None)

    def send_to_user(self, username: str, msg: str):
        for addr, info in list(self.state.clients.items()):
            if info.get("username") == username:
                try:
                    self.sock.sendto(msg.encode(), addr)
                except Exception:
                    self.state.clients.pop(addr, None)
                return True
        return False

    def send_user_list(self, target_addr=None):
        user_list = ";".join(info["username"] for info in self.state.clients.values())
        msg = f"[USERS]|{user_list}"
        if target_addr:
            try:
                self.sock.sendto(msg.encode(), target_addr)
            except Exception:
                pass
        else:
            self.broadcast(msg)

    # TODO - fix 
    def send_admin_list(self, target_addr=None):
        admins = ";".join(sorted(self.state.admins))
        msg = f"[ADMINS]|{admins}"
        if target_addr:
            try:
                self.sock.sendto(msg.encode(), target_addr)
            except Exception:
                pass
        else:
            self.broadcast(msg)


    def send_max_message_len(self, target_addr):
        msg = f"[MAX_MSG_LEN]|{self.state.MAX_MSG_LEN}"
        try:
            self.sock.sendto(msg.encode(), target_addr)
        except Exception:
            pass

    def send_user_list_detailed(self, target_addr, requesting_username: str):
        online = set(info["username"] for info in self.state.clients.values())
        last_dm = self.state.get_last_dm_time_for_user(requesting_username)
        all_users = set(online)
        for u in last_dm:
            all_users.add(u)
        entries = []
        for u in sorted(all_users):

            if self.state.is_banned(u):
                continue 
            status = "online" if u in online else "offline"
            ts = last_dm.get(u, 0)
            entries.append(f"{u},{status},{ts}")
        msg = f"[USERS_DETAILED]|{';'.join(entries)}"
        try:
            self.sock.sendto(msg.encode(), target_addr)
        except Exception:
            pass

    def handle_ping(self, addr):
        self.sock.sendto(b"[ping]", addr)
        if addr in self.state.clients:
            self.state.clients[addr]["last_seen"] = time.time()

    def handle_register(self, msg, addr):
        parts = msg.split("|", 2)
        if len(parts) < 3:
            try:
                self.sock.sendto("[REGISTER_FAIL]|Invalid format".encode(), addr)
            except Exception:
                pass
            return
        _, username, password = parts
        username = username.strip()
        if not username:
            try:
                self.sock.sendto("[REGISTER_FAIL]|Username required".encode(), addr)
            except Exception:
                pass
            return
        if self.state.user_exists(username):
            try:
                self.sock.sendto("[REGISTER_FAIL]|Username taken".encode(), addr)
            except Exception:
                pass
            return


        if self.state.register_user(username, password):
            try:
                self.sock.sendto("[REGISTER_OK]".encode(), addr)
            except Exception:
                pass
            print(f"[green][+][/green] New user registered: {username}")
        else:
            try:
                self.sock.sendto("[REGISTER_FAIL]|Registration failed".encode(), addr)
            except Exception:
                pass

    def handle_login(self, msg, addr):
        parts = msg.split("|", 2)
        if len(parts) < 3:
            try:
                self.sock.sendto("[AUTH_FAIL]|Invalid format".encode(), addr)
            except Exception:
                pass
            return
        _, username, password = parts
        username = username.strip()
        if not username:
            try:
                self.sock.sendto("[AUTH_FAIL]|Username required".encode(), addr)
            except Exception:
                pass
            return

        if self.state.is_banned(username):
            try:
                self.sock.sendto("[AUTH_FAIL]|You are banned".encode(), addr)
            except Exception:
                pass
            return

        if not self.state.validate_user(username, password):
            try:
                self.sock.sendto("[AUTH_FAIL]|Bad username or password".encode(), addr)
            except Exception:
                pass
            return
        # issue token 
        token = self.state.create_session(username)
        self.state.set_pending_auth(addr, username)

        try:
            self.sock.sendto(f"[AUTH_OK]|{token}".encode(), addr)
            print(token)
        except Exception:
            pass
        print(f"[cyan][~][/cyan] User authenticated: {username} from {addr}")

    def handle_join(self, msg, addr):
        parts = msg.split("|", 1)
        if len(parts) < 2:
            return
        _, username = parts
        username = username.strip()
        pending = self.state.pop_pending_auth(addr)
        if pending != username:
            try:
                self.sock.sendto("[AUTH_FAIL]|Please login first".encode(), addr)
            except Exception:
                pass
            return
        now = time.time()
        self.state.clients[addr] = {"username": username, "last_seen": now}
        print(f"[green][+][/green] {username} joined from {addr}")
        self.broadcast(f"[{username} joined]", exclude_addr=addr)
        self.send_user_list()
        self.send_user_list(addr)
        self.send_admin_list(addr)
        history = self.state.get_channel_history()
        payload = json.dumps(history)
        chunk_size = 4000
        for i in range(0, len(payload), chunk_size):
            chunk = payload[i : i + chunk_size]
            try:
                self.sock.sendto(f"[CHANNEL_HISTORY]|{i // chunk_size}|{chunk}".encode(), addr)
            except Exception:
                pass
        try:
            self.sock.sendto("[CHANNEL_HISTORY_END]".encode(), addr)
        except Exception:
            pass

    def handle_leave(self, msg, addr):
        username = self.state.clients.get(addr, {}).get("username", "unknown")
        self.state.clients.pop(addr, None)
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
        # block muted users from sending to the main channel
        if self.state.is_muted(sender):
            try:
                self.sock.sendto(
                    "[ADMIN_ERROR]|You are muted and cannot send to the main channel".encode(),
                    addr,
                )
            except Exception:
                pass
            return
        print(f"[purple][>][/purple] {sender}: {msg}")
        self.state.add_channel_message(sender, msg)
        self.broadcast(msg, exclude_addr=addr)

    def handle_dm(self, msg, addr):
        sender_info = self.state.clients.get(addr, {})
        sender = sender_info.get("username")
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
            try:
                self.sock.sendto(f"[DM_FAIL]|User {recipient} not found".encode(), addr)
            except Exception:
                pass
            return
        self.state.add_dm(sender, recipient, text)
        ts = int(time.time())
        payload = f"[DM]|{sender}|{ts}|{text}"
        self.send_to_user(recipient, payload)
        try:
            self.sock.sendto(payload.encode(), addr)
        except Exception:
            pass

    def handle_req_dm_history(self, msg, addr):
        sender = self.state.clients.get(addr, {}).get("username")
        if not sender:
            return
        parts = msg.split("|", 1)
        other = parts[1].strip() if len(parts) > 1 else None
        if not other:
            return
        history = self.state.get_dm_history(sender, other)
        payload = json.dumps(history)
        try:
            self.sock.sendto(f"[DM_HISTORY]|{other}|{payload}".encode(), addr)
        except Exception:
            pass


    def handle_admin_cmd(self, msg, addr):
        # expected format: [ADMIN_CMD]|<command>|<actor>|<token>|<args...>
        parts = msg.split("|", 4)
        if len(parts) < 4:
            try:
                self.sock.sendto("[ADMIN_ERROR]|Invalid admin command format".encode(), addr)
            except Exception:
                pass
            return

        _, command, actor, token = parts[:4]
        rest = parts[4] if len(parts) > 4 else ""
        actor = actor.strip()

        current = self.state.clients.get(addr, {})
        if current.get("username") != actor:
            try:
                self.sock.sendto("[ADMIN_ERROR]|Actor mismatch for this connection".encode(), addr)
            except Exception:
                pass
            return

        expected_token = self.state.get_session_token(actor)
        if not expected_token or token != expected_token:
            try:
                self.sock.sendto("[ADMIN_ERROR]|Invalid or missing session token".encode(), addr)
            except Exception:
                pass
            return

        if not self.state.is_admin(actor):
            try:
                self.sock.sendto("[ADMIN_ERROR]|You are not an admin on this server".encode(), addr)
            except Exception:
                pass
            return

        command = command.lower().strip()

        if command in ("mute", "unmute", "ban"):
            target = (rest or "").strip()
            if not target:
                try:
                    self.sock.sendto(f"[ADMIN_ERROR]|/{command} requires a target username".encode(), addr)
                except Exception:
                    pass
                return
            if not self.state.user_exists(target):
                try:
                    self.sock.sendto(f"[ADMIN_ERROR]|User '{target}' not found".encode(), addr)
                except Exception:
                    pass
                return

            if command == "mute":
                self.state.set_muted(target, True)
                info = f"[system] {actor} muted {target}"
            elif command == "unmute":
                self.state.set_muted(target, False)
                info = f"[system] {actor} unmuted {target}"
            else:  # ban
                self.state.set_banned(target, True)
                # drop any active connections for the banned user
                kicked_addrs = []
                for a, info_dict in list(self.state.clients.items()):
                    if info_dict.get("username") == target:
                        kicked_addrs.append(a)
                for a in kicked_addrs:
                    try:
                        #dedicated banned message so clients can immediately exit
                        self.sock.sendto(
                            "[BANNED]|You have been banned from this server".encode(),
                            a,
                        )
                    except Exception:
                        pass
                    # reuse leave semantics
                    self.handle_leave(f"[LEAVE]|{target}", a)
                info = f"[system] {actor} banned {target}"

            try:
                self.sock.sendto("[ADMIN_OK]|Command applied".encode(), addr)
            except Exception:
                pass
            # announce to channel
            self.broadcast(info)
            self.state.add_channel_message("system", info)
            return

        if command == "changeuser":
            # rest: "<target>|<new_name>"
            if "|" not in rest:
                try:
                    self.sock.sendto(
                        "[ADMIN_ERROR]|/changeuser requires 'old_name|new_name'".encode(),
                        addr,
                    )
                except Exception:
                    pass
                return
            old_name, new_name = [p.strip() for p in rest.split("|", 1)]
            if not old_name or not new_name:
                try:
                    self.sock.sendto(
                        "[ADMIN_ERROR]|Both old and new usernames are required".encode(),
                        addr,
                    )
                except Exception:
                    pass
                return
            if not self.state.user_exists(old_name):
                try:
                    self.sock.sendto(f"[ADMIN_ERROR]|User '{old_name}' not found".encode(), addr)
                except Exception:
                    pass
                return
            if self.state.user_exists(new_name):
                try:
                    self.sock.sendto(f"[ADMIN_ERROR]|Username '{new_name}' is already taken".encode(), addr)
                except Exception:
                    pass
                return
            if not self.state.rename_user(old_name, new_name):
                try:
                    self.sock.sendto(
                        "[ADMIN_ERROR]|Failed to rename user (validation or storage error)".encode(),
                        addr,
                    )
                except Exception:
                    pass
                return

            info = f"[system] {actor} renamed user {old_name} to {new_name}"
            try:
                self.sock.sendto("[ADMIN_OK]|Username changed".encode(), addr)
            except Exception:
                pass
            #update any active client records using the old username

            for a, info_dict in list(self.state.clients.items()):
                if info_dict.get("username") == old_name:
                    info_dict["username"] = new_name

            self.broadcast(info)
            self.state.add_channel_message("system", info)
            # refresh admin list for all, in case an admin was renamed
            self.send_admin_list()
            # refresh user list so panels don't show the old name
            self.send_user_list()
            return

        try:
            self.sock.sendto(f"[ADMIN_ERROR]|Unknown admin command '{command}'".encode(), addr)
        except Exception:
            pass


    def cleanup_loop(self):
        while True:
            time.sleep(5)
            now = time.time()
            to_remove = []
            for addr, info in list(self.state.clients.items()):
                if now - info["last_seen"] > TIMEOUT:
                    to_remove.append((addr, info["username"]))
            for addr, username in to_remove:
                print(f"[yellow][TIMEOUT][/yellow] {username} removed")
                self.state.clients.pop(addr, None)
                self.broadcast(f"[{username} left]")
                self.send_user_list()

    def run(self):
        print(f"[blue][*][/blue] UDP server listening on {self.host}:{self.port}")
        threading.Thread(target=self.cleanup_loop, daemon=True).start()
        while True:
            try:
                try:
                    data, addr = self.sock.recvfrom(4096)
                except BlockingIOError:
                    continue
                msg = data.decode(errors="ignore").strip()
                now = time.time()

                if addr in self.state.clients:
                    self.state.clients[addr]["last_seen"] = now

                if msg == "[ping]":
                    self.handle_ping(addr)
                    continue

                if msg.startswith("[REQ_MAX_MSG_LEN]"):
                    self.send_max_message_len(addr)
                    continue

                if msg.startswith("[REGISTER]|"):
                    self.handle_register(msg, addr)
                    continue

                if msg.startswith("[LOGIN]|"):
                    self.handle_login(msg, addr)
                    continue

                if msg.startswith("[JOIN]|"):
                    self.handle_join(msg, addr)
                    continue

                if msg.startswith("[LEAVE]|"):
                    self.handle_leave(msg, addr)
                    continue


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

                if msg.startswith("["):
                    self.handle_message(msg, addr)
                else:
                    self.handle_message(msg, addr)

            except Exception as e:
                print("[red][ERROR][/red]", e)
