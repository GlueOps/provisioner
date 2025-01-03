from pydantic import BaseModel, Field
from typing import Dict

class ExistingVm(BaseModel):
    dom_id: int = Field(...,example = 1)
    name: str = Field(...,example = 'dinosaur-cat')
    region_name: str = Field(...,example = 'andromeda')
    state: str = Field(...,example = 'running')
    tags: Dict[str, str] = Field(...,example = {"customkey1": "customvalue1", "customkey2": "customvalue2", "customkey3": "customvalue3"})

class Vm(BaseModel):
    vm_name: str = Field(...,example = 'dinosaur-cat')
    tags: dict = Field(...,example = {"owner": "john-doe"})
    user_data: str = Field(...,example = 'I2Nsb3VkLWNvbmZpZwpydW5jbWQ6CiAgLSBbJ3Bhc3N3ZCcsICctZCcsICdkZWJpYW4nXQo=')
    image: str = Field(...,example = 'v0.72.0-rc4')
    region_name: str = Field(...,example = 'andromeda')
    instance_type: str = Field(...,example = 'small')

class VmMeta(BaseModel):
    vm_name: str = Field(...,example = 'dinosaur-cat')
    region_name: str = Field(...,example = 'andromeda')

class Message(BaseModel):
    message: str = Field(...,example = 'Success')
