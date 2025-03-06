from dataclasses import dataclass
from enum import Enum
import functools
import logging
import os
from pathlib import Path
import re
import shutil
import socket
import time
from typing import Callable, Literal


RETR_OUT = Path("retr_files")

### ALL STATE SHOULD BE STORED IN THE GLOABL SERVER_STATE VARIABLE

@dataclass
class ServerState:
    NUM_RETRD:int = 0
    ACTIVE:bool = True #parsing new commands - HW1 only
    USERNAME:bool = False
    PASSWORD:bool = False
    PORT_OPEN:bool = False

    def reset_state(self):
        self.NUM_RETRD = 0
        self.ACTIVE = False
        self.USERNAME = False
        self.PASSWORD = False
        self.PORT_OPEN = False



SERVER_STATE:ServerState

CR = "\r"
LF = "\n"

replies:dict[int|tuple[int,...],str|dict[str|None,str]] = {
    150:"150 File status okay.\r\n",
    200:{
        None:"200 Command OK.\r\n",
        "TYPE":"200 Type set to {type}.\r\n",
        "PORT":"200 Port command successful ({address},{port}).\r\n"
    },
    215:"215 UNIX Type: L8.\r\n",
    220:"220 COMP 431 FTP server ready.\r\n",
    221:"221 Goodbye.\r\n",
    230:"230 Guest login OK.\r\n",
    250:"250 Requested file action completed.\r\n",
    331:"331 Guest access OK, send password.\r\n",
    425:"425 Can not open data connection.\r\n", 
    500:"500 Syntax error, command unrecognized.\r\n",
    501:"501 Syntax error in parameter.\r\n",
    503:"503 Bad sequence of commands.\r\n",
    530:"530 Not logged in.\r\n",
    550:"550 File not found or access denied.\r\n",
}
replies[(150,425)] = replies[150] + replies[425] #dirty hack lmfao

class FTPAction:
    def __init__(self,reply:str,callback:Callable[[],None]|None=None):
        self.reply = reply
        self.callback = callback

    def execute(self):
        if self.callback:
            self.callback();

class FTPError(Exception,Enum):
    invalid_command = 500
    invalid_parameter = 501
    IP = 501
    bad_order = 503
    not_logged_in = 530
    file_error = 550
    file_ok_bad_transfer = ((150,425),)

    def __init__(self,value:int):
        self.val = value
        super().__init__(self.reply());
        
    def reply(self)->str:
        return replies[self.val]
    
    def isAction(self)->bool:
        return False

class FTPReply(Enum):
    file_ok = 150
    server_ok = 220
    goodbye = 221
    guest_login = 230
    guest_ok = 331
    command_ok = 200
    type_I = (200,"TYPE",{"type":"I"})
    type_A = (200,"TYPE",{"type":"A"})
    port_success = (200,"PORT")
    system = 215
    file_completed = 250

    def __init__(self,value:int,command:str|None=None,args:dict[str,str]={}):
        self.val = value
        self.command = command
        self.args = args
        
    def reply(self,**kwargs)->str:
        rep = replies[self.val];
        if isinstance(rep,dict):
            rep = rep[self.command];
        d = dict(**self.args,**kwargs)
        if len(d) > 0:
            rep = rep.format(**d)
        return rep;
    
    def __call__(self,*args,**kwargs):
        return self.reply(*args,**kwargs)

    def bytes(self,encoding:str='utf-8',*args,**kwargs):
        return self.reply(*args,**kwargs).encode(encoding=encoding)


def parseCommand(command:str,include_command=True):
    reply = ""
    nextline = command
    try:
        if include_command: reply += nextline + "\n"

        #parse end-of-line
        if not nextline.endswith("\r"):
            raise FTPError.invalid_parameter
        else:
            nextline = nextline.removesuffix("\r")

        #parse command token
        comm_idx = re.search(" ",nextline)
        if comm_idx == None:
            comm_idx = len(nextline)
        else:
            comm_idx = comm_idx.start()
        comm = nextline[:comm_idx].upper()
        logging.info("parsing command token: '" + comm + "'")
        if comm not in parsers: #invalid command token
            logging.error("No Command")
            raise FTPError.invalid_command
            
        #parse command
        logging.info("parsing command: " + nextline)
        nextline = nextline[comm_idx:]
        command_action = parsers[comm](nextline)
        if isinstance(command_action,str):
            command_action = FTPAction(command_action);
        
        logging.info("command parsed successfully")

        #command valid, validate command order
        logging.info(SERVER_STATE)
        if not SERVER_STATE.USERNAME and comm != 'USER':
            #valid command preceding valid USER+PASS sequence
            raise FTPError.not_logged_in
        elif not SERVER_STATE.PASSWORD and comm not in ['USER','PASS']:
            SERVER_STATE.USERNAME = False #consumes USER
            #valid command preceding valid USER+PASS sequence
            raise FTPError.not_logged_in
        elif comm == 'RETR' and not SERVER_STATE.PORT_OPEN:
            raise FTPError.bad_order
        
        logging.info("command is valid to execute")
        
        #if command is valid, execute it
        command_action.execute()
        if comm == 'PORT':
            SERVER_STATE.PORT_OPEN = True
        if comm == 'RETR':
            SERVER_STATE.PORT_OPEN = False

        #if execution is valid, record command
        if comm == 'USER':
            logging.info("Username Recorded")
            SERVER_STATE.USERNAME = True
            SERVER_STATE.PASSWORD = False
        if comm == 'PASS':
            logging.info("Password Recorded")
            SERVER_STATE.PASSWORD = True

        #finally, reply
        reply += command_action.reply
        logging.info("command executed successfully")
    except FTPError as f:
        logging.error("FTP Error: " + f.reply())
        reply += f.reply()
   
    return reply





