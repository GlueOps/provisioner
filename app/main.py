from fastapi import FastAPI, Security, HTTPException, Depends, status, requests, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from typing import Optional, Dict, List
from pydantic import BaseModel, Field
from util import ssh, virt, virsh, formatter, b64, regions, github, guacamole, tailscale, proxmox
import os, glueops.setup_logging, traceback, base64, yaml, tempfile, json, asyncio
from schemas.schemas import ExistingVm, Vm, VmMeta, Message, VmTags


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logger = glueops.setup_logging.configure(level=LOG_LEVEL)
BAREMETAL_SERVER_CONFIGS = os.getenv('BAREMETAL_SERVER_CONFIGS', '[]')
REGIONS = regions.get_region_configs(BAREMETAL_SERVER_CONFIGS)
HAS_PROXMOX = any(getattr(cfg, "backend_type", "libvirt") == "proxmox" for cfg in REGIONS)

try:
    PROVISIONER_ENVIRONMENT = os.environ['PROVISIONER_ENVIRONMENT']
    API_TOKEN = os.environ['API_TOKEN']
    DOWNLOAD_SERVER_URL = os.environ['DOWNLOAD_SERVER_URL']
    GUACAMOLE_SERVER_URL = os.environ['GUACAMOLE_SERVER_URL']
    GUACAMOLE_SERVER_USERNAME = os.environ['GUACAMOLE_SERVER_USERNAME']
    GUACAMOLE_SERVER_PASSWORD = os.environ['GUACAMOLE_SERVER_PASSWORD']
    BASTION_SERVER_IP = os.environ['BASTION_SERVER_IP']
    BASTION_SERVER_PORT = int(os.environ['BASTION_SERVER_PORT'])
    BASTION_SERVER_USER = os.environ['BASTION_SERVER_USER']
    BASTION_SERVER_KEY = os.environ['BASTION_SERVER_KEY']
    TAILSCALE_TAILNET_NAME = os.environ['TAILSCALE_TAILNET_NAME']
    TAILSCALE_API_TOKEN = os.environ['TAILSCALE_API_TOKEN']
except KeyError as e:
    logger.critical(f"Required environment variable {e} is not set")
    raise SystemExit(1)

PROXMOX_DOWNLOAD_SERVER_URL = os.environ.get('PROXMOX_DOWNLOAD_SERVER_URL')
if HAS_PROXMOX and not PROXMOX_DOWNLOAD_SERVER_URL:
    logger.critical("PROXMOX_DOWNLOAD_SERVER_URL is required when Proxmox regions are configured")
    raise SystemExit(1)

api_key_header = APIKeyHeader(name="Authorization")

app = FastAPI()

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    stack_trace = traceback.format_exc()
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal server error occurred.",
            "error": str(exc),
            "traceback": stack_trace,
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


def _remove_guacamole_and_tailscale(vm_name: str):
    guacamole_token, data_source = guacamole.get_data(
        GUACAMOLE_SERVER_URL, GUACAMOLE_SERVER_USERNAME, GUACAMOLE_SERVER_PASSWORD
    )
    connections = guacamole.get_connections(GUACAMOLE_SERVER_URL, guacamole_token, data_source)
    connection_id = guacamole.find_connection_id_by_name(connections, vm_name)
    if connection_id is None:
        logger.warning(f"No matching connection found for VM: {vm_name}. Skipping deletion in Guacamole.")
    else:
        guacamole.delete_vm(GUACAMOLE_SERVER_URL, guacamole_token, data_source, connection_id)

    tailscale_devices = tailscale.get_devices(
        server_name=vm_name,
        tailscale_tailnet_name=TAILSCALE_TAILNET_NAME,
        tailscale_api_token=TAILSCALE_API_TOKEN
    )
    if tailscale_devices['device_id']:
        tailscale.remove_device(TAILSCALE_API_TOKEN, tailscale_devices['device_id'])
    else:
        logger.warning(f"No Tailscale device found for VM: {vm_name}")


