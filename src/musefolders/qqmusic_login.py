"""Nonblocking login jobs launched only by a user's login button."""
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import uuid
from .qqmusic_catalog import _bridge_paths, QQMusicConnectionError

@dataclass
class LoginJob:
    process: object
    result_path: Path


def start_login(root: Path) -> LoginJob:
    python, _ = _bridge_paths()
    helper = Path(__file__).resolve().parents[2] / "scripts" / "qqmusic_login.py"
    if not helper.is_file():
        raise QQMusicConnectionError("未找到 QQ 音乐登录程序。")
    result = root / ".local" / ("qq-login-" + uuid.uuid4().hex + ".json")
    try:
        result.parent.mkdir(parents=True, exist_ok=True)
        process = subprocess.Popen([str(python), str(helper), str(result)], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        raise QQMusicConnectionError("登录窗口未能启动，请检查 QQ 音乐连接程序。") from None
    return LoginJob(process, result)


def login_result(job: LoginJob) -> dict | None:
    if job.process.poll() is None:
        return None
    try:
        result = json.loads(job.result_path.read_text(encoding="utf-8"))
        if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
            raise ValueError("invalid result")
        if result["ok"]:
            status = result["status"]
            if not isinstance(status, dict) or not isinstance(status.get("account_hint"), str) or not isinstance(status.get("playlist_count"), int):
                raise ValueError("invalid status")
        return result
    except (OSError, ValueError, KeyError, TypeError):
        return {"ok": False, "message": "登录程序未能完成，请重试。"}
    finally:
        job.result_path.unlink(missing_ok=True)
