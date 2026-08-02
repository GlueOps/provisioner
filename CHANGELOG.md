# Changelog

## [4.1.0](https://github.com/GlueOps/provisioner/compare/v4.0.0...v4.1.0) (2026-08-02)


### Features

* add tunnel_endpoint to region configs and /v1/regions ([#229](https://github.com/GlueOps/provisioner/issues/229)) ([d80b92d](https://github.com/GlueOps/provisioner/commit/d80b92d7df816b959c5df6575eea2ae3efc333a7))
* update docker/login-action to v4.3.0 #minor ([#228](https://github.com/GlueOps/provisioner/issues/228)) ([95f4afb](https://github.com/GlueOps/provisioner/commit/95f4afb892b3d18326c0e93fce12efec59bd6253))
* update docker/metadata-action to v6.2.0 #minor ([#230](https://github.com/GlueOps/provisioner/issues/230)) ([6b13047](https://github.com/GlueOps/provisioner/commit/6b13047dc89f559cce8249d7cb913972f263a392))
* update docker/setup-buildx-action to v4.2.0 #minor ([#231](https://github.com/GlueOps/provisioner/issues/231)) ([3abfd54](https://github.com/GlueOps/provisioner/commit/3abfd54e37773c94f1aabaf3a96e8db4faa7beac))
* update docker/setup-buildx-action to v4.2.0 #minor ([#232](https://github.com/GlueOps/provisioner/issues/232)) ([a341eea](https://github.com/GlueOps/provisioner/commit/a341eeacebe4df3ba77e939fe38a0d5a7cd6923a))


### Miscellaneous Chores

* **patch:** update dataaxiom/ghcr-cleanup-action to v1.2.2 #patch ([#217](https://github.com/GlueOps/provisioner/issues/217)) ([93352e2](https://github.com/GlueOps/provisioner/commit/93352e2f487f854fec6e3035aaf199dcc46ddac0))

## [4.0.0](https://github.com/GlueOps/provisioner/compare/v3.0.0...v4.0.0) (2026-08-01)


### ⚠ BREAKING CHANGES

* WAGGLE_API_URL and WAGGLE_API_KEY env vars are removed; set waggle_api_url/waggle_api_key on every proxmox entry in BAREMETAL_SERVER_CONFIGS instead.

### Features

* per-region waggle credentials ([#226](https://github.com/GlueOps/provisioner/issues/226)) ([d87f49f](https://github.com/GlueOps/provisioner/commit/d87f49f868d6d2f7883069fd977f80e3228c05e2))
* update docker/build-push-action to v7.3.0 #minor ([#224](https://github.com/GlueOps/provisioner/issues/224)) ([1793430](https://github.com/GlueOps/provisioner/commit/179343096ec9ea66e988d52e46a92af624e6a772))

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
