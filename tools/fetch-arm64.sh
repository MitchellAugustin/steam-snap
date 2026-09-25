#!/bin/bash

set -eu

runtime_url=https://repo.steampowered.com/steamrt3c/images/3c.0.20260824.257593
install_root="$CRAFT_PART_INSTALL/usr/lib/steam"
mkdir -p "$install_root/native-runtime"
curl --fail --location --retry 3 https://client-update.steamstatic.com/bins_linuxarm64_linuxarm64.zip.f523fa87fc6b9b5435a5e7370cb0d664ef53b50b -o bootstrap.zip
echo '96347e25acce1b4fc65e69f12d3e32587e0e180e4cbd3b4ad98af43d0f09f070  bootstrap.zip' | sha256sum --check --strict
unzip -p bootstrap.zip steamrtarm64/steam > "$install_root/steam-arm64"
chmod 755 "$install_root/steam-arm64"
while read -r suffix digest; do
    name="steam-runtime-steamrt-arm64.$suffix"
    curl --fail --location --retry 3 "$runtime_url/$name" -o "$name"
    echo "$digest  $name" | sha256sum --check --strict
    cp "$name" "$install_root/native-runtime/steam-runtime-steamrt.$suffix"
done <<'CHECKSUMS'
tar.xz 2f2be461b6a4360828e200e1644e18cd957eedc36a38e5a1e13a39276320b6e2
sh 803d5a5f4ac198002450b57ef5387df234353f83ca012049c2f6b3a9a13ccbb9
VERSIONS.txt 83779212d56d85307ec5a51668c7e0bc1e85a30ca0262c847086143f6b6b2020
CHECKSUMS
craftctl set version=native-arm64-poc-20260925d
craftctl set grade=devel