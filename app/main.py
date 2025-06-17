from fastapi import FastAPI, Security, HTTPException, Depends, status, requests, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from typing import Optional, Dict, List
from pydantic import BaseModel, Field
from util import ssh, virt, virsh, formatter, b64, regions, github, guacamole
import os, glueops.setup_logging, traceback, base64, yaml, tempfile, json, asyncio
from schemas.schemas import ExistingVm, Vm, VmMeta, Message



# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logger = glueops.setup_logging.configure(level=LOG_LEVEL)
BAREMETAL_SERVER_CONFIGS = os.getenv('BAREMETAL_SERVER_CONFIGS', '[]')
REGIONS = regions.get_region_configs(BAREMETAL_SERVER_CONFIGS)
try:
    PROVISIONER_ENVIRONMENT = os.environ['PROVISIONER_ENVIRONMENT']
    API_TOKEN = os.environ['API_TOKEN']
    DOWNLOAD_SERVER_URL = os.environ['DOWNLOAD_SERVER_URL']
    GUACAMOLE_SERVER_URL = os.environ['GUACAMOLE_SERVER_URL']
    GUACAMOLE_SERVER_USERNAME = os.environ['GUACAMOLE_SERVER_USERNAME']
    GUACAMOLE_SERVER_PASSWORD = os.environ['GUACAMOLE_SERVER_PASSWORD']
except KeyError as e:
    logger.critical(f"Required environment variable {e} is not set")
    raise SystemExit(1)

api_key_header = APIKeyHeader(name="Authorization")

app = FastAPI()

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Extract the full stack trace
    stack_trace = traceback.format_exc()
    
    # Return the full stack trace in the response
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal server error occurred.",
            "error": str(exc),
            "traceback": stack_trace,  # Include the full stack trace
        },
    )


def get_api_key(api_key: Optional[str] = Security(api_key_header)):
    if api_key == API_TOKEN:
        return api_key
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Token",
            headers={"WWW-Authenticate": "Bearer"},
        )

@app.post("/v1/create", response_model=Message)
async def create_vm(vm: Vm, api_key: str = Depends(get_api_key)):
    logger.info(vm)
    vm_specs = regions.get_instance_specs(vm.region_name, vm.instance_type, REGIONS)
    # Decode user data
    decoded_user_data = formatter.fix_indentation(base64.b64decode(vm.user_data).decode('utf-8').strip())

    # Validate YAML format
    try:
        yaml.safe_load(decoded_user_data)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in user data: {e}")

    command = f'bash <(curl -L -o "/var/lib/libvirt/images/{vm.vm_name}.qcow2" "{DOWNLOAD_SERVER_URL}/{vm.image}.qcow2")'
    cfg = regions.get_server_config(vm.region_name, REGIONS)
    ssh.execute_ssh_command(cfg.host, cfg.user, cfg.port, command)

    command = f'qemu-img resize /var/lib/libvirt/images/{vm.vm_name}.qcow2 {vm_specs.storage_mb}M'
    ssh.execute_ssh_command(cfg.host, cfg.user, cfg.port, command)

    try:
        # Create a temporary file for user-data
        with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".cloud-config") as temp_file:
            temp_file.write(decoded_user_data)
            temp_file.flush()
            temp_file_path = temp_file.name
        
        logger.info(f"Temporary file created at {temp_file_path}")

        # Execute the virt-install command
        virt.create_virtual_machine(
            connect=cfg.connect_uri,
            name=f"{vm.vm_name}",
            metadata_description=b64.encode_string(json.dumps(vm.tags)),
            ram=vm_specs.memory_mb,
            vcpus=vm_specs.vcpus,
            disk_path=f"/var/lib/libvirt/images/{vm.vm_name}.qcow2",
            disk_format="qcow2",
            os_variant="linux2022",
            network_bridge="virbr0",
            network_model="virtio",
            user_data=temp_file_path,
            import_option=True
        )

        guacamole_token, data_source = guacamole.get_data(
            GUACAMOLE_SERVER_URL,
            GUACAMOLE_SERVER_USERNAME,
            GUACAMOLE_SERVER_PASSWORD
        )

        connectionGroups = guacamole.get_connection_groups(GUACAMOLE_SERVER_URL, guacamole_token, data_source)
        connection_group_id = guacamole.find_group_id_by_name(connectionGroups, vm.tags.owner)
        vm_id = guacamole.create_vm(
            GUACAMOLE_SERVER_URL,
            guacamole_token,
            data_source,
            connection_group_id,
            vm.vm_name,
            cfg.host,
            cfg.port,
            cfg.user,
            cfg.private_key
        )
        guacamole.grant_connection_permission(
            GUACAMOLE_SERVER_URL,
            guacamole_token,
            data_source,
            vm.tags.owner,
            vm_id
        )

    except Exception as e:
        logger.error(f"virt-install failed: {e.stderr}")
        raise
    finally:
        # Clean up the temporary file
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            logger.info(f"Temporary file deleted: {temp_file_path}")

    logger.info(vm.tags)
    return JSONResponse(status_code=200, content={"message": "Success"})

