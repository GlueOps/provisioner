# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **For AI agents:** See [`.ai/AGENTS.md`](.ai/AGENTS.md) for module imports, test script patterns, Proxmox API reference, key invariants, and debugging guidance.


## What This Project Does

Provisioner is a FastAPI service that manages VM lifecycles across distributed regions. It supports two backends: **libvirt** (provisions VMs via virt-install over SSH) and **Waggle-backed Proxmox VE**. [Waggle](https://github.com/glueops/waggle) is the placement oracle: one provisioner region == one Waggle datacenter == one Proxmox cluster. Creating a VM creates a single-VM Waggle pool, reads back the placement's hypervisor, provisions the VM there via the Proxmox REST API (through the `glueops-helpers` `ProxmoxClient`/`WaggleClient`), and backfills the vmid onto the placement. Both backends register VMs with Guacamole for remote access and integrate with Tailscale for networking. All operations are multi-region: requests fan out across configured regions.

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
- `proxmox.py` — Waggle-backed Proxmox orchestration built on `glueops.proxmox.ProxmoxClient` and `glueops.waggle.WaggleClient` (from the glueops-helpers library): pool-per-VM placement, vmid backfill, VM create/start/stop/delete/edit-tags, tag-based VM discovery, placeable-slot availability for `/v1/regions`
- `regions.py` — Parses `BAREMETAL_SERVER_CONFIGS` env var into `RegionBase`, `SSHConfig` (libvirt), and `ProxmoxConfig` (one Waggle datacenter + the Proxmox credentials to provision into it) Pydantic models
- `guacamole.py` — Creates/deletes Guacamole connections and grants ownership to the VM creator
- `tailscale.py` — Removes Tailscale devices when VMs are deleted
- `github.py` — Fetches available VM images from GitHub releases (filtered by `PROVISIONER_ENVIRONMENT`)
- `b64.py` / `formatter.py` — Base64 encode/decode and string indentation helpers

**Data models:** `app/schemas/schemas.py` — Pydantic models: `Vm` (create request), `ExistingVm` (list response), `VmMeta`, `VmTags`.

## Key Patterns

**Backend routing:** Each endpoint calls `proxmox.get_proxmox_config()` first; if the region name exactly matches a Proxmox region config the Proxmox path runs, otherwise the libvirt path runs unchanged. A Proxmox region name is the Waggle datacenter / cluster name (e.g. `proxmox-cluster-1`) — the hypervisor is chosen by Waggle at create time and never appears in the region name. Availability is expressed by which slots are listed in `available_instance_types`; the legacy capacity fields on the region object always serialize as `null`.

**Waggle placement (Proxmox creates):** `proxmox.create()` looks up the datacenter (`waggle_datacenter_name`) and the slot named by the request's `instance_type`, creates a Waggle pool named `cde-codespaces-{vm_name}` with `desired_count=1`, and provisions the VM on the placement's hypervisor. The vmid backfill onto the placement is best-effort bookkeeping — a Waggle blip there logs a warning and never triggers compensation against a healthy VM. On real failures the VM (if created) is deleted and the pool released; if the VM deletion itself fails the pool is intentionally kept so Waggle doesn't overbook the hypervisor. Deleting a VM removes it from Proxmox first and only then deletes the Waggle pool, for the same reason. Create and delete are serialized per `(region, vm_name)` via module-level `asyncio.Lock`s (assumes the single-worker `fastapi run` deployment), and delete is idempotent under retry: an already-gone VM or Waggle pool (404) is treated as success. A failed pool create raises `PlacementError` (→ HTTP 409 "at capacity"); unknown datacenter/slot raises `UnknownTargetError` (→ HTTP 422, a dedicated type so a `KeyError` from a malformed Waggle response can't masquerade as a client error). Neither provisions anything nor triggers compensation. There is deliberately no duplicate-name guard on create: callers (the slackbot) generate a unique random name per request and never retry, so an existing-VM check would be dead code — a duplicate create is a known-and-accepted non-scenario. Pool cleanup on delete is scoped to the region's datacenter (`datacenter_id` filter) so a same-named pool elsewhere is never released, and the datacenter is resolved before any destruction so a Waggle outage fails the delete cleanly up front. Every managed VM carries native Proxmox tags `[glueops-provisioner, cde, codespaces, {vm_name}]`; find/start/stop/delete/list match on `glueops-provisioner` + `{vm_name}` only (cluster-wide) — `cde`/`codespaces` are informational labels for the PVE UI and deliberately not part of the identity match. Tags alone don't authorize destruction: before acting on a matched VM, the `managed-by: github.com/GlueOps/provisioner` marker in its description is verified as a second factor (tags are hand-editable in the PVE UI; the description marker is set at create). A tagged-but-unmarked VM is skipped, and the delete then **fails and keeps the Waggle pool** — as long as anything tagged with that name may occupy a hypervisor, the capacity stays booked. `vm_name` and `image` are pattern-validated at the API boundary (`app/schemas/schemas.py`) so they round-trip safely through Proxmox tags, cloud-init YAML, ISO filenames, and URL paths.

**VM metadata storage:** Tags/metadata are JSON-serialized, base64-encoded, and stored in the VM description field. For Proxmox, the description is a YAML document with a human-readable warning header, a `managed-by` key, and a `data` key containing the base64 blob. `_encode_description`/`_decode_description` in `proxmox.py` handle the format; `virsh.py` reads/writes raw base64 for libvirt.

