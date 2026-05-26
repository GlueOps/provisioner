# Agent Guidance

Operational reference for AI agents working in this repo. Read alongside CLAUDE.md (project overview, architecture, env vars).

## Connected Repos

- **[slackbot-developer-workspaces](https://github.com/GlueOps/slackbot-developer-workspaces)** — primary consumer of this API. See its [`.ai/AGENTS.md`](https://github.com/GlueOps/slackbot-developer-workspaces/blob/main/.ai/AGENTS.md) for how it consumes `/v1/regions`, handles the `(Over Allocated)` instance type suffix, and renders Proxmox capacity/load in Slack modals.

---

## Module Import Map

```python
# Entry point — all FastAPI endpoints
import app.main

# Utility modules
from app.util import proxmox     # Proxmox VE REST API (image cache, VM lifecycle, guest exec)
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
import asyncio, types, sys
sys.path.insert(0, "/workspaces/glueops/provisioner")
from app.util import proxmox

cfg = types.SimpleNamespace(
    proxmox_host="<PROXMOX_HOST_OR_IP>",
    proxmox_port=8006,
    proxmox_token_id="<USER>@<REALM>!<TOKENNAME>",   # e.g. root@pam!mytoken
    proxmox_token_secret="<UUID>",                    # UUID only — NOT "tokenname=UUID"
    proxmox_storage="<STORAGE_NAME>",                 # e.g. "local"
    proxmox_bridge="<BRIDGE_NAME>",                   # e.g. "vmbr0"
    proxmox_vlan_tag=100,                             # VLAN tag applied to net0
    proxmox_verify_ssl=True,                          # set False for self-signed certs
    region_name="<REGION_NAME>",                      # e.g. "proxmox-cluster-1"
)

NODE = "<NODE_NAME>"   # e.g. "pve-node-01"
```

### Example: validate _agent_exec against a live VM

```python
async def main():
    vmid = await proxmox.find_vmid_by_name(cfg, NODE, "my-test-vm")

    # Success path — file exists after cloud-init completes
    out = await proxmox._agent_exec(cfg, NODE, vmid, ["ls", "/var/lib/cloud/instance/boot-finished"])
    print(f"boot-finished: {out!r}")

    # Failure path — nonexistent file should raise RuntimeError
    try:
        await proxmox._agent_exec(cfg, NODE, vmid, ["ls", "/tmp/does-not-exist"])
        print("ERROR: no exception raised")
    except RuntimeError as e:
        print(f"Correctly raised: {e}")

asyncio.run(main())
```

### Example: full end-to-end VM create (with placeholders)

```python
async def main():
    import base64, json

    user_data = "#cloud-config\npassword: changeme\nchpasswd: {expire: false}\n"
    meta_data = f"instance-id: test-vm\nlocal-hostname: test-vm\n"
    iso_bytes = proxmox.build_iso(user_data.encode(), meta_data.encode())

    vmid = await proxmox.get_next_vmid(cfg)
    iso_filename = None
    vm_created = False
    try:
        await proxmox.ensure_image_cached(cfg, NODE, "<IMAGE_VERSION>", "<DOWNLOAD_BASE_URL>")
        iso_filename = await proxmox.upload_iso(cfg, NODE, "test-vm", iso_bytes)
        await proxmox.create_vm(cfg, NODE, vmid, "test-vm", 2, 4096, "<IMAGE_VERSION>", iso_filename, {"owner": "test"})
        vm_created = True
        await proxmox.resize_disk(cfg, NODE, vmid, 32000)
        await proxmox.start_vm(cfg, NODE, vmid)
        await proxmox.wait_for_cloud_init(cfg, NODE, vmid)
        print("VM ready")
    except Exception as e:
        if vm_created:
            await proxmox.delete_vm(cfg, NODE, vmid)
        raise
    finally:
        if iso_filename:
            await proxmox.eject_and_delete_iso(cfg, NODE, vmid, iso_filename)

asyncio.run(main())
```

---

## Proxmox Module Public API

| Function | Signature | Purpose |
|---|---|---|
| `get_next_vmid` | `(cfg) -> str` | Next available VMID from cluster |
| `ensure_image_cached` | `(cfg, node, image, download_url)` | Download qcow2 to import storage if missing |
| `build_iso` | `(user_data: bytes, meta_data: bytes) -> bytes` | Build cidata ISO with pycdlib |
| `upload_iso` | `(cfg, node, vm_name, iso_bytes) -> str` | Upload ISO, returns filename |
| `eject_and_delete_iso` | `(cfg, node, vmid, iso_filename)` | Eject cdrom + delete ISO from storage |
| `create_vm` | `(cfg, node, vmid, vm_name, vcpus, memory_mb, image, iso_filename, tags)` | Create VM from imported qcow2 |
| `resize_disk` | `(cfg, node, vmid, storage_mb)` | Resize `virtio0` disk |
| `start_vm` | `(cfg, node, vmid)` | Start VM, polls task to completion |
| `stop_vm` | `(cfg, node, vmid)` | Stop VM, polls task to completion |
| `delete_vm` | `(cfg, node, vmid)` | Stop if running, delete with purge |
| `wait_for_cloud_init` | `(cfg, node, vmid, agent_timeout=120, cloudinit_timeout=300)` | Two-phase poll: agent up → cloud-init done |
| `find_vmid_by_name` | `(cfg, node, vm_name) -> str` | Resolve VM name to VMID |
| `list_vms` | `(cfg) -> list` | All VMs in cluster with decoded tags |
| `get_nodes_with_capacity` | `(cfg) -> list` | Per-node capacity as list of dicts with `region_name`, capacity fields (`total_vcpus`, `total_memory_gb`, `total_storage_gb`, `free_vcpus`, `free_memory_gb`, `free_storage_gb`), and load fields (`cpu_pct`, `ram_pct`) |
| `parse_proxmox_region_name` | `(region_name, configs) -> (cfg, node)` | Strip legacy capacity suffix if present, return stable config+node |
| `edit_vm_tags` | `(cfg, node, vmid, tags)` | Update VM description with encoded tags |
| `_agent_exec` | `(cfg, node, vmid, command: list[str]) -> str` | Run command in guest via qemu-guest-agent |

Internal helpers available in test scripts (not for production use):
- `_get`, `_post`, `_put`, `_delete` — raw HTTP wrappers
- `poll_task(cfg, upid)` — wait for async Proxmox task

---

## Key Invariants

These are load-bearing. Do not change without understanding the impact.

1. **`_agent_exec` command is `list[str]`** — Proxmox agent/exec API requires a JSON array. `command.split()` is explicitly avoided — pass `["ls", "/path"]` not `"ls /path"`.

2. **ISO eject is in `finally`** — `eject_and_delete_iso` always runs regardless of success or failure. Moving it outside `finally` creates ISO leaks on error paths.

3. **`wait_for_cloud_init` runs before `eject_and_delete_iso`** — the cidata ISO must remain mounted until cloud-init reads it on first boot. Order: `start_vm` → `wait_for_cloud_init` → eject (via `finally`).

4. **VM metadata is base64-encoded JSON in the description field** — encode: `b64.encode_string(json.dumps(tags))`; decode: `json.loads(b64.decode_string(desc))`. Both libvirt and Proxmox backends use this format.

5. **Proxmox region names are bare `{region_name}-{node}`** — e.g. `proxmox-cluster-1-pve-node-01`. Capacity and load are separate fields on the region object (`total_vcpus`, `free_vcpus`, `cpu_pct`, etc.), never embedded in the name string. `_CAPACITY_SUFFIX` exists only to strip old-format names from external clients — the provisioner itself never generates suffixed names. Always call `parse_proxmox_region_name()` to recover stable `(cfg, node)` — never parse the string manually.

6. **`serial0: socket` on all Proxmox VMs** — prevents a Debian 12 kernel panic after disk resize. Do not remove from `create_vm`.

7. **`exitcode` check in `_agent_exec`** — a command exiting with non-zero raises `RuntimeError`. The `ls boot-finished` polling loop in `wait_for_cloud_init` depends on this: exit 1/2 (file not found) raises, exit 0 (file exists) returns. The `except RuntimeError` in the polling loop is intentional and load-bearing.

---

## Cloud-init Completion Detection

`wait_for_cloud_init` uses a two-phase approach:

1. Poll `GET /nodes/{node}/qemu/{vmid}/agent/info` every 5s until the guest agent responds (VM has booted, agent is up).
2. Poll `ls /var/lib/cloud/instance/boot-finished` via `_agent_exec` every 5s until exit code 0.

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
out = await proxmox._agent_exec(cfg, NODE, vmid, ["cat", "/var/log/cloud-init.log"])
print(out[-3000:])  # tail of cloud-init log
```

---

## Testing Without Automated Tests

There are no automated tests or linters. Validate changes by:

1. Writing a `test.py` in `/workspaces/glueops/provisioner/` targeting a live VM or cluster.
2. Running it with `devbox run -- pipenv run python3 test.py`.
3. For new Proxmox functions: test the happy path, the failure path (bad inputs), and check that compensating actions (delete_vm) fire correctly on exception.
4. For changes to `wait_for_cloud_init` or `_agent_exec`: test against a running VM with `find_vmid_by_name` — avoid spinning up new VMs just to test small changes.

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
