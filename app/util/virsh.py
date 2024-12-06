from . import b64
import subprocess, os, glueops.setup_logging, traceback, re, json
# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logger = glueops.setup_logging.configure(level=LOG_LEVEL)

def destroy_vm(connect, vm_name):
    """Destroy a virtual machine."""
    cmd = ["virsh", "--connect", connect, "destroy", vm_name]
    try:
        result = subprocess.run(cmd, check=True, text=True, capture_output=True)
        logger.info(f"VM '{vm_name}' destroyed successfully. {result.stdout}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error destroying VM '{vm_name}': {e.stderr}")
        logger.error(traceback.format_exc())
        raise


def undefine_vm(connect, vm_name, remove_all_storage=False):
    """Undefine a virtual machine."""
    cmd = ["virsh", "--connect", connect, "undefine", vm_name]
    if remove_all_storage:
        cmd.append("--remove-all-storage")
    
    try:
        result = subprocess.run(cmd, check=True, text=True, capture_output=True)
        logger.info(f"VM '{vm_name}' undefined successfully. {result.stdout}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error undefining VM '{vm_name}': {e.stderr}")
        logger.error(traceback.format_exc())
        raise


def start_vm(connect, vm_name):
    """Start a virtual machine."""
    cmd = ["virsh", "--connect", connect, "start", vm_name]
    try:
        result = subprocess.run(cmd, check=True, text=True, capture_output=True)
        logger.info(f"VM '{vm_name}' started successfully. {result.stdout}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error starting VM '{vm_name}': {e.stderr}")
        logger.error(traceback.format_exc())
        raise

def describe_vm(connect, vm_name):
    """describe a virtual machine."""
    cmd = ["virsh", "--connect", connect, "desc", vm_name]
    try:
        result = subprocess.run(cmd, check=True, text=True, capture_output=True)
        logger.info(f"VM: {vm_name} Description: {result.stdout.strip()}")
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"Error starting VM '{vm_name}': {e.stderr}")
        logger.error(traceback.format_exc())
        raise

def list_vms(connect):
    """Start a virtual machine."""
    cmd = ["virsh", "--connect", connect, "list", "--all"]
    try:
        result = subprocess.run(cmd, check=True, text=True, capture_output=True)
        logger.info(f"{result.stdout}")
        vms = format_vm_list(connect, result.stdout)
        logger.info(vms)
        return vms
    except subprocess.CalledProcessError as e:
        logger.error(f"Error listing vms")
        logger.error(traceback.format_exc())
        raise


def format_vm_list(connect, output):
    """
    Parses the output of 'virsh list --all' and returns a list of domains with a description.
    Each domain is represented as a dictionary with keys: id, name, state, description.
    """
    lines = output.strip().split('\n')
    if len(lines) < 2:
        logger.error("Unexpected output format.")
        return []

    # The actual data starts after the header and separator lines
    data_lines = lines[2:]

    domains = []
    for line in data_lines:
        if not line.strip():
            continue  # Skip empty lines
        
        # Split the line based on two or more spaces
        parts = re.split(r'\s{2,}', line.strip())
        if len(parts) != 3:
            logger.error(f"Unexpected line format: '{line}'")
            raise Exception(f'Unexpected vm line item {line}')

        dom_id, name, state = parts
        domains.append({
            'id': dom_id,
            'name': name,
            'state': state,
            'description': json.loads(encoder.decode_string(describe_vm(connect, name)))
        })
    return domains
