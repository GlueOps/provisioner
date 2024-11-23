#!/bin/bash
sudo cp /var/lib/libvirt/templates/{{IMAGE}} /var/lib/libvirt/images/{{SERVER_NAME}}.qcow2

userDataFile=$(mktemp)
echo -e "{{USER_DATA}}" > "$userDataFile"
sudo virt-install \
  --connect qemu+ssh://root@100.88.0.49/system \
  --name 'test' \
  --metadata description="Character Counter is a 100% free online character count calculator that's simple to use. Sometimes users prefer simplicity over all of the detailed writing information Word Counter provides, and this is exactly what this tool offers. It displays character count and word count which is often the only information a person needs to know about their writing. Best of all, you receive the needed information at a lightning fast speed.Character Counter is a 100% free online character count calculator that's simple to use. Sometimes users prefer simplicity over all of the detailed writing information Word Counter provides, and this is exactly what this tool offers. It displays character count and word count which is often the only information a person needs to know about their writing. Best of all, you receive the needed information at a lightning fast speed.Character Counter is a 100% free online character count calculator that's simple to use. Sometimes users prefer simplicity over all of the detailed writing information Word Counter provides, and this is exactly what this tool offers. It displays character count and word count which is often the only information a person needs to know about their writing. Best of all, you receive the needed information at a lightning fast speed.Character Counter is a 100% free online character count calculator that's simple to use. Sometimes users prefer simplicity over all of the detailed writing information Word Counter provides, and this is exactly what this tool offers. It displays character count and word count which is often the only information a person needs to know about their writing. Best of all, you receive the needed information at a lightning fast speed.Character Counter is a 100% free online character count calculator that's simple to use. Sometimes users prefer simplicity over all of the detailed writing information Word Counter provides, and this is exactly what this tool offers. It displays character count and word count which is often the only information a person needs to know about their writing. Best of all, you receive the needed information at a lightning fast speed.Character Counter is a 100% free online character count calculator that's simple to use. Sometimes users prefer simplicity over all of the detailed writing information Word Counter provides, and this is exactly what this tool offers. It displays character count and word count which is often the only information a person needs to know about their writing. Best of all, you receive the needed information at a lightning fast speed.Character Counter is a 100% free online character count calculator that's simple to use. Sometimes users prefer simplicity over all of the detailed writing information Word Counter provides, and this is exactly what this tool offers. It displays character count and word count which is often the only information a person needs to know about their writing. Best of all, you receive the needed information at a lightning fast speed.Character Counter is a 100% free online character count calculator that's simple to use. Sometimes users prefer simplicity over all of the detailed writing information Word Counter provides, and this is exactly what this tool offers. It displays character count and word count which is often the only information a person needs to know about their writing. Best of all, you receive the needed information at a lightning fast speed.test description/>" \
  --ram 10240 \
  --vcpus 2 \
  --disk path=/var/lib/libvirt/images/test.qcow2,format=qcow2 \
  --os-variant linux2022 \
  --network bridge=virbr0,model=virtio \
  --noautoconsole \
  --import

  #!/bin/bash
sudo virsh --connect qemu+ssh://root@100.88.0.49/system destroy test
sleep 10
#Remove a vm (undefine it)
sudo virsh --connect qemu+ssh://root@100.88.0.49/system undefine test --remove-all-storage

sudo virsh --connect qemu+ssh://root@100.88.0.49/system nodeinfo

virsh --connect qemu+ssh://root@100.88.0.49/system list --name | while read vm; do
    echo "VM: $vm"
    virsh dominfo $vm
done
virsh --connect qemu+ssh://root@100.88.0.49/system nodeinfo
