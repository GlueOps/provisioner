import asyncio, io, re, json, urllib.parse, os
import httpx, pycdlib
import glueops.setup_logging
from . import b64

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logger = glueops.setup_logging.configure(level=LOG_LEVEL)

# Matches the capacity suffix appended to region names, e.g. "-40cpu-96gb-381gb"
_CAPACITY_SUFFIX = re.compile(r'-\d+cpu-\d+gb-\d+gb$')


def _client(cfg):
    headers = {"Authorization": f"PVEAPIToken={cfg.proxmox_token_id}={cfg.proxmox_token_secret}"}
    return httpx.AsyncClient(verify=False, timeout=30.0, headers=headers)


def _base(cfg):
    return f"https://{cfg.proxmox_host}:{cfg.proxmox_port}/api2/json"


async def _get(cfg, path, **params):
    async with _client(cfg) as c:
        r = await c.get(f"{_base(cfg)}{path}", params=params or None)
        r.raise_for_status()
        return r.json()["data"]


async def _post(cfg, path, data=None, files=None):
    async with _client(cfg) as c:
        r = await c.post(f"{_base(cfg)}{path}", data=data, files=files)
        r.raise_for_status()
        return r.json()["data"]


async def _put(cfg, path, data):
    async with _client(cfg) as c:
        r = await c.put(f"{_base(cfg)}{path}", data=data)
        r.raise_for_status()
        return r.json()["data"]


async def _delete(cfg, path, **params):
    async with _client(cfg) as c:
        r = await c.delete(f"{_base(cfg)}{path}", params=params or None)
        r.raise_for_status()
        return r.json()["data"]


async def poll_task(cfg, upid: str):
    task_node = upid.split(":")[1]
    encoded = urllib.parse.quote(upid, safe="")
    while True:
        data = await _get(cfg, f"/nodes/{task_node}/tasks/{encoded}/status")
        if data["status"] == "stopped":
            if data.get("exitstatus") != "OK":
                raise RuntimeError(f"Task failed: {data}")
            return
        await asyncio.sleep(3)


async def get_next_vmid(cfg) -> str:
    return await _get(cfg, "/cluster/nextid")


async def ensure_image_cached(cfg, node: str, image: str, download_url: str):
    content = await _get(cfg, f"/nodes/{node}/storage/{cfg.proxmox_storage}/content", content="import")
    volid = f"{cfg.proxmox_storage}:import/{image}.qcow2"
    if volid in {v["volid"] for v in (content or [])}:
        logger.info(f"Image {image} already cached on {node}")
        return
    logger.info(f"Downloading {image} to {node}")
    try:
        upid = await _post(cfg, f"/nodes/{node}/storage/{cfg.proxmox_storage}/download-url", data={
            "url": f"{download_url}/{image}.qcow2",
            "filename": f"{image}.qcow2",
            "content": "import",
        })
        await poll_task(cfg, upid)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 409:
            # Another download already in progress — wait for it to complete
            logger.info(f"Image {image} download already in progress on {node}, waiting...")
            for _ in range(60):
                await asyncio.sleep(5)
                content = await _get(cfg, f"/nodes/{node}/storage/{cfg.proxmox_storage}/content", content="import")
                if volid in {v["volid"] for v in (content or [])}:
                    return
            raise RuntimeError(f"Timed out waiting for {image} to become available on {node}")
        raise


def build_iso(user_data: bytes, meta_data: bytes) -> bytes:
    iso = pycdlib.PyCdlib()
    iso.new(vol_ident="cidata", rock_ridge="1.09")
    iso.add_fp(io.BytesIO(user_data), length=len(user_data), iso_path="/USERDATA;1", rr_name="user-data")
    iso.add_fp(io.BytesIO(meta_data), length=len(meta_data), iso_path="/METADATA;1", rr_name="meta-data")
    buf = io.BytesIO()
    iso.write_fp(buf)
    iso.close()
    return buf.getvalue()


async def upload_iso(cfg, node: str, vm_name: str, iso_bytes: bytes) -> str:
    iso_filename = f"{vm_name}-cloudinit.iso"
    upid = await _post(
        cfg,
        f"/nodes/{node}/storage/{cfg.proxmox_storage}/upload",
        data={"content": "iso"},
        files={"filename": (iso_filename, io.BytesIO(iso_bytes), "application/octet-stream")}
    )
    await poll_task(cfg, upid)
    return iso_filename


async def eject_and_delete_iso(cfg, node: str, vmid: str, iso_filename: str):
    try:
        await _put(cfg, f"/nodes/{node}/qemu/{vmid}/config", data={"ide2": "none,media=cdrom"})
    except Exception as e:
        logger.error(f"Failed to eject ISO from VM {vmid}: {e}")
    try:
        iso_volid = urllib.parse.quote(f"{cfg.proxmox_storage}:iso/{iso_filename}", safe="")
        await _delete(cfg, f"/nodes/{node}/storage/{cfg.proxmox_storage}/content/{iso_volid}")
    except Exception as e:
        logger.error(f"Failed to delete ISO {iso_filename}: {e}")


