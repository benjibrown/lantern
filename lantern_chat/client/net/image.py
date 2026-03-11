import platform
import subprocess
import base64
import io
import os

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    Image = None
    _PIL_AVAILABLE = False

IMG_MAX_WIDTH = 80
IMG_MAX_HEIGHT = 40


def _img_to_rows(data: bytes):
    # converts each img row into bytes :)
    # also works for gifs but will only take the first frame, which is probably fine for now lol
    if not _PIL_AVAILABLE:
        return None
    img = Image.open(io.BytesIO(data)).convert("RGB")
    # terminal chars are ~2x taller than wide so halve the height
    w = min(img.width, IMG_MAX_WIDTH)
    h = max(1, min(int(img.height * (w / img.width) * 0.45), IMG_MAX_HEIGHT))
    img = img.resize((w, h), Image.LANCZOS)
    rows = []
    for y in range(h):
        row = []
        for x in range(w):
            r, g, b = img.getpixel((x, y))
            row.append(("█", r, g, b))
        rows.append(row)
    return rows


def get_clipboard_image():
    # an attempt to get imgs from cliboard - this is so cancer 
    # only tested on linux so if u have a mac please lmk.
    # if doesnt work, then no big deal as you can still send with /img 
    # returns (bytes, filename) or (None, None) if no image found or on error 

    system = platform.system()
    try:
        if system == "Darwin":
            # osascript can read PNG data from the macOS clipboard
            script = (
                'set img to (get the clipboard as «class PNGf»)\n'
                'return img as string'
            )
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout, "clipboard.png"
        else:
            # Try Wayland first, then X11 - wayland is so much better frfr but understand not everyone uses it yet
            for cmd in (
                ["wl-paste", "--type", "image/png", "--no-newline"],
                ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
            ):
                result = subprocess.run(cmd, capture_output=True)
                if result.returncode == 0 and result.stdout:
                    return result.stdout, "clipboard.png"
    except Exception:
        pass
    return None, None
