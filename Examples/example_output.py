import sys

sys.stdout.write("220 COMP 431 FTP server ready.\r\n")
sys.stdout.write("USER jasleen\r\n")
sys.stdout.write("331 Guest access OK, send password.\r\n")   
sys.stdout.write("user jasleen\r\n")    
sys.stdout.write("331 Guest access OK, send password.\r\n")   
sys.stdout.write("UsEr jasleen\r\n")  
sys.stdout.write("331 Guest access OK, send password.\r\n")     
sys.stdout.write("USERjasleen\r\n") 
sys.stdout.write("500 Syntax error, command unrecognized.\r\n")    
sys.stdout.write("usr jasleen\r\n")
sys.stdout.write("500 Syntax error, command unrecognized.\r\n")    
sys.stdout.write("USER    jasleen\r\n") 
sys.stdout.write("331 Guest access OK, send password.\r\n")  
sys.stdout.write("USER jasleen" )   
sys.stdout.write("500 Syntax error, command unrecognized.\r\n") 