def parseCommands(commands:str):
    logging.info("beginning command parsing")
    reply:str = FTPReply.server_ok()
    
    while True:
        if not SERVER_STATE.ACTIVE or commands == "":
            break
        try:
            #get line
            idx = re.search("\n",commands)
            if idx == None:
                reply += commands
                commands = ""
                SERVER_STATE.ACTIVE = False
                logging.error("No CRLF")
                raise FTPError.invalid_parameter
            idx = idx.start()
            nextline,commands = commands[:idx],commands[idx+1:]
            
            reply += parseCommand(nextline)
        except FTPError as f:
            logging.error("FTP Error: " + f.reply())
            reply += f.reply()
            continue


    return reply



def parseUser(command:str):
    command = command.lstrip(" ")
    username = re.fullmatch("[ -~]+",command)
    if username is None:
        raise FTPError.invalid_parameter
    else:
        return FTPReply.guest_ok()

def parsePass(command:str)->str:
    command = command.lstrip(" ")
    password = re.fullmatch("[ -~]+",command)
    if password is None:
        raise FTPError.invalid_parameter
    else:
        return FTPReply.guest_login()

def parseType(command:str)->str:
    command = command.lstrip(" ")
    if command == "I":
        return FTPReply.type_I();
    elif command == "A":
        return FTPReply.type_A();
    else:
        raise FTPError.IP;

def parseSyst(command:str)->str:
    if command == "":
        return FTPReply.system()
    else:
        raise FTPError.IP

def parseNoop(command:str)->str:
    if command == "":
        return FTPReply.command_ok()
    else:
        logging.error("No-parameter 'NOOP' command has parameter '" + command + "'")
        raise FTPError.IP

def parseQuit(command:str)->str:
    if command == "":
        SERVER_STATE.ACTIVE = False
        return FTPReply.goodbye()
        # return FTPReply.command_ok()
    else:
        raise FTPError.IP

def parsePort(command:str):
    command = command.lstrip(" ")
    nums = command.split(",")
    if len(nums) != 6:
        raise FTPError.IP
    if not all(map(str.isdigit,nums)):
        raise FTPError.IP
    try:
        nums = list(map(int,nums))
    except ValueError:
        raise FTPError.IP
    if any([num < 0 or num > 255 for num in nums]):
        raise FTPError.IP
    address = ".".join(map(str,nums[:4]))
    portnum = nums[4]*256 + nums[5]
    port = str(portnum)


    callback = functools.partial(record_port,address,portnum)
    return FTPAction(FTPReply.port_success.reply(address=address,port=port),callback)

def record_port(address:str,port:int):
    if isinstance(SERVER_STATE,TCPServerState):
        SERVER_STATE.CLIENT_ADDR = address;
        SERVER_STATE.CLIENT_PORT = port;
    pass


def parseRetr(command:str)->FTPAction:
    command = command.lstrip(" ")
    command = command.replace("\\","/")
    if len(command) > 0 and command[0] == "/":
        command = command[1:]
    filepath = re.fullmatch("[ -~]+",command)
    if filepath is None:
        raise FTPError.invalid_parameter    
    callback = functools.partial(perform_retr,filepath.string)
    return FTPAction(FTPReply.file_ok() + FTPReply.file_completed(),callback); #this is just dumb but whatever

def perform_retr(command):
    if os.path.exists(command):
        if isinstance(SERVER_STATE,TCPServerState):
            try:
                #TODO: socket error handling
                datasock = socket.socket(socket.AF_INET,socket.SOCK_STREAM);
                datasock.connect((SERVER_STATE.CLIENT_ADDR,SERVER_STATE.CLIENT_PORT))
                logging.info(datasock)
                with open(command,"rb") as f:
                    datasock.sendfile(f);
                datasock.close()
                return
            except OSError as e:
                import traceback as tb
                logging.error("\n".join(tb.format_exception(e)))
                raise FTPError.file_ok_bad_transfer

        else:
            SERVER_STATE.NUM_RETRD += 1
            try:
                shutil.copy(command,RETR_OUT/f"file{SERVER_STATE.NUM_RETRD}");
                return 
            except OSError as e:
                import traceback as tb
                logging.error(tb.format_exception(e))
                pass
    raise FTPError.file_error
    

