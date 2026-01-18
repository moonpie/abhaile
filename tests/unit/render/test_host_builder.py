# Merged host builder tests
# Modules under test: tools.render.lib.host.resolved_builder, tools.render.lib.host.software_builder, tools.render.lib.host.user_builder

from pathlib import Path
import yaml
import pytest

from tools.render.host.resolved_builder import build_resolved_configs
from tools.render.host.software_builder import build_software_configs
from tools.render.host import software_builder as software_builder_mod
from tools.render.host.user_builder import build_user_configs
from tools.render.host import user_builder as user_builder_mod


def test_build_resolved_configs_from_host_dir(tmp_path: Path):
    cfg = tmp_path / "config" / "hosts"
    host_dir = cfg / "phobos" / "systemd-resolved"
    host_dir.mkdir(parents=True)
    f = host_dir / "resolved.conf"
    f.write_text("DNS=1.1.1.1")

    out = tmp_path / "out"
    build_resolved_configs("phobos", cfg, out)

    dest = out / "phobos" / "systemd-resolved" / "etc" / "systemd" / "resolved.conf"
    assert dest.exists()
    assert dest.read_text() == "DNS=1.1.1.1"


def test_build_resolved_configs_falls_back_to_common(tmp_path: Path):
    cfg = tmp_path / "config" / "hosts"
    common = cfg / "common" / "systemd-resolved"
    common.mkdir(parents=True)
    (common / "c.conf").write_text("DNS=8.8.8.8")

    out = tmp_path / "out"
    build_resolved_configs("phobos", cfg, out)
    dest = out / "phobos" / "systemd-resolved" / "etc" / "systemd" / "c.conf"
    assert dest.exists()
    assert dest.read_text() == "DNS=8.8.8.8"


def test_build_resolved_configs_no_files_no_output(tmp_path: Path):
    cfg = tmp_path / "config" / "hosts"
    cfg.mkdir(parents=True)
    out = tmp_path / "out"
    build_resolved_configs("phobos", cfg, out)
    assert not (out / "phobos").exists()


def test_build_software_configs_writes_scripts_and_md(tmp_path: Path):
    hosts = tmp_path / "config" / "hosts"
    common = hosts / "common"
    hostdir = hosts / "phobos"
    common.mkdir(parents=True)
    hostdir.mkdir(parents=True)

    (common / "software" / "downloads").mkdir(parents=True)
    (common / "software" / "builds").mkdir(parents=True)
    (common / "software" / "commands").mkdir(parents=True)

    common_yaml = common / "software.yaml"
    common_yaml.write_text(
        yaml.safe_dump(
            {
                "packages": ["curl", "git"],
                "downloads": ["dl1"],
                "builds": ["b1"],
                "commands": ["cmd1"],
            }
        )
    )

    (common / "software" / "downloads" / "dl1.yaml").write_text(
        yaml.safe_dump(
            {"name": "download1", "description": "desc", "commands": ["echo dl"]}
        )
    )
    (common / "software" / "builds" / "b1.yaml").write_text(
        yaml.safe_dump({"name": "build1", "commands": ["make all"]})
    )
    (common / "software" / "commands" / "cmd1.yaml").write_text(
        yaml.safe_dump({"name": "run1", "commands": ["echo run"]})
    )

    out = tmp_path / "out"
    build_software_configs("phobos", hosts, out)

    sw_dir = out / "phobos" / "software"
    assert (sw_dir / "software.yaml").exists()
    assert (sw_dir / "install-packages.sh").exists()
    assert (sw_dir / "downloads.sh").exists()
    assert (sw_dir / "builds.sh").exists()
    assert (sw_dir / "commands.sh").exists()
    assert (sw_dir / "SOFTWARE.md").exists()


def test_build_software_configs_no_files_no_output(tmp_path: Path):
    hosts = tmp_path / "config" / "hosts"
    hosts.mkdir(parents=True)
    out = tmp_path / "out"
    build_software_configs("phobos", hosts, out)
    assert not out.exists()


