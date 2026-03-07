<div align='center'>

# Lantern

A curses based chat client and server.


![PyPI - Downloads](https://img.shields.io/pypi/dw/lantern-chat)
</div>


### Screenshots
<div align="center"> <a href=""><img src="https://u.cubeupload.com/benjibrown/screenshot2026030620.png" alt='image' width='800'/></a> </div>




## Getting Started

### Prerequisites

- Python
- Pip package manager
- a brain


### Installation

```
pip install lantern-chat
```

### Usage
To start the server, run:
```
lantern-server
```
You can specify a custom port with the `-p` flag, for example:
```
lantern-server -p 12345
```
To start the client, run:
```
lantern
```
You can specify the server host and port with the `-s` and `-p` flags, for example:
```
lantern -s 1.1.1.1 -p 12345
```

The default port is 6000 and default server host is localhost.

All client and server config is saved to `~/.config/lantern/config.json` and `~/.config/lantern/server_config.json` respectively.
In the server config, you can set the server admins, port, message and fetch cooldown.


# Details

Lantern requires a server to be running at the configured host and port for clients to be able to connect and communicate. This can either be locally (using default server IP and port in client config) which will allow you to communicate across a LAN or by setting up the server on a public facing IP (eg using a VPS) or by tunnelling a port on your local network to a publicly accessible IP.

## Contributing

Just make a pull req. lol