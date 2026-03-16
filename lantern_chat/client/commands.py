import sys
import threading
import os 
import time
from dataclasses import dataclass
from lantern_chat.client.state import Message

try:
    import cv2 as _cv2
    _CV2_AVAILABLE = True
except ImportError:
    _cv2 = None
    _CV2_AVAILABLE = False


@dataclass
class CommandContext:
    config: object
    state: object
    network: object
    ui: object
    stdscr: object


def notify(ctx: CommandContext, text):
    # system notice in current view
    with ctx.state.lock:
        if ctx.state.current_view == "dm" and ctx.state.dm_target:
            ctx.state.append_dm(ctx.state.dm_target, text, True)
        else:
            ctx.state.messages.append(Message(text=text, is_self=True, ts=0))
            ctx.state.messages[:] = ctx.state.messages[-ctx.config.MAX_MESSAGES:]


class CommandRegistry:
    def __init__(self):
        # ordered list of (trigger, is_prefix, handler, description)
        self._commands = []

    def register(self, trigger, description, prefix: bool = False):
        # decorator to register a cmd handler
        def decorator(fn):
            self._commands.append((trigger, prefix, fn, description))
            return fn
        return decorator

    def dispatch(self, msg, ctx: CommandContext):
        for trigger, is_prefix, fn, _ in self._commands:
            if is_prefix:
                if msg.startswith(trigger):
                    return fn(ctx, msg[len(trigger):].strip())
            else:
                if msg == trigger:
                    return fn(ctx, "")
        return False

    def all_commands(self):
        # returns list for autocomplete
        return [(trigger, desc) for trigger, _, _, desc in self._commands]


registry = CommandRegistry()
register = registry.register


# gen cmds 

@register("/exit", "Exit the chat")
def cmd_exit(ctx, _):
    if ctx.ui.confirm_exit(ctx.stdscr):
        ctx.state.running = False
        ctx.network.send_leave()
        ctx.network.close()
        sys.exit(0)
    return True


@register("/logout", "Log out and close")
def cmd_logout(ctx, _):
    if ctx.ui.confirm_exit(ctx.stdscr):
        ctx.config.clear_session()
        ctx.state.running = False
        ctx.network.send_leave()
        ctx.network.close()
        sys.exit(0)
    return True


@register("/help", "Show help menu")
def cmd_help(ctx, _):
    ctx.ui.show_help(ctx.stdscr)
    return True


@register("/clear", "Clear messages from main chat for this session")
def cmd_clear(ctx, _):
    with ctx.state.lock:
        ctx.state.messages.clear()
    return True


@register("/fetch", "Send system info to chat (30s cooldown)")
def cmd_fetch(ctx, _):
    ctx.network.request_fetch()
    return True


@register("/dnd", "Toggle do not disturb")
def cmd_dnd(ctx, _):
    with ctx.state.lock:
        ctx.state.dnd = not ctx.state.dnd
        status = "on (notifications off)" if ctx.state.dnd else "off (notifications on)"
    ctx.config.save_dnd(ctx.state.dnd)
    notify(ctx, f"[system] Do not disturb {status}")
    return True


@register("/panel", "List users, pick one to DM")
def cmd_panel(ctx, _):
    ctx.ui.show_user_panel(ctx.stdscr)
    return True


@register("/channel", "Switch to channel view")
def cmd_channel(ctx, _):
    with ctx.state.lock:
        ctx.state.current_view = "channel"
        ctx.state.dm_target = None
    return True


@register("/back", "Return to main channel")
def cmd_back(ctx, _):
    return cmd_channel(ctx, _)


@register("/img", "Send an image (file picker)")
def cmd_img(ctx, _):
    path = ctx.ui.show_file_picker(ctx.stdscr)
    if path:
        with ctx.state.lock:
            dm_target = ctx.state.dm_target if ctx.state.current_view == "dm" else None
        threading.Thread(target=ctx.network.send_img, args=(path, dm_target), daemon=True).start()
    return True

# i kinda rewrote all of ur cmd dennis, hope u dont mind :P 
# appreciate the pr tho but added some error handling - aswell as for the import of cv2 (look up)
@register("/snap", "Send a webcam snapshot")
def cmd_snap(ctx, _):
    if not _CV2_AVAILABLE:
        notify(ctx, "[system] /snap requires opencv-python (pip install opencv-python)")
        return True
    with ctx.state.lock:
        dm_target = ctx.state.dm_target if ctx.state.current_view == "dm" else None

    def _capture_and_send():
        devnull = os.open(os.devnull, os.O_WRONLY)
        old_stderr = os.dup(2)
        os.dup2(devnull, 2)
        os.close(devnull)
        try:
            cap = _cv2.VideoCapture(0)
            if not cap.isOpened():
                notify(ctx, "[system] Could not access webcam")
                return
            for _ in range(5):
                cap.read()
            ret, frame = cap.read()
            if not ret or frame is None:
                notify(ctx, "[system] Could not capture frame from webcam")
                return
            success, encoded = _cv2.imencode('.png', frame)
            if not success or encoded is None:
                notify(ctx, "[system] Could not encode webcam frame")
                return
            ctx.network.send_img_bytes(encoded.tobytes(), "snap.png", dm_target)
        except Exception as exc:
            notify(ctx, f"[system] Snap failed: {exc}")
        finally:
            cap.release()
            os.dup2(old_stderr, 2)
            os.close(old_stderr)

    threading.Thread(target=_capture_and_send, daemon=True).start()
    return True




@register("/dm ", "Open DM with a user", prefix=True)
def cmd_dm(ctx, target):
    if not target:
        return True
    if target == ctx.config.USERNAME:
        notify(ctx, "[system] Cannot DM yourself")
        return True
    ctx.state.pending_dm_history = target
    ctx.network.request_dm_history(target)
    return True




