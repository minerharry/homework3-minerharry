###################################
#             COMP 431            #
#        FTP Client Program       #
#           Starter Code          #
###################################

import itertools
import logging
from pathlib import Path
import sys
import os
import socket as sock
from socket import *
import time
from typing import Iterable, Iterator

# Define dictionary of useful ASCII codes
# Use ord(char) to get decimal ascii code for char
ascii_codes = {
    "A": ord("A"), "Z": ord("Z"), 
    "a": ord("a"), "z": ord("z"), 
    "0": ord("0"), "9": ord("9"),
    "min_ascii_val": 0, "max_ascii_val": 127}

##############################################################################################
#                                                                                            # 
#     This function is intended to manage the command processing loop.                       #
#     The general idea is to loop over the input stream, identify which command              #
#     was entered, and then delegate the command-processing to the appropriate function.     #
#                                                                                            #
##############################################################################################
def read_commands():
    # Initially, only the CONNECT command is valid
    # Commands are case-sensitive
    expected_commands = ["CONNECT"]

    # Initial port number for a “welcoming” socket 
    welcoming_port = int(sys.argv[1])                     # sys.argv[0] is the filename
    ftp_control_connection = None
    num_copied_files = 0



    for command in sys.stdin:
        # Echo command exactly as it was input
        writeOutput(command,raw=False)
        tokens = command.split()
        if len(tokens) > 0 and tokens[0] in expected_commands:
            match tokens[0]:
                case 'CONNECT':
                    reply,port,host = parse_connect(command)
                    writeOutput(reply + "\n",raw=False)

                    if reply.startswith("ERROR"):
                        continue

                    if ftp_control_connection is not None:
                        ftp_control_connection.close()

                    #make connection with server
                    ftp_control_connection = socket(sock.AF_INET,sock.SOCK_STREAM)
                    ftp_control_connection.connect((host,port))

                    writeOutput(send_commands(ftp_control_connection,[None])) #get server response! kind of a hack oh well

                    process_connect(ftp_control_connection);
                    
                    expected_commands = ["CONNECT","GET","QUIT"]
                case 'GET':
                    assert ftp_control_connection is not None
                    reply,pathname = parse_get(command)
                    writeOutput(reply + "\n",raw=False)

                    if reply.startswith("ERROR"):
                        continue
                    
                    num_copied_files += 1;
                    process_get(ftp_control_connection,welcoming_port,pathname,num_copied_files);
                    welcoming_port += 1
                case 'QUIT':
                    assert ftp_control_connection is not None
                    reply = parse_quit(command);
                    writeOutput(reply + "\n",raw=False)
                    
                    if reply.startswith("ERROR"):
                        continue

                    process_quit(ftp_control_connection);

                    ftp_control_connection.close()

                    sys.exit(0)
        else:
            writeOutput("ERROR -- Command Unexpected/Unknown\n",raw=False)


def writeOutput(output:str|Iterator[str],raw=True,encoding:str="utf-8"):
    if not isinstance(output,Iterator):
        output = iter([output])

    for text in output:
        if raw:
            logging.info(f"writing raw text ({len(text)} characters):\n" + text)
            sys.stdout.buffer.write(text.encode(encoding=encoding))
        else:
            logging.info(f"writing non-raw text ({len(text)} characters):\n" + text)
            sys.stdout.write(text)
        sys.stdout.flush()




class FTPError(Exception):
    pass

