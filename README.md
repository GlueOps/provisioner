# Provisioner

FastAPI service that manages VM lifecycles across distributed regions. Supports two backends:

- **libvirt** — provisions VMs via virt-install over SSH on remote bare-metal nodes
- **Proxmox VE** — provisions VMs via the Proxmox REST API

Both backends register VMs with Guacamole for remote access and integrate with Tailscale for networking.

---

## Prerequisites

- [Devbox](https://www.jetify.com/devbox)
- Docker

## Development

```bash
devbox shell          # enter the dev environment
pipenv install        # install Python dependencies
fastapi dev           # start dev server with hot reload (runs app/main.py)
```

See [`CLAUDE.md`](CLAUDE.md) for architecture details and [`.ai/AGENTS.md`](.ai/AGENTS.md) for module reference and testing patterns.

---

## Configuration

All configuration is passed via environment variables. Create a file called `secrets` with the following:

### Required (all deployments)

```bash
API_TOKEN=                        # bearer token for all API endpoints
PROVISIONER_ENVIRONMENT=          # prod or nonprod (filters available VM images)
DOWNLOAD_SERVER_URL=              # base URL for VM disk images (libvirt regions)
GUACAMOLE_SERVER_URL=
GUACAMOLE_SERVER_USERNAME=
GUACAMOLE_SERVER_PASSWORD=
BASTION_SERVER_IP=
BASTION_SERVER_PORT=
BASTION_SERVER_USER=
BASTION_SERVER_KEY=
TAILSCALE_TAILNET_NAME=
TAILSCALE_API_TOKEN=
BAREMETAL_SERVER_CONFIGS=         # JSON array of region configs (see below)
```

### Required if any Proxmox region is configured

```bash
PROXMOX_DOWNLOAD_SERVER_URL=      # base URL for VM disk images (Proxmox regions)
```

### Optional

```bash
LOG_LEVEL=INFO                    # default: INFO
```

### BAREMETAL_SERVER_CONFIGS format

A JSON array of region config objects. Each entry is either a libvirt (`SSHConfig`) or Proxmox (`ProxmoxConfig`) region, detected by the `backend_type` field (defaults to `"libvirt"`).

**Libvirt region:**
```json
{
  "backend_type": "libvirt",
  "region_name": "us-east-1",
  "enabled": true,
  "host": "10.0.0.1",
  "port": 2222,
  "user": "debian",
  "connect_uri": "qemu+ssh://debian@10.0.0.1:2222/system?keyfile=/app/id_ed25519",
  "available_instance_types": [
    {"instance_type": "2vcpu-8gb-32ssd", "vcpus": 2, "memory_mb": 8192, "storage_mb": 32000}
  ]
}
```

**Proxmox region:**
```json
{
  "backend_type": "proxmox",
  "region_name": "proxmox-cluster-1",
  "enabled": true,
  "proxmox_host": "1.2.3.4",
  "proxmox_port": 8006,
  "proxmox_token_id": "root@pam!tokenid",
  "proxmox_token_secret": "<uuid>",
  "proxmox_storage": "local",
  "proxmox_bridge": "vmbr0",
  "proxmox_verify_ssl": true,
  "available_instance_types": [
    {"instance_type": "2vcpu-8gb-32ssd",    "vcpus": 2,  "memory_mb": 8192,  "storage_mb": 32000},
    {"instance_type": "4vcpu-16gb-32ssd",   "vcpus": 4,  "memory_mb": 16384, "storage_mb": 32000},
    {"instance_type": "20vcpu-52gb-120ssd", "vcpus": 20, "memory_mb": 53248, "storage_mb": 120000}
  ]
}
```

Proxmox region names are dynamic — the API expands each node into a name like `proxmox-cluster-1-node-01-24cpu-48gb-200gb` reflecting live available capacity.

---

## Deployment

### Docker

```bash
docker build -t provisioner:latest .
docker run -d --env-file secrets provisioner:latest
```

### Tailscale ACLs

The provisioner API and its nodes communicate over Tailscale. Example ACL policy:

- `tag:app-prod-provisioner-api` ↔ `tag:app-prod-provisioner-nodes` (mutual access)
- `group:app-prod-provisioner-developers` can reach both
- Per-user workspace tags (e.g. `tag:tim-cook`) allow the [slackbot](https://github.com/GlueOps/slackbot-developer-workspaces) to assign VMs to users

```json
{
  "acls": [
    {
      "action": "accept",
      "src": ["group:app-prod-provisioner-developers"],
      "dst": ["tag:app-prod-provisioner-api:*", "tag:app-prod-provisioner-nodes:*"]
    },
    {
      "action": "accept",
      "src": ["tag:app-prod-provisioner-api"],
      "dst": ["tag:app-prod-provisioner-nodes:*"]
    }
  ],
  "groups": {
    "group:app-prod-provisioner-developers": ["user@example.com"]
  },
  "tagOwners": {
    "tag:app-prod-provisioner-api":   ["group:app-prod-provisioner-developers"],
    "tag:app-prod-provisioner-nodes": ["group:app-prod-provisioner-developers"]
  }
}
```

### Libvirt nodes

- Run `install-server.sh` on each provisioner node
- Assign the appropriate Tailscale tag (e.g. `tag:app-nonprod-provisioner-nodes`)

### Proxmox nodes

- Proxmox VE 8.x with qemu-guest-agent enabled on VM images
- API token with sufficient permissions to create/delete/manage VMs
- Storage pool and network bridge configured per the region config above

---

## CI/CD

- **`container_image.yaml`** — builds and pushes Docker image to ghcr.io on version tags (`v*`)
- **`bump_version.yaml`** — auto-generates new releases every 2 days via shared GlueOps workflow
