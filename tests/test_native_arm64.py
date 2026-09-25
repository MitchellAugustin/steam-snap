import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import yaml
import vdf


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


native = load_module("native", ROOT / "src/steam-native")


class NativeTests(unittest.TestCase):
    def test_dispatcher_preserves_arguments_on_both_architectures(self):
        with tempfile.TemporaryDirectory() as directory:
            snap = Path(directory)
            for arch, relative in (("amd64", "usr/lib/steam/bin_steam.sh"), ("arm64", "bin/steam-native")):
                executable = snap / relative
                executable.parent.mkdir(parents=True, exist_ok=True)
                executable.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\nexit 37\n')
                executable.chmod(0o755)
                result = subprocess.run(
                    ["/bin/bash", str(ROOT / "src/steam-launch"), "-no-cef-sandbox", "steam://test with spaces"],
                    env=dict(os.environ, SNAP=str(snap), SNAP_ARCH=arch), capture_output=True, text=True)
                self.assertEqual(result.returncode, 37)
                self.assertEqual(result.stdout.splitlines(), ["-no-cef-sandbox", "steam://test with spaces"])

    def test_proton_default_defers_while_steam_is_running(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "steam.pid").write_text(str(os.getpid()))
            native.set_default_proton(root)
            self.assertFalse((root / "config/config.vdf").exists())
            self.assertFalse((root / "config/.snap-proton11-arm64-default").exists())

    def test_proton_default_preserves_games_and_user_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            config.mkdir()
            path = config / "config.vdf"
            original = '''"InstallConfigStore"
{
    "Software"
    {
        "Valve"
        {
            "Steam"
            {
                "CompatToolMapping"
                {
                    "0"
                    {
                        "name" "proton_experimental"
                    }
                    "123"
                    {
                        "name" "custom_proton"
                        "config" "keep"
                    }
                }
                "Other" "one"
                "Other" "two"
            }
        }
    }
}
'''
            path.write_text(original)
            native.set_default_proton(root)
            data = vdf.loads(path.read_text(), mapper=vdf.VDFDict)
            steam = data["InstallConfigStore"]["Software"]["Valve"]["Steam"]
            mapping = steam["CompatToolMapping"]
            self.assertEqual(mapping["0"]["name"], "proton_11-arm64")
            self.assertEqual(list(mapping).count("0"), 1)
            self.assertEqual(mapping["123"]["name"], "custom_proton")
            self.assertEqual(mapping["123"]["config"], "keep")
            self.assertEqual(steam[(1, "Other")], "two")
            self.assertEqual((config / "config.vdf.before-snap-proton11-arm64").read_text(), original)
            path.write_text(original)
            native.set_default_proton(root)
            self.assertEqual(path.read_text(), original)

    def test_proton_default_initializes_new_config_and_skips_invalid_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native.set_default_proton(root)
            path = root / "config/config.vdf"
            self.assertIn("proton_11-arm64", path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            path = root / "config/config.vdf"
            path.write_text('"InstallConfigStore" "not a section"')
            native.set_default_proton(root)
            self.assertEqual(path.read_text(), '"InstallConfigStore" "not a section"')
            self.assertFalse((root / "config/.snap-proton11-arm64-default").exists())

    def test_game_shell_uses_private_service_and_preserves_command(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            client = home / ".local/share/Steam/steamrtarm64/pv-runtime/steam-runtime-steamrt/pressure-vessel/bin/steam-runtime-launch-client"
            client.parent.mkdir(parents=True)
            client.write_text('#!/bin/bash\nprintf "%s\\0" "$@"\nexit 37\n')
            client.chmod(0o755)
            private = "com.steampowered.PressureVessel.LaunchAlongsideSteam.Instance123"
            command = 'printf "%s" "argument with spaces; not a separate command"'
            environment = dict(os.environ, SNAP_USER_COMMON=str(home),
                               SNAP_STEAM_LAUNCH_SERVICE=private,
                               SRT_LAUNCHER_SERVICE_ALONGSIDE_STEAM="com.steampowered.PressureVessel.LaunchAlongsideSteam")
            result = subprocess.run(["/bin/bash", str(ROOT / "src/steam-native-game"), command],
                                    env=environment, cwd=home, capture_output=True)
            self.assertEqual(result.returncode, 37)
            arguments = result.stdout.decode().rstrip("\0").split("\0")
            self.assertEqual(arguments[:2], ["--bus-name=" + private, "--directory=" + str(home)])
            self.assertEqual(arguments[-4:], ["--", "/bin/sh", "-c", command])
            self.assertNotIn("--alongside-steam", arguments)
            self.assertNotIn("--pass-env=LD_LIBRARY_PATH", arguments)
            for values in ([], [command, "extra"]):
                rejected = subprocess.run(["/bin/bash", str(ROOT / "src/steam-native-game"), *values],
                                          env=environment, capture_output=True)
                self.assertEqual(rejected.returncode, 2)
            environment["SNAP_STEAM_LAUNCH_SERVICE"] = "com.steampowered.PressureVessel.LaunchAlongsideSteam"
            rejected = subprocess.run(["/bin/bash", str(ROOT / "src/steam-native-game"), command],
                                      env=environment, capture_output=True)
            self.assertEqual(rejected.returncode, 2)

    def test_runtime_wrapper_scopes_home_and_forwards_client_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "real home"
            runtime = home / ".local/share/Steam/steamrtarm64/pv-runtime"
            run = runtime / "steam-runtime-steamrt/run"
            run.parent.mkdir(parents=True)
            run.write_text('#!/bin/bash\nprintf "%s\\n" "$HOME" "$@"\n')
            run.chmod(0o755)
            result = subprocess.run([
                "/bin/bash", str(ROOT / "src/steam-native-runtime"),
                "--for-steam-client", "--", "/bin/true",
            ], env=dict(os.environ, HOME=str(home), SNAP_USER_COMMON=str(home)),
                check=True, capture_output=True, text=True)
            self.assertEqual(result.stdout.splitlines(), [
                str(runtime / "client-container-home"), "--for-steam-client", "--", "/bin/true",
            ])

    def test_client_restores_home_before_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "real home"
            root = home / ".local/share/Steam"
            platform = root / "steamrtarm64"
            platform.mkdir(parents=True)
            executable = platform / "steam"
            executable.write_text('#!/bin/bash\nprintf "%s\\n" "$HOME" "$PWD" "$SNAP_STEAM_LAUNCH_SERVICE" "$STEAM_GAME_LAUNCH_SHELL" "$@"\n')
            executable.chmod(0o755)
            result = subprocess.run([
                "/bin/bash", str(ROOT / "src/steam-native-client"), "steam://open/main",
            ], env=dict(os.environ, HOME=str(Path(directory) / "container home"),
                        SNAP_USER_COMMON=str(home), SNAP=str(ROOT),
                        SRT_LAUNCHER_SERVICE_ALONGSIDE_STEAM="com.steampowered.PressureVessel.LaunchAlongsideSteam.Instance123"),
                check=True, capture_output=True, text=True)
            self.assertEqual(result.stdout.splitlines(), [
                str(home), str(root), "com.steampowered.PressureVessel.LaunchAlongsideSteam.Instance123",
                str(ROOT / "bin/steam-native-game"), "steam://open/main",
            ])

    def test_launch_service_wraps_client_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            snap = Path(directory) / "snap"
            runtime = home / "runtime"
            entry_point = str(runtime / "steam-runtime-steamrt/_v2-entry-point")
            with mock.patch.dict(native.os.environ, {"SNAP_USER_COMMON": str(home), "SNAP": str(snap)}), \
                    mock.patch.object(native.sys, "argv", ["steam-native", "steam://open/main"]), \
                    mock.patch.object(native, "seed_client", return_value=(home, runtime)), \
                    mock.patch.object(native.subprocess, "check_output", return_value=entry_point + "\n") as unpack, \
                    mock.patch.object(native.os, "execv") as execute:
                native.main()
            self.assertIn("--unpack-dir=" + str(runtime), unpack.call_args.args[0])
            executable, arguments = execute.call_args.args
            self.assertTrue(executable.endswith("/srt-client-container"))
            self.assertEqual(arguments[1:4], [
                "--pv-entry-point", str(snap / "bin/steam-native-runtime"), "--",
            ])
            self.assertEqual(arguments[-1], "steam://open/main")

    def test_container_home_does_not_export_legacy_subdirectories(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            root = home / ".local/share/Steam"
            runtime = root / "steamrtarm64/pv-runtime"
            links = home / ".steam"
            links.mkdir()
            for name, target in {"sdk32": "linux32", "bin32": "ubuntu12_32"}.items():
                (root / target).mkdir(parents=True)
                (links / name).symlink_to(root / target)
            container_home = native.client_container_home(root, runtime)
            self.assertEqual(native.client_container_home(root, runtime), container_home)
            self.assertEqual({link.name for link in (container_home / ".steam").iterdir()}, {"root", "steam"})
            self.assertEqual((container_home / ".steam/root").resolve(), root)
            self.assertEqual((links / "sdk32").resolve(), root / "linux32")
            self.assertEqual((links / "bin32").resolve(), root / "ubuntu12_32")

    def test_recipe_supports_both_architectures_directly(self):
        with (ROOT / "snap/snapcraft.yaml").open() as stream:
            recipe = yaml.safe_load(stream)
        self.assertEqual(recipe["name"], "steam")
        self.assertEqual(recipe["base"], "core24")
        self.assertEqual(recipe["confinement"], "strict")
        self.assertEqual(recipe["platforms"], {"amd64": None, "arm64": None})
        self.assertEqual(recipe["apps"]["steam"]["environment"]["HOME"], "$SNAP_USER_COMMON")
        self.assertEqual(recipe["apps"]["steam"]["command"], "bin/steam-launch -no-cef-sandbox")
        packages = recipe["parts"]["steam"]["stage-packages"]
        self.assertIn("steam-launcher", packages[0]["on amd64"])
        self.assertIn("python3-vdf", packages[1]["on arm64"])
        for package in packages[1]["on arm64"]:
            self.assertNotIn(":", package)
            self.assertNotIn("multilib", package)
        self.assertIn("tools/fetch-arm64.sh", recipe["parts"]["steam"]["override-build"])
        self.assertNotIn("fex", recipe["parts"])
        self.assertNotIn("amd64-rootfs", recipe["parts"])

    def test_bootstrap_preserves_existing_data_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home with spaces"
            snap = Path(directory) / "snap"
            seed = snap / "usr/lib/steam"
            (seed / "native-runtime").mkdir(parents=True)
            (seed / "steam-arm64").write_bytes(b"bootstrap")
            (seed / "native-runtime/steam-runtime-steamrt.sh").write_bytes(b"runtime")
            steam = home / ".local/share/Steam"
            preserved = ["steamapps/compatdata/123/pfx/save", "config/config.vdf", "userdata/123/save", "package/beta"]
            for name in preserved:
                target = steam / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"existing user data")
            native.seed_client(home, snap)
            executable = steam / "steamrtarm64/steam"
            self.assertEqual(executable.read_bytes(), b"bootstrap")
            executable.write_bytes(b"updated by Valve")
            native.seed_client(home, snap)
            self.assertEqual(executable.read_bytes(), b"updated by Valve")
            for name in preserved:
                self.assertEqual((steam / name).read_bytes(), b"existing user data")
            self.assertEqual((home / ".steam/root").resolve(), steam)

    def test_bootstrap_preserves_external_library_links(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            snap = Path(directory) / "snap"
            seed = snap / "usr/lib/steam"
            (seed / "native-runtime").mkdir(parents=True)
            (seed / "steam-arm64").write_bytes(b"bootstrap")
            steam = home / ".local/share/Steam"
            steam.mkdir(parents=True)
            external = Path(directory) / "external library"
            external.mkdir()
            (steam / "steamapps").symlink_to(external)
            (home / ".steam").mkdir()
            (home / ".steam/root").symlink_to(steam)
            native.seed_client(home, snap)
            self.assertTrue((steam / "steamapps").is_symlink())
            self.assertEqual((steam / "steamapps").resolve(), external)
            self.assertEqual((steam / "package/beta").read_text(), "publicbeta\n")


if __name__ == "__main__":
    unittest.main()