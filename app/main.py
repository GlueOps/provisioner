from fastapi import FastAPI, Security, HTTPException, Depends, status, requests
from fastapi.security import APIKeyHeader
from typing import Optional
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
from util import ssh, virt, virsh
import os, glueops.setup_logging, traceback

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logger = glueops.setup_logging.configure(level=LOG_LEVEL)

#ENV variables
SSH_USER = os.getenv('SSH_USER')
SSH_HOST = os.getenv('SSH_HOST')
SSH_PORT = os.getenv('SSH_PORT')
API_TOKEN = os.getenv('API_TOKEN')

CONNECT_URI = f'qemu+ssh://{SSH_USER}@{SSH_HOST}:{SSH_PORT}/system'

api_key_header = APIKeyHeader(name="Authorization")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup function to test env variables
    crashes if env variables are not set

    Args:
        app (FastAPI)

    Raises:
        Exception: env variables not set
    """
    
    required_env_vars = ["SSH_USER", "SSH_HOST", "SSH_PORT", "API_TOKEN"]

    for var in required_env_vars:
        if var not in os.environ:
            raise Exception(f"Environment variable {var} is not set.")
    yield

#define the FastAPI app with lifespan
#for startup function

app = FastAPI()
# app = FastAPI(lifespan=lifespan)

class Vm(BaseModel):
    vm_name: str = Field(...,example = 'dinosaur-cat')
    tags: dict = Field(...,example = {"owner": {"name": "john-doe"}})
    user_data: str = Field(...,example = 'cloud-init user data string')
    image: str = Field(...,example = 'v0.72.0-rc4')

class VmMeta(BaseModel):
    vm_name: str = Field(...,example = 'dinosaur-cat')

def get_api_key(api_key: Optional[str] = Security(api_key_header)):
    if api_key == API_TOKEN:
        return api_key
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Token",
            headers={"WWW-Authenticate": "Bearer"},
        )

@app.post("/v1/create")
async def create_vm(vm: Vm, api_key: str = Depends(get_api_key)):
    logger.info(vm)
    command = f'TAG={vm.image} VM_NAME={vm.vm_name} bash <(curl https://raw.githubusercontent.com/GlueOps/development-only-utilities/refs/tags/v0.23.1/tools/developer-setup/download-qcow2-image.sh)'
    # ssh.execute_ssh_command(SSH_HOST, SSH_USER, SSH_PORT, command)
    file = ssh.execute_ssh_command(SSH_HOST, SSH_USER, SSH_PORT, f'userDataFile=$(mktemp) && echo -e "{vm.user_data}" > "$userDataFile"')

    virt.create_virtual_machine(
        connect=CONNECT_URI,
        name=f"{vm.vm_name}",
        metadata_description=vm.tags,
        ram=10240,
        vcpus=2,
        disk_path=f"/var/lib/libvirt/images/{vm.vm_name}.qcow2",
        disk_format="qcow2",
        os_variant="linux2022",
        network_bridge="virbr0",
        network_model="virtio",
        user_data=file,
        import_option=True
    )

    ssh.execute_ssh_command(SSH_HOST, SSH_USER, SSH_PORT, f'rm {file}')

    return 'Success'

@app.get("/v1/list")
async def list_vms(api_key: str = Depends(get_api_key)):
    return virsh.list_vms(CONNECT_URI)

@app.post("/v1/start")
async def start_vm(vm: VmMeta, api_key: str = Depends(get_api_key)):
    virsh.start_vm(CONNECT_URI, vm.vm_name)
    return 'Success'
    
@app.post("/v1/stop")
async def stop_vm(vm: VmMeta, api_key: str = Depends(get_api_key)):
    virsh.destroy_vm(CONNECT_URI, vm.vm_name)
    return 'Success'

@app.delete("/v1/delete")
async def delete_vm(vm: VmMeta, api_key: str = Depends(get_api_key)):
    try:
        virsh.destroy_vm(CONNECT_URI, vm.vm_name)
    except Exception as e:
        pass
    finally:
        virsh.undefine_vm(CONNECT_URI, vm.vm_name, remove_all_storage=True)
    return 'Success'

@app.get("/health")
async def health():
    """health check

    Returns:
        dict: health status
    """
    return {"status": "healthy"}
