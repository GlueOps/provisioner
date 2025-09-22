from . import b64, ssh
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

def edit_vm_description(connect, vm_name, description):
    """edit a virtual machine's description."""
    cmd = ["virsh", "--connect", connect, "desc", vm_name, "--config", "--live", "--new-desc", description]
    try:
        result = subprocess.run(cmd, check=True, text=True, capture_output=True)
        logger.info(f"VM '{vm_name}' description updated successfully. {result.stdout}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error updating VM '{vm_name}' description: {e.stderr}")
        logger.error(traceback.format_exc())
        raise

def list_vms(region_config):
    """List virtual machines."""
    bash_get_all_vms_script = f"""
        printf "%-5s %-30s %-12s %-40s\\n" "Id" "Name" "State" "Description"
        echo "-------------------------------------------------------------------------------------------------------------"
        
        # Use 'virsh list --all' to get all VM names, IDs, and states in one call
        all_info=$(virsh list --all)
    
        # Process each line of the `virsh list --all` output
        echo "$all_info" | awk 'NR>2 {{print $1,$2,$3}}' | while read -r id name state; do
            # Skip machines that are not named
            [ -z "$name" ] && continue
    
            # For each VM, get its description as a single additional call
            desc=$(virsh desc "$name" 2>/dev/null | head -n 1)
            desc=${{desc:-<No description>}}
    
            # Print the formatted output in a single printf call
            printf "%-5s %-30s %-12s %-40s\\n" "$id" "$name" "$state" "$desc"
        done
        """
    try:
        result = ssh.execute_ssh_command(region_config.host, region_config.user, region_config.port, bash_get_all_vms_script)
        logger.info(f"{result}")
        vms = format_vm_list(region_config.region_name, result)
        logger.info(vms)
        return vms
    except Exception as e:
        logger.error(f"Error listing vms")
        logger.error(traceback.format_exc())
        raise


def format_vm_list(region_name, output):
    """
    Parses the outputs of 'virsh list --all' and 'virsh desc' and returns a list of domains with a description.
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
        if len(parts) != 4:
            logger.error(f"Unexpected line format: '{line}'")
            raise Exception(f'Unexpected vm line item {line}')

        dom_id, name, state, description = parts
        domains.append({
            'dom_id': dom_id,
            'name': name,
            'region_name': region_name,
            'state': state,
            'tags': json.loads(b64.decode_string(description))
        })
    return domains