**Multi-region fan-out:** The `/v1/list` endpoint gathers results from all regions concurrently using `asyncio.gather()`. Proxmox regions find managed VMs by the `glueops-provisioner` native tag; libvirt regions use `virsh list`. The `/v1/regions` endpoint returns one entry per Proxmox region (datacenter) whose `available_instance_types` are the Waggle slots that can currently be placed — a slot is listed iff it fits within the bookable capacity (total − reserved − used) of at least one schedulable hypervisor (`WaggleClient.list_available_slots`). Slot fields map `name`/`vcpu`/`ram_gb`/`disk_gb` → `instance_type`/`vcpus`/`memory_mb`/`storage_mb`. No live Proxmox scans, no per-node region expansion, no capacity fields, and no "(Over Allocated)" instance-type suffix — a listed slot is creatable right now; if capacity races away, pool creation fails all-or-nothing.

**Proxmox cloud-init:** VM creation builds a cidata ISO with `glueops.proxmox.build_cloudinit_iso` (pycdlib, Rock Ridge, `vol_ident="cidata"`) containing `user-data` and `meta-data`, uploads it to Proxmox storage, and attaches it as `ide2`. After the VM starts, `ProxmoxClient.wait_for_cloud_init` polls the qemu-guest-agent until `/var/lib/cloud/instance/boot-finished` exists (cloud-init's own completion marker), then the ISO is ejected and deleted. The ISO eject is in a `finally` block — it always runs even if cloud-init times out; after `/v1/delete` responds, a fire-and-forget background task sweeps orphaned `cde-codespaces-{vm_name}-cloudinit.iso` files and prunes the image cache (slow cluster-wide sweeps never delay or fail the user's delete; ISOs carry the same `cde-codespaces-` ownership prefix as cached images, so sweeps only ever match our resources). `serial0: socket` is set on all Proxmox VMs (by the helpers client) to prevent a Debian 12 kernel panic after disk resize.

**Proxmox image caching:** Disk images are downloaded once per node into import storage as `{storage}:import/cde-codespaces-{image}.qcow2` (via `ProxmoxClient.ensure_image_cached` with `cache_name` — the `cde-codespaces-` prefix labels the volumes as ours in the Proxmox UI) and reused across VMs. Concurrent download races are handled by catching 409 and polling until the image appears. The cache is pruned in the background after `/v1/delete` (best-effort, never fails or delays the delete): only the newest `PROXMOX_IMAGE_CACHE_KEEP` (default 5) *offered* versions are kept, plus any image an in-flight create is importing from; the prune regex only matches the `cde-codespaces-` prefix, and the prune is skipped entirely if the GitHub releases fetch fails. Evicted versions that are still offered simply re-download on demand.

**Error handling:** Client-addressable Proxmox failures map to 4xx with an actionable `detail` (see the Waggle placement pattern above: `UnknownTargetError`→422, `PlacementError`→409, VM-not-found `ValueError`→404); everything else hits the global FastAPI exception handler, which returns full stack traces. Individual modules log errors with `glueops.setup_logging.configure()`. Proxmox VM creates include a compensating cleanup (VM + Waggle pool) if any step after provisioning starts fails.

## Required Environment Variables

| Variable | Purpose |
|---|---|
| `API_TOKEN` | Bearer token for all API endpoints |
| `PROVISIONER_ENVIRONMENT` | `prod` or `nonprod` (filters GitHub image releases) |
| `DOWNLOAD_SERVER_URL` | Base URL for VM disk images (libvirt regions) |
| `WAGGLE_API_URL` | Base URL of the Waggle server (org-level, shared by all Proxmox regions); required only if any Proxmox region is configured |
| `WAGGLE_API_KEY` | Waggle org API key (`wgl_...`); required only if any Proxmox region is configured |
| `PROXMOX_DOWNLOAD_SERVER_URL` | Base URL for VM disk images (Proxmox regions); required only if any Proxmox region is configured |
| `BAREMETAL_SERVER_CONFIGS` | JSON array of region configs — libvirt (`SSHConfig`) or Proxmox (`ProxmoxConfig`) entries; detected by `backend_type` field (defaults to `"libvirt"`) |
| `GUACAMOLE_SERVER_URL` / `_USERNAME` / `_PASSWORD` | Guacamole credentials |
| `BASTION_SERVER_IP` / `_PORT` / `_USER` / `_KEY` | Bastion host for Guacamole connections |
| `PROXMOX_IMAGE_CACHE_KEEP` | Newest N offered image versions kept cached per node (default 5); optional |
| `TAILSCALE_TAILNET_NAME` / `TAILSCALE_API_TOKEN` | Tailscale integration |
| `LOG_LEVEL` | Logging level (default: INFO) |

### Proxmox region config fields

One entry per Waggle datacenter. The datacenter, its hypervisors, and the slots must already exist in Waggle; instance types come from Waggle slots, so there is no `available_instance_types` here. The Proxmox credentials are the provisioner's own (Waggle stores its token write-only and never returns it).

```json
{
  "backend_type": "proxmox",
  "region_name": "proxmox-cluster-1",
  "enabled": true,
  "waggle_datacenter_name": "proxmox-cluster-1",
  "proxmox_host": "1.2.3.4",
  "proxmox_port": 8006,
  "proxmox_token_id": "root@pam!tokenid",
  "proxmox_token_secret": "...",
  "proxmox_storage": "local",
  "proxmox_bridge": "vmbr_nat",
  "proxmox_vlan_tag": 100,
  "proxmox_verify_ssl": true
}
```

`waggle_datacenter_name` defaults to `region_name`; `proxmox_vlan_tag` is optional (omit or `null` for no VLAN tag).

## CI/CD

- **`container_image.yaml`** — Builds and pushes Docker image to ghcr.io on version tags (`v*`)
- **`bump_version.yaml`** — Scheduled every 2 days to auto-generate new releases via shared GlueOps workflow
