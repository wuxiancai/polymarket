import os
import shutil
import stat
import subprocess
from pathlib import Path


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_start_script_reuses_existing_systemd_database_path(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    shutil.copy(Path("start.sh"), root / "start.sh")
    python_bin = root / ".venv" / "bin" / "python"
    python_bin.parent.mkdir(parents=True)
    _write_executable(python_bin, "#!/usr/bin/env bash\nexit 0\n")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    service_output = tmp_path / "generated.service"
    old_db = tmp_path / "old-data" / "paper.sqlite3"
    old_db.parent.mkdir()
    old_db.write_text("")

    _write_executable(
        fake_bin / "systemctl",
        f"""#!/usr/bin/env bash
if [[ "$1" == "show" ]]; then
  echo 'Environment=POLYARB_DB={old_db} REFRESH_SECONDS=30'
  exit 0
fi
exit 0
""",
    )
    _write_executable(
        fake_bin / "sudo",
        f"""#!/usr/bin/env bash
if [[ "$1" == "tee" ]]; then
  cat > "{service_output}"
  exit 0
fi
exit 0
""",
    )
    _write_executable(fake_bin / "hostname", "#!/usr/bin/env bash\necho '127.0.1.1'\n")

    env = os.environ.copy()
    env.pop("POLYARB_DB", None)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    subprocess.run(["bash", "start.sh"], cwd=root, env=env, check=True, text=True, capture_output=True)

    service = service_output.read_text()
    assert f"Environment=POLYARB_DB={old_db}" in service
    assert f"Environment=POLYARB_DB={root / 'data' / 'paper.sqlite3'}" not in service
    assert "Environment=FEE_BUFFER=0" in service
    assert "Environment=SLIPPAGE_BUFFER_CENTS=3" in service


def test_start_script_passes_fee_buffer_to_systemd(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    shutil.copy(Path("start.sh"), root / "start.sh")
    python_bin = root / ".venv" / "bin" / "python"
    python_bin.parent.mkdir(parents=True)
    _write_executable(python_bin, "#!/usr/bin/env bash\nexit 0\n")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    service_output = tmp_path / "generated.service"
    _write_executable(fake_bin / "systemctl", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(
        fake_bin / "sudo",
        f"#!/usr/bin/env bash\nif [[ \"$1\" == \"tee\" ]]; then cat > \"{service_output}\"; fi\n",
    )
    _write_executable(fake_bin / "hostname", "#!/usr/bin/env bash\necho '127.0.1.1'\n")
    env = os.environ.copy()
    env["FEE_BUFFER"] = "0.0125"
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    subprocess.run(["bash", "start.sh"], cwd=root, env=env, check=True, text=True, capture_output=True)

    assert "Environment=FEE_BUFFER=0.0125" in service_output.read_text()


def test_start_script_allows_explicit_database_override(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    shutil.copy(Path("start.sh"), root / "start.sh")
    python_bin = root / ".venv" / "bin" / "python"
    python_bin.parent.mkdir(parents=True)
    _write_executable(python_bin, "#!/usr/bin/env bash\nexit 0\n")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    service_output = tmp_path / "generated.service"
    old_db = tmp_path / "old-data" / "paper.sqlite3"
    explicit_db = tmp_path / "new-data" / "paper.sqlite3"
    old_db.parent.mkdir()
    explicit_db.parent.mkdir()
    old_db.write_text("")
    explicit_db.write_text("")

    _write_executable(
        fake_bin / "systemctl",
        f"""#!/usr/bin/env bash
if [[ "$1" == "show" ]]; then
  echo 'Environment=POLYARB_DB={old_db} REFRESH_SECONDS=30'
  exit 0
fi
exit 0
""",
    )
    _write_executable(
        fake_bin / "sudo",
        f"""#!/usr/bin/env bash
if [[ "$1" == "tee" ]]; then
  cat > "{service_output}"
  exit 0
fi
exit 0
""",
    )
    _write_executable(fake_bin / "hostname", "#!/usr/bin/env bash\necho '127.0.1.1'\n")

    env = os.environ.copy()
    env["POLYARB_DB"] = str(explicit_db)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    subprocess.run(["bash", "start.sh"], cwd=root, env=env, check=True, text=True, capture_output=True)

    service = service_output.read_text()
    assert f"Environment=POLYARB_DB={explicit_db}" in service
    assert f"Environment=POLYARB_DB={old_db}" not in service
