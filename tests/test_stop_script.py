import os
import shutil
import stat
import subprocess
from pathlib import Path


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run_stop_script(root: Path, fake_bin: Path, env_extra: dict[str, str] | None = None):
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["POLYARB_STOP_GRACE_SECONDS"] = "0"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", "stop.sh"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
    )


def test_stop_script_stops_systemd_service_and_local_processes(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    shutil.copy(Path("stop.sh"), root / "stop.sh")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls_log = tmp_path / "calls.log"
    pids_file = tmp_path / "pids.txt"
    pids_file.write_text("123\n456\n")

    _write_executable(
        fake_bin / "systemctl",
        """#!/usr/bin/env bash
printf 'polyarb.service enabled enabled\\n'
""",
    )
    _write_executable(
        fake_bin / "sudo",
        f"""#!/usr/bin/env bash
echo "sudo $*" >> "{calls_log}"
""",
    )
    _write_executable(
        fake_bin / "pgrep",
        f"""#!/usr/bin/env bash
cat "{pids_file}" 2>/dev/null || true
""",
    )
    _write_executable(
        fake_bin / "pkill",
        f"""#!/usr/bin/env bash
printf 'pkill %s\\n' "$*" >> "{calls_log}"
""",
    )

    result = _run_stop_script(root, fake_bin)

    assert result.returncode == 0, result.stderr
    assert "sudo systemctl stop polyarb" in calls_log.read_text()
    assert "pkill -TERM -f [p]ython .* -m polyarb" in calls_log.read_text()
    assert "pkill -KILL -f [p]ython .* -m polyarb" in calls_log.read_text()


def test_stop_script_skips_systemd_when_unit_not_installed(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    shutil.copy(Path("stop.sh"), root / "stop.sh")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls_log = tmp_path / "calls.log"
    empty_pids = tmp_path / "empty-pids.txt"
    empty_pids.write_text("")

    _write_executable(
        fake_bin / "systemctl",
        """#!/usr/bin/env bash
exit 0
""",
    )
    _write_executable(
        fake_bin / "sudo",
        f"""#!/usr/bin/env bash
echo "sudo $*" >> "{calls_log}"
""",
    )
    _write_executable(
        fake_bin / "pgrep",
        f"""#!/usr/bin/env bash
cat "{empty_pids}" 2>/dev/null || true
""",
    )
    _write_executable(
        fake_bin / "pkill",
        """#!/usr/bin/env bash
exit 1
""",
    )

    result = _run_stop_script(root, fake_bin)

    assert result.returncode == 0, result.stderr
    assert not calls_log.exists()
    assert "未发现 systemd 服务" in result.stdout
    assert "未发现本机 polyarb 进程" in result.stdout


def test_stop_script_reports_systemd_stop_failure(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    shutil.copy(Path("stop.sh"), root / "stop.sh")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls_log = tmp_path / "calls.log"
    empty_pids = tmp_path / "empty-pids.txt"
    empty_pids.write_text("")

    _write_executable(
        fake_bin / "systemctl",
        """#!/usr/bin/env bash
printf 'polyarb.service enabled enabled\\n'
""",
    )
    _write_executable(
        fake_bin / "sudo",
        f"""#!/usr/bin/env bash
echo "sudo $*" >> "{calls_log}"
exit 1
""",
    )
    _write_executable(
        fake_bin / "pgrep",
        f"""#!/usr/bin/env bash
cat "{empty_pids}" 2>/dev/null || true
""",
    )
    _write_executable(
        fake_bin / "pkill",
        """#!/usr/bin/env bash
exit 1
""",
    )

    result = _run_stop_script(root, fake_bin)

    assert result.returncode == 1
    assert "停止 systemd 服务失败" in result.stderr
    assert "sudo systemctl stop polyarb" in calls_log.read_text()
