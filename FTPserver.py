from enum import Enum
import functools
import logging
import os
from pathlib import Path
import re
import shutil
from typing import Callable, Literal

logger = logging.getLogger(__name__)

CR = "\r"
LF = "\n"

replies:dict[int,str|dict[str|None,str]] = {
    150:"150 File status okay.\r\n",
    200:{
        None:"200 Command OK.\r\n",
        "TYPE":"200 Type set to {type}.\r\n",
        "PORT":"200 Port command successful ({address},{port}).\r\n"
    },
    215:"215 UNIX Type: L8.\r\n",
    220:"220 COMP 431 FTP server ready.\r\n",
    230:"230 Guest login OK.\r\n",
    250:"250 Requested file action completed.\r\n",
    331:"331 Guest access OK, send password.\r\n",
    500:"500 Syntax error, command unrecognized.\r\n",
    501:"501 Syntax error in parameter.\r\n",
    503:"503 Bad sequence of commands.\r\n",
    530:"530 Not logged in.\r\n",
    550:"550 File not found or access denied.\r\n",
}

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



def parseCommands(commands:str):
    logger.info("beginning command parsing")
    reply:str = FTPReply.server_ok()
    userd:bool = False
    passd:bool = False
    portOpen:bool = False
    while True:
        if commands == "":
            break
        try:
            #get line
            idx = re.search("\n",commands)
            if idx == None:
                reply += commands
                commands = ""
                logger.error("No CRLF")
                raise FTPError.invalid_parameter
            idx = idx.start()
            nextline,commands = commands[:idx],commands[idx+1:]
            
            reply += nextline + "\n"

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
            logger.info("parsing command token: '" + comm + "'")
            if comm not in parsers: #invalid command token
                logger.error("No Command")
                raise FTPError.invalid_command
                
            #parse command
            logger.info("parsing command: " + nextline)
            nextline = nextline[comm_idx:]
            command_action = parsers[comm](nextline)
            if isinstance(command_action,str):
                command_action = FTPAction(command_action);
            
            logger.info("command parsed successfully")

            #command valid, validate command order
            if comm == 'QUIT':
                commands = ""
            elif userd == False and comm != 'USER':
                #valid command preceding valid USER+PASS sequence
                raise FTPError.not_logged_in
            elif passd == False and comm not in ['USER','PASS']:
                userd = False #consumes USER
                #valid command preceding valid USER+PASS sequence
                raise FTPError.not_logged_in
            elif comm == 'RETR' and not portOpen:
                raise FTPError.bad_order
            
            logger.info("command is valid to execute")
            
            #if command is valid, execute it
            command_action.execute()
            if comm == 'PORT':
                portOpen = True
            if comm == 'RETR':
                portOpen = False

            #if execution is valid, record command
            if comm == 'USER':
                userd = True
                passd = False
            if comm == 'PASS':
                passd = True

            #finally, reply
            reply += command_action.reply
            logger.info("command executed successfully")
        except FTPError as f:
            logger.error("FTP Error: " + f.reply())
            reply += f.reply()
            continue
        except Exception as e:
            print(type(e))
            print(isinstance(e,FTPError))
            raise e

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
        logger.error("No-parameter 'NOOP' command has parameter '" + command + "'")
        raise FTPError.IP

def parseQuit(command:str)->str:
    if command == "":
        return FTPReply.command_ok()
    else:
        raise FTPError.IP

def parsePort(command:str)->str:
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
    port = str(nums[4]*256 + nums[5])

    return FTPReply.port_success.reply(address=address,port=port)

RETR_OUT = Path("retr_files")
NUM_RETRD = 0

def parseRetr(command:str)->FTPAction:
    command = command.lstrip(" ")
    command = command.replace("\\","/")
    if len(command) > 0 and command[0] == "/":
        command = command[1:]
    callback = functools.partial(perform_retr,command)
    return FTPAction(FTPReply.file_ok() + FTPReply.file_completed(),callback); #this is just dumb but whatever

def perform_retr(command):
    global NUM_RETRD
    if os.path.exists(command):
        NUM_RETRD += 1
        try:
            shutil.copy(command,RETR_OUT/f"file{NUM_RETRD}");
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

if __name__ == "__main__":
    import sys
    text = sys.stdin.buffer.read().decode('UTF-8');

    logging.basicConfig(filename='server.log', level=logging.INFO,filemode='w')

    sys.stdout.buffer.write(parseCommands(text).encode('UTF-8'))