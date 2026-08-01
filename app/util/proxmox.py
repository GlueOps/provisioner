"""Waggle-backed Proxmox VM orchestration.

Waggle (the placement oracle) decides which hypervisor each VM lands on:
one provisioner region == one Waggle datacenter == one Proxmox cluster.
Creating a VM creates a single-VM Waggle pool, reads back the placement's
hypervisor, provisions the VM there via the Proxmox API (glueops helpers),
and backfills the vmid onto the placement. Deleting a VM removes it from
Proxmox first and only then releases the Waggle pool, so Waggle can never
overbook a hypervisor that still holds the VM.

Instance types are Waggle slots (name, vcpu, ram_gb, disk_gb); the slots
offered by /v1/regions are pre-filtered against Waggle's hypervisor ledger
(a slot is listed iff it fits some schedulable hypervisor's bookable
capacity) instead of live Proxmox scans.
"""

import asyncio, json, os, random, re, yaml
from collections import Counter
import glueops.setup_logging
from glueops.proxmox import ProxmoxClient, build_cloudinit_iso
from glueops.waggle import WaggleClient
from . import b64, github

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logger = glueops.setup_logging.configure(level=LOG_LEVEL)

_MANAGED_BY = "github.com/GlueOps/provisioner"
# Native Proxmox tag on every VM we create; find/delete match on
# [CREATOR_TAG, vm_name] so no other tool's VMs are ever touched.
CREATOR_TAG = "glueops-provisioner"
# Additional informational tags for visibility/filtering in the PVE UI.
# Deliberately NOT part of the find/delete match: identity is CREATOR_TAG +
# vm_name, so a hand-stripped label can't strand a VM from the API.
EXTRA_TAGS = ("cde", "codespaces")
# Everything we create outside the VM itself is labelled with this prefix so
# ownership is obvious at a glance and every sweep/lookup only ever matches
# our own resources:
#   Waggle pools:        cde-codespaces-{vm_name}
#   cached images:       {storage}:import/cde-codespaces-v0.143.0.qcow2
#   cloud-init ISOs:     {storage}:iso/cde-codespaces-{vm_name}-cloudinit.iso
_CDE_PREFIX = "cde-codespaces-"
# Keep the newest N offered image versions cached; older ones are pruned on
# delete and simply re-download on demand if requested again.
_IMAGE_CACHE_KEEP = int(os.getenv("PROXMOX_IMAGE_CACHE_KEEP", "5"))

_waggle_clients = {}  # (waggle_api_url, waggle_api_key) -> WaggleClient, shared across same-org regions
_proxmox_clients = {}  # region_name -> ProxmoxClient
# region_name -> Counter of cached-image names used by in-flight creates;
# the prune keep-set includes these so a concurrent create's import source
# is never deleted out from under it.
_inflight_images = {}
# (region_name, vm_name) -> asyncio.Lock serializing create/delete (and the
# background ISO sweep) per VM, so a retry-during-create can't build a
# duplicate pool/VM and a delete can't yank the ISO from under an in-flight
# create. NOTE: this lock and _inflight_images guard within ONE event loop —
# they assume the single-worker `fastapi run` deployment; running multiple
# workers or replicas would silently disable them.
_vm_locks = {}
# Strong refs to fire-and-forget cleanup tasks (asyncio only keeps weak ones).
_background_tasks = set()


class PlacementError(RuntimeError):
    """Waggle could not place the VM (pool create failed all-or-nothing —
    typically the datacenter is at capacity for the requested slot)."""


class UnknownTargetError(Exception):
    """The configured datacenter or requested slot doesn't exist in Waggle.
    Nothing was provisioned. Deliberately NOT a LookupError subclass mapping:
    a KeyError from a malformed Waggle response (KeyError ⊂ LookupError) must
    surface as a 500, not masquerade as client error 422."""


def _vm_lock(cfg, vm_name: str) -> asyncio.Lock:
    return _vm_locks.setdefault((cfg.region_name, vm_name), asyncio.Lock())


def _encode_description(tags: dict) -> str:
    return (
        "# ⚠️ Managed by automation. Do not edit.\n\n"
        f"managed-by: {_MANAGED_BY}\n\n"
        f"data: {b64.encode_string(json.dumps(tags))}"
    )


