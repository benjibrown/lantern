# yes, im restructuring lantern so it uses TCP not UDP 
# i fear that udp has made be lose more brain cells than packets it has lost# which is a lot

import socket 


MAX_MESSAGE_BYTES = 10 * 1024 * 1024 # 10mb should be way more than enough


def _recv_exact(sock: socket.socket, n: int):
    # read bytes and return none if disconnected 
    buf = b""
    
    while len(buf) < n:
        try:
            # chunky
            chunk = sock.recv(n - len(buf))
        except OSError:
            return None
        if not chunk:
            return None
        buf += chunk
    return buf

def send_msg(sock: socket.socket, text: str):
    # send msg - length prefixed 
    # TODO - encrypt here 
    data = text.encode()
    sock.sendall(len(data).to_bytes(4, "big") + data)


def recv_msg(sock: socket.socket):
    # recv a message 
    raw_len = _recv_exact(sock, 4)
    if raw_len is None:
        return None
    length = int.from_bytes(raw_len, "big")
    if length > MAX_MESSAGE_BYTES:
        return None # reject big messages 
    data = _recv_exact(sock, length)
    if data is None:
        return None
    return data.decode(errors="ignore")





