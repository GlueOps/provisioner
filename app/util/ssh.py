import paramiko, subprocess, os, glueops.setup_logging, traceback
from contextlib import contextmanager

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logger = glueops.setup_logging.configure(level=LOG_LEVEL)

@contextmanager
def ssh_client_context(host, username, port, timeout=10):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(host, port=port, username=username, allow_agent=True, timeout=timeout)
        yield ssh
    finally:
        ssh.close()

def execute_ssh_command(host, username, port, command):
    with ssh_client_context(host, username, port) as ssh:
        stdin, stdout, stderr = ssh.exec_command(command)
        
        # Wait for the command to complete
        exit_status = stdout.channel.recv_exit_status()
        
        # Read the output and error streams
        output = stdout.read().decode().strip()
        error = stderr.read().decode().strip()
        
        if exit_status == 0:
            logger.info(f"Command: {command} executed successfully: {output}")
        else:
            logger.error(f"Command: {command} failed with exit status {exit_status} Error: {error}")
            raise Exception('SSH command failed')
