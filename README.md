# Lantern 

A really niche TUI chat client

![ss](https://iili.io/qJSgXaa.png)

# UNDER ACTIVE DEVELOPMENT - if anything breaks please make an issue or a PR

## Setup

### Prerequisites
- Python 3.10 or higher
- pip (Python package installer)
- a brain 

### Installation
```bash 
git clone https://github.com/benjibrown/lantern.git
cd lantern 
pip3 install -r requirements.txt 
```

### Usage

There are a couple things you need to know before running lantern. 

Firstly, there is a server script that acts as the backend for the client. Atleast one instance of the server needs to be running for the client to work. You can run the server with the following command:
```bash 
python3 server.py
```
This will spin up a server on localhost:6000, which is also the default connection address for the client. This can be changed in the `serverconfig.json` file (WIP). 

Once a sever is running, you can start the client with the following command:
```bash
python3 client.py 
```
This will automatically connect to the server at localhost:6000. You can change which connection address the client uses by passing it as an argument when starting the client, like so:
```bash 
python3 client.py -s <server_ip_address> -p <server_port>
```
For the client to function, there must be a server running at the specified address and port. 

After opening the client, you will be prompted to login or register. After that, you will be able to chat with other users who are connected to the same server. You will only need to login once, as your credentials will be saved in a local file - `.lantern_session`.



![Badge](https://hitscounter.dev/api/hit?url=https%3A%2F%2Fgithub.com%2Fbenjibrown%2Flantern&label=git&icon=lamp-fill&color=%23198754&message=&style=flat&tz=UTC)
