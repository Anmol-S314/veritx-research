# Creating a VM on the AlmaLinux Host

How to log into our self-hosted AlmaLinux server and create a new **Ubuntu
24.04 Server** VM on it using **Virtual Machine Manager** (virt-manager).

VMs live on the internal `172.30.20.x` subnet, which only exists *inside* the
AlmaLinux host — you can't reach it from your laptop directly, only from the
AlmaLinux desktop.

---

## 1. Log in to the AlmaLinux host (Remmina / VNC)

| Field    | Value                  |
|----------|------------------------|
| Protocol | VNC                    |
| Server   | `161.248.22.228:5901`  |
| Password | `Deenet@123`           |

1. Open **Remmina**.
2. New connection (or the saved one) → **Protocol = VNC**.
3. **Server:** `161.248.22.228:5901`
4. **Password:** `Deenet@123`
5. Connect → you land on the AlmaLinux graphical desktop.

---

## 2. Create the VM (Virtual Machine Manager)

1. Open **Virtual Machine Manager** (search "Virtual Machine Manager" or run
   `virt-manager` in a terminal).
2. Click **Create a new virtual machine** (top-left, monitor icon).
3. **Install method** → *Local install media (ISO image or CDROM)* → **Forward**.
4. **Browse** → select the **Ubuntu 24.04 Server** ISO → **Forward**.
   (If the OS isn't auto-detected, set it to Ubuntu 24.04 manually.)
5. **Memory and CPU** → set RAM and vCPUs for the workload → **Forward**.
6. **Storage:**
   - Select **Create a disk image for the virtual machine**.
   - Enter the size in **GiB** — this is how much storage the VM gets.
   - virt-manager creates a **`.qcow2`** disk in the default pool
     (`/var/lib/libvirt/images/<vm-name>.qcow2`). qcow2 is thin-provisioned, so
     it only grows on disk as the VM actually uses space.
   - **Forward**.

   > Prefer a custom size/location? Click **Select or create custom storage** →
   > **Manage** → **+** to make a `.qcow2` volume in a specific pool, or
   > pre-create one on the host:
   > ```bash
   > qemu-img create -f qcow2 /var/lib/libvirt/images/<vm-name>.qcow2 100G
   > ```
7. **Final step:**
   - **Name** the VM.
   - Expand **Network selection** → **`eno4`** as a **macvtap** device (this is
     what the existing `172.30.20.x` VMs use — match theirs).
   - **Finish**.

   > ⚠️ **macvtap gotcha:** with macvtap, the AlmaLinux *host itself* cannot
   > talk to the guest over the network (and vice-versa) — but other machines
   > and VMs on the subnet can. Use the VM console for host-side access.
8. The VM boots the Ubuntu installer.

---

## 3. Ubuntu 24.04 Server install — network config

Run through the installer normally. The one part that matters for us is the
**network** screen.

> ⛔ **Before you pick static:** the subnet is a `/29` and is **currently full**
> (see §6). There is **no free static address** right now — a static install
> will collide. Free up an address first, or expand the subnet. The steps below
> are the procedure for when an address *is* available.

**Static IP:**
1. At the network screen, select the interface → **Edit IPv4**.
2. **IPv4 Method: Manual**.
3. Fill in:
   - **Address:** a free `172.30.20.x` (`.1`–`.6` only; all taken today — see §6)
   - **Netmask:** `255.255.255.248` (this is the `/29`)
   - **Gateway:** `172.30.20.1`
   - **DNS:** your usual resolver (e.g. `8.8.8.8` / `1.1.1.1`)
4. Continue the install.

**DHCP (fallback / simpler):**
- Leave **IPv4 Method: Automatic (DHCP)**. The VM gets an address
  automatically; look it up after boot (see §4).
- Note: DHCP only helps if there's a free address in the `/29` — with the
  subnet full, neither method works until one is freed.

Finish the install and reboot.

---

## 4. Find the VM's IP

In virt-manager, double-click the VM → the console login shows it. Or from a
host terminal:

```bash
virsh list --all            # all VMs and their state
virsh domifaddr <vm-name>   # the VM's IP on 172.30.20.x
```

> With **macvtap** networking, `virsh domifaddr` frequently returns nothing
> (libvirt can't see the lease). The reliable way is the **VM console** in
> virt-manager — log in and run `ip -brief addr`.

---

## 5. Access map — how to reach each thing

The public IP `161.248.22.228` **port-forwards different ports to different
machines** — this is the part that trips everyone up.

| To reach                         | Use                                            | Login                       |
|----------------------------------|------------------------------------------------|-----------------------------|
| **AlmaLinux host** (hypervisor)  | Remmina **VNC** → `161.248.22.228:5901`        | VNC password `Deenet@123`   |
| **gitlab VM** (`172.30.20.2`)    | **SSH** → `161.248.22.228` **port 8904**       | `deenet` / `deenet`         |

Notes:
- The hypervisor's SSH (port 22) is **firewalled** — you administer it through
  the VNC desktop, not SSH.
- The internal `172.30.20.x` VMs are **only reachable from on the subnet**
  (e.g. from the gitlab box, or the host). They're not routable from a laptop.

### VS Code / SSH config

Add to `~/.ssh/config`:

```
# Jump host — the one box on the subnet we can SSH into directly
Host gitlab-vm
  HostName 161.248.22.228
  User deenet
  Port 8904

# Any internal VM on the subnet — jump through gitlab-vm automatically.
# Usage: ssh 172.30.20.3  (any address in the range just works)
Host 172.30.20.*
  ProxyJump gitlab-vm
  User <guest-user>   # set to the login on the target VM
```

Then `ssh gitlab-vm` for the jump box itself, or `ssh 172.30.20.3` to land
directly on an internal VM — SSH tunnels through gitlab-vm automatically. In
VS Code: **Remote-SSH → Connect to Host → 172.30.20.3**.

> `ProxyJump gitlab-vm` = SSH first connects to gitlab-vm, then opens a second
> hop to the internal IP through it. The internal VM never needs a public port.
> If a VM uses a different login, add an explicit `Host` block for it above the
> wildcard with its own `User`.

---

## 6. IP allocation — the subnet is FULL

> **⚠️ This is why you "ran out of VMs."** The subnet is `172.30.20.0/29` — a
> `/29` has only **6 usable addresses** (`.1`–`.6`), and **all six are taken.**
> It's not a virt-manager limit and DHCP won't help — there are literally no
> free addresses left in the range. To add more VMs you need a **bigger subnet**
> (e.g. re-provision as `/28` = 14 hosts, or `/27` = 30) or free up an address.

Current occupancy (from a network scan on 2026-07-15 via the `gitlab` box):

| IP           | MAC                 | What it is                                  |
|--------------|---------------------|---------------------------------------------|
| 172.30.20.1  | `e4:8d:8c:c8:47:9b` | Gateway — the AlmaLinux host (physical NIC) |
| 172.30.20.2  | `52:54:00:80:b1:b9` | **gitlab** — Ubuntu 24.04 VM                |
| 172.30.20.3  | `52:54:00:38:17:fa` | KVM VM (in use)                             |
| 172.30.20.4  | `52:54:00:89:3e:60` | KVM VM (in use)                             |
| 172.30.20.5  | `52:54:00:b9:eb:2c` | KVM VM (in use)                             |
| 172.30.20.6  | `52:54:00:d6:26:12` | KVM VM (in use)                             |

`52:54:00:*` MACs = QEMU/KVM guests (the virt-manager VMs). All addresses are
occupied. To map a MAC to a VM name later, run on the AlmaLinux host:
`virsh list --all` then `virsh dumpxml <vm> | grep 'mac address'`.

---

## 7. Expanding the subnet (making room for more VMs)

The blocker to new VMs is that `172.30.20.0/29` is full (6 IPs). To get more,
widen the subnet — e.g. `/28` = 14 hosts, `/27` = 30. **How** depends on where
the subnet is defined, so diagnose that first.

Because the VMs use **macvtap on `eno4`**, they share `eno4`'s L2 segment, and
the subnet size lives on whatever device owns the gateway `172.30.20.1`
(MAC `e4:8d:8c:c8:47:9b`).

### Step 1 — find out who owns the gateway `.1`

On the **AlmaLinux host** (VNC desktop terminal):

```bash
ip -brief addr | grep 172.30.20      # does the HOST hold 172.30.20.1 on eno4?
ip route
```

- **If the host shows `172.30.20.1/29` on `eno4`** → the host is the gateway;
  you change the mask here (case A).
- **If it doesn't** → `.1` is an upstream router/firewall; the mask has to be
  changed there, not on the host (case B).

### Case A — subnet defined on the AlmaLinux host

1. Confirm the wider range (`172.30.20.0/28`, i.e. `.1`–`.14`) isn't already
   used elsewhere on the network.
2. Change the host's address on `eno4` from `/29` to `/28` (e.g. edit the
   NetworkManager connection: `nmtui`, or
   `nmcli con mod <con> ipv4.addresses 172.30.20.1/28`, then bring it up).
3. Update the **netmask on every existing VM** from `255.255.255.248` to
   `255.255.255.240` (`/28`) — otherwise they won't see the new `.7`–`.14`
   addresses as local. (VMs on DHCP just pick it up on renew.)
4. New VMs can now use `172.30.20.7`–`.14`.

### Case B — subnet defined upstream (router/firewall)

The AlmaLinux host can't fix this. Whoever administers the gateway (`.1`)
device has to widen the range there, then the host + all VMs get the new mask
(step 3 above). Flag it to whoever owns the network hardware.

### Alternative — don't expand, use NAT instead

If touching the shared subnet is risky, create a **separate libvirt NAT
network** for new VMs instead of macvtap: in virt-manager, *Edit → Connection
Details → Virtual Networks → +*, define e.g. `192.168.100.0/24` with NAT +
DHCP. New VMs on that network get their own private range and reach the
internet via the host — they just won't be directly addressable on
`172.30.20.x`. Good for VMs that don't need a subnet-visible IP.

---

## Notes

- **The subnet (`/29`) is full** — that's the real "ran out of VMs." Neither
  static nor DHCP can add a VM until an address is freed or the subnet is
  expanded (`/28`+). Keep the §6 table current so it's obvious at a glance.
- **`eno4` (macvtap)** is the network device to pick so a VM reaches the
  subnet — confirm against an existing VM's NIC if virt-manager labels it
  differently.
