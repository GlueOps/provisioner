import subprocess, os, glueops.setup_logging, traceback
# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logger = glueops.setup_logging.configure(level=LOG_LEVEL)

def create_virtual_machine(
    connect,
    name,
    metadata_description,
    ram,
    vcpus,
    disk_path,
    disk_format,
    os_variant,
    network_bridge,
    network_model,
    user_data,
    meta_data,
    import_option,
):
    cmd = [
        "virt-install",
        "--connect", connect,
        "--name", name,
        "--metadata", f"description={metadata_description}",
        "--ram", str(ram),
        "--vcpus", str(vcpus),
        "--disk", f"path={disk_path},format={disk_format}",
        "--os-variant", os_variant,
        "--network", f"bridge={network_bridge},model={network_model}",
        "--cloud-init", f"user-data={user_data},meta-data={meta_data}",
        "--noautoconsole",
    ]
    
    if import_option:
        cmd.append("--import")

    try:
        result = subprocess.run(cmd, check=True, text=True, capture_output=True)
        logger.info(f"Command executed successfully. {result.stdout}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Error during execution: {e.stderr}")
        logger.error(traceback.format_exc())
        raise