@register("/stats", "Show user statistics", prefix=True)
def cmd_stats(ctx, args):
    target = args.strip() or ctx.config.USERNAME
    ctx.network.request_user_stats(target)
    notify(ctx, f"[system] Requesting stats for '{target}'...")
    return True



@register("/disp ", "Send a disappearing message: /disp <secs> <msg>", prefix=True)
def cmd_disp(ctx, args):
    with ctx.state.lock:
        in_dm = ctx.state.current_view == "dm" and bool(ctx.state.dm_target)
    if in_dm:
        notify(ctx, "[system] /disp is not supported in DMs")
        return True
    parts = args.split(None, 1)
    if len(parts) < 2 or not parts[0].isdigit():
        notify(ctx, "[system] Usage: /disp <seconds> <message>")
        return True
    ctx.network.send_disp(int(parts[0]), parts[1])
    return True


# admin cmds

@register("/mute ", "Mute a user (admin)", prefix=True)
def cmd_mute(ctx, args):
    if not args:
        notify(ctx, "[system] Usage: /mute <user>")
        return True
    ctx.network.send_admin_command("mute", args)
    return True


@register("/unmute ", "Unmute a user (admin)", prefix=True)
def cmd_unmute(ctx, args):
    if not args:
        notify(ctx, "[system] Usage: /unmute <user>")
        return True
    ctx.network.send_admin_command("unmute", args)
    return True


@register("/ban ", "Ban a user (admin)", prefix=True)
def cmd_ban(ctx, args):
    if not args:
        notify(ctx, "[system] Usage: /ban <user>")
        return True
    reason = ctx.ui.prompt_ban_reason(ctx.stdscr, args)
    if reason is None:
        return True
    ctx.network.send_admin_command("ban", f"{args}|{reason}")
    return True


@register("/unban ", "Unban a user (admin)", prefix=True)
def cmd_unban(ctx, args):
    if not args:
        notify(ctx, "[system] Usage: /unban <user>")
        return True
    ctx.network.send_admin_command("unban", args)
    return True

@register("/rename ", "Change a username (admin): /rename <old> <new>", prefix=True)
def cmd_rename(ctx, args):
    parts = args.split()
    if len(parts) != 2:
        notify(ctx, "[system] Usage: /rename <old_username> <new_username>")
        return True
    ctx.network.send_admin_command("rename", f"{parts[0]}|{parts[1]}")
    return True

# TODO - add server side stuff for this and make it work
@register("/purge ", "Purge last N messages from chat (admin)", prefix=True)
def cmd_purge(ctx, args):
    if not args.strip().isdigit() or int(args.strip()) <= 0:
        notify(ctx, "[system] Usage: /purge <number>")
        return True
    ctx.network.send_admin_command("purge", args.strip())
    return True


@register("/reload", "Reload server config (admin)")
def cmd_reload(ctx, _):
    ctx.network.send_admin_command("reload", "")
    return True

# useless ahh cmd
'''
# /snap command but with multiple shots 
@register("/snapburst ", "Send multiple webcam snapshots: /snapburst <count>", prefix=True)
def cmd_snapburst(ctx, args):
    if not _CV2_AVAILABLE:
        notify(ctx, "[system] /snapburst requires opencv-python (pip install opencv-python)")
        return True
    if not args.strip().isdigit() or int(args.strip()) <= 0:
        notify(ctx, "[system] Usage: /snapburst <count>")
        return True
    count = int(args.strip())
    with ctx.state.lock:
        dm_target = ctx.state.dm_target if ctx.state.current_view == "dm" else None

    def _capture_and_send_burst():
        
        # Suppress cv2 / V4L2 stderr noise (select() timeout etc)
        devnull = os.open(os.devnull, os.O_WRONLY)
        old_stderr = os.dup(2)
        os.dup2(devnull, 2)
        os.close(devnull)
        
        try:
            cap = _cv2.VideoCapture(0)
            cap.set(_cv2.CAP_PROP_BUFFERSIZE, 1)
            
            if not cap.isOpened():
                notify(ctx, "[system] Could not access webcam")
                return
            
            # Warm up camera once at start (not per-frame)
            for _ in range(5):
                cap.read()
            
            sent = 0
            for i in range(count):
                ret, frame = cap.read()
                if not ret or frame is None:
                    notify(ctx, f"[system] Could not capture frame {i+1}")
                    continue
                success, encoded = _cv2.imencode('.png', frame)
                if not success or encoded is None:
                    continue
                ctx.network.send_img_bytes(encoded.tobytes(), f"snapburst_{i+1}.png", dm_target)
                sent += 1
                # Small pause between frames — enough for camera to fill buffer again
                # but not so long that V4L2 times out
                if i < count - 1:
                    time.sleep(0.05)
            
            if sent < count:
                notify(ctx, f"[system] Snap burst sent {sent}/{count} frames")
                
        except Exception as exc:
            notify(ctx, f"[system] Snap burst failed: {exc}")
        finally:
            cap.release()
            # Restore stderr
            os.dup2(old_stderr, 2)
            os.close(old_stderr)

    threading.Thread(target=_capture_and_send_burst, daemon=True).start()
    return True
'''


class CommandHandler:
    def __init__(self, config, state, network, ui):
        self.config = config
        self.state = state
        self.network = network
        self.ui = ui

    def handle_command(self, msg: str, stdscr) -> bool:
        ctx = CommandContext(self.config, self.state, self.network, self.ui, stdscr)
        return registry.dispatch(msg, ctx)

    def shutdown(self):
        self.state.running = False
        self.network.send_leave()
        self.network.close()
        sys.exit(0)









