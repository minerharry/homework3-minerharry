import sys
import socket
from threading import Thread
import time

if __name__ == "__main__":
    
    addr = sys.argv[1]
    port = sys.argv[2]

    sock = socket.socket()
    sock.connect((addr,int(port)))

    
    def send_msg():
        while True:
            data = sys.stdin.readline()
            data = data.replace("\n","\r\n")
            sock.send(data.encode())
            time.sleep(0.2)

    def recv_msg():
        while True:
            data = sock.recv(1024)
            sys.stdout.buffer.write(data)
            sys.stdout.flush()

    Thread(target=send_msg,daemon=True).start()
    Thread(target=recv_msg,daemon=True).start()

    while True:
        time.sleep(0.1)