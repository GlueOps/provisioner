from util import ssh, virt, virsh

def download_codespace_image(host, username, tag, vm_name):
    command = f'TAG={tag} VM_NAME={vm_name} bash <(curl https://raw.githubusercontent.com/GlueOps/development-only-utilities/refs/tags/v0.23.1/tools/developer-setup/download-qcow2-image.sh)'
    ssh.execute_ssh_command(host, username, command)

if __name__ == '__main__':
    connect_uri = "qemu+ssh://<user>@<host>:<port>/system"
    vm_name = "test"
    owner = 'nicholas'

    # download_codespace_image(host, user, 'v0.72.0-rc4', vm_name)

    virt.create_virtual_machine(
        connect=connect_uri,
        name=f"{vm_name}",
        metadata_description=f"Owner: {owner}",
        ram=10240,
        vcpus=2,
        disk_path=f"/var/lib/libvirt/images/{vm_name}.qcow2",
        disk_format="qcow2",
        os_variant="linux2022",
        network_bridge="virbr0",
        network_model="virtio",
        import_option=True
    )

    # # Destroy the VM
    # virsh.destroy_vm(connect_uri, vm_name)
    
    # # Undefine the VM
    # virsh.undefine_vm(connect_uri, vm_name, remove_all_storage=True)
    
    # # Start the VM
    # virsh.start_vm(connect_uri, vm_name)

    #List all vms
    virsh.list_vms(connect_uri)
