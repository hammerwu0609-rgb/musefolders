"""Local, per-Windows-user encrypted model settings. Never log credentials."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import uuid
from urllib import request, error
from urllib.parse import urlsplit, urlunsplit

from .theme_assistant import DEEPSEEK_URL, DEEPSEEK_MODEL


class ModelSettingsError(RuntimeError):
    """User-safe configuration error."""


@dataclass(frozen=True)
class ModelSettings:
    api_url: str = DEEPSEEK_URL
    model: str = DEEPSEEK_MODEL
    api_key: str = field(default="", repr=False)


def validate(settings: ModelSettings) -> ModelSettings:
    url = settings.api_url.strip().rstrip("/")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise ModelSettingsError("API 地址格式不正确。") from None
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or any(c.isspace() for c in url)):
        raise ModelSettingsError("请填写 API 基础地址或完整的 chat/completions 地址。")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise ModelSettingsError("远程 API 请使用 HTTPS；本机服务可使用 HTTP。")
    path = parsed.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path += "/chat/completions"
    url = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    model, key = settings.model.strip(), settings.api_key.strip()
    if not model or len(model) > 128 or any(c.isspace() for c in model):
        raise ModelSettingsError("请填写有效的模型名称，例如 deepseek-flash。")
    if len(key) > 4096 or any(c.isspace() for c in key):
        raise ModelSettingsError("API 密钥格式不正确，请检查是否含空格或换行。")
    return ModelSettings(url, model, key)


def defaults() -> ModelSettings:
    return validate(ModelSettings(os.getenv("MUSEFOLDERS_API_URL", DEEPSEEK_URL),
                                  os.getenv("MUSEFOLDERS_MODEL", DEEPSEEK_MODEL),
                                  os.getenv("DEEPSEEK_API_KEY", "")))


def config_path(root: Path) -> Path:
    return root / ".local" / "model_settings.dpapi"


def _crypt(data: bytes, *, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise ModelSettingsError("本机加密保存需要 Windows；可以选择仅本次会话使用。")
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    protect = crypt32.CryptProtectData
    protect.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    protect.restype = wintypes.BOOL
    unprotect = crypt32.CryptUnprotectData
    unprotect.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    unprotect.restype = wintypes.BOOL
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    success = unprotect(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)) if decrypt else protect(ctypes.byref(source), "MuseFolders model settings", None, None, None, 1, ctypes.byref(output))
    if not success:
        raise ModelSettingsError("Windows 加密配置无法读取或保存，请在同一个 Windows 账号下运行，或仅本次会话使用。")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel32.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


def save_settings(root: Path, settings: ModelSettings) -> None:
    settings = validate(settings)
    if not settings.api_key:
        raise ModelSettingsError("请先填写 API 密钥。")
    encrypted = _crypt(json.dumps({"version": 1, "api_url": settings.api_url, "model": settings.model,
                                  "api_key": settings.api_key}).encode("utf-8"))
    path = config_path(root)
    pending = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        pending.write_bytes(encrypted)
        pending.replace(path)
    except OSError:
        raise ModelSettingsError("本机配置未能保存，请检查项目目录的写入权限。") from None
    finally:
        pending.unlink(missing_ok=True)


def load_settings(root: Path) -> ModelSettings | None:
    path = config_path(root)
    if not path.exists():
        return None
    try:
        if path.stat().st_size > 32768:
            raise ValueError("size")
        data = json.loads(_crypt(path.read_bytes(), decrypt=True))
        if data["version"] != 1:
            raise ValueError("version")
        settings = validate(ModelSettings(data["api_url"], data["model"], data["api_key"]))
        if not settings.api_key:
            raise ValueError("key")
        return settings
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise ModelSettingsError("保存的模型配置无法读取，请重新配置或删除后重试。") from None


def delete_settings(root: Path) -> None:
    try:
        config_path(root).unlink(missing_ok=True)
    except OSError:
        raise ModelSettingsError("本机配置未能删除，请检查文件权限。") from None


def active_settings(root: Path) -> ModelSettings:
    import streamlit as st
    if "simple_model_settings" not in st.session_state:
        try:
            saved = load_settings(root)
            st.session_state.simple_model_settings = saved or defaults()
            st.session_state.simple_model_origin = "本机加密配置" if saved else "环境变量" if st.session_state.simple_model_settings.api_key else "尚未配置"
        except ModelSettingsError as exc:
            st.session_state.simple_model_settings = ModelSettings()
            st.session_state.simple_model_error = str(exc)
            st.session_state.simple_model_origin = "尚未配置"
    return st.session_state.simple_model_settings


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def secure_urlopen(req, **kwargs):
    # Do not forward a bearer credential to a redirected host.
    return request.build_opener(_NoRedirect()).open(req, **kwargs)


def model_options(api_url: str) -> dict:
    return {"thinking": {"type": "disabled"}} if urlsplit(api_url).hostname == "api.deepseek.com" else {}


def test_connection(settings: ModelSettings, *, opener=secure_urlopen) -> None:
    settings = validate(settings)
    if not settings.api_key:
        raise ModelSettingsError("请先填写 API 密钥。")
    body = {"model": settings.model, "temperature": 0, "max_tokens": 64,
            "response_format": {"type": "json_object"}, **model_options(settings.api_url),
            "messages": [{"role": "user", "content": 'Return only JSON: {"ok":true}'}]}
    req = request.Request(settings.api_url, data=json.dumps(body).encode(), method="POST",
                          headers={"Authorization": "Bearer " + settings.api_key, "Content-Type": "application/json"})
    try:
        with opener(req, timeout=25) as response:
            result = json.loads(response.read(65536))
        choice = result["choices"][0]
        if choice.get("finish_reason") == "length" or json.loads(choice["message"]["content"]).get("ok") is not True:
            raise ValueError("invalid completion")
    except error.HTTPError as exc:
        reason = {401: "密钥无效", 403: "账号或模型访问受限", 404: "API 地址或模型名称不正确", 402: "账户余额不足", 429: "请求过于频繁或额度不足"}.get(exc.code, "服务暂时不可用")
        raise ModelSettingsError(f"连接失败：HTTP {exc.code}，{reason}。") from None
    except (error.URLError, TimeoutError, OSError):
        raise ModelSettingsError("连接超时或网络不可用，请检查 API 地址和网络。") from None
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise ModelSettingsError("服务已响应，但模型未返回有效 JSON；请使用支持 JSON 输出的聊天模型。") from None