def test_build_software_configs_no_files_noop(tmp_path):
    hosts_path = tmp_path / "config" / "hosts"
    output_path = tmp_path / "out"
    software_builder_mod.build_software_configs("phobos", hosts_path, output_path)
    assert not (output_path / "phobos").exists()


def test_build_software_configs_malformed_action_yaml_raises(tmp_path):
    hosts_path = tmp_path / "config" / "hosts"
    (hosts_path / "common").mkdir(parents=True)
    (hosts_path / "software" / "downloads").mkdir(parents=True)

    common_yaml = hosts_path / "common" / "software.yaml"
    common_yaml.write_text(yaml.safe_dump({"downloads": ["badname"]}))

    bad_file = hosts_path / "software" / "downloads" / "badname.yaml"
    bad_file.write_text(": [invalid_yaml")

    import yaml as yaml_module

    with pytest.raises((yaml_module.YAMLError, Exception)):
        software_builder_mod.build_software_configs(
            "phobos", hosts_path, tmp_path / "out"
        )


def test_build_software_configs_write_permission_error(tmp_path, monkeypatch):
    hosts_path = tmp_path / "config" / "hosts"
    (hosts_path / "common").mkdir(parents=True)

    common_yaml = hosts_path / "common" / "software.yaml"
    common_yaml.write_text(yaml.safe_dump({"packages": ["curl", "vim"]}))

    real_write_text = Path.write_text

    def fake_write_text(self, data, encoding=None):
        if str(self).endswith("install-packages.sh"):
            raise PermissionError("Permission denied")
        return real_write_text(self, data, encoding=encoding)

    monkeypatch.setattr(Path, "write_text", fake_write_text)

    with pytest.raises(PermissionError):
        software_builder_mod.build_software_configs(
            "phobos", hosts_path, tmp_path / "out"
        )


def test_build_user_configs_merges_and_writes(tmp_path: Path):
    cfg = tmp_path / "config" / "hosts"
    cfg_common = cfg / "common"
    cfg_host = cfg / "phobos"
    cfg_common.mkdir(parents=True)
    cfg_host.mkdir(parents=True)

    common_yaml = cfg_common / "users.yaml"
    host_yaml = cfg_host / "users.yaml"

    common_yaml.write_text(
        yaml.safe_dump(
            {
                "users": {"alice": {"uid": 1000, "primary_group": "users"}},
                "groups": {"users": {"gid": 100}},
                "sudoers": [
                    {"name": "admin", "rules": ["%admin ALL=(ALL) NOPASSWD:ALL"]}
                ],
            }
        )
    )

    host_yaml.write_text(
        yaml.safe_dump(
            {
                "users": {
                    "bob": {
                        "uid": 1001,
                        "primary_group": "users",
                        "additional_groups": ["docker"],
                    }
                }
            }
        )
    )

    out = tmp_path / "out"
    build_user_configs("phobos", cfg, out)

    users_yaml = out / "phobos" / "users" / "users.yaml"
    assert users_yaml.exists()
    data = yaml.safe_load(users_yaml.read_text())
    assert "alice" in data["users"]
    assert "bob" in data["users"]

    sudo = out / "phobos" / "users" / "sudoers.d-admin"
    assert sudo.exists()

    script = out / "phobos" / "users" / "setup-users.sh"
    assert script.exists()
    content = script.read_text()
    assert "useradd" in content
    assert "usermod -aG docker bob" in content


def test_build_user_configs_no_files_no_output(tmp_path: Path):
    cfg = tmp_path / "config" / "hosts"
    cfg.mkdir(parents=True)
    out = tmp_path / "out"
    build_user_configs("phobos", cfg, out)
    assert not out.exists()