@app.get("/v1/regions", response_model=List[regions.SSHConfig])
async def list_regions(api_key: str = Depends(get_api_key)):
    region_configs = regions.get_enabled_regions_only(REGIONS)
    return region_configs

@app.get("/v1/list", response_model=List[ExistingVm])
async def list_vms(api_key: str = Depends(get_api_key)):
    async def list_vm_for_region(cfg):
        try:
            logger.info(f"Requesting VM list from: {cfg.connect_uri}")
            # Use `asyncio.to_thread` to call a blocking function; 
            # if virsh.list_vms is already async, just call it directly.
            return await asyncio.to_thread(virsh.list_vms, cfg)
        except Exception as e:
            logger.error(f"Error listing VMs from {cfg.connect_uri}: {e}")
            logger.error(traceback.format_exc())

    tasks = [list_vm_for_region(cfg) for cfg in REGIONS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_vms = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            # If you used `return_exceptions=False`, this code wouldn't be reached 
            # because the first exception would raise.
            # With `return_exceptions=True`, you can handle them per-task.
            logger.error(f"Error with region {REGIONS[i].connect_uri}: {result}")
        else:
            all_vms.extend(result)

    return [ExistingVm(**item) for item in all_vms]

@app.post("/v1/start", response_model=Message)
async def start_vm(vm: VmMeta, api_key: str = Depends(get_api_key)):
    cfg = regions.get_server_config(vm.region_name, REGIONS)
    virsh.start_vm(cfg.connect_uri, vm.vm_name)
    return JSONResponse(status_code=200, content={"message": "Success"})
    
@app.post("/v1/stop", response_model=Message)
async def stop_vm(vm: VmMeta, api_key: str = Depends(get_api_key)):
    cfg = regions.get_server_config(vm.region_name, REGIONS)
    virsh.destroy_vm(cfg.connect_uri, vm.vm_name)
    return JSONResponse(status_code=200, content={"message": "Success"})

@app.delete("/v1/delete", response_model=Message)
async def delete_vm(vm: VmMeta, api_key: str = Depends(get_api_key)):
    cfg = regions.get_server_config(vm.region_name, REGIONS)
    try:
        virsh.destroy_vm(cfg.connect_uri, vm.vm_name)

        guacamole_token, data_source = guacamole.get_data(
            GUACAMOLE_SERVER_URL,
            GUACAMOLE_SERVER_USERNAME,
            GUACAMOLE_SERVER_PASSWORD
        )

        connections = guacamole.get_connections(GUACAMOLE_SERVER_URL, guacamole_token, data_source)
        connection_id = guacamole.find_connection_id_by_name(connections, vm.vm_name)
        guacamole.delete_vm(
            GUACAMOLE_SERVER_URL,
            guacamole_token,
            data_source,
            connection_id
        )

    except Exception as e:
        pass
    finally:
        virsh.undefine_vm(cfg.connect_uri, vm.vm_name, remove_all_storage=True)
    return JSONResponse(status_code=200, content={"message": "Success"})

@app.get("/health")
async def health():
    """health check

    Returns:
        dict: health status
    """
    return {"status": "healthy"}

@app.get("/v1/get-images")
async def get_vm_images():
    return { "images": github.get_codespace_releases(PROVISIONER_ENVIRONMENT) }
