import re

from FTPServer import FTPError, FTPReply

def parse_ftp_input_user_command(ftp_input_data):
    """
    Parses FTP input to extract the username from the USER command (case-insensitive).
    
    Args:
        input_data (str): The raw FTP input string.
    
    Returns:
        str: Extracted username if the USER command is valid, else an error message.
    """
    # Regular expression to match the USER command (case-insensitive)
    user_command_pattern = r'^(USER)\s+([a-zA-Z0-9_.-]+)\r\n$'

    match = re.match(user_command_pattern, ftp_input_data, re.IGNORECASE)
    
    if match:
        username = match.group(2)  # Extract the username from the second capturing group
        return FTPReply.guest_ok.reply()
    raise FTPError.invalid_parameter