# Our encoded descriptions are far smaller than this; anything bigger is a
# hand-edited description and gets rejected before yaml parsing, which caps
# YAML anchor/alias expansion tricks.
_MAX_DESCRIPTION_BYTES = 16384


def _is_managed(desc: str) -> bool:
    if len(desc) > _MAX_DESCRIPTION_BYTES:
        return False
    try:
        parsed = yaml.safe_load(desc)
        return isinstance(parsed, dict) and parsed.get("managed-by") == _MANAGED_BY
    except Exception:
        return False


def _decode_description(desc: str) -> dict:
    if len(desc) > _MAX_DESCRIPTION_BYTES:
        return {}
    parsed = yaml.safe_load(desc)
    if isinstance(parsed, dict) and parsed.get("managed-by") == _MANAGED_BY and "data" in parsed:
        return json.loads(b64.decode_string(parsed["data"]))
    return {}


def _pool_name(vm_name: str) -> str:
    return f"{_CDE_PREFIX}{vm_name}"


def _waggle(cfg) -> WaggleClient:
    key = (cfg.waggle_api_url, cfg.waggle_api_key)
    client = _waggle_clients.get(key)
    if client is None:
        client = WaggleClient(cfg.waggle_api_url, cfg.waggle_api_key)
        _waggle_clients[key] = client
    return client


def _proxmox(cfg) -> ProxmoxClient:
    px = _proxmox_clients.get(cfg.region_name)
    if px is None:
        px = ProxmoxClient(
            host=cfg.proxmox_host,
            token_id=cfg.proxmox_token_id,
            token_secret=cfg.proxmox_token_secret,
            storage=cfg.proxmox_storage,
            port=cfg.proxmox_port,
            verify_ssl=cfg.proxmox_verify_ssl,
            download_server_url=os.environ.get("PROXMOX_DOWNLOAD_SERVER_URL"),
        )
        _proxmox_clients[cfg.region_name] = px
    return px


def get_proxmox_config(region_name: str, configs: list):
    """Return the ProxmoxConfig whose region_name matches exactly, else None."""
    for cfg in configs:
        if getattr(cfg, "backend_type", "libvirt") == "proxmox" and cfg.region_name == region_name:
            return cfg
    return None


async def _is_vm_managed(px, vm):
    """Second authorization factor before acting on a VM: native tags are
    hand-editable in the PVE UI, so additionally require the managed-by marker
    in the description (set at create, not casually editable).

    Returns True (managed), False (tagged but unmarked — do not touch), or
    None (the VM vanished between listing and this check — already deleted).
    Any other config-fetch error propagates — an unverifiable VM must fail the
    request, not be silently skipped or acted on."""
    try:
        config = await px.get_vm_config(vm["node"], vm["vmid"])
    except Exception as e:
        if ProxmoxClient._is_missing_vm_error(e):
            return None
        raise
    return _is_managed(config.get("description", ""))


async def find_vm(cfg, vm_name: str) -> dict:
    """Return {node, vmid, name, status} for the managed VM, cluster-wide.
    Requires both the native tags and the managed-by description marker."""
    px = _proxmox(cfg)
    for vm in await px.list_vms_by_tags([CREATOR_TAG, vm_name]):
        managed = await _is_vm_managed(px, vm)
        if managed:
            return vm
        if managed is False:
            logger.warning(
                f"VM {vm['vmid']} on {vm['node']} carries tags [{CREATOR_TAG}, {vm_name}] "
                f"but not the managed-by description marker; ignoring it"
            )
    raise ValueError(f"VM {vm_name!r} not found in region {cfg.region_name}")


async def create(cfg, vm_name: str, tags: dict, user_data: str, image: str, instance_type: str):
    """Create one VM: Waggle picks the hypervisor, Proxmox runs the VM.
    Serialized per (region, vm_name) against concurrent create/delete.

    Raises UnknownTargetError (unknown datacenter/slot — nothing was
    provisioned) or PlacementError (Waggle couldn't place the VM — nothing
    was provisioned).
    On any later failure the VM (if created) is deleted and the Waggle pool
    released; if the VM deletion itself fails, the pool is kept on purpose so
    Waggle doesn't hand the reserved capacity to someone else.
    """
    async with _vm_lock(cfg, vm_name):
        await _create_locked(cfg, vm_name, tags, user_data, image, instance_type)


