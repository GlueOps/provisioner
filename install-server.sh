#!/bin/bash
set -e

echo -e "\n\nEverything is now getting setup. This process will take a few minutes...\n\n"

#Install tailscale
curl -fsSL https://tailscale.com/install.sh | sh

#Install libvirt and related packages
sudo apt install -y qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils virtinst virt-manager dnsmasq qemu-utils xmlstarlet jq

#If you have trouble with dnsmasq
sudo systemctl disable --now systemd-resolved || true
sudo apt remove systemd-resolved || true
sudo rm /etc/resolv.conf || true
{ echo "nameserver 1.1.1.1"; echo "nameserver 8.8.8.8"; } | sudo tee /etc/resolv.conf

#Enable and start libvirt
sudo systemctl enable libvirtd
sudo systemctl start libvirtd

#Enable the default network
sudo virsh net-start default
sudo virsh net-autostart default

# Replace '#Port' with 'Port 22' and 'Port 2222'
sudo sed -i 's/^#Port .*/Port 22\nPort 2222/' /etc/ssh/sshd_config

# Restart the ssh service to apply changes
echo "Restarting ssh service."
sudo systemctl restart ssh
