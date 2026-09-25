import importlib.machinery
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("native", str(ROOT / "src/steam-native"))
spec = importlib.util.spec_from_loader(loader.name, loader)
native = importlib.util.module_from_spec(spec)
loader.exec_module(native)


def main():
    base = Path(os.environ["SNAP_USER_COMMON"])
    snap = Path(os.environ["SNAP"])
    with tempfile.TemporaryDirectory(prefix="native-mount-probe-", dir=base) as directory:
        home = Path(directory) / "home with spaces"
        root, runtime = native.seed_client(home, snap)
        for name, target in {
            "sdk32": "linux32", "sdk64": "linux64",
            "bin32": "ubuntu12_32", "bin64": "ubuntu12_64",
        }.items():
            (root / target).mkdir()
            (home / ".steam" / name).symlink_to(root / target)
        source = root / "package/tmp/linux32/probe"
        source.parent.mkdir(parents=True)
        destination = root / "linux32/probe"
        entry_point = subprocess.check_output([
            "/bin/bash", str(runtime / "steam-runtime-steamrt.sh"),
            "--runtime=steam-runtime-steamrt", f"--unpack-dir={runtime}",
        ], text=True).strip()
        corrected_home = native.client_container_home(root, runtime)
        executable = ROOT / "tests/native-rename-probe"
        for label, container_home, expected in (
            ("legacy", home, 18), ("corrected", corrected_home, 0),
        ):
            source.write_bytes(b"disposable update")
            environment = dict(os.environ, HOME=str(container_home))
            for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
                environment[name] = str(home / name.lower())
            environment["PRESSURE_VESSEL_GC_RUNTIMES"] = "0"
            environment["STEAM_LINUX_RUNTIME_LOG"] = "0"
            result = subprocess.run([
                entry_point, "--", str(executable), str(source), str(destination),
            ], env=environment, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            log = ROOT / "tests" / (label + "-mount-probe.log")
            log.write_text(result.stdout)
            print(f"{label}: exit={result.returncode}, expected={expected}; log={log}", flush=True)
            if result.returncode != expected:
                print(result.stdout[-12000:])
                raise SystemExit(1)
        if destination.read_bytes() != b"disposable update":
            raise SystemExit("renamed file contents differ")
        print("PASS: old setup fails with EXDEV; corrected setup preserves atomic rename")

        fake_snap = Path(directory) / "snap"
        (fake_snap / "bin").mkdir(parents=True)
        (fake_snap / "usr").symlink_to(snap / "usr")
        for name in ("steam-native", "steam-native-client", "steam-native-runtime", "steam-native-game"):
            target = fake_snap / "bin" / name
            shutil.copy2(ROOT / "src" / name, target)
            target.chmod(0o755)
        fake_client = root / "steamrtarm64/steam"
        fake_client.write_text('''#!/bin/bash
set -eu
test "$HOME" = "$SNAP_USER_COMMON"
case "$SRT_LAUNCHER_SERVICE_ALONGSIDE_STEAM" in
    com.steampowered.PressureVessel.LaunchAlongsideSteam.Instance*) ;;
    *) exit 90 ;;
esac
test -d /run/pressure-vessel
printf 'CLIENT_NAMESPACE=%s\\n' "$(readlink /proc/self/ns/mnt)"
cat /etc/os-release
test ! -x /usr/bin/python3
"$PROBE_RENAME" "$PROBE_SOURCE" "$PROBE_DESTINATION"
test "$SNAP_STEAM_LAUNCH_SERVICE" = "$SRT_LAUNCHER_SERVICE_ALONGSIDE_STEAM"
export SRT_LAUNCHER_SERVICE_ALONGSIDE_STEAM=com.steampowered.PressureVessel.LaunchAlongsideSteam
export PROTON_LOG=1 SteamAppId=123456 STEAM_COMPAT_APP_ID=123456
printf -v command '/bin/bash %q' "$PROBE_OUTER"
"$STEAM_GAME_LAUNCH_SHELL" "$command"
set +e
"$STEAM_GAME_LAUNCH_SHELL" 'exit 37'
status=$?
set -e
test "$status" -eq 37
printf 'GAME_SHELL_STATUS_OK\\n'
''')
        fake_client.chmod(0o755)
        outer = Path(directory) / "outer-probe.sh"
        outer.write_text('''#!/bin/bash
set -eu
test ! -d /run/pressure-vessel
test "$PROTON_LOG" = 1
test "$SteamAppId" = 123456
test "$STEAM_COMPAT_APP_ID" = 123456
test "$PWD" = "$HOME/.local/share/Steam"
printf 'OUTER_NAMESPACE=%s\\n' "$(readlink /proc/self/ns/mnt)"
cat /etc/os-release
python3 -c 'import os, runpy, sys; from pathlib import Path; path = os.environ["PROBE_FEX"]; sys.path.insert(0, str(Path(path).parent)); runpy.run_path(path, run_name="fex_import_probe"); print("FEX launcher Python imports: OK")'
"$PROBE_WRAPPER" -- /usr/bin/python3 -c 'print("Steam launch wrapper: Python OK")'
"$PROBE_WRAPPER" -- "$PROBE_GAME_RUNTIME/_v2-entry-point" --verb=run -- /bin/bash -c 'set -eu; /bin/true; python3 --version; cat /etc/os-release; printf "GAME_RUNTIME_OK\\n"'
''')
        source.write_bytes(b"helper update")
        real_root = base / ".local/share/Steam"
        environment = dict(os.environ, HOME=str(home), SNAP_USER_COMMON=str(home), SNAP=str(fake_snap))
        environment.update({
            "PROBE_RENAME": str(executable), "PROBE_SOURCE": str(source),
            "PROBE_DESTINATION": str(destination), "PROBE_OUTER": str(outer),
            "PROBE_WRAPPER": str(real_root / "linuxarm64/steam-launch-wrapper"),
            "PROBE_FEX": str(real_root / "steamapps/common/FEX-Emu/fex-compat-tool"),
            "PROBE_GAME_RUNTIME": str(real_root / "steamapps/common/SteamLinuxRuntime_4-arm64"),
            "PRESSURE_VESSEL_VARIABLE_DIR": str(Path(directory) / "runtime-var"),
            "PRESSURE_VESSEL_GC_RUNTIMES": "0", "STEAM_LINUX_RUNTIME_LOG": "0",
        })
        for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
            environment[name] = str(home / name.lower())
        result = subprocess.run([
            "/usr/bin/python3", str(fake_snap / "bin/steam-native"),
        ], env=environment, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180)
        log = ROOT / "tests/handoff-probe.log"
        log.write_text(result.stdout)
        print(f"handoff: exit={result.returncode}; log={log}", flush=True)
        for line in result.stdout.splitlines():
            if line.startswith(("CLIENT_NAMESPACE=", "OUTER_NAMESPACE=", "PRETTY_NAME=",
                                "FEX launcher", "Steam launch wrapper", "Python ",
                                "GAME_RUNTIME_OK", "GAME_SHELL_STATUS_OK", "rename succeeded")):
                print(line)
        if result.returncode != 0 or "GAME_RUNTIME_OK" not in result.stdout or "GAME_SHELL_STATUS_OK" not in result.stdout:
            print("Probe failed; inspect the saved log for details")
            raise SystemExit(1)
        print("PASS: official helper preserves updates and launches the game runtime outside the client container")


if __name__ == "__main__":
    main()