def test_build_user_configs_malformed_yaml_raises(tmp_path):
    cfg = tmp_path / "config" / "hosts"
    (cfg / "common").mkdir(parents=True)
    (cfg / "common" / "users.yaml").write_text("{unbalanced: [}")

    import yaml as yaml_module

    with pytest.raises((yaml_module.YAMLError, Exception)):
        user_builder_mod.build_user_configs("phobos", cfg, tmp_path / "out")


def test_merge_duplicate_user_additional_groups(tmp_path):
    cfg = tmp_path / "config" / "hosts"
    (cfg / "common").mkdir(parents=True)
    (cfg / "phobos").mkdir(parents=True)

    common = {"users": {"alice": {"additional_groups": ["g1"], "uid": 1000}}}
    host = {"users": {"alice": {"additional_groups": ["g2"], "description": "host"}}}

    (cfg / "common" / "users.yaml").write_text(yaml.safe_dump(common))
    (cfg / "phobos" / "users.yaml").write_text(yaml.safe_dump(host))

    user_builder_mod.build_user_configs("phobos", cfg, tmp_path / "out")

    out_users = tmp_path / "out" / "phobos" / "users" / "users.yaml"
    assert out_users.exists()
    data = yaml.safe_load(out_users.read_text())
    assert "alice" in data.get("users", {})
    addl = data["users"]["alice"].get("additional_groups", [])
    assert set(addl) == {"g1", "g2"}


def test_sudoers_conflict_first_used(tmp_path):
    cfg = tmp_path / "config" / "hosts"
    (cfg / "common").mkdir(parents=True)
    (cfg / "phobos").mkdir(parents=True)

    common = {
        "sudoers": [{"name": "common", "rules": ["ALL=NOPASSWD: /bin/true"]}],
        "users": {"u": {}},
    }
    host = {
        "sudoers": [{"name": "host", "rules": ["ALL=NOPASSWD: /bin/false"]}],
        "users": {"u": {}},
    }

    (cfg / "common" / "users.yaml").write_text(yaml.safe_dump(common))
    (cfg / "phobos" / "users.yaml").write_text(yaml.safe_dump(host))

    user_builder_mod.build_user_configs("phobos", cfg, tmp_path / "out")

    sudo_file = tmp_path / "out" / "phobos" / "users" / "sudoers.d-common"
    assert sudo_file.exists()
    content = sudo_file.read_text()
    assert "/bin/true" in content
    assert "/bin/false" not in content


def test_defaults_for_missing_home_shell_in_setup_script(tmp_path):
    cfg = tmp_path / "config" / "hosts"
    (cfg / "common").mkdir(parents=True)
    (cfg / "phobos").mkdir(parents=True)

    data = {
        "users": {"bob": {"uid": 2000, "primary_group": "users"}},
        "groups": {"users": {"gid": 100}},
    }
    (cfg / "common" / "users.yaml").write_text(yaml.safe_dump(data))

    user_builder_mod.build_user_configs("phobos", cfg, tmp_path / "out")

    script = tmp_path / "out" / "phobos" / "users" / "setup-users.sh"
    assert script.exists()
    txt = script.read_text()
    assert "-d /home/bob" in txt
    assert "-s /bin/bash" in txt
    assert "mkdir -p /home/bob" in txt


def test_write_permission_error_on_setup_script(tmp_path, monkeypatch):
    cfg = tmp_path / "config" / "hosts"
    (cfg / "common").mkdir(parents=True)

    (cfg / "common" / "users.yaml").write_text(yaml.safe_dump({"users": {"u": {}}}))

    real_write = Path.write_text

    def fake_write(self, data, encoding=None):
        if str(self).endswith("setup-users.sh"):
            raise PermissionError("denied")
        return real_write(self, data, encoding=encoding)

    monkeypatch.setattr(Path, "write_text", fake_write)

    with pytest.raises(PermissionError):
        user_builder_mod.build_user_configs("phobos", cfg, tmp_path / "out")