async def _create_locked(cfg, vm_name: str, tags: dict, user_data: str, image: str, instance_type: str):
    waggle = _waggle(cfg)
    px = _proxmox(cfg)
    try:
        datacenter = await waggle.get_datacenter_by_name(cfg.waggle_datacenter_name)
        slot = await waggle.get_slot_by_name(instance_type)
    except LookupError as e:
        raise UnknownTargetError(str(e)) from e

    # Subscript OUTSIDE the try: a malformed Waggle response (KeyError) must
    # surface as an internal error, not be swallowed into PlacementError/409.
    datacenter_id = datacenter["id"]
    slot_id = slot["id"]
    try:
        pool = await waggle.create_pool(datacenter_id, slot_id, _pool_name(vm_name), 1)
    except Exception as e:
        # All-or-nothing placement: a failed pool create provisioned nothing.
        # Collapse the wrapped error to one trimmed line — this text travels
        # to the Slack user via the 409 detail.
        err_text = " ".join(str(e).split())[:200]
        raise PlacementError(
            f"Waggle could not place a {instance_type!r} VM in {cfg.region_name} "
            f"(likely at capacity): {err_text}"
        ) from e

    cached_image = f"{_CDE_PREFIX}{image}"
    inflight = _inflight_images.setdefault(cfg.region_name, Counter())
    inflight[cached_image] += 1

    node = None
    vmid = None
    iso_filename = None
    vm_created = False
    try:
        placements = await waggle.get_pool_placements(pool["id"])
        if not placements:
            raise RuntimeError(f"Waggle pool {pool['id']} has no placements")
        placement = placements[0]
        node = placement["hypervisor_name"]
        logger.info(f"Waggle placed VM {vm_name} on hypervisor {node} in {cfg.region_name}")

        await px.ensure_image_cached(node, image, cache_name=cached_image)
        meta_data = f"instance-id: {vm_name}\nlocal-hostname: {vm_name}\n"
        iso_bytes = build_cloudinit_iso(user_data.encode(), meta_data.encode())
        iso_filename = await px.upload_iso(node, f"{_CDE_PREFIX}{vm_name}-cloudinit.iso", iso_bytes)

        # get_next_vmid is non-reserving; retry on collision with a concurrent create
        for attempt in range(5):
            vmid = await px.get_next_vmid()
            try:
                await px.create_vm(
                    node=node,
                    vmid=vmid,
                    vm_name=vm_name,
                    vcpus=slot["vcpu"],
                    memory_mb=slot["ram_gb"] * 1024,
                    image=cached_image,
                    iso_filename=iso_filename,
                    bridge=cfg.proxmox_bridge,
                    vlan_tag=cfg.proxmox_vlan_tag,
                    tags=[CREATOR_TAG, *EXTRA_TAGS, vm_name],
                    description=_encode_description(tags),
                )
                break
            except Exception as e:
                if attempt < 4 and ("already exist" in str(e) or "can't lock file" in str(e)):
                    logger.warning(f"VMID {vmid} conflict on attempt {attempt + 1}, retrying")
                    continue
                raise
        vm_created = True
        try:
            await waggle.set_placement_vmid(placement["id"], int(vmid))
        except Exception as e:
            # Ledger bookkeeping only — a Waggle blip here must not trigger
            # compensation that destroys a perfectly healthy VM. Discovery
            # still reconciles used capacity; the placement just lacks a vmid.
            logger.warning(f"Failed to backfill vmid {vmid} onto placement {placement['id']}: {e}")

        for attempt in range(5):
            try:
                await px.resize_disk(node, vmid, disk_gb=slot["disk_gb"])
                break
            except Exception as e:
                if attempt < 4 and "got timeout" in str(e):
                    delay = (2 ** attempt) * 5 + random.uniform(0, 5)
                    logger.warning(f"resize_disk timeout for VM {vmid} on attempt {attempt + 1}, retrying in {delay:.1f}s")
                    await asyncio.sleep(delay)
                    continue
                raise
        await px.start_vm(node, vmid)
        try:
            await px.wait_for_cloud_init(node, vmid)
        except RuntimeError as e:
            # Guest agent never came up — the VM may still be usable; the
            # cloud-init ISO is ejected in the finally block regardless.
            logger.warning(f"VM {vmid}: {e}")
    except Exception:
        try:
            if vm_created:
                await px.delete_vm(node, vmid)
            await waggle.delete_pool(pool["id"])
        except Exception as cleanup_err:
            logger.error(f"Compensating cleanup failed for VM {vm_name}: {cleanup_err}")
        raise
    finally:
        inflight[cached_image] -= 1
        if inflight[cached_image] <= 0:
            del inflight[cached_image]
        if iso_filename and vmid:
            await px.eject_and_delete_iso(node, vmid, iso_filename)