@app.post("/v1/create", response_model=Message)
async def create_vm(vm: Vm, api_key: str = Depends(get_api_key)):
    logger.info(vm)
    decoded_user_data = formatter.fix_indentation(base64.b64decode(vm.user_data).decode('utf-8').strip())
    try:
        yaml.safe_load(decoded_user_data)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in user data: {e}")

    # Resolve backend
    proxmox_cfg, node = None, None
    try:
        proxmox_cfg, node = proxmox.parse_proxmox_region_name(vm.region_name, REGIONS)
    except ValueError:
        pass

    if proxmox_cfg is not None:
        vm_specs = next(
            (it for it in proxmox_cfg.available_instance_types if it.instance_type == vm.instance_type),
            None
        )
        if vm_specs is None:
            raise ValueError(f"Instance type {vm.instance_type} not found in region {vm.region_name}")

        vmid = await proxmox.get_next_vmid(proxmox_cfg)
        iso_filename = None
        vm_created = False
        try:
            await proxmox.ensure_image_cached(proxmox_cfg, node, vm.image, PROXMOX_DOWNLOAD_SERVER_URL)
            meta_data = f"instance-id: {vm.vm_name}\nlocal-hostname: {vm.vm_name}\n"
            iso_bytes = proxmox.build_iso(decoded_user_data.encode(), meta_data.encode())
            iso_filename = await proxmox.upload_iso(proxmox_cfg, node, vm.vm_name, iso_bytes)
            await proxmox.create_vm(proxmox_cfg, node, vmid, vm.vm_name, vm_specs.vcpus, vm_specs.memory_mb, vm.image, iso_filename, vm.tags)
            vm_created = True
            await proxmox.resize_disk(proxmox_cfg, node, vmid, vm_specs.storage_mb)
            await proxmox.start_vm(proxmox_cfg, node, vmid)

            guacamole_token, data_source = guacamole.get_data(GUACAMOLE_SERVER_URL, GUACAMOLE_SERVER_USERNAME, GUACAMOLE_SERVER_PASSWORD)
            connection_groups = guacamole.get_connection_groups(GUACAMOLE_SERVER_URL, guacamole_token, data_source)
            owner = vm.tags.get('owner')
            connection_group_id = guacamole.find_group_id_by_name(connection_groups, owner, GUACAMOLE_SERVER_URL, guacamole_token, data_source)
            vm_id = guacamole.create_vm(GUACAMOLE_SERVER_URL, guacamole_token, data_source, connection_group_id, vm.vm_name, BASTION_SERVER_IP, BASTION_SERVER_PORT, BASTION_SERVER_USER, BASTION_SERVER_KEY)
            if owner:
                guacamole.grant_connection_permission(GUACAMOLE_SERVER_URL, guacamole_token, data_source, owner, vm_id)
        except Exception:
            if vm_created:
                try:
                    await proxmox.delete_vm(proxmox_cfg, node, vmid)
                except Exception as cleanup_err:
                    logger.error(f"Compensating delete failed for VM {vmid}: {cleanup_err}")
            raise
        finally:
            if iso_filename:
                await proxmox.eject_and_delete_iso(proxmox_cfg, node, vmid, iso_filename)

        logger.info(vm.tags)
        return JSONResponse(status_code=200, content={"message": "Success"})

    # Libvirt path
    vm_specs = regions.get_instance_specs(vm.region_name, vm.instance_type, REGIONS)
    command = f'bash <(curl -L -o "/var/lib/libvirt/images/{vm.vm_name}.qcow2" "{DOWNLOAD_SERVER_URL}/{vm.image}.qcow2")'
    cfg = regions.get_server_config(vm.region_name, REGIONS)
    ssh.execute_ssh_command(cfg.host, cfg.user, cfg.port, command)

    command = f'qemu-img resize /var/lib/libvirt/images/{vm.vm_name}.qcow2 {vm_specs.storage_mb}M'
    ssh.execute_ssh_command(cfg.host, cfg.user, cfg.port, command)

    try:
        meta_data = yaml.dump({
            "instance-id": vm.vm_name,
            "local-hostname": vm.vm_name,
        })

        with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".user-cloud-config") as user_temp_file:
            user_temp_file.write(decoded_user_data)
            user_temp_file.flush()
            user_temp_file_path = user_temp_file.name

        logger.info(f"User-Data temporary file created at {user_temp_file_path}")

        with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".meta-cloud-config") as meta_temp_file:
            meta_temp_file.write(meta_data)
            meta_temp_file.flush()
            meta_temp_file_path = meta_temp_file.name

        logger.info(f"Meta-Data temporary file created at {meta_temp_file_path}")

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
            user_data=user_temp_file_path,
            meta_data=meta_temp_file_path,
            import_option=True
        )

        guacamole_token, data_source = guacamole.get_data(GUACAMOLE_SERVER_URL, GUACAMOLE_SERVER_USERNAME, GUACAMOLE_SERVER_PASSWORD)
        connection_groups = guacamole.get_connection_groups(GUACAMOLE_SERVER_URL, guacamole_token, data_source)
        owner = vm.tags.get('owner')
        connection_group_id = guacamole.find_group_id_by_name(connection_groups, owner, GUACAMOLE_SERVER_URL, guacamole_token, data_source)
        vm_id = guacamole.create_vm(GUACAMOLE_SERVER_URL, guacamole_token, data_source, connection_group_id, vm.vm_name, BASTION_SERVER_IP, BASTION_SERVER_PORT, BASTION_SERVER_USER, BASTION_SERVER_KEY)
        if owner:
            guacamole.grant_connection_permission(GUACAMOLE_SERVER_URL, guacamole_token, data_source, owner, vm_id)

    except Exception as e:
        logger.error(f"virt-install failed: {e.stderr}")
        raise
    finally:
        if os.path.exists(user_temp_file_path):
            os.remove(user_temp_file_path)
            logger.info(f"User Data temporary file deleted: {user_temp_file_path}")
        if os.path.exists(meta_temp_file_path):
            os.remove(meta_temp_file_path)
            logger.info(f"Meta Data temporary file deleted: {meta_temp_file_path}")

    logger.info(vm.tags)
    return JSONResponse(status_code=200, content={"message": "Success"})


