# Agent Guidance

Operational reference for AI agents working in this repo. Read alongside CLAUDE.md (project overview, architecture, env vars).

## Connected Repos

- **[slackbot-developer-workspaces](https://github.com/GlueOps/slackbot-developer-workspaces)** — primary consumer of this API. See its [`.ai/AGENTS.md`](https://github.com/GlueOps/slackbot-developer-workspaces/blob/main/.ai/AGENTS.md) for how it consumes `/v1/regions` (pre-filtered placeable slots) in Slack modals.
- **[waggle](https://github.com/glueops/waggle)** — the placement oracle behind Proxmox regions. One provisioner region == one Waggle datacenter == one Proxmox cluster; Waggle picks the hypervisor for each VM (anti-affinity, all-or-nothing) and this service provisions it there, then backfills the vmid onto the placement.
- **[python-glueops-helpers-library](https://github.com/GlueOps/python-glueops-helpers-library)** — provides `glueops.proxmox.ProxmoxClient` (Proxmox REST API: image cache, cloud-init ISO, VM lifecycle, tag discovery, guest agent) and `glueops.waggle.WaggleClient` (datacenters, slots, pools, placements, hypervisor ledger). `app/util/proxmox.py` is a thin orchestration layer over these two clients.

---

## Module Import Map

```python
# Entry point — all FastAPI endpoints
import app.main

# Utility modules
from app.util import proxmox     # Waggle-backed Proxmox orchestration (pool-per-VM placement, VM lifecycle, placeable-slot availability)
from glueops.proxmox import ProxmoxClient, build_cloudinit_iso   # helpers library: Proxmox REST API client
from glueops.waggle import WaggleClient                          # helpers library: Waggle API client
from app.util import virsh       # virsh commands for libvirt VMs
from app.util import virt        # virt-install VM creation
from app.util import ssh         # Paramiko SSH execution on remote libvirt hosts
from app.util import regions     # Parse BAREMETAL_SERVER_CONFIGS into typed config objects
from app.util import guacamole   # Guacamole connection create/delete/permissions
from app.util import tailscale   # Tailscale device removal
from app.util import github      # GitHub releases filtered by PROVISIONER_ENVIRONMENT
from app.util import b64         # Base64 encode/decode for VM metadata (description field)
from app.util import formatter   # String indentation helpers for cloud-init YAML

# Schemas
from app.schemas.schemas import Vm, ExistingVm, VmMeta, VmTags, Message
```

---

## Writing and Running Test Scripts

**Always run from `/workspaces/glueops/provisioner/` using devbox:**
```bash
devbox run -- pipenv run python3 test.py
```

Do not use `python3` directly, `.venv`, or `devbox shell --`. The `devbox run --` form is required.

### Standard Proxmox cfg for test scripts

```python
import asyncio, os, sys
sys.path.insert(0, "/workspaces/glueops/provisioner")

# The module reads the image-server setting from env; Waggle credentials
# are per region config (multiple Waggle orgs/servers supported).
os.environ["PROXMOX_DOWNLOAD_SERVER_URL"] = "<DOWNLOAD_BASE_URL>"

from app.util import proxmox, regions

cfg = regions.ProxmoxConfig(
    region_name="<REGION_NAME>",                      # == Waggle datacenter name (or set waggle_datacenter_name)
    enabled=True,
    waggle_api_url="<WAGGLE_URL>",
    waggle_api_key="wgl_...",
    proxmox_host="<PROXMOX_HOST_OR_IP>",
    proxmox_port=8006,
    proxmox_token_id="<USER>@<REALM>!<TOKENNAME>",   # e.g. root@pam!mytoken
    proxmox_token_secret="<UUID>",                    # UUID only — NOT "tokenname=UUID"
    proxmox_storage="<STORAGE_NAME>",                 # e.g. "local"
    proxmox_bridge="<BRIDGE_NAME>",                   # e.g. "vmbr0"
    proxmox_vlan_tag=100,                             # optional; omit for no VLAN tag
    proxmox_verify_ssl=True,                          # set False for self-signed certs
)
```

### Example: validate guest exec against a live VM

```python
async def main():
    vm = await proxmox.find_vm(cfg, "my-test-vm")     # {node, vmid, name, status}
    px = proxmox._proxmox(cfg)                        # glueops.proxmox.ProxmoxClient

    # Success path — file exists after cloud-init completes
    out = await px.agent_exec(vm["node"], vm["vmid"], ["ls", "/var/lib/cloud/instance/boot-finished"])
    print(f"boot-finished: {out!r}")

    # Failure path — nonexistent file should raise RuntimeError
    try:
        await px.agent_exec(vm["node"], vm["vmid"], ["ls", "/tmp/does-not-exist"])
        print("ERROR: no exception raised")
    except RuntimeError as e:
        print(f"Correctly raised: {e}")

asyncio.run(main())
```

### Example: full end-to-end VM create (with placeholders)

```python
async def main():
    user_data = "#cloud-config\npassword: changeme\nchpasswd: {expire: false}\n"
    # Waggle picks the hypervisor, provisions, backfills vmid, compensates on failure
    await proxmox.create(cfg, "test-vm", {"owner": "test"}, user_data,
                         image="<IMAGE_VERSION>", instance_type="<WAGGLE_SLOT_NAME>")
    print("VM ready")
    # cleanup: removes VM by tags and releases its Waggle pool (this datacenter
    # only); the ISO sweep + image prune run afterwards as a background task
    await proxmox.delete(cfg, "test-vm")

asyncio.run(main())
```

---

## Proxmox Module Public API (`app/util/proxmox.py`)

High-level orchestration; all Proxmox/Waggle HTTP calls live in the glueops-helpers clients.

| Function | Signature | Purpose |
|---|---|---|
| `get_proxmox_config` | `(region_name, configs) -> ProxmoxConfig \| None` | Exact-match region resolution (backend routing) |
| `create` | `(cfg, vm_name, tags, user_data, image, instance_type)` | Per-(region,vm_name) lock → datacenter/slot lookup (`UnknownTargetError` → 422) → Waggle pool (`cde-codespaces-{vm_name}`, count 1; failure → `PlacementError` → 409) → placement → image cache → cloud-init ISO → VM create (vmid retry) → best-effort vmid backfill (warn-only) → resize to slot disk_gb → start → wait_for_cloud_init. Compensates (VM + pool) only on failure after provisioning started. No duplicate-name guard by design — callers generate unique names and never retry |
| `delete` | `(cfg, vm_name)` | Per-(region,vm_name) lock → resolve datacenter (Waggle outage fails before destruction) → delete VM(s) by tags **after verifying the managed-by description marker**; a tagged-but-unmarked VM fails the delete and keeps the pool (no overbooking); vanished VMs and already-gone pools count as success (idempotent retry); pool release filtered to this datacenter's pools only. ISO sweep + image prune run afterwards as a fire-and-forget background task |
| `_prune_image_cache` | `(cfg)` | Best-effort: prune `cde-codespaces-*` import volumes beyond the newest `PROXMOX_IMAGE_CACHE_KEEP` (default 5) offered versions ∪ in-flight images. Never raises; skipped if the releases fetch fails |
| `start` / `stop` | `(cfg, vm_name)` | Find by tags, start/stop |
| `edit_tags` | `(cfg, vm_name, tags)` | Find by tags, rewrite encoded description |
| `find_vm` | `(cfg, vm_name) -> dict` | `{node, vmid, name, status}` via native tags `[glueops-provisioner, vm_name]` + managed-by description verification, cluster-wide |
| `list_vms` | `(cfg) -> list` | All managed VMs (creator tag + managed description) in the `/v1/list` contract shape |
| `get_region` | `(cfg) -> dict` | One region entry: `available_instance_types` = the Waggle slots currently placeable in the datacenter (via `WaggleClient.list_available_slots` — fits on some schedulable hypervisor's bookable capacity) |

Helpers clients available in test scripts:
- `proxmox._proxmox(cfg)` — cached `glueops.proxmox.ProxmoxClient` for the region
- `proxmox._waggle(cfg)` — cached `glueops.waggle.WaggleClient` for the region's org (entries sharing `waggle_api_url`+`waggle_api_key` share a client)

---

## Key Invariants

These are load-bearing. Do not change without understanding the impact.

1. **`agent_exec` command is `list[str]`** — Proxmox agent/exec API requires a JSON array. `command.split()` is explicitly avoided — pass `["ls", "/path"]` not `"ls /path"`.

2. **ISO eject is in `finally`** — `eject_and_delete_iso` always runs in `create()` regardless of success or failure. Moving it outside `finally` creates ISO leaks on error paths. `delete()` additionally sweeps `cde-codespaces-{vm_name}-cloudinit.iso` orphans left by crashed creates; the `cde-codespaces-` prefix on ISOs (and cached images) scopes every sweep to resources we own.

3. **`wait_for_cloud_init` runs before `eject_and_delete_iso`** — the cidata ISO must remain mounted until cloud-init reads it on first boot. Order: `start_vm` → `wait_for_cloud_init` → eject (via `finally`).

4. **VM metadata is base64-encoded JSON in the description field** — encode: `b64.encode_string(json.dumps(tags))`; decode: `json.loads(b64.decode_string(desc))`. Both libvirt and Proxmox backends use this format. Native Proxmox tags (`glueops-provisioner`, `cde`, `codespaces`, `{vm_name}`) are for discovery/visibility only — user-facing tags live in the description. Identity for find/delete is `glueops-provisioner` + `{vm_name}`; `cde`/`codespaces` are informational and not matched on, so a hand-stripped label can't strand a VM. Tags identify, the description marker *authorizes*: `_is_vm_managed` must pass before any start/stop/edit/delete — a config-fetch error fails the request (never silently skip or act), while a tagged-but-unmarked VM is skipped with a warning.

5. **Proxmox region names are the Waggle datacenter / cluster name** — e.g. `proxmox-cluster-1`. The hypervisor is chosen by Waggle at create time and never appears in the region name. Always resolve regions with `get_proxmox_config()` (exact match). `/v1/regions` carries no capacity fields for Proxmox regions — availability is expressed by which slots are listed.

6. **`serial0: socket` on all Proxmox VMs** — prevents a Debian 12 kernel panic after disk resize. Set by `glueops.proxmox.ProxmoxClient.create_vm`; do not override.

7. **`exitcode` check in `agent_exec`** — a command exiting with non-zero raises `RuntimeError`. The `ls boot-finished` polling loop in `wait_for_cloud_init` depends on this: exit 1/2 (file not found) raises, exit 0 (file exists) returns. The `except RuntimeError` in the polling loop is intentional and load-bearing.

8. **Waggle pool lifecycle mirrors the VM** — pool `cde-codespaces-{vm_name}` is created before the VM and deleted only after the VM is confirmed gone. If VM deletion fails, keep the pool: Waggle must keep the capacity booked or it will overbook the hypervisor. Never delete the pool first.

9. **Per-(region, vm_name) `asyncio.Lock` serializes create/delete/ISO-sweep** — a delete can't yank the cloud-init ISO from under an in-flight create, and same-name operations never interleave. It serializes only — it does NOT dedupe: a sequential duplicate create is an accepted non-scenario (callers generate unique names and never retry; see CLAUDE.md). These locks (and `_inflight_images`) live in one event loop: the deployment assumption is the single-worker `fastapi run`; multiple workers/replicas would silently disable them.

10. **Image-cache pruning rides on deletes and is strictly best-effort** — cached volumes are labelled `cde-codespaces-{tag}.qcow2` and pruned only from `delete()`, never from the create path. Keep-set = newest `PROXMOX_IMAGE_CACHE_KEEP` offered releases ∪ `_inflight_images` (images a concurrent create is importing — pruning one mid-import fails that create). A prune error only logs; if `get_codespace_releases` fails, the prune is skipped entirely (never prune against an unknown keep-set). Eviction never makes an image unavailable — `ensure_image_cached` re-downloads on demand.

---

## Cloud-init Completion Detection

`wait_for_cloud_init` uses a two-phase approach:

1. Poll `GET /nodes/{node}/qemu/{vmid}/agent/info` every 5s until the guest agent responds (VM has booted, agent is up).
2. Poll `ls /var/lib/cloud/instance/boot-finished` via `agent_exec` every 5s until exit code 0.

`boot-finished` is cloud-init's documented final-stage completion marker. It is created after all cloud-init stages (local, network, config, final) have run.

**Do not use `cloud-init status` via guest-exec** — the Python interpreter startup time (~1–2s) exceeds Proxmox's QMP response window and always returns 596 (Broken pipe). Use compiled binaries (`ls`, `hostname`, `cat`) only.

**guest-exec must be explicitly enabled** on Debian 12 — it is blacklisted by default. The CDE base image (v0.133.0+) ships `/etc/qemu/qemu-ga.conf` with `[general]\nblacklist =` to clear the blacklist. If testing with an older image, guest-exec will return 500.

---

## Debugging Live VMs

When something is wrong, debug the running VM directly rather than recreating it.

From inside the VM:
```bash
# Check cloud-init completed
ls /var/lib/cloud/instance/boot-finished

# Check guest-exec is enabled
cat /etc/qemu/qemu-ga.conf   # should contain: [general]\nblacklist =

# Check guest agent is active
systemctl status qemu-guest-agent
```

From a test script against the Proxmox API:
```python
# Run any command in the guest
vm = await proxmox.find_vm(cfg, "my-test-vm")
out = await proxmox._proxmox(cfg).agent_exec(vm["node"], vm["vmid"], ["cat", "/var/log/cloud-init.log"])
print(out[-3000:])  # tail of cloud-init log
```

---

## Testing Without Automated Tests

There are no automated tests or linters. Validate changes by:

1. Writing a `test.py` in `/workspaces/glueops/provisioner/` targeting a live VM or cluster.
2. Running it with `devbox run -- pipenv run python3 test.py`.
3. For new Proxmox functions: test the happy path, the failure path (bad inputs), and check that compensating actions (VM delete + Waggle pool release) fire correctly on exception — and that the pool is *kept* when the VM deletion fails.
4. For changes to `wait_for_cloud_init` or `agent_exec` behaviour: test against a running VM with `find_vm` — avoid spinning up new VMs just to test small changes.

Delete `test.py` before committing (it typically contains credentials).

---

## Commit Conventions

All commits must follow [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): short description

Optional body explaining why, not what.
```

**Types:**
| Type | When to use |
|---|---|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `chore` | Build, deps, config — no production code change |
| `ci` | CI/CD pipeline changes |
| `perf` | Performance improvement |
| `revert` | Reverts a previous commit |

**Examples:**
```
feat: add Proxmox backend support for VM lifecycle management
fix: clamp free_vcpus to zero when node is overcommitted
docs: update AGENTS.md with regionStats null guard invariant
refactor: move capacity fields out of region name string into separate fields
chore: remove test.py containing dev credentials
```

**Rules:**
- Subject line is lowercase, no trailing period, 72 chars max
- Use imperative mood ("add" not "added", "fix" not "fixed")
- Breaking changes must include `BREAKING CHANGE:` in the commit body or `!` after the type: `feat!: rename region capacity fields`
