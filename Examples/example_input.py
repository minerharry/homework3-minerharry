import sys

sys.stdout.buffer.write(b"USER jasleen\r\n")    # Valid
sys.stdout.buffer.write(b"user jasleen\r\n")    # Valid (lowercase command)
sys.stdout.buffer.write(b"UsEr jasleen\r\n")    # Valid (mixed-case command)
sys.stdout.buffer.write(b"USERjasleen\r\n")     # Invalid (no space after USER)
sys.stdout.buffer.write(b"user jasleen\n")     # Invalid (unrecognized command keyword) 
sys.stdout.buffer.write(b"USER    jasleen\r\n") # Valid (multiple spaces allowed)
sys.stdout.buffer.write(b"USER jasleen" )       # Invalid (no CRLF terminator)