@app.get("/v1/regions", response_model=List[regions.RegionBase])
async def list_regions(api_key: str = Depends(get_api_key)):
    result = []
    for cfg in regions.get_enabled_regions_only(REGIONS):
        if getattr(cfg, "backend_type", "libvirt") == "proxmox":
            nodes = await proxmox.get_nodes_with_capacity(cfg)
            result.extend(nodes)
        else:
            result.append(cfg)
    return result


@app.get("/v1/list", response_model=List[ExistingVm])
async def list_vms(api_key: str = Depends(get_api_key)):
    async def list_vm_for_region(cfg):
        try:
            if getattr(cfg, "backend_type", "libvirt") == "proxmox":
                return await proxmox.list_vms(cfg)
            else:
                logger.info(f"Requesting VM list from: {cfg.connect_uri}")
                return await asyncio.to_thread(virsh.list_vms, cfg)
        except Exception as e:
            logger.error(f"Error listing VMs from {getattr(cfg, 'connect_uri', cfg.region_name)}: {e}")
            logger.error(traceback.format_exc())
            return []

    tasks = [list_vm_for_region(cfg) for cfg in REGIONS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_vms = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Error with region {getattr(REGIONS[i], 'connect_uri', REGIONS[i].region_name)}: {result}")
        elif result:
            all_vms.extend(result)

    return [ExistingVm(**item) for item in all_vms]


@app.post("/v1/start", response_model=Message)
async def start_vm(vm: VmMeta, api_key: str = Depends(get_api_key)):
    try:
        proxmox_cfg, node = proxmox.parse_proxmox_region_name(vm.region_name, REGIONS)
    except ValueError:
        proxmox_cfg, node = None, None

    if proxmox_cfg is not None:
        vmid = await proxmox.find_vmid_by_name(proxmox_cfg, node, vm.vm_name)
        await proxmox.start_vm(proxmox_cfg, node, vmid)
    else:
        cfg = regions.get_server_config(vm.region_name, REGIONS)
        virsh.start_vm(cfg.connect_uri, vm.vm_name)
    return JSONResponse(status_code=200, content={"message": "Success"})


@app.post("/v1/stop", response_model=Message)
async def stop_vm(vm: VmMeta, api_key: str = Depends(get_api_key)):
    try:
        proxmox_cfg, node = proxmox.parse_proxmox_region_name(vm.region_name, REGIONS)
    except ValueError:
        proxmox_cfg, node = None, None

    if proxmox_cfg is not None:
        vmid = await proxmox.find_vmid_by_name(proxmox_cfg, node, vm.vm_name)
        await proxmox.stop_vm(proxmox_cfg, node, vmid)
    else:
        cfg = regions.get_server_config(vm.region_name, REGIONS)
        virsh.destroy_vm(cfg.connect_uri, vm.vm_name)
    return JSONResponse(status_code=200, content={"message": "Success"})


@app.post("/v1/edit-tags", response_model=Message)
async def edit_vm_tags(vm: VmTags, api_key: str = Depends(get_api_key)):
    try:
        proxmox_cfg, node = proxmox.parse_proxmox_region_name(vm.region_name, REGIONS)
    except ValueError:
        proxmox_cfg, node = None, None

    if proxmox_cfg is not None:
        vmid = await proxmox.find_vmid_by_name(proxmox_cfg, node, vm.vm_name)
        await proxmox.edit_vm_tags(proxmox_cfg, node, vmid, vm.tags)
    else:
        cfg = regions.get_server_config(vm.region_name, REGIONS)
        virsh.edit_vm_tags(cfg.connect_uri, vm.vm_name, vm.tags)
    return JSONResponse(status_code=200, content={"message": "Success"})


@app.delete("/v1/delete", response_model=Message)
async def delete_vm(vm: VmMeta, api_key: str = Depends(get_api_key)):
    try:
        proxmox_cfg, node = proxmox.parse_proxmox_region_name(vm.region_name, REGIONS)
    except ValueError:
        proxmox_cfg, node = None, None

    if proxmox_cfg is not None:
        vmid = await proxmox.find_vmid_by_name(proxmox_cfg, node, vm.vm_name)
        try:
            _remove_guacamole_and_tailscale(vm.vm_name)
            await proxmox.delete_vm(proxmox_cfg, node, vmid)
        except Exception as e:
            logger.error(f"Failed to delete VM {vm.vm_name}: {e}")
            raise
        return JSONResponse(status_code=200, content={"message": "Success"})

    # Libvirt path
    cfg = regions.get_server_config(vm.region_name, REGIONS)
    try:
        virsh.destroy_vm(cfg.connect_uri, vm.vm_name)
    except Exception as e:
        logger.error(f"Failed to stop VM {vm.vm_name}: {e}")

    try:
        _remove_guacamole_and_tailscale(vm.vm_name)
        virsh.undefine_vm(cfg.connect_uri, vm.vm_name, remove_all_storage=True)
    except Exception as e:
        logger.error(f"Failed to delete VM {vm.vm_name}: {e}")
        raise

    return JSONResponse(status_code=200, content={"message": "Success"})


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/v1/get-images")
async def get_vm_images():
    return {"images": github.get_codespace_releases(PROVISIONER_ENVIRONMENT)}