def send_commands(fcc:socket,commands:Iterable[str|None]):
    # commands = list(commands)
    # logging.info("sending command batch: " + "|".join(commands))
    def isError(code:int):
        return 400 <= code <= 599
    for comm in commands:

        if comm is not None: #allow for a null command to pick up the initial response
            fcc.send(comm.encode('utf-8'))
            
            yield comm
        else:
            comm = ""

        #so here's the fun part. How do I know when the server's stopped sending a reply?
        #well, we can assume the server is formatting everything, so the end of one line will always be \r\n
        #however, how many lines is it going to send?
        #If I had confidence I could format the server however I liked, I'd have it communicate how many lines.
        #Unfortunately, I don't have that confidence
        #Luckily, we do know one thing: each command, **with the exception of RETR**, should only return one line
        #RETR is weird, because it doesn't *always* return two - however, it's still deterministic based on the first reply
        #if the first response is an error, there won't be another; otherwise, there will *always* be another, error or success

        is_retr = comm.lower().startswith("retr")

        error = None

        resp = "" #to be returned
        buff = "" #to hold text from server
        for it in [1,2]: #this loop will only ever run once or twice
            while True: #TODO: timeout?
                logging.info("Awaiting reply, curent buffer:\n"+buff)
                if ("\n" in buff):
                    break;
                fcc.settimeout(5)
                try:
                    buff += fcc.recv(1024).decode('utf-8')
                except TimeoutError:
                    pass
                
            logging.info("newlines in buffer: " + str(buff.count("\n")))
            ind = buff.index("\n")+1
            
            reply,buff = buff[:ind],buff[ind:]
            reply,code = parse_reply(reply)

            resp += reply + os.linesep

            if isError(code):
                error = code
            
            if (is_retr and not isError(code)):
                continue

            break
        
        
        yield resp
        if error is not None:
            raise FTPError(error)







##############################################################################################
#                                                                                            # 
#     This function is intended to handle processing valid CONNECT commands.                 #
#     This includes generating the four-command sequence to send to the server and           #
#     parsing any responses the server returns                                               #
#                                                                                            #
##############################################################################################
def process_connect(ftp_control_connection:socket):
    commands = generate_connect_output()

    try:
        writeOutput(send_commands(ftp_control_connection,commands));
    except FTPError:
        return

##############################################################################################
#                                                                                            # 
#     This function is intended to handle processing valid GET commands.                     #
#     The client will try to create a "welcoming" socket, and if successful, will            #
#     then send the PORT/RETR commands to the server and process the received data.          #
#                                                                                            #
##############################################################################################
def process_get(ftp_control_connection:socket, welcoming_port, file_path, num_copied_files):
    #TODO: TEST SOCKET OPENING ERRORS - CONFLICTING PORTS
    dataport = socket()
    dataport.setsockopt(sock.SOL_SOCKET, sock.SO_REUSEADDR, 1) 
    dataport.bind(("", welcoming_port))
    dataport.listen(1)
    
    commands = generate_get_output(welcoming_port,file_path)

    comit = send_commands(ftp_control_connection,commands)

    try:
        writeOutput(itertools.islice(comit,3));
    except FTPError:
        dataport.close()
        return

    conn,(hostaddr,hostport) = dataport.accept()

    
    dest = Path("retr_files")/f"file{num_copied_files}"
    dest.parent.mkdir(parents=True,exist_ok=True)
    with open(dest,"wb") as f:
        while True:
            data = conn.recv(1024)
            if len(data) == 0: #connection closed, file done
                break
            f.write(data)
    
    conn.close()
    dataport.close()

    writeOutput(comit)        


##############################################################################################
#                                                                                            # 
#     This function is intended to handle processing valid QUIT commands.                    #
#     The client will send the necessary commands to the server and print any server         #
#     responses. It will then close the ftp_control_conneciton and terminate execution.      #
#                                                                                            #
##############################################################################################
def process_quit(ftp_control_connection:socket):
    commands = ["QUIT\r\n"]
    try:
        writeOutput(send_commands(ftp_control_connection,commands));
    except FTPError:
        return

##############################################################
#       The following two methods are for generating         #
#       the appropriate output for each valid command.       #
##############################################################
def generate_connect_output():
    connect_commands = ["USER anonymous\r\n",
                      "PASS guest@\r\n",
                      "SYST\r\n",
                      "TYPE I\r\n"]
    return connect_commands

def generate_get_output(port_num, file_path):
    my_ip = gethostbyname(gethostname())

    FTP_ip = my_ip.replace(".",",")
    FTP_port = ",".join([str(int(hex(port_num)[2:4],base=16)), str(int(hex(port_num)[4:6],base=16))])
    FTP_address = FTP_ip + "," + FTP_port

    get_commands = [
        "PORT " + FTP_address + "\r\n",
        "RETR " + file_path + "\r\n",
    ]

    return get_commands

