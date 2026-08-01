# Changelog

## [3.0.0](https://github.com/GlueOps/provisioner/compare/v2.4.1...v3.0.0) (2026-08-01)


### ⚠ BREAKING CHANGES

* proxmox region config now carries waggle_datacenter_name plus proxmox credentials only (no available_instance_types); requires WAGGLE_API_URL and WAGGLE_API_KEY; region names are datacenter-level (no {cluster}-{node} names). Proxmox was not in production; libvirt config and behavior are unchanged.

### Features

* waggle-backed proxmox placement ([#225](https://github.com/GlueOps/provisioner/issues/225)) ([0091d9c](https://github.com/GlueOps/provisioner/commit/0091d9c3b7649b6497c9ceeedb6dd394a3ee7188))


### Miscellaneous Chores

* add Apache-2.0 LICENSE ([#222](https://github.com/GlueOps/provisioner/issues/222)) ([817d24a](https://github.com/GlueOps/provisioner/commit/817d24aab0795f20256b9ccd54bca938ad9e74e7))

## [2.4.1](https://github.com/GlueOps/provisioner/compare/v2.4.0...v2.4.1) (2026-06-30)


### Continuous Integration

* bring release-please config up to GlueOps convention ([#214](https://github.com/GlueOps/provisioner/issues/214)) ([7a07ece](https://github.com/GlueOps/provisioner/commit/7a07ece81cb747c1c04781a0ca49e3cb42bd1346))

## [2.4.0](https://github.com/GlueOps/provisioner/compare/v2.3.0...v2.4.0) (2026-06-29)


### Features

* consolidate dependency updates ([#211](https://github.com/GlueOps/provisioner/issues/211)) ([ec52440](https://github.com/GlueOps/provisioner/commit/ec524408accfe591006bce8dc8a70464090d5d82))
