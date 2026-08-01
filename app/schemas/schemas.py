from pydantic import BaseModel, Field
from typing import Dict

# vm_name flows into Proxmox native tags (";"/"," are tag separators there),
# cloud-init meta-data YAML, ISO filenames, and Waggle pool names — restrict it
# to safe DNS-style names so it round-trips verbatim through all of them.
VM_NAME_PATTERN = r'^[a-z0-9][a-z0-9.-]{0,62}$'
# image becomes a URL path segment on the download server and a PVE storage
# filename — release-tag charset only (no path separators or traversal).
IMAGE_PATTERN = r'^v[0-9A-Za-z._-]{1,63}$'

class ExistingVm(BaseModel):
    dom_id: str = Field(...,example = "1")
    name: str = Field(...,example = 'dinosaur-cat')
    region_name: str = Field(...,example = 'andromeda')
    state: str = Field(...,example = 'running')
    tags: Dict[str, str] = Field(...,example = {"customkey1": "customvalue1", "customkey2": "customvalue2", "customkey3": "customvalue3"})

class Vm(BaseModel):
    vm_name: str = Field(...,pattern = VM_NAME_PATTERN, example = 'dinosaur-cat')
    tags: dict = Field(...,example = {"owner": "john.doe@example.com"})
    user_data: str = Field(...,example = 'I2Nsb3VkLWNvbmZpZwpydW5jbWQ6CiAgLSBbJ3Bhc3N3ZCcsICctZCcsICdkZWJpYW4nXQo=')
    image: str = Field(...,pattern = IMAGE_PATTERN, example = 'v0.76.0')
    region_name: str = Field(...,example = 'andromeda')
    instance_type: str = Field(...,example = 'basic')

class VmMeta(BaseModel):
    vm_name: str = Field(...,pattern = VM_NAME_PATTERN, example = 'dinosaur-cat')
    region_name: str = Field(...,example = 'andromeda')

class Message(BaseModel):
    message: str = Field(...,example = 'Success')

class VmTags(BaseModel):
    vm_name: str = Field(...,pattern = VM_NAME_PATTERN, example = 'dinosaur-cat')
    region_name: str = Field(...,example = 'andromeda')
    tags: dict = Field(...,example = {"owner": "john.doe@example.com", "description": "New vm description"})