def _reraise_if_vm_vanished(e: Exception, cfg, vm_name: str):
    """A delete racing this request can remove the VM between find_vm and the
    action; surface that as the same not-found ValueError (→ 404), not a 500."""
    if ProxmoxClient._is_missing_vm_error(e):
        raise ValueError(f"VM {vm_name!r} no longer exists in region {cfg.region_name}") from e


async def start(cfg, vm_name: str):
    vm = await find_vm(cfg, vm_name)
    try:
        await _proxmox(cfg).start_vm(vm["node"], vm["vmid"])
    except Exception as e:
        _reraise_if_vm_vanished(e, cfg, vm_name)
        raise


async def stop(cfg, vm_name: str):
    vm = await find_vm(cfg, vm_name)
    try:
        await _proxmox(cfg).stop_vm(vm["node"], vm["vmid"])
    except Exception as e:
        _reraise_if_vm_vanished(e, cfg, vm_name)
        raise


async def edit_tags(cfg, vm_name: str, tags: dict):
    vm = await find_vm(cfg, vm_name)
    try:
        await _proxmox(cfg).update_vm_config(vm["node"], vm["vmid"], description=_encode_description(tags))
    except Exception as e:
        _reraise_if_vm_vanished(e, cfg, vm_name)
        raise


async def _prune_image_cache(cfg):
    """Best-effort: drop cached cde-codespaces image volumes beyond the newest
    _IMAGE_CACHE_KEEP offered versions (plus any image an in-flight create is
    importing from). Never raises — a prune failure must not fail the delete
    that triggered it. If the offered-releases fetch fails, the prune is
    skipped entirely: never prune against an unknown keep-set."""
    try:
        offered = await asyncio.to_thread(
            github.get_codespace_releases, os.environ["PROVISIONER_ENVIRONMENT"]
        )
    except Exception as e:
        logger.warning(f"Skipping image-cache prune for {cfg.region_name}: could not list offered images: {e}")
        return
    try:
        keep = {f"{_CDE_PREFIX}{tag}" for tag in (offered or [])[:_IMAGE_CACHE_KEEP]}
        keep |= set(_inflight_images.get(cfg.region_name) or ())
        deleted = await _proxmox(cfg).prune_import_images(
            rf"{re.escape(_CDE_PREFIX)}v[^/]*\.qcow2", keep=keep
        )
        if deleted:
            logger.info(f"Pruned {deleted} cached image volume(s) in {cfg.region_name}")
    except Exception as e:
        logger.error(f"Image-cache prune failed for {cfg.region_name}: {e}")


async def delete(cfg, vm_name: str):
    """Delete the VM, then release the Waggle pool. Serialized per (region,
    vm_name) against concurrent create/delete, and idempotent under retry.

    The pool is intentionally kept — and the request fails — if a VM deletion
    fails OR a tagged VM had to be skipped as unmanaged: as long as anything
    tagged with this name may still occupy a hypervisor, Waggle must keep the
    capacity booked. The orphan ISO sweep and image-cache prune run afterwards
    as a fire-and-forget background task (see _background_cleanup), so slow
    cluster-wide sweeps never delay or fail the user's delete."""
    async with _vm_lock(cfg, vm_name):
        await _delete_locked(cfg, vm_name)
    _spawn_background_cleanup(cfg, vm_name)


