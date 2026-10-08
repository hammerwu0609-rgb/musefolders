import hashlib
import json

import pytest

from musefolders.library_import import MusicImportError, _verify_manifest


def manifest_bundle(root):
    audio = root / "audio" / "song.mp3"
    audio.parent.mkdir()
    audio.write_bytes(b"audio checked by the manifest")
    data = {"format": "musefolders-music-v1", "files": [
        {"path": "audio/song.mp3", "size": audio.stat().st_size,
         "sha256": hashlib.sha256(audio.read_bytes()).hexdigest()},
    ]}
    (root / "music_package.json").write_text(json.dumps(data), encoding="utf-8")
    (root / "experience.zip").write_bytes(b"the server transport copy")
    return audio


def test_server_archive_is_not_a_member_of_its_own_manifest(tmp_path):
    manifest_bundle(tmp_path)
    _verify_manifest(tmp_path, lambda *args: None, server_package=True)
    # Uploaded packages keep strict inventory validation.
    with pytest.raises(MusicImportError, match="清单不一致"):
        _verify_manifest(tmp_path, lambda *args: None)


def test_server_manifest_still_rejects_unexpected_files(tmp_path):
    manifest_bundle(tmp_path)
    (tmp_path / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(MusicImportError, match="清单不一致"):
        _verify_manifest(tmp_path, lambda *args: None, server_package=True)


def test_server_manifest_still_verifies_audio_bytes(tmp_path):
    audio = manifest_bundle(tmp_path)
    audio.write_bytes(b"changed recording")
    with pytest.raises(MusicImportError, match="文件不完整"):
        _verify_manifest(tmp_path, lambda *args: None, server_package=True)