parsers:dict[str,Callable[[str],str|FTPAction]] = {
    "USER":parseUser,
    "PASS":parsePass,
    "TYPE":parseType,
    "SYST":parseSyst,
    "NOOP":parseNoop,
    "QUIT":parseQuit,
    "PORT":parsePort,
    "RETR":parseRetr,}


##### Server Networking stuff #####
@dataclass(kw_only=True)
class TCPServerState(ServerState):
    SERVER_PORT:int
    SERVERSOCK:socket.socket|None = None
    CONN:socket.socket|None = None
    CLIENT_ADDR:str|None = None
    CLIENT_PORT:int|None = None

    def __post_init__(self):
        self.reset_state()

    def reset_state(self):
        super().reset_state()
        self.CLIENT_ADDR = None
        self.CLIENT_PORT = None

        
        #close existing connection if it exists
        if self.CONN is not None:
            self.CONN.close()

        #open new TCP socket if needed
        if self.SERVERSOCK is None:
            self.SERVERSOCK = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
            self.SERVERSOCK.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) 
            self.SERVERSOCK.bind(("", self.SERVER_PORT)) 
            self.SERVERSOCK.listen(1)  # Allow only one connection at a time 


class PortClosed(Exception):
    pass

def start_FTP_server():
    assert isinstance(SERVER_STATE,TCPServerState)
    logging.info("Opening FTP server")
    sock = SERVER_STATE.SERVERSOCK
    assert sock is not None
    while True:
        logging.info("awaiting connection")
        res = None
        while True: #for keyboardinterrupt reasons
            sock.settimeout(2)
            try:
                res = sock.accept()
                break
            except TimeoutError:
                continue
        conn,(hostaddr,hostport) = res
        # print("server connected")
        logging.info("client connected from address " + str((hostaddr,hostport)))

        SERVER_STATE.CONN = conn
        SERVER_STATE.ACTIVE = True

        conn.send(FTPReply.server_ok.bytes())
        sys.stdout.buffer.write(FTPReply.server_ok.bytes());
        sys.stdout.flush()

        commands = ""

        while True:
            if not SERVER_STATE.ACTIVE:
                SERVER_STATE.reset_state()
                break
            try:
                logging.info("awaiting next command")
                while True:
                    #update command buffer
                    conn.settimeout(5)
                    try:
                        data = conn.recv(1024,).decode('utf-8')
                        if len(data) == 0: #port closed! close server
                            logging.info("Port closed! Resetting server...")
                            raise PortClosed()
                        commands += data
                    except TimeoutError:
                        continue

                    #find line
                    idx = re.search("\n",commands)
                    if idx == None:
                        #enter not received, keep polling
                        time.sleep(0.1)
                        continue
                    idx = idx.start()
                    nextline,commands = commands[:idx],commands[idx+1:]
                    break;

                logging.info("command received:\n" + nextline) 
                sys.stdout.buffer.write((nextline + "\n").encode('utf-8'))
                sys.stdout.flush()
                reply = parseCommand(nextline,include_command=False);
                conn.send(reply.encode('utf-8'))
                logging.info(f"Reply sent ({len(reply)} character(s)):\n" + reply)
                sys.stdout.buffer.write(reply.encode('utf-8'))
                sys.stdout.flush()
                
            except FTPError as f:
                logging.error("FTP Error: " + f.reply())
                conn.send(f.reply().encode('utf-8'))
                sys.stdout.buffer.write(f.reply().encode('utf-8'))
                sys.stdout.flush()
                continue
            except PortClosed:
                SERVER_STATE.reset_state()
        
        # print("server disconnected")
        logging.info("client disconnected")


    return reply

# def reset_server():
    






if __name__ == "__main__":
    server_type:Literal['local','networked'] = "networked"

    logging.basicConfig(filename='server.log', level=logging.INFO,filemode='w')

    if server_type == "local":

        SERVER_STATE = ServerState()

        import sys
        text = sys.stdin.buffer.read().decode('UTF-8');

        

        sys.stdout.buffer.write(parseCommands(text).encode('UTF-8'))
    
    elif server_type == "networked":
        import sys
        port = int(sys.argv[1])

        SERVER_STATE = TCPServerState(SERVER_PORT=port)

        while True:
            try:
                start_FTP_server()
            except (ConnectionResetError,ConnectionAbortedError):
                # print("Connection broken! Restarting server...")
                SERVER_STATE.reset_state()
                continue
        