async def create_vm(cfg, node: str, vmid: str, vm_name: str, vcpus: int, memory_mb: int, image: str, iso_filename: str, tags: dict):
    upid = await _post(cfg, f"/nodes/{node}/qemu", data={
        "vmid": vmid,
        "name": vm_name,
        "memory": memory_mb,
        "cores": vcpus,
        "cpu": "x86-64-v2-AES",
        "ostype": "l26",
        "agent": "1",
        "virtio0": f"{cfg.proxmox_storage}:0,import-from={cfg.proxmox_storage}:import/{image}.qcow2,iothread=1,format=raw",
        "ide2": f"{cfg.proxmox_storage}:iso/{iso_filename},media=cdrom",
        "boot": "order=virtio0",
        "net0": f"virtio,bridge={cfg.proxmox_bridge}",
        "serial0": "socket",
        "description": b64.encode_string(json.dumps(tags)),
    })
    await poll_task(cfg, upid)


async def resize_disk(cfg, node: str, vmid: str, storage_mb: int):
    result = await _put(cfg, f"/nodes/{node}/qemu/{vmid}/resize", data={"disk": "virtio0", "size": f"{storage_mb}M"})
    if isinstance(result, str) and result.startswith("UPID:"):
        await poll_task(cfg, result)


async def start_vm(cfg, node: str, vmid: str):
    upid = await _post(cfg, f"/nodes/{node}/qemu/{vmid}/status/start")
    await poll_task(cfg, upid)


async def stop_vm(cfg, node: str, vmid: str):
    upid = await _post(cfg, f"/nodes/{node}/qemu/{vmid}/status/stop")
    await poll_task(cfg, upid)


async def delete_vm(cfg, node: str, vmid: str):
    try:
        status_data = await _get(cfg, f"/nodes/{node}/qemu/{vmid}/status/current")
        if status_data.get("status") == "running":
            upid = await _post(cfg, f"/nodes/{node}/qemu/{vmid}/status/stop")
            await poll_task(cfg, upid)
    except Exception as e:
        logger.error(f"Failed to stop VM {vmid} before delete: {e}")
    upid = await _delete(cfg, f"/nodes/{node}/qemu/{vmid}", purge=1)
    await poll_task(cfg, upid)


async def find_vmid_by_name(cfg, node: str, vm_name: str) -> str:
    vms = await _get(cfg, f"/nodes/{node}/qemu")
    for vm in (vms or []):
        if vm.get("name") == vm_name:
            return str(vm["vmid"])
    raise ValueError(f"VM {vm_name!r} not found on node {node}")


async def edit_vm_tags(cfg, node: str, vmid: str, tags: dict):
    await _put(cfg, f"/nodes/{node}/qemu/{vmid}/config", data={
        "description": b64.encode_string(json.dumps(tags))
    })


async def list_vms(cfg) -> list:
    resources = await _get(cfg, "/cluster/resources", type="vm")
    qemu_vms = [r for r in (resources or []) if r.get("type") == "qemu"]

    async def get_vm_details(r):
        tags = {}
        try:
            vm_config = await _get(cfg, f"/nodes/{r['node']}/qemu/{r['vmid']}/config")
            desc = vm_config.get("description", "")
            if desc:
                tags = json.loads(b64.decode_string(desc))
        except Exception:
            pass
        return {
            "dom_id": str(r["vmid"]),
            "name": r.get("name", ""),
            "region_name": f"{cfg.region_name}-{r['node']}",
            "state": r.get("status", "unknown"),
            "tags": tags,
        }

    return list(await asyncio.gather(*[get_vm_details(r) for r in qemu_vms]))


async def get_nodes_with_capacity(cfg) -> list:
    nodes = await _get(cfg, "/nodes")
    results = []
    for n in (nodes or []):
        if n.get("status") != "online":
            continue
        node = n["node"]
        try:
            storage = await _get(cfg, f"/nodes/{node}/storage/{cfg.proxmox_storage}/status")
            free_storage_gb = int(storage.get("avail", 0) // (1024 ** 3))
        except Exception:
            free_storage_gb = 0
        free_vcpus = int(round(n["maxcpu"] * (1 - n.get("cpu", 0))))
        free_memory_gb = int((n["maxmem"] - n.get("mem", 0)) // (1024 ** 3))
        results.append({
            "region_name": f"{cfg.region_name}-{node}-{free_vcpus}cpu-{free_memory_gb}gb-{free_storage_gb}gb",
            "enabled": cfg.enabled,
            "available_instance_types": [it.model_dump() for it in cfg.available_instance_types],
        })
    return results


def parse_proxmox_region_name(region_name: str, configs: list) -> tuple:
    """Strip capacity suffix and find the matching ProxmoxConfig + node name."""
    stable = _CAPACITY_SUFFIX.sub("", region_name)
    for cfg in configs:
        if getattr(cfg, "backend_type", "libvirt") != "proxmox":
            continue
        prefix = cfg.region_name + "-"
        if stable.startswith(prefix):
            node = stable[len(prefix):]
            if node:
                return cfg, node
    raise ValueError(f"No Proxmox config found for region: {region_name}")
