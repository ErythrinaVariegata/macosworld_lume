
# Configure VMware Environment for macOSWorld

Environment configuration consists of two steps: (1) [Download and install VMware](#download-and-install-vmware); (2) [Download the virtual machine](#download-virtual-machine).

## Download and Install VMware

### Windows

> 💡 **Credit**  
> The installation steps below were prototyped based on this YouTube tutorial: https://www.youtube.com/watch?v=akgl2urRIyk. You can also refer to this video tutorial to download and install VMware and unlock it for running macOS.

1. Download and install VMware Workstation 17.5.2
    - Official link: https://support.broadcom.com/group/ecx/productfiles?subFamily=VMware%20Workstation%20Pro&displayGroup=VMware%20Workstation%20Pro%2017.0%20for%20Windows&release=17.5.2&os=&servicePk=520398&language=EN&freeDownloads=true
    - You can also obtain `VMware-workstation-full-17.5.2-23775571.exe` from other sources, MD5: `c0a0353c1dade2089b55ce04ca942964`
    - Please prepare a serial number before installation

2. Download and install unlocker: See [this tutorial](https://github.com/DrDonk/unlocker?tab=readme-ov-file#2-running-the-unlocker)

### Ubuntu

1. Download and install VMware Workstation 17.5.1
     - Please prepare a serial number before installation
```bash
wget https://softwareupdate.vmware.com/cds/vmw-desktop/ws/17.5.1/23298084/linux/core/VMware-Workstation-17.5.1-23298084.x86_64.bundle.tar 
tar -xvf VMware-Workstation-17.5.1-23298084.x86_64.bundle.tar
sudo sh VMware-Workstation-17.5.1-23298084.x86_64.bundle --console
```

2. Apply patches for recent kernels
```bash
cd <any_temp_folder>
git clone https://github.com/mkubecek/vmware-host-modules
cd vmware-host-modules
git checkout workstation-17.5.1
make
tar -cf vmnet.tar vmnet-only
tar -cf vmmon.tar vmmon-only
mv vmnet.tar /usr/lib/vmware/modules/source/
mv vmmon.tar /usr/lib/vmware/modules/source/
sudo vmware-modconfig --console --install-all
```

3. Disable 5-level paging: Modify `/etc/default/grub`
```bash
GRUB_CMDLINE_LINUX_DEFAULT="no5lvl"
GRUB_CMDLINE_LINUX="no5lvl"
```

4. Restart your computer

## Download Virtual Machine

1. For AMD CPUs, download:
```bash
git lfs install
git clone git@hf.co:datasets/yangpei-comp/macosworld_vmware_amd
```

2. For Intel CPUs, download:
```bash
git lfs install
git clone git@hf.co:datasets/yangpei-comp/macosworld_vmware_intel
```

3. Navigate to the macosworld_vmware directory and locate the path to `macOSWorld.vmx`

VMware environment configuration is now complete. You can launch the virtual machine from VMware to test whether it runs properly. Note that after using the virtual machine, you don't need to shut it down before starting the benchmark, as the testbench supports snapshot recovery directly from a running virtual machine.