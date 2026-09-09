from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_ansible_local_convergence_layout_exists() -> None:
    ansible_cfg = REPO_ROOT / "ansible" / "ansible.cfg"
    requirements = REPO_ROOT / "ansible" / "requirements.yml"
    playbook = REPO_ROOT / "ansible" / "playbooks" / "converge.yml"
    preflight = REPO_ROOT / "ansible" / "roles" / "preflight" / "tasks" / "main.yml"
    runtime_dirs = REPO_ROOT / "ansible" / "roles" / "runtime_dirs" / "tasks" / "main.yml"
    service_account = REPO_ROOT / "ansible" / "roles" / "service_account" / "tasks" / "main.yml"
    base_services = REPO_ROOT / "ansible" / "roles" / "base_services" / "tasks" / "main.yml"
    base_packages = REPO_ROOT / "ansible" / "roles" / "base_packages" / "tasks" / "main.yml"
    ops_tooling = REPO_ROOT / "ansible" / "roles" / "ops_tooling" / "tasks" / "main.yml"
    sudoers = REPO_ROOT / "ansible" / "roles" / "sudoers" / "tasks" / "main.yml"
    ssh_access = REPO_ROOT / "ansible" / "roles" / "ssh_access" / "tasks" / "main.yml"
    gitops_runner = REPO_ROOT / "ansible" / "roles" / "gitops_runner" / "tasks" / "main.yml"
    runner_env = REPO_ROOT / "ansible" / "roles" / "runner_env" / "tasks" / "main.yml"
    entrypoints = REPO_ROOT / "ansible" / "roles" / "entrypoints" / "tasks" / "main.yml"
    repo_layout = REPO_ROOT / "ansible" / "roles" / "repo_layout" / "tasks" / "main.yml"
    config_validation = REPO_ROOT / "ansible" / "roles" / "config_validation" / "tasks" / "main.yml"
    network_runtime = REPO_ROOT / "ansible" / "roles" / "network_runtime" / "tasks" / "main.yml"
    python_venv = REPO_ROOT / "ansible" / "roles" / "python_venv" / "tasks" / "main.yml"
    git_repo = REPO_ROOT / "ansible" / "roles" / "git_repo" / "tasks" / "main.yml"
    rootless_runtime = REPO_ROOT / "ansible" / "roles" / "rootless_runtime" / "tasks" / "main.yml"
    vault_agent = REPO_ROOT / "ansible" / "roles" / "vault_agent" / "tasks" / "main.yml"
    git_access = REPO_ROOT / "ansible" / "roles" / "git_access" / "tasks" / "main.yml"
    log_runtime = REPO_ROOT / "ansible" / "roles" / "log_runtime" / "tasks" / "main.yml"

    assert ansible_cfg.exists()
    assert requirements.exists()
    assert playbook.exists()
    assert preflight.exists()
    assert runtime_dirs.exists()
    assert service_account.exists()
    assert base_services.exists()
    assert base_packages.exists()
    assert ops_tooling.exists()
    assert sudoers.exists()
    assert ssh_access.exists()
    assert gitops_runner.exists()
    assert runner_env.exists()
    assert entrypoints.exists()
    assert repo_layout.exists()
    assert config_validation.exists()
    assert network_runtime.exists()
    assert python_venv.exists()
    assert git_repo.exists()
    assert rootless_runtime.exists()
    assert vault_agent.exists()
    assert git_access.exists()
    assert log_runtime.exists()

    cfg_text = ansible_cfg.read_text(encoding="utf-8")
    assert "inventory = localhost" in cfg_text
    assert "host_key_checking = False" in cfg_text

    playbook_text = playbook.read_text(encoding="utf-8")
    assert "hosts: localhost" in playbook_text
    assert "connection: local" in playbook_text
    assert "gather_facts: true" in playbook_text
    assert "runtime_dirs" in playbook_text
    assert "service_account" in playbook_text
    assert "base_services" in playbook_text
    assert "base_packages" in playbook_text
    assert "ops_tooling" in playbook_text
    assert "sudoers" in playbook_text
    assert "ssh_access" in playbook_text
    assert "gitops_runner" in playbook_text
    assert "runner_env" in playbook_text
    assert "entrypoints" in playbook_text
    assert "repo_layout" in playbook_text
    assert "config_validation" in playbook_text
    assert "network_runtime" in playbook_text
    assert "python_venv" in playbook_text
    assert "git_repo" in playbook_text
    assert "rootless_runtime" in playbook_text
    assert "vault_agent" in playbook_text
    assert "git_access" in playbook_text
    assert "log_runtime" in playbook_text

    preflight_text = preflight.read_text(encoding="utf-8")
    assert "preflight" in preflight_text.lower()
    assert "debian" in preflight_text.lower()
    assert "trixie" in preflight_text.lower()
    assert "network" in preflight_text.lower()

    runtime_text = runtime_dirs.read_text(encoding="utf-8")
    assert "/var/lib/abhaile" in runtime_text
    assert "state" in runtime_text.lower()
    assert "file" in runtime_text.lower()

    account_text = service_account.read_text(encoding="utf-8")
    assert "abhaile" in account_text
    assert "group" in account_text.lower()
    assert "user" in account_text.lower()

    base_services_text = base_services.read_text(encoding="utf-8")
    assert "systemd-networkd" in base_services_text
    assert "systemd-resolved" in base_services_text
    assert "enabled" in base_services_text.lower()

    base_packages_text = base_packages.read_text(encoding="utf-8")
    assert "ansible.builtin.package" in base_packages_text
    assert "python3" in base_packages_text
    assert "python3-venv" in base_packages_text
    assert "podman" in base_packages_text
    assert "curl" in base_packages_text

    ops_tooling_text = ops_tooling.read_text(encoding="utf-8")
    assert "sops" in ops_tooling_text.lower()
    assert "vault" in ops_tooling_text.lower()
    assert "checksum" in ops_tooling_text.lower() or "sha256" in ops_tooling_text.lower()
    assert (
        "ansible.builtin.get_url" in ops_tooling_text
        or "ansible.builtin.command" in ops_tooling_text
    )

    sudoers_text = sudoers.read_text(encoding="utf-8")
    assert "abhaile" in sudoers_text
    assert "NOPASSWD" in sudoers_text
    assert "/opt/abhaile/.venv/bin/abhaile-apply" in sudoers_text
    assert "NOPASSWD:ALL" not in sudoers_text
    assert "sudoers" in sudoers_text.lower()

    ssh_access_text = ssh_access.read_text(encoding="utf-8")
    assert "abhaile" in ssh_access_text
    assert "authorized_keys" in ssh_access_text.lower()
    assert ".ssh" in ssh_access_text
    assert "0700" in ssh_access_text or 'mode: "0700"' in ssh_access_text

    gitops_runner_text = gitops_runner.read_text(encoding="utf-8")
    assert "abhaile-runner" in gitops_runner_text
    assert "systemd" in gitops_runner_text.lower()
    assert "daemon-reload" in gitops_runner_text.lower() or "enabled" in gitops_runner_text.lower()
    assert "timer" in gitops_runner_text.lower()

    runner_env_text = runner_env.read_text(encoding="utf-8")
    assert "/etc/abhaile" in runner_env_text
    assert "ABHAILE_OUTPUT" in runner_env_text
    assert "ABHAILE_BRANCH" in runner_env_text
    assert "ABHAILE_REMOTE" in runner_env_text
    assert "runner.env" in runner_env_text

    entrypoints_text = entrypoints.read_text(encoding="utf-8")
    assert "abhaile-render" in entrypoints_text
    assert "abhaile-apply" in entrypoints_text
    assert "abhaile-health" in entrypoints_text
    assert "install-abhaile-entrypoints" in entrypoints_text

    repo_layout_text = repo_layout.read_text(encoding="utf-8")
    assert "/opt/abhaile" in repo_layout_text
    assert "abhaile" in repo_layout_text
    assert "0750" in repo_layout_text or '"0750"' in repo_layout_text
    assert "owner" in repo_layout_text.lower()
    assert "group" in repo_layout_text.lower()

    config_validation_text = config_validation.read_text(encoding="utf-8")
    assert "mapping.yaml" in config_validation_text
    assert "network.yaml" in config_validation_text
    assert ".sops.yaml" in config_validation_text
    assert "vault-agent.sops.yaml" in config_validation_text
    assert "secrets" in config_validation_text
    assert (
        "ABHAILE_HOST" in config_validation_text
        or "abhaile_expected_host" in config_validation_text
    )
    assert (
        "ansible.builtin.assert" in config_validation_text
        or "ansible.builtin.command" in config_validation_text
    )

    network_runtime_text = network_runtime.read_text(encoding="utf-8")
    assert "systemd-networkd" in network_runtime_text
    assert "systemd-resolved" in network_runtime_text
    assert (
        "daemon-reload" in network_runtime_text.lower() or "enabled" in network_runtime_text.lower()
    )
    assert "/etc/systemd" in network_runtime_text

    python_venv_text = python_venv.read_text(encoding="utf-8")
    assert "/opt/abhaile/.venv" in python_venv_text
    assert "python3 -m venv" in python_venv_text or "ansible.builtin.command" in python_venv_text
    assert "pip" in python_venv_text.lower()
    assert "requirements" in python_venv_text.lower()

    git_repo_text = git_repo.read_text(encoding="utf-8")
    assert "/opt/abhaile" in git_repo_text
    assert "git" in git_repo_text.lower()
    assert "checkout" in git_repo_text.lower() or "clone" in git_repo_text.lower()
    assert "origin" in git_repo_text.lower()

    rootless_runtime_text = rootless_runtime.read_text(encoding="utf-8")
    assert "loginctl" in rootless_runtime_text.lower()
    assert "linger" in rootless_runtime_text.lower()
    assert "podman" in rootless_runtime_text.lower()
    assert "XDG_RUNTIME_DIR" in rootless_runtime_text or "XDG_RUNTIME_DIR" in rootless_runtime_text

    vault_agent_text = vault_agent.read_text(encoding="utf-8")
    assert "/home/abhaile/.config/vault-agent" in vault_agent_text
    assert "vault-agent" in vault_agent_text.lower()
    assert "systemd" in vault_agent_text.lower() or "daemon-reload" in vault_agent_text.lower()
    assert "mkdir" in vault_agent_text.lower() or "file" in vault_agent_text.lower()

    git_access_text = git_access.read_text(encoding="utf-8")
    assert "/home/abhaile/.ssh" in git_access_text
    assert "gitops_ed25519" in git_access_text
    assert "known_hosts" in git_access_text
    assert "authorized_keys" in git_access_text.lower() or "deploy" in git_access_text.lower()
    assert "placeholder" not in git_access_text.lower()

    log_runtime_text = log_runtime.read_text(encoding="utf-8")
    assert "/var/log/abhaile" in log_runtime_text
    assert "log" in log_runtime_text.lower()
    assert "mode" in log_runtime_text.lower() or "0750" in log_runtime_text
