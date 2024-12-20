from dataclasses import dataclass
from typing import List, Any
from pydantic import BaseModel, Field
import os, glueops.setup_logging, traceback, json

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logger = glueops.setup_logging.configure(level=LOG_LEVEL)



class InstanceType(BaseModel):
    instance_type: str
    vcpus: int
    memory_mb: int
    storage_mb: int

class SSHConfig(BaseModel):
    user: str
    host: str
    port: int
    region_name: str
    enabled: bool
    available_instance_types: List[InstanceType]

    connect_uri: str = Field(default=None)

    def __init__(self, **data):
        # Initialize the object with Pydantic's internal __init__
        super().__init__(**data)
        
        # Now we can set connect_uri using self.user, self.host, and self.port
        self.connect_uri = f'qemu+ssh://{self.user}@{self.host}:{self.port}/system'


def load_configs_from_env(server_configs) -> List[SSHConfig]:
    try:
        configs = json.loads(server_configs)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid BAREMETAL_SERVER_CONFIGS JSON: {e}")
        raise ValueError(f"Invalid BAREMETAL_SERVER_CONFIGS JSON: {e}")

    return [SSHConfig(**cfg) for cfg in configs]

def get_region_configs(server_configs):
    return load_configs_from_env(server_configs)


def get_server_config(region_name, ssh_configs):
    for cfg in ssh_configs:
        if cfg.region_name == region_name:
            return cfg
    logger.error(f"Region {region_name} not found in SSH configs")
    raise ValueError(f"Region {region_name} not found in SSH configs")

def get_enabled_regions_only(ssh_configs):
    regions = []
    for cfg in ssh_configs:
        if cfg.enabled == True:
            regions.append(cfg)
    return regions


def get_instance_specs(region_name, instance_type, ssh_configs):
    cfg = get_server_config(region_name, ssh_configs)
    for instance in cfg.available_instance_types:
        if instance.instance_type == instance_type:
            return instance
    logger.error(f"Instance type {instance_type} not found in region {region_name}")
    raise ValueError(f"Instance type {instance_type} not found in region {region_name}")

def load_configs_from_file(file_path: str) -> List[SSHConfig]:
    with open(file_path, 'r') as f:
        configs = json.load(f)
    return [SSHConfig(**cfg) for cfg in configs]
