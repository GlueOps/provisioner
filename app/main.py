from fastapi import FastAPI, Security, HTTPException, Depends, status
from fastapi.security import APIKeyHeader
from typing import Optional
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
import os

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
    image: str = Field(...,example = 'v0.72.0')

def get_api_key(api_key: Optional[str] = Security(api_key_header)):
    if api_key == API_TOKEN:
        return api_key
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Token",
            headers={"WWW-Authenticate": "Bearer"},
        )

@app.get("/protected")
def another_protected(api_key: str = Depends(get_api_key)):
    return {"info": "This is a protected route"}

@app.post("/v1/create")
async def create_vm(vm: Vm):
    return vm

@app.get("/health")
async def health():
    """health check

    Returns:
        dict: health status
    """
    return {"status": "healthy"}
