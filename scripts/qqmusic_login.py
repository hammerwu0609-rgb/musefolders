"""User-initiated official-browser login; never output or copy cookies to the UI."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
import sys
from qqmusic_organizer.browser_auth import capture_qqmusic_cookie
from qqmusic_organizer.qqmusic import QQMusicClient
from qqmusic_organizer.session_cache import save_cookie
from qqmusic_organizer.storage import default_data_dir

async def verify(cookie):
    async with QQMusicClient(cookie) as client:
        playlists = await client.list_created_playlists()
        return {"authenticated": True, "account_hint": "***" + str(client.uin)[-4:], "playlist_count": len(playlists)}

def run():
    target = Path(sys.argv[1])
    try:
        cookie = capture_qqmusic_cookie(timeout_seconds=180)
        status = asyncio.run(verify(cookie))
        # Replace only after successful verification, preserving the old account on cancel.
        save_cookie(default_data_dir() / "session.dpapi", cookie)
        result = {"ok": True, "status": status}
    except TimeoutError:
        result = {"ok": False, "message": "登录等待已超时，请点击登录后重试。"}
    except Exception:
        result = {"ok": False, "message": "登录未完成，浏览器可能已关闭或接口暂时不可用。原登录配置保留，请重试。"}
    pending = target.with_suffix(".pending")
    pending.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    pending.replace(target)

if __name__ == "__main__":
    run()
