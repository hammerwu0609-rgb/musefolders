import json
from types import SimpleNamespace
import pytest
from musefolders import qqmusic_login as login
from musefolders.qqmusic_catalog import QQMusicConnectionError


def test_start_login_uses_installed_runtime_without_credentials(tmp_path, monkeypatch):
    captured = []
    python = tmp_path / "python.exe"
    monkeypatch.setattr(login, "_bridge_paths", lambda: (python, tmp_path / "bridge.py"))
    monkeypatch.setattr(login.subprocess, "Popen", lambda args, **kwargs: captured.append((args, kwargs)) or SimpleNamespace(poll=lambda: None))
    job = login.start_login(tmp_path)
    assert job.result_path.parent == tmp_path / ".local"
    args, options = captured[0]
    assert args[0] == str(python) and args[1].endswith("qqmusic_login.py")
    assert args[2] == str(job.result_path)
    assert options["stdout"] == login.subprocess.DEVNULL
    assert login.login_result(job) is None


def test_completed_login_cleans_status_file_and_preserves_safe_result(tmp_path):
    path = tmp_path / "result.json"
    job = login.LoginJob(SimpleNamespace(poll=lambda: 0), path)
    path.write_text(json.dumps({"ok": True, "status": {"account_hint": "***1234", "playlist_count": 4}}), encoding="utf-8")
    assert login.login_result(job)["status"]["account_hint"] == "***1234"
    assert not path.exists()
    path.write_text('{"ok":true,"status":{}}',encoding="utf-8")
    assert login.login_result(job)["ok"] is False
    assert not path.exists()
    path.write_text('{"ok":false,"message":"取消登录"}',encoding="utf-8")
    assert login.login_result(job)["message"] == "取消登录"


def test_login_spawn_failure_is_user_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(login, "_bridge_paths", lambda: (tmp_path / "missing.exe", tmp_path / "bridge.py"))
    def fail(*args, **kwargs): raise OSError("internal-path-or-cookie")
    monkeypatch.setattr(login.subprocess, "Popen", fail)
    with pytest.raises(QQMusicConnectionError, match="未能启动") as caught:
        login.start_login(tmp_path)
    assert "internal-path-or-cookie" not in str(caught.value)