##############################################################
#         Any method below this point is for parsing         #
##############################################################

############################################
#        Following methods are for         #
#         parsing input commands           #
############################################
# CONNECT<SP>+<server-host><SP>+<server-port><EOL>
def parse_connect(command):
    server_host = ""
    server_port = -1

    if command[0:7] != "CONNECT" or len(command) == 7:
        return "ERROR -- request", server_port, server_host
    command = command[7:]
    
    command = parse_space(command)
    if len(command) > 1:
        command, server_host = parse_server_host(command)
    else:
        command = "ERROR -- server-host"

    if "ERROR" in command:
        return command, server_port, server_host

    command = parse_space(command)
    if len(command) > 1:
        command, server_port = parse_server_port(command)
    else:
        command = "ERROR -- server-port"

    server_port = int(server_port)
    
    if "ERROR" in command:
        return command, server_port, server_host
    elif command != '\r\n' and command != '\n':
        return "ERROR -- <CRLF>", server_port, server_host
    return f"CONNECT accepted for FTP server at host {server_host} and port {server_port}", server_port, server_host

# GET<SP>+<pathname><EOL>
def parse_get(command):
    if command[0:3] != "GET":
        return "ERROR -- request",""
    command = command[3:]
    
    command = parse_space(command)
    command, pathname = parse_pathname(command)

    if "ERROR" in command:
        return command,""
    elif command != '\r\n' and command != '\n':
        return "ERROR -- <CRLF>",""
    return f"GET accepted for {pathname}", pathname

# QUIT<EOL>
def parse_quit(command):
    if command != "QUIT\r\n" and command != "QUIT\n":
        return "ERROR -- <CRLF>"
    else:
        return "QUIT accepted, terminating FTP client"

# <server-host> ::= <domain>
def parse_server_host(command):
    command, server_host = parse_domain(command)
    if command == "ERROR":
        return "ERROR -- server-host", server_host
    else:
        return command, server_host

# <server-port> ::= character representation of a decimal integer in the range 0-65535 (09678 is not ok; 9678 is ok)
def parse_server_port(command):
    port_nums = []
    port_string = ""
    for char in command:
        if ord(char) >= ascii_codes["0"] and ord(char) <= ascii_codes["9"]:
            port_nums.append(char)
            port_string += char
        else:
            break
    if len(port_nums) < 5:
        if ord(port_nums[0]) == ascii_codes["0"] and len(port_nums) > 1:
            return "ERROR -- server-port"
        return command[len(port_nums):], port_string
    elif len(port_nums) == 5:
        if ord(port_nums[0]) == ascii_codes["0"] or  int(command[0:5]) > 65535:
            return "ERROR -- server-port"
    return command[len(port_nums):], port_string

# <pathname> ::= <string>
# <string> ::= <char> | <char><string>
# <char> ::= any one of the 128 ASCII characters
def parse_pathname(command):
    pathname = ""
    if command[0] == '\n' or command[0:2] == '\r\n':
        return "ERROR -- pathname", pathname
    else:
        while len(command) > 1:
            if len(command) == 2 and command[0:2] == '\r\n':
                return command, pathname
            elif ord(command[0]) >= ascii_codes["min_ascii_val"] and ord(command[0]) <= ascii_codes["max_ascii_val"]:
                pathname += command[0]
                command = command[1:]
            else:
                return "ERROR -- pathname", pathname
        return command, pathname

# <domain> ::= <element> | <element>"."<domain>
def parse_domain(command):
    command, server_host = parse_element(command)
    return command, server_host

