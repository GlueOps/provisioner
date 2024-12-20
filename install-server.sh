#!/bin/bash
set -e

echo -e "\n\nEverything is now getting setup. This process will take a few minutes...\n\n"

# Script to change the hostname on a Debian system and update /etc/hosts.
# Prompt the user for the new hostname
read -p "Enter the new hostname: " NEW_HOSTNAME
read -p "Enter the tailscale auth key that will be used with --auth-key. This auth-key should have the correct tag attached to it (e.g. tag:app-nonprod-provisioner-nodes): " TAILSCALE_AUTH_KEY
# Prompt for the public key
echo "Please paste your public key (e.g., contents of id_rsa.pub), then press Enter: "
read -r PUBLIC_KEY


# Get the current hostname
CURRENT_HOSTNAME=$(hostname)

# Change the hostname using hostnamectl
sudo hostnamectl set-hostname "$NEW_HOSTNAME"

# Update /etc/hostname
echo "$NEW_HOSTNAME" | sudo tee /etc/hostname > /dev/null

# Update /etc/hosts
# Replace occurrences of the old hostname with the new hostname
sudo sed -i "s/$CURRENT_HOSTNAME/$NEW_HOSTNAME/g" /etc/hosts

# Display a confirmation message
echo "Hostname has been changed from '$CURRENT_HOSTNAME' to '$NEW_HOSTNAME'."
#set hostname for current session
sudo hostname $NEW_HOSTNAME
echo "Please reboot the system for all changes to take full effect."

#Install tailscale
curl -fsSL https://tailscale.com/install.sh | sh

sudo tailscale up --ssh --auth-key=$TAILSCALE_AUTH_KEY

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


# Use ssh to append the public key to the remote authorized_keys file
sudo echo '$PUBLIC_KEY' >> ~/.ssh/authorized_keys

# Restart the ssh service to apply changes
echo "Restarting ssh service."
sudo systemctl restart ssh

echo "Restarting...."

sudo reboot
