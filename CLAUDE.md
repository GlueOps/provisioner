# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

Provisioner is a FastAPI service that manages VM lifecycles across distributed regions. It supports two backends: **libvirt** (provisions VMs via virt-install over SSH) and **Proxmox VE** (provisions VMs via the Proxmox REST API). Both backends register VMs with Guacamole for remote access and integrate with Tailscale for networking. All operations are multi-region: requests fan out across configured regions.

## Development Commands

```bash
devbox shell          # Enter the dev environment (required before other commands)
pipenv install        # Install Python dependencies
fastapi dev           # Start dev server with hot reload (runs app/main.py)
devbox run fix_cffi   # Fix cffi installation issues if they arise
```

**Docker:**
```bash
docker build -t provisioner:latest .
docker run -it --env-file secrets provisioner:latest
```

There are no automated tests or linting tools configured in this project.

## Architecture

**Entry point:** `app/main.py` — defines all FastAPI endpoints and wires together the utility modules. Every endpoint requires an `Authorization` header validated against `API_TOKEN`.

**Utility modules** (`app/util/`):
- `ssh.py` — Paramiko-based SSH execution on remote provisioner nodes; the bridge between this API and remote libvirt hosts
- `virt.py` — Builds and executes `virt-install` commands for VM creation (cloud-init integration, disk image download + resize)
- `virsh.py` — Wraps `virsh` commands: destroy, start, undefine, list, edit-tags; list operations run concurrently via `asyncio.to_thread()`
- `proxmox.py` — All Proxmox VE REST API logic: image caching, pycdlib ISO build/upload/eject, VM create/resize/start/stop/delete, cluster list, tag editing, per-node capacity queries, region name parsing
- `regions.py` — Parses `BAREMETAL_SERVER_CONFIGS` env var into `RegionBase`, `SSHConfig` (libvirt), and `ProxmoxConfig` Pydantic models
- `guacamole.py` — Creates/deletes Guacamole connections and grants ownership to the VM creator
- `tailscale.py` — Removes Tailscale devices when VMs are deleted
- `github.py` — Fetches available VM images from GitHub releases (filtered by `PROVISIONER_ENVIRONMENT`)
- `b64.py` / `formatter.py` — Base64 encode/decode and string indentation helpers

**Data models:** `app/schemas/schemas.py` — Pydantic models: `Vm` (create request), `ExistingVm` (list response), `VmMeta`, `VmTags`.

## Key Patterns

**Backend routing:** Each endpoint calls `proxmox.parse_proxmox_region_name()` first; if it matches a Proxmox cluster config the Proxmox path runs, otherwise the libvirt path runs unchanged. Proxmox region names are dynamic strings like `{cluster}-{node}-{free_vcpu}cpu-{free_gb}gb-{free_storage_gb}gb` — the capacity suffix is stripped at request time to recover the stable cluster+node identifier.

**VM metadata storage:** Tags/metadata are JSON-serialized then base64-encoded and stored in the VM description field. `b64.py` handles encoding; `virsh.py` reads/writes it for libvirt, `proxmox.py` reads/writes it for Proxmox.

**Multi-region fan-out:** The `/v1/list` endpoint gathers results from all regions concurrently using `asyncio.gather()`. Proxmox regions use `GET /cluster/resources?type=vm`; libvirt regions use `virsh list`. The `/v1/regions` endpoint queries each Proxmox cluster live on every request and expands each cluster into per-node entries with current free capacity in the name.

**Proxmox cloud-init:** VM creation builds a cidata ISO with pycdlib (Rock Ridge, `vol_ident="cidata"`) containing `user-data` and `meta-data`, uploads it to Proxmox storage, attaches it as `ide2`, then ejects and deletes it after the VM starts. `serial0: socket` is set on all Proxmox VMs to prevent a Debian 12 kernel panic after disk resize.

**Proxmox image caching:** Disk images are downloaded once per node into import storage (`{storage}:import/{image}.qcow2`) and reused across VMs. The cache is never evicted. Concurrent download races are handled by catching 409 and polling until the image appears.

**Error handling:** A global FastAPI exception handler returns full stack traces. Individual modules log errors with `glueops.setup_logging.configure()`. Proxmox VM creates include a compensating `delete_vm` if any step after VM definition fails.

## Required Environment Variables

| Variable | Purpose |
|---|---|
| `API_TOKEN` | Bearer token for all API endpoints |
| `PROVISIONER_ENVIRONMENT` | `prod` or `nonprod` (filters GitHub image releases) |
| `DOWNLOAD_SERVER_URL` | Base URL for VM disk images (libvirt regions) |
| `PROXMOX_DOWNLOAD_SERVER_URL` | Base URL for VM disk images (Proxmox regions); required only if any Proxmox region is configured |
| `BAREMETAL_SERVER_CONFIGS` | JSON array of region configs — libvirt (`SSHConfig`) or Proxmox (`ProxmoxConfig`) entries; detected by `backend_type` field (defaults to `"libvirt"`) |
| `GUACAMOLE_SERVER_URL` / `_USERNAME` / `_PASSWORD` | Guacamole credentials |
| `BASTION_SERVER_IP` / `_PORT` / `_USER` / `_SSH_KEY` | Bastion host for Guacamole connections |
| `TAILSCALE_TAILNET_NAME` / `TAILSCALE_API_TOKEN` | Tailscale integration |
| `LOG_LEVEL` | Logging level (default: INFO) |

### Proxmox region config fields

```json
{
  "backend_type": "proxmox",
  "region_name": "proxmox-cluster-1",
  "enabled": true,
  "proxmox_host": "1.2.3.4",
  "proxmox_port": 8006,
  "proxmox_token_id": "root@pam!tokenid",
  "proxmox_token_secret": "...",
  "proxmox_storage": "local",
  "proxmox_bridge": "vmbr_nat",
  "available_instance_types": [
    {"instance_type": "2vcpu-8gb-32ssd",    "vcpus": 2,  "memory_mb": 8192,  "storage_mb": 32000},
    {"instance_type": "4vcpu-8gb-32ssd",    "vcpus": 4,  "memory_mb": 8192,  "storage_mb": 32000},
    {"instance_type": "4vcpu-16gb-32ssd",   "vcpus": 4,  "memory_mb": 16384, "storage_mb": 32000},
    {"instance_type": "20vcpu-32gb-120ssd", "vcpus": 20, "memory_mb": 32768, "storage_mb": 120000},
    {"instance_type": "20vcpu-52gb-120ssd", "vcpus": 20, "memory_mb": 53248, "storage_mb": 120000}
  ]
}
```

## CI/CD

- **`container_image.yaml`** — Builds and pushes Docker image to ghcr.io on version tags (`v*`)
- **`bump_version.yaml`** — Scheduled every 2 days to auto-generate new releases via shared GlueOps workflow
