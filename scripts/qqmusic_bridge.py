"""Read-only worker run with the installed QQ Music MCP's Python runtime."""
from __future__ import annotations

import asyncio
import html
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from musefolders.qqmusic_catalog import choose_candidate, normalize_detail, version_tags
from qqmusic_organizer.qqmusic import AuthenticationError, QQMusicClient, QQMusicError
from qqmusic_organizer.session_cache import load_cookie
from qqmusic_organizer.storage import default_data_dir


def emit(event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


async def main(payload):
    try:
        cookie = load_cookie(default_data_dir() / "session.dpapi")
    except (OSError, ValueError, RuntimeError):
        emit({"event": "fatal", "message": "无法读取本机 QQ 音乐登录态，请从正常启动窗口运行曲境或重新登录。"})
        return
    if not cookie:
        emit({"event": "fatal", "message": "请先在 QQ 音乐 MCP 中登录账号。"})
        return
    async with QQMusicClient(cookie) as client:
        playlists = await client.list_created_playlists()
        if payload.get("operation") == "status":
            emit({"event": "status", "result": {"authenticated": True,
                  "account_hint": "***" + str(client.uin)[-4:], "playlist_count": len(playlists)}})
            return
        semaphore = asyncio.Semaphore(5)

        async def enrich(query):
            async with semaphore:
                try:
                    words = f"{query['title']} {query['artist']}"[:100]
                    found = await client.search_songs(words, page_size=10)
                    song, status = choose_candidate(query, found.get("songs", []))
                    if song is None:
                        found = await client.search_songs(query["title"][:100], page_size=20)
                        song, status = choose_candidate(query, found.get("songs", []))
                    if song is None:
                        result = {"status": status}
                    else:
                        detail = await client.get_song_detail(song["mid"])
                        result = {**normalize_detail(song, detail), "status": "matched", "match_score": song["match_score"]}
                        if version_tags(query["title"]) != tuple(result["version_tags"]):
                            result = {"status": "not_matched"}
                        else:
                            try:
                                lyrics = html.unescape((await client.get_lyrics(song["mid"])).get("lyric", ""))
                                result.update(lyrics=lyrics, has_lyrics=bool(lyrics.strip()))
                            except AuthenticationError:
                                raise
                            except QQMusicError:
                                result.update(has_lyrics=False, lyrics_error=True)
                except AuthenticationError:
                    raise
                except (QQMusicError, TypeError, ValueError, KeyError):
                    result = {"status": "error"}
                emit({"event": "song", "track_id": query["track_id"], "result": result})

        await asyncio.gather(*(enrich(query) for query in payload.get("tracks", [])))
        emit({"event": "done"})


if __name__ == "__main__":
    try:
        payload = json.load(sys.stdin)
        asyncio.run(main(payload))
    except AuthenticationError:
        emit({"event": "fatal", "message": "QQ 音乐登录已失效，请重新登录。"})
    except QQMusicError:
        emit({"event": "fatal", "message": "QQ 音乐接口暂时无法访问，请稍后重试。"})
    except Exception:
        emit({"event": "fatal", "message": "QQ 音乐连接程序未能完成，请检查安装环境。"})
