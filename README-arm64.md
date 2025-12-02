steam_218_amd64: Retrieve this from an AMD64 machine by using `snap download steam`, and then `unsquashfs` it into the directory.
amd64_rootfs: Retrieve this using FEXRootFSFetcher and unsquashfs it into amd64_rootfs/x86_rootfs. Modify as needed. (Eventually, will bind some required host driver components into this.)
fex-emu-armv8.0 / fex-emu-wine: extracted using dpkg -x from `apt download fex-emu-armv8.0` `apt download fex-emu-wine` from FEX PPA. (TBD: Download these the proper way though snapcraft.yaml).

Other modifications are tracked here in git.

Example structure:
ls fex-emu-* amd64_rootfs/ steam_218_amd64/
fex-emu-armv8.0_2511~n_arm64.deb  fex-emu-wine_2511~n_arm64.deb

amd64_rootfs/:
x86_rootfs

fex-emu-wine:
usr

steam_218_amd64/:
60-steam-input.rules  60-steam-vr.rules  bin  etc  lib  LICENSE  meta  snap  tests  usr  var

