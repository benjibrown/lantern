import json
import time
import uuid
import base64
import threading

from rich import print
from lantern_chat.frame import send_msg


TIMEOUT = 60
# set of banned characters - only _ and - are allowed as special characters, no spaces allowed
# this is checked server side and client side so users cannot just modify client code to bypass
# its better to check if a username only contains allow chars rather than bad chars since there is way more banned chars than this yet only allow any letters, num, _ and -
ALLOWED_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


class HandlerRegistry:
    def __init__(self):
        self._handlers = []

    def register(self, trigger):
        def decorator(fn):
            self._handlers.append((trigger, fn))
            return fn
        return decorator

    def dispatch(self, msg, ctx, handler_instance):
        for trigger, fn in self._handlers:
            if msg.startswith(trigger):
                fn(handler_instance, msg, ctx)
                return True
        return None

    def get_handler_names(self):
        return [trigger for trigger, _ in self._handlers]


registry = HandlerRegistry()
register = registry.register


class HandlerMixin:
    # all the handler methods below

    def handlePing(self, addr):
        self.send(addr, "[ping]")
        if addr in self.state.clients:
            self.state.clients[addr]["last_seen"] = time.time()

    @register("[REGISTER]|")
    def handleRegister(self, msg, ctx):
        conn = ctx["conn"]
        parts = msg.split("|", 2)
        if len(parts) < 3:
            self.sendConn(conn, "[REGISTER_FAIL]|Invalid format")
            return
        _, username, password = parts
        username = username.strip()
        if not username:
            self.sendConn(conn, "[REGISTER_FAIL]|Username required")
            return
        if self.state.user_exists(username):
            self.sendConn(conn, "[REGISTER_FAIL]|Username taken")
            return
        if any(c not in ALLOWED_CHARS for c in username):
            self.sendConn(conn, "[REGISTER_FAIL]|Username may only contain letters, numbers, _ and -")
            return
        if username.lower() == "you":
            self.sendConn(conn, "[REGISTER_FAIL]|Username 'you' is not allowed")
            return
        if len(username) > 16:
            self.sendConn(conn, "[REGISTER_FAIL]|Username too long (max 16 characters)")
            return
        if self.state.register_user(username, password):
            self.sendConn(conn, "[REGISTER_OK]")
            print(f"[green][+][/green] New user registered: {username}")
        else:
            self.sendConn(conn, "[REGISTER_FAIL]|Registration failed")

    @register("[LOGIN]|")
    def handleLogin(self, msg, ctx):
        addr = ctx["addr"]
        conn = ctx["conn"]
        parts = msg.split("|", 2)
        if len(parts) < 3:
            self.sendConn(conn, "[AUTH_FAIL]|Invalid format")
            return

        # check rate limit first
        if self.state.isLoginRateLimited(addr[0]):
            self.sendConn(conn, "[AUTH_FAIL]|Too many failed login attempts. Try again later.") # no bruteforce pls
            return

        _, username, password = parts
        username = username.strip()
        if not username:
            self.sendConn(conn, "[AUTH_FAIL]|Username required")
            return
        if self.state.is_banned(username):
            reason = self.state.get_ban_reason(username)
            out = f"You are banned: {reason}" if reason else "You are banned from this server"
            self.sendConn(conn, f"[AUTH_FAIL]|{out}")
            return
        if not self.state.validate_user(username, password):
            lockoutSecs = self.state.recordFailedLogin(addr[0])
            lockoutMins = lockoutSecs // 60
            if lockoutSecs > 0:
                self.sendConn(conn, f"[AUTH_FAIL]|Bad username or password (account locked for {lockoutMins}mins)")
            else:
                self.sendConn(conn, "[AUTH_FAIL]|Bad username or password")
            return

        # successful login — clear rate limit
        self.state.clearLoginAttempts(addr[0])

        # i love tokens
        token = self.state.create_session(username)
        self.state.set_pending_auth(addr, username)
        self.sendConn(conn, f"[AUTH_OK]|{token}")
        print(f"[cyan][~][/cyan] User authenticated: {username} from {addr}")

    @register("[JOIN]|")
    def handleJoin(self, msg, ctx):
        addr = ctx["addr"]
        conn = ctx["conn"]
        parts = msg.split("|", 1)
        if len(parts) < 2:
            return True
        _, username = parts
        username = username.strip()
        pending = self.state.pop_pending_auth(addr)
        if pending != username:
            self.sendConn(conn, "[AUTH_FAIL]|Please login first")
            return True
        now = time.time()
        self.state.clients[addr] = {"username": username, "last_seen": now, "conn": conn}
        print(f"[green][+][/green] {username} joined from {addr}")
        self.broadcast(f"[{username} joined]", excludeAddr=addr)
        self.sendUserList()
        self.sendUserList(addr)
        self.sendAdminList(addr)

        # send unread message counts
        unreadCounts = self.state.getUnreadCounts(username)
        if unreadCounts:
            self.send(addr, f"[UNREAD]|{json.dumps(unreadCounts)}")

        # send recent channel history so new joiners have some context
        # with TCP this is a single reliable stream so chunking is just for protocol consistency
        history = self.state.get_channel_history()
        payload = json.dumps(history)
        chunkSize = 4000
        for i in range(0, max(1, len(payload)), chunkSize):
            chunk = payload[i : i + chunkSize]
            self.send(addr, f"[CHANNEL_HISTORY]|{i // chunkSize}|{chunk}")
        self.send(addr, "[CHANNEL_HISTORY_END]")
        return True

    @register("[LEAVE]|")
    def handleLeave(self, msg, ctx):
        if ctx is None:
            # Called from cleanup, msg is actually {"addr": ..., "conn": ...}
            info = msg
            addr = info["addr"]
        else:
            # Called from registry with proper ctx
            addr = ctx["addr"]
        
        info = self.state.clients.pop(addr, {})
        username = info.get("username", "unknown")
        conn = info.get("conn")
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        self.state.clear_session(username)
        print(f"[red][-][/red] {username} left")
        self.broadcast(f"[{username} left]")
        self.sendUserList()
        return True

    @register("[REQ_USERS]|")
    def handleReqUsers(self, msg, ctx):
        addr = ctx["addr"]
        self.sendUserList(addr)

    @register("[REQ_USERS_DETAILED]|")
    def handleReqUsersDetailed(self, msg, ctx):
        addr = ctx["addr"]
        parts = msg.split("|", 1)
        username = parts[1].strip() if len(parts) > 1 else None
        if not username:
            username = self.state.clients.get(addr, {}).get("username", "")
        self.sendUserListDetailed(addr, username)

    @register("[DM]|")
    def handleDm(self, msg, ctx):
        addr = ctx["addr"]
        senderInfo = self.state.clients.get(addr, {})
        sender = senderInfo.get("username")
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
            self.send(addr, f"[DM_FAIL]|User {recipient} not found")
            return
        now = time.time()
        last = senderInfo.get("last_msg", 0)
        if self.state.msg_rate_limit > 0 and (now - last) < self.state.msg_rate_limit:
            wait = round(self.state.msg_rate_limit - (now - last), 1)
            self.send(addr, f"[RATE_LIMITED]|{wait}")
            return
        senderInfo["last_msg"] = now
        self.state.add_dm(sender, recipient, text)
        ts = int(time.time())
        payload = f"[DM]|{sender}|{ts}|{text}"

        # always track unread (online or offline)
        self.state.addUnreadMessage(recipient, sender)

        self.sendToUser(recipient, payload)
        self.send(addr, payload)

    @register("[REQ_DM_HISTORY]|")
    def handleReqDmHistory(self, msg, ctx):
        addr = ctx["addr"]
        sender = self.state.clients.get(addr, {}).get("username")
        if not sender:
            return
        parts = msg.split("|", 1)
        other = parts[1].strip() if len(parts) > 1 else None
        if not other:
            return
        if not self.state.user_exists(other):
            self.send(addr, f"[DM_FAIL]|User '{other}' not found")
            return
        history = self.state.get_dm_history(sender, other)
        self.send(addr, f"[DM_HISTORY]|{other}|{json.dumps(history)}")

    @register("[CLEAR_UNREAD]|")
    def handleClearUnread(self, msg, ctx):
        # [CLEAR_UNREAD]|other_user
        addr = ctx["addr"]
        username = self.state.clients.get(addr, {}).get("username")
        if not username:
            return
        parts = msg.split("|", 1)
        other = parts[1].strip() if len(parts) > 1 else None
        if not other:
            return
        self.state.clearUnread(username, other)

    @register("[ADMIN_CMD]|")
    def handleAdminCmd(self, msg, ctx):
        addr = ctx["addr"]
        parts = msg.split("|", 4)
        if len(parts) < 4:
            self.send(addr, "[ADMIN_ERROR]|Invalid admin command format")
            return

        _, command, actor, token = parts[:4]
        rest = parts[4] if len(parts) > 4 else ""
        actor = actor.strip()

        current = self.state.clients.get(addr, {})
        if current.get("username") != actor:
            self.send(addr, "[ADMIN_ERROR]|Actor mismatch for this connection")
            return

        expectedToken = self.state.get_session_token(actor)
        if not expectedToken or token != expectedToken:
            self.send(addr, "[ADMIN_ERROR]|Invalid or missing session token")
            return

        if not self.state.is_admin(actor):
            self.send(addr, "[ADMIN_ERROR]|You are not an admin on this server")
            return

        command = command.lower().strip()

        if command in ("mute", "unmute", "ban", "unban"):
            raw = (rest or "").strip()
            target = raw
            banReason = None
            if command == "ban" and "|" in raw:
                t, r = raw.split("|", 1)
                target = t.strip()
                banReason = r.strip() or None
            if not target:
                self.send(addr, f"[ADMIN_ERROR]|/{command} requires a target username")
                return
            if not self.state.user_exists(target):
                self.send(addr, f"[ADMIN_ERROR]|User '{target}' not found")
                return
            if target == actor:
                self.send(addr, f"[ADMIN_ERROR]|You cannot {command} yourself")
                return


            if command == "mute":
                self.state.set_muted(target, True)
                info = f"[system] {actor} muted {target}"
            elif command == "unmute":
                self.state.set_muted(target, False)
                info = f"[system] {actor} unmuted {target}"
            elif command == "unban":
                if not self.state.is_banned(target):
                    self.send(addr, f"[ADMIN_ERROR]|User '{target}' is not banned")
                    return
                self.state.set_banned(target, False)
                info = f"[system] {actor} unbanned {target}"
            else:  # ban
                self.state.set_banned(target, True, reason=banReason)
                kickedAddrs = [a for a, d in list(self.state.clients.items()) if d.get("username") == target]
                # construct a stable ban message that includes the optional reason
                bannedText = banReason or self.state.get_ban_reason(target) or "None"
                for a in kickedAddrs:
                    self.send(a, f"[BANNED]|{bannedText}")
                    self.handleLeave({"addr": a, "conn": None}, None)
                info = f"[system] {actor} banned {target}"

            self.send(addr, "[ADMIN_OK]|Command applied")
            # announce to channel
            self.broadcast(info)
            self.state.add_channel_message("system", info)
            return

        if command == "rename":
            # rest: "<old_name>|<new_name>"
            if "|" not in rest:
                self.send(addr, "[ADMIN_ERROR]|/rename requires 'old_name|new_name'")
                return
            oldName, newName = [p.strip() for p in rest.split("|", 1)]
            if not oldName or not newName:
                self.send(addr, "[ADMIN_ERROR]|Both old and new usernames are required")
                return
            if len(newName) > 16:
                self.send(addr, "[ADMIN_ERROR]|New username too long (max 16 characters)")
                return
            if any(c not in ALLOWED_CHARS for c in newName):
                self.send(addr, "[ADMIN_ERROR]|New username may only contain letters, numbers, _ and -")
                return
            if not self.state.user_exists(oldName):
                self.send(addr, f"[ADMIN_ERROR]|User '{oldName}' not found")
                return
            if self.state.user_exists(newName):
                self.send(addr, f"[ADMIN_ERROR]|Username '{newName}' is already taken")
                return
            if newName.lower() == "you":
                self.send(addr, "[ADMIN_ERROR]|Username 'you' is not allowed")
                return
            if not self.state.rename_user(oldName, newName):
                self.send(addr, "[ADMIN_ERROR]|Failed to rename user (validation or storage error)")
                return

            info = f"[system] {actor} renamed user {oldName} to {newName}"
            self.send(addr, "[ADMIN_OK]|Username changed")
            for infoDict in self.state.clients.values():
                if infoDict.get("username") == oldName:
                    infoDict["username"] = newName
            self.broadcast(info)
            self.state.add_channel_message("system", info)
            # refresh admin list for all, in case an admin was renamed
            self.sendAdminList()
            # refresh user list so panels don't show the old name
            self.sendUserList()
            return
        # peak purge command
        if command == "purge":
            try:
                count = int(rest.strip())
                if count <= 0:
                    raise ValueError
            except (ValueError, AttributeError):
                self.send(addr, "[ADMIN_ERROR]|Usage: /purge <number>")
                return
            removed = self.state.purge_channel_messages(count)
            self.broadcast(f"[PURGE]|{removed}")
            info = f"[system] {actor} purged {removed} message(s)"
            self.state.add_channel_message("system", info)
            self.broadcast(info)
            self.send(addr, f"[ADMIN_OK]|Purged {removed} message(s)")
            return

        # reload server config
        if command == "reload":
            self.state.reload_config()
            info = f"[system] {actor} reloaded server config"
            self.state.add_channel_message("system", info)
            self.broadcast(info)
            self.send(addr, "[ADMIN_OK]|Config reloaded")
            return

        self.send(addr, f"[ADMIN_ERROR]|Unknown admin command '{command}'")

    @register("[REQ_FETCH]")
    def handleReqFetch(self, msg, ctx):
        addr = ctx["addr"]
        clientInfo = self.state.clients.get(addr)
        if not clientInfo:
            return
        username = clientInfo.get("username")
        if not username:
            return
        cooldown = self.state.fetch_cooldown
        if cooldown > 0:
            now = time.time()
            last = self.state.fetch_last.get(username, 0)
            remaining = cooldown - (now - last)
            if remaining > 0:
                self.send(addr, f"[FETCH_COOLDOWN]|{int(remaining)}")
                return
            self.state.fetch_last[username] = now
        # parse system info sent by client and broadcast it directly (bypasses rate limiting)
        parts = msg.split("|", 1)
        info = {}
        if len(parts) > 1:
            try:
                info = json.loads(parts[1])
            except Exception:
                pass
        lines = [f"[{username}] system"] + [f"  {k}: {v}" for k, v in info.items()]
        for line in lines:
            self.state.add_channel_message(username if line == lines[0] else "system", line)
            self.broadcast(line)
        self.send(addr, "[FETCH_OK]")

    # all the handling img methods below,
    @register("[IMG]|")
    def handleImg(self, msg, ctx):
        addr = ctx["addr"]
        clientInfo = self.state.clients.get(addr)
        if not clientInfo:
            return
        sender = clientInfo.get("username")
        if not sender:
            return
        if self.state.is_muted(sender):
            self.send(addr, "[ADMIN_ERROR]|You are muted and cannot send messages")
            return

        now = time.time()
        last = clientInfo.get("last_msg", 0)
        if self.state.msg_rate_limit > 0 and (now - last) < self.state.msg_rate_limit:
            wait = round(self.state.msg_rate_limit - (now - last), 1)
            self.send(addr, f"[RATE_LIMITED]|{wait}")
            return
        clientInfo["last_msg"] = now

        # [IMG]|<filename>|<base64_data>
        parts = msg.split("|", 2)
        if len(parts) < 3:
            return
        filename, b64 = parts[1], parts[2]
        filename = "".join(c for c in filename if 32 <= ord(c) < 127 and c not in '|\\/')[:64] or "image.png"
        if len(b64) > 8 * 1024 * 1024:
            self.send(addr, "[ADMIN_ERROR]|Image too large (max ~8MB)")
            return
        try:
            base64.b64decode(b64, validate=True)
        except Exception:
            self.send(addr, "[ADMIN_ERROR]|Invalid image data")
            return

        self.broadcast(f"[IMG]|{sender}|{filename}|{b64}")
        self.state.add_channel_message(sender, f"[{sender}]: [image: {filename}]")
    # ik this is basically the same as handle_img but i couldnt get it to work any other way - trying to do it in with same method made all dm images show up in the main channel for recipients which was v bad.
    @register("[DM_IMG]|")
    def handleDmImg(self, msg, ctx):
        addr = ctx["addr"]
        clientInfo = self.state.clients.get(addr)
        if not clientInfo:
            return
        sender = clientInfo.get("username")
        if not sender:
            return
        if self.state.is_muted(sender):
            self.send(addr, "[ADMIN_ERROR]|You are muted and cannot send messages")
            return

        now = time.time()
        last = clientInfo.get("last_msg", 0)
        if self.state.msg_rate_limit > 0 and (now - last) < self.state.msg_rate_limit:
            wait = round(self.state.msg_rate_limit - (now - last), 1)
            self.send(addr, f"[RATE_LIMITED]|{wait}")
            return
        clientInfo["last_msg"] = now

        # [DM_IMG]|<recipient>|<base64>
        parts = msg.split("|", 3)
        if len(parts) < 4:
            return
        recipient, filename, b64 = parts[1], parts[2], parts[3]
        filename = "".join(c for c in filename if 32 <= ord(c) < 127 and c not in '|\\/')[:64] or "image.png"

        if not self.state.user_exists(recipient):
            self.send(addr, "[DM_FAIL]|User not found")
            return
        if len(b64) > 8 * 1024 * 1024:
            self.send(addr, "[ADMIN_ERROR]|Image too large (max ~8MB)")
            return
        try:
            base64.b64decode(b64, validate=True)
        except Exception:
            self.send(addr, "[ADMIN_ERROR]|Invalid image data")
            return

        # send to recipient (if online) and echo back to sender
        wire = f"[DM_IMG]|{sender}|{recipient}|{filename}|{b64}"
        self.sendToUser(recipient, wire)
        self.send(addr, wire)
        self.state.add_dm(sender, recipient, f"[image: {filename}]")

    def _redact(self, text):
        return " ".join("*" * len(w) for w in text.split(" "))

    @register("[DISP]|")
    def handleDisp(self, msg, ctx):
        addr = ctx["addr"]
        clientInfo = self.state.clients.get(addr)
        if not clientInfo:
            return
        sender = clientInfo.get("username")
        if not sender:
            return
        if self.state.is_muted(sender):
            self.send(addr, "[ADMIN_ERROR]|You are muted and cannot send messages")
            return

        # [DISP]|<seconds>|<text>
        parts = msg.split("|", 2)
        if len(parts) < 3:
            self.send(addr, "[ADMIN_ERROR]|Usage: /disp <seconds> <message>")
            return
        try:
            seconds = max(1, min(int(parts[1]), 3600))
        except ValueError:
            self.send(addr, "[ADMIN_ERROR]|/disp requires a number of seconds")
            return
        text = parts[2].strip()
        if not text:
            return
        # create an id for each disp message so we can expire/redact it later without affecting other msgs
        msgId = str(uuid.uuid4())
        now = time.time()
        expiresAt = now + seconds
        payload = f"[DISP]|{msgId}|{sender}|{expiresAt}|{text}"
        self.broadcast(payload)

        # schedule server-side expiry
        def _expire():
            time.sleep(seconds)
            redacted = self._redact(text)
            self.broadcast(f"[DISP_EXPIRE]|{msgId}|{redacted}")

        threading.Thread(target=_expire, daemon=True).start()

    @register("[TYPING]|")
    def handleTyping(self, msg, ctx):
        addr = ctx["addr"]
        clientInfo = self.state.clients.get(addr)
        if not clientInfo:
            return
        sender = clientInfo.get("username")
        if not sender:
            return
        # broadcast typing notification to all other clients
        # format: [TYPING]|<username>
        self.broadcast(f"[TYPING]|{sender}", excludeAddr=addr)

    @register("[TYPING_STOP]|")
    def handleTypingStop(self, msg, ctx):
        addr = ctx["addr"]
        clientInfo = self.state.clients.get(addr)
        if not clientInfo:
            return
        sender = clientInfo.get("username")
        if not sender:
            return
        # broadcast typing stop to all other clients
        # format: [TYPING_STOP]|<username>
        self.broadcast(f"[TYPING_STOP]|{sender}", excludeAddr=addr)


