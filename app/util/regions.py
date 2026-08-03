from typing import List, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator
import os, re, glueops.setup_logging, json

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logger = glueops.setup_logging.configure(level=LOG_LEVEL)


class InstanceType(BaseModel):
    instance_type: str
    vcpus: int
    memory_mb: int
    storage_mb: int


class RegionBase(BaseModel):
    region_name: str
    enabled: bool
    # sish host codespace VMs in this region tunnel to (e.g.
    # "nyc1.tunnels.cde.glueopshosted.com"). Required: there is no central
    # tunnel to fall back to, so a region without one cannot serve CDEs and
    # should fail at config load rather than at VM-create time.
    tunnel_endpoint: str

    @field_validator("tunnel_endpoint")
    @classmethod
    def validate_tunnel_endpoint(cls, v: str) -> str:
        # Bare hostname only — no scheme, port, path, or userinfo. A malformed
        # value must fail startup rather than propagate: downstream it becomes
        # a permanent VM tag, the access URL, and the endpoint the VM's
        # autossh dials, so a bad value means dead URLs for the VM's life.
        # DNS is case-insensitive and a trailing dot is equivalent, so
        # normalize rather than merely validate — the value is compared and
        # concatenated as an exact string by every consumer.
        v = v.strip().lower().removesuffix(".")
        if not v:
            raise ValueError("tunnel_endpoint must not be empty")
        label = r"[a-z0-9]([a-z0-9-]*[a-z0-9])?"
        if not re.fullmatch(rf"{label}(\.{label})*", v):
            raise ValueError(f"invalid tunnel_endpoint {v!r}: must be a bare hostname")
        if v == "tunnels.glueopshosted.com":
            raise ValueError(
                "tunnel_endpoint is the retired central tunnel; use this region's "
                "<region>.tunnels.cde.glueopshosted.com endpoint"
            )
        return v
    # Libvirt regions declare instance types in config; Proxmox regions get
    # theirs from Waggle slots at request time, so the field defaults empty.
    available_instance_types: List[InstanceType] = []
    total_vcpus: Optional[int] = None
    total_memory_gb: Optional[int] = None
    total_storage_gb: Optional[int] = None
    free_vcpus: Optional[int] = None
    free_memory_gb: Optional[int] = None
    free_storage_gb: Optional[int] = None
    cpu_pct: Optional[int] = None
    ram_pct: Optional[int] = None


class SSHConfig(RegionBase):
    backend_type: str = "libvirt"
    # Required for libvirt (re-declared without the RegionBase default): a
    # typo'd key in config should fail startup, not silently offer no sizes.
    available_instance_types: List[InstanceType]
    user: str
    host: str
    port: int
    connect_uri: str = ""

    @model_validator(mode='after')
    def set_connect_uri(self) -> 'SSHConfig':
        self.connect_uri = f'qemu+ssh://{self.user}@{self.host}:{self.port}/system'
        return self


class ProxmoxConfig(RegionBase):
    """One Waggle datacenter backed by one Proxmox cluster.

    Waggle decides which hypervisor each VM lands on; the Proxmox credentials
    here are what the provisioner uses to actually create the VMs (Waggle
    stores its own Proxmox token write-only and never returns it).
    """
    backend_type: str = "proxmox"
    # Waggle org this datacenter belongs to. Each region entry carries its own
    # credentials, so different regions can live in different Waggle orgs or
    # servers; entries sharing the same url+key share one client.
    waggle_api_url: str
    waggle_api_key: str = Field(exclude=True)
    # Waggle datacenter this region maps to; defaults to region_name.
    waggle_datacenter_name: Optional[str] = None
    proxmox_host: str
    proxmox_port: int = 8006
    proxmox_token_id: str = Field(exclude=True)
    proxmox_token_secret: str = Field(exclude=True)
    proxmox_storage: str
    proxmox_bridge: str
    proxmox_vlan_tag: Optional[int] = None
    proxmox_verify_ssl: bool = True

    @model_validator(mode='after')
    def default_datacenter_name(self) -> 'ProxmoxConfig':
        if not self.waggle_datacenter_name:
            self.waggle_datacenter_name = self.region_name
        return self


def load_configs_from_env(server_configs) -> List[Union[SSHConfig, ProxmoxConfig]]:
    try:
        configs = json.loads(server_configs)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid BAREMETAL_SERVER_CONFIGS JSON: {e}")
        raise ValueError(f"Invalid BAREMETAL_SERVER_CONFIGS JSON: {e}")

    result = []
    for cfg in configs:
        if cfg.get("backend_type", "libvirt") == "proxmox":
            result.append(ProxmoxConfig(**cfg))
        else:
            result.append(SSHConfig(**cfg))
    return result


def get_region_configs(server_configs):
    return load_configs_from_env(server_configs)


def get_server_config(region_name, configs):
    for cfg in configs:
        if cfg.region_name == region_name:
            return cfg
    logger.error(f"Region {region_name} not found in configs")
    raise ValueError(f"Region {region_name} not found in configs")


def get_enabled_regions_only(configs):
    return [cfg for cfg in configs if cfg.enabled]


def get_instance_specs(region_name, instance_type, configs):
    cfg = get_server_config(region_name, configs)
    for instance in cfg.available_instance_types:
        if instance.instance_type == instance_type:
            return instance
    logger.error(f"Instance type {instance_type} not found in region {region_name}")
    raise ValueError(f"Instance type {instance_type} not found in region {region_name}")


def load_configs_from_file(file_path: str) -> List[Union[SSHConfig, ProxmoxConfig]]:
    with open(file_path, 'r') as f:
        configs = json.load(f)
    result = []
    for cfg in configs:
        if cfg.get("backend_type", "libvirt") == "proxmox":
            result.append(ProxmoxConfig(**cfg))
        else:
            result.append(SSHConfig(**cfg))
    return result