# <element> ::= <a><let-dig-hyp-str>
def parse_element(command, element_string=""):
    # Keep track of all elements delimited by "." to return to calling function

    # Ensure first character is a letter
    if (ord(command[0]) >= ascii_codes["A"] and ord(command[0]) <= ascii_codes["Z"]) \
    or (ord(command[0]) >= ascii_codes["a"] and ord(command[0]) <= ascii_codes["z"]):
        element_string += command[0]
        command, let_dig_string = parse_let_dig_str(command[1:])
        element_string += let_dig_string
        if command[0] == ".":
            element_string += "."
            return parse_element(command[1:], element_string)
        elif command[0] == ' ':
            return command, element_string
        else:
            return "ERROR", element_string
    elif command[0] == ' ':
        return command, element_string
    return "ERROR", element_string

# <let-dig-hyp-str> ::= <let-dig-hyp> | <let-dig-hyp><let-dig-hyp-str>
# <a> ::= any one of the 52 alphabetic characters "A" through "Z"in upper case and "a" through "z" in lower case
# <d> ::= any one of the characters representing the ten digits 0 through 9
def parse_let_dig_str(command):
    let_dig_string = ""
    while (ord(command[0]) >= ascii_codes["A"] and ord(command[0]) <= ascii_codes["Z"]) \
    or (ord(command[0]) >= ascii_codes["a"] and ord(command[0]) <= ascii_codes["z"]) \
    or (ord(command[0]) >= ascii_codes["0"] and ord(command[0]) <= ascii_codes["9"]) \
    or (ord(command[0]) == ord('-')):
        let_dig_string += command[0]
        if len(command) > 1:
            command = command[1:]
        else:
            return command, let_dig_string
    return command, let_dig_string

# <SP>+ ::= one or more space characters
def parse_space(line):
    if line[0] != ' ':
        return "ERROR"
    while line[0] == ' ':
        line = line[1:]
    return line


#############################################
#    Any method below this point is for     #
#         parsing server responses          #
#############################################
# <reply-code><SP><reply-text><CRLF> 
def parse_reply(reply):
    logging.info("parsing FTP reply:\n" + reply)
    # <reply-code>
    reply, reply_code = parse_reply_code(reply)
    if "ERROR" in reply:
        return reply, reply_code
    
    # <SP>
    reply = parse_space(reply)
    if "ERROR" in reply:
        return "ERROR -- reply-code", reply_code
    
    # <reply-text>
    reply, reply_text = parse_reply_text(reply)
    if "ERROR" in reply:
        return reply, reply_code
    
    # <CRLF>
    if reply != '\r\n' and reply != '\n':
        return "ERROR -- <CRLF>", reply_code
    return f"FTP reply {reply_code} accepted. Text is: {reply_text}", reply_code

# <reply-code> ::= <reply-number>  
def parse_reply_code(reply):
    reply, reply_code = parse_reply_number(reply)
    if "ERROR" in reply:
        return "ERROR -- reply-code", reply_code
    return reply, reply_code

# <reply-number> ::= character representation of a decimal integer in the range 100-599
def parse_reply_number(reply:str):
    reply_number = 0
    if len(reply) < 3:
        return "ERROR", reply_number
    try:
        reply_number = int(reply[0:3])
    except ValueError:
        return "ERROR", reply_number
    reply_number = int(reply[0:3])
    if reply_number < 100 or reply_number > 599:
        return "ERROR", reply_number
    return reply[3:], reply_number

# <reply-text> ::= <string>
# <string> ::= <char> | <char><string>
# <char> ::= any one of the 128 ASCII characters
def parse_reply_text(reply):
    reply_text = ""
    if reply[0] == '\n' or reply[0:2] == '\r\n':
        return "ERROR -- reply_text", reply_text
    else:
        while len(reply) > 1:
            if len(reply) == 2 and reply[0:2] == '\r\n':
                return reply, reply_text
            elif ord(reply[0]) >= ascii_codes["min_ascii_val"] and ord(reply[0]) <= ascii_codes["max_ascii_val"]:
                reply_text += reply[0]
                reply = reply[1:]
            else:
                return "ERROR -- reply_text", reply_text
        return reply, reply_text

if __name__ == "__main__":

    logging.basicConfig(filename='client.log', level=logging.INFO,filemode='w')
    read_commands()
