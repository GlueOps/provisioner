#!/bin/bash
set -e

echo -e "\n\nEverything is now getting setup. This process will take a few minutes...\n\n"

#Install tailscale
curl -fsSL https://tailscale.com/install.sh | sh

#Install nix package manager
sh <(curl -L https://nixos.org/nix/install) --daemon --yes

# Load the Nix environment
. /etc/profile.d/nix.sh

# Install packages from a pinned version of Nixpkgs
nix-env -iA \
  -f https://github.com/NixOS/nixpkgs/archive/53f3c92b4d1f5f297258954c5026e39c45afd180.tar.gz \
  libvirt qemu bridge-utils virt-manager dnsmasq

# Find the Nix-installed dnsmasq binary
DNSMASQ_BIN=$(which dnsmasq)
LIBVIRTD_BIN=$(which libvirtd)


if [[ -z "$DNSMASQ_BIN" || -z "$LIBVIRTD_BIN" ]]; then
    echo "Error: One or both binaries (dnsmasq, libvirtd) not found after installation!"
    exit 1
fi

# Create a systemd service for dnsmasq
echo "Creating systemd service for dnsmasq..."
sudo bash -c "cat > /etc/systemd/system/dnsmasq-nix.service" <<EOF
[Unit]
Description=DNS caching server (via Nix)
After=network.target

[Service]
ExecStart=$DNSMASQ_BIN --no-daemon --no-resolv --server=1.1.1.1 --server=8.8.8.8
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Create a systemd service for libvirtd
echo "Creating systemd service for libvirtd..."
sudo bash -c "cat > /etc/systemd/system/libvirtd-nix.service" <<EOF
[Unit]
Description=Virtualization daemon (via Nix)
After=network.target

[Service]
ExecStart=$LIBVIRTD_BIN
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd, enable, and start the service
echo "Enabling and starting dnsmasq service..."
sudo systemctl daemon-reload
sudo systemctl enable dnsmasq-nix libvirtd-nix
sudo systemctl start dnsmasq-nix libvirtd-nix

sudo systemctl start dnsmasq-nix libvirtd-nix
 
# Verify services are actually running
if ! systemctl is-active --quiet dnsmasq-nix || ! systemctl is-active --quiet libvirtd-nix; then
    echo "Error: One or more services failed to start properly"
    exit 1
fi
