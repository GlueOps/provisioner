# Provisioner

FastAPI service that manages VM lifecycles across distributed regions. Supports two backends:

- **libvirt** — provisions VMs via virt-install over SSH on remote bare-metal nodes
- **Waggle-backed Proxmox VE** — [Waggle](https://github.com/glueops/waggle) is the placement oracle: one provisioner region == one Waggle datacenter == one Proxmox cluster. Waggle decides which hypervisor each VM lands on (anti-affinity, all-or-nothing); the provisioner then creates the VM on that node via the Proxmox REST API and backfills the vmid onto the Waggle placement. Instance types are Waggle *slots*, pre-filtered against Waggle's hypervisor ledger so `/v1/regions` only lists slots that can be placed right now.

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

Waggle credentials are **per region entry** (`waggle_api_url` / `waggle_api_key` in `BAREMETAL_SERVER_CONFIGS`), not env vars — different regions can belong to different Waggle orgs or servers.

```bash
```

### Optional

```bash
LOG_LEVEL=INFO                    # default: INFO
PROXMOX_IMAGE_CACHE_KEEP=5        # newest N offered image versions kept cached on Proxmox storage (default: 5);
                                  # older cached versions are pruned during VM deletes and re-download on demand
```

### BAREMETAL_SERVER_CONFIGS format

A JSON array of region config objects. Each entry is either a libvirt (`SSHConfig`) or Proxmox (`ProxmoxConfig`) region, detected by the `backend_type` field (defaults to `"libvirt"`).

**Libvirt region:**
```json
{
  "backend_type": "libvirt",
  "region_name": "us-east-1",
  "tunnel_endpoint": "us-east-1.tunnels.cde.glueopshosted.com",
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

**Proxmox region** (one per Waggle datacenter — the datacenter, hypervisors, and slots must already exist in Waggle):
```json
{
  "backend_type": "proxmox",
  "region_name": "proxmox-cluster-1",
  "tunnel_endpoint": "proxmox-cluster-1.tunnels.cde.glueopshosted.com",
  "enabled": true,
  "waggle_api_url": "https://waggle.example.com",
  "waggle_api_key": "wgl_...",
  "waggle_datacenter_name": "proxmox-cluster-1",
  "proxmox_host": "1.2.3.4",
  "proxmox_port": 8006,
  "proxmox_token_id": "root@pam!tokenid",
  "proxmox_token_secret": "<uuid>",
  "proxmox_storage": "local",
  "proxmox_bridge": "vmbr0",
  "proxmox_vlan_tag": null,
  "proxmox_verify_ssl": true
}
```

- `waggle_datacenter_name` defaults to `region_name` when omitted.
- The Proxmox credentials here are what the provisioner uses to create VMs — Waggle stores its own Proxmox token write-only for hypervisor discovery and never returns it.
- No `available_instance_types`: instance types are Waggle slots (org-level, shared by all datacenters).

The Proxmox region name is the cluster/datacenter name (e.g. `proxmox-cluster-1`) — the hypervisor is chosen by Waggle at create time and never appears in the region name. Each region entry in the `/v1/regions` response lists only the Waggle slots that can currently be placed (i.e. fit within the bookable capacity of at least one schedulable hypervisor): if a slot is listed, a VM can be created with it right now.

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

### Onboarding a new Proxmox datacenter

Prerequisites: Proxmox VE **8.4+** (the image cache uses the `download-url` import content type introduced in 8.4), qemu-guest-agent enabled in the VM images, and a storage pool + network bridge configured on every node.

Do these **in order** — the region only works once all of them exist:

1. **Create the datacenter in Waggle** (UI, API, or the terraform provider) with the cluster's PVE API URL and a *read-only* PVE token for discovery. Name it exactly what you'll use as the region's `region_name` (or set `waggle_datacenter_name` explicitly in the region config).
2. **Run hypervisor discovery** (`POST /datacenters/{id}/discover`). This creates one Waggle hypervisor per Proxmox node with its live capacity.
3. **Set operator capacity policy per hypervisor**: `reserved` headroom and the `schedulable` flag. Both are preserved across re-discovery; set `schedulable: false` to drain a node for maintenance.
4. **Ensure slots exist** (org-level, shared by all datacenters). Slot names are exactly the instance types users see in the Slack dropdown; `vcpu`/`ram_gb`/`disk_gb` are what gets provisioned.
5. **Create a PVE API token for the provisioner** — separate from Waggle's discovery token — with permission to create/delete/configure VMs and upload to the storage pool.
6. **Stand up the region's tunnel endpoint** — all four artifacts, in order, or cert issuance stalls:
   1. add `<region>` and `*.<region>` to `module.acme_dns01_user_cde.cert_domains` in **aws-dns-production** so the box's ACME user may write that region's `_acme-challenge` records;
   2. in **aws-cloud-development-environment-assets-production**, add the region with `create_distribution = false`, apply, and copy the emitted `acm_validation_record_entry` into aws-dns-production along with the region's A records (`<region>.tunnels.cde`, `origin.<region>.tunnels.cde`);
   3. flip `create_distribution = true`, apply, and copy the emitted `wildcard_cname_entry` (`*.<region>.tunnels.cde`) into aws-dns-production;
   4. deploy the sish stack (**GlueOps/cde-sish-tunnels**) on the box with `DOMAIN=<region>.tunnels.cde.glueopshosted.com` and the ACME credentials, then smoke-test a tunnel.

   CDE VMs in this region cannot come up without it.
7. **Add the region entry** to `BAREMETAL_SERVER_CONFIGS` (see format above) with the org's `waggle_api_url`/`waggle_api_key`, the datacenter's Proxmox credentials, and the **required** `tunnel_endpoint` from step 6 — a bare hostname; the provisioner refuses to start if any region omits it or if it is malformed. Make sure `PROXMOX_DOWNLOAD_SERVER_URL` is set, and deploy.
8. **Verify**: `GET /v1/regions` must list the region with the expected slots. A region that silently disappears from the response means its Waggle lookup failed — check the provisioner logs for `Skipping region <name>`.

> ⚠️ **Load-bearing invariant: Waggle hypervisor names must equal Proxmox node names.** The provisioner uses a placement's `hypervisor_name` verbatim as the node in Proxmox API paths. Discovery guarantees this automatically — never hand-create hypervisor entries in Waggle with different names, or every create in that datacenter will fail.

---

## CI/CD

- **`container_image.yaml`** — builds and pushes Docker image to ghcr.io on version tags (`v*`)
- **`bump_version.yaml`** — auto-generates new releases every 2 days via shared GlueOps workflow