async def _delete_locked(cfg, vm_name: str):
    px = _proxmox(cfg)
    waggle = _waggle(cfg)
    # Resolve the datacenter (and subscript its id) up front: pool cleanup
    # below is scoped to it (a same-named pool in ANOTHER datacenter must
    # never be released from here), and a Waggle outage or malformed response
    # then fails the delete before anything is destroyed instead of leaving a
    # half-done VM-gone/pool-booked state.
    datacenter = await waggle.get_datacenter_by_name(cfg.waggle_datacenter_name)
    datacenter_id = datacenter["id"]
    vms = await px.list_vms_by_tags([CREATOR_TAG, vm_name])
    if not vms:
        logger.warning(f"No VM tagged {vm_name!r} in region {cfg.region_name}; cleaning up Waggle pool anyway")
    skipped = []
    for vm in vms:
        managed = await _is_vm_managed(px, vm)
        if managed is None:
            continue  # vanished between listing and check — already deleted
        if not managed:
            logger.warning(
                f"NOT deleting VM {vm['vmid']} on {vm['node']}: tagged [{CREATOR_TAG}, {vm_name}] "
                f"but missing the managed-by description marker"
            )
            skipped.append(vm["vmid"])
            continue
        await px.delete_vm(vm["node"], vm["vmid"])
    if skipped:
        raise RuntimeError(
            f"Refusing to release Waggle pool {_pool_name(vm_name)!r}: VM(s) {', '.join(skipped)} "
            f"carry our tags but not the managed-by description marker and were left in place. "
            f"Restore or remove them in Proxmox, then retry the delete."
        )
    for pool in await waggle.find_pools_by_name(_pool_name(vm_name)):
        if pool.get("datacenter_id") == datacenter_id:
            await waggle.delete_pool(pool["id"])


def _spawn_background_cleanup(cfg, vm_name: str):
    task = asyncio.create_task(_background_cleanup(cfg, vm_name))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _background_cleanup(cfg, vm_name: str):
    """Post-delete housekeeping, entirely best-effort: sweep this VM's orphaned
    cloud-init ISO (under the per-VM lock, so it can't race a same-name create)
    and prune the image cache. Failures only log — orphans self-heal on a
    later delete's sweep."""
    try:
        async with _vm_lock(cfg, vm_name):
            await _proxmox(cfg).delete_isos_matching(
                rf"{re.escape(_CDE_PREFIX)}{re.escape(vm_name)}-cloudinit\.iso"
            )
    except Exception as e:
        logger.error(f"Orphan ISO sweep failed for {vm_name}: {e}")
    await _prune_image_cache(cfg)


async def list_vms(cfg) -> list:
    """Return every managed VM in this region in the /v1/list contract shape."""
    px = _proxmox(cfg)
    vms = await px.list_vms_by_tags([CREATOR_TAG])

    async def get_vm_details(vm):
        try:
            config = await px.get_vm_config(vm["node"], vm["vmid"])
            desc = config.get("description", "")
            if not _is_managed(desc):
                return None
            tags = _decode_description(desc)
        except Exception:
            return None
        return {
            "dom_id": vm["vmid"],
            "name": vm["name"],
            "region_name": cfg.region_name,
            "state": vm["status"],
            "tags": tags,
        }

    results = await asyncio.gather(*[get_vm_details(vm) for vm in vms])
    return [r for r in results if r is not None]


async def get_region(cfg) -> dict:
    """One region entry per Waggle datacenter. available_instance_types lists
    only the Waggle slots that can currently be placed (fit within the bookable
    capacity of at least one schedulable hypervisor) — a slot that is listed is
    a slot a VM can be created with right now."""
    waggle = _waggle(cfg)
    datacenter = await waggle.get_datacenter_by_name(cfg.waggle_datacenter_name)
    slots = await waggle.list_available_slots(datacenter["id"])
    return {
        "region_name": cfg.region_name,
        "enabled": cfg.enabled,
        "tunnel_endpoint": cfg.tunnel_endpoint,
        "available_instance_types": [
            {
                "instance_type": s["name"],
                "vcpus": s["vcpu"],
                "memory_mb": s["ram_gb"] * 1024,
                "storage_mb": s["disk_gb"] * 1024,
            }
            for s in slots
        ],
    }
