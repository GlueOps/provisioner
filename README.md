# provisioner

FastAPI to provision virtualmachines using libvirt via SSH.

# Provisioner

This project provides an API to provision virtual machines (VMs) through libvirt.

### Prerequisites

- Devbox
- Docker

### Devbox

To set up the development environment using Devbox, run:
```sh
devbox shell
devbox run dev
```


### Deployment

#### Setup tailscale ACLs

Here is an example ACL that does the following:

- Machines with `tag:app-prod-provisioner-api` can talk to `tag:app-prod-provisioner-nodes` and vice versa.
- Users in `group:app-prod-provisioner-developers` can talk to `tag:app-prod-provisioner-api` and  `tag:app-prod-provisioner-nodes` 
- `tim.cook@glueops.dev` is part of `group:app-prod-provisioner-developers`
- `tim.cook@glueops.dev` can access their own instances tagged with `tag:tim-cook` however because we are using a SVC Admin account to tag the machines `tim.cook` doesn't actually own the tag itself.

The goals of this ACL policy are to allow the provisioner API to access "provisioner nodes" via SSH (port 2222 since tailscale SSH takes over port 22). `tim.cook` needs to be able to admistrate provisioner nodes so he is part of `group:app-prod-provisioner-developers` otherwise he can be kept out of this group. `tim.cook` also uses a workspace himself so he needs to have a tag himself. Any user that uses a developer workspace will need their own tag so that this slack workspace bot can assign machines to them (e.g.  `tag:tim-cook`).

When testing new policies/ACLs it's best to just create a separate tailnet/tailscale account for testing.

```json
{
    "acls": [
        {
            "action": "accept",
            "dst": [
                "tag:app-prod-provisioner-api:*",
                "tag:app-prod-provisioner-nodes:*"
            ],
            "src": [
                "group:app-prod-provisioner-developers"
            ]
        },
        {
            "action": "accept",
            "dst": [
                "tag:app-prod-provisioner-nodes:*"
            ],
            "src": [
                "tag:app-prod-provisioner-api"
            ]
        },
        {
            "action": "accept",
            "dst": [
                "tag:tim-cook:*"
            ],
            "src": [
                "tim.cook@glueops.dev"
            ]
        }
    ],
    "groups": {
        "group:app-prod-provisioner-developers": [
            "tim.cook@glueops.dev"
        ]
    },
    "ssh": [
        {
            "action": "check",
            "dst": [
                "autogroup:self"
            ],
            "src": [
                "autogroup:member"
            ],
            "users": [
                "autogroup:nonroot",
                "root"
            ]
        },
        {
            "action": "check",
            "dst": [
                "tag:tim-cook"
            ],
            "src": [
                "autogroup:member",
                "autogroup:admin"
            ],
            "users": [
                "autogroup:nonroot",
                "root"
            ]
        },
        {
            "action": "check",
            "dst": [
                "tag:app-prod-provisioner-api",
                "tag:app-prod-provisioner-nodes"
            ],
            "src": [
                "group:app-prod-provisioner-developers"
            ],
            "users": [
                "autogroup:nonroot",
                "root"
            ]
        }
    ],
    "tagOwners": {
        "tag:tim-cook": [
            "autogroup:admin"
        ],
        "tag:app-prod-provisioner-api": [
            "group:app-prod-provisioner-developers"
        ],
        "tag:app-prod-provisioner-nodes": [
            "group:app-prod-provisioner-developers"
        ]
    }
}
```



### Deploy Provisioner Nodes

- Run `install-server.sh` on the provisioner nodes.
- Ensure proper tailscale tags are assigned to provisioner nodes (e.g. `tag:app-nonprod-provisioner-nodes`)


### Deploy Provisioner APIs

- Deploy a debian host
- Run `curl setup.glueops.dev | bash` and then add it to tailscale with the respective tag (e.g. `tag:app-nonprod-provisioner-api`)
- Create a file called `provisioner/secrets`
- Add these `env` variables to the `secrets` file
```bash
API_TOKEN
SSH_HOST
SSH_PORT
SSH_PRIVATE_KEY_ED25519_BASE64_ENCODED
SSH_USER
```
- Run with `docker run -it --env-file provisioner/secrets <container-image/tag>`

_NOTE: this will run within an interactive terminal so it's best to use tmux or similar so that it keeps running in the background. Alternatively you can remove `it` and just use `d` to have it run as a daemon in the background._
