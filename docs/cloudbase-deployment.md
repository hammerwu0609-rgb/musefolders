# CloudBase 演示版

在线体验：[曲境](https://musefolders-demo-323000-10-1422230198.sh.run.tcloudbase.com/)。
2026-10-03 发布版本 002；默认 95 首测试曲库。仓库仅包含代码、界面素材和部署配置，不包含音频、歌词、个人收藏档案、密钥或登录凭据。

## 与本地版的关系

- 本地入口 `app.py`，使用 `run_local.ps1`；Windows 模型设置可在本机加密保存，QQ 登录使用本机连接程序。
- 云端入口 `cloud_app.py`；Dockerfile 将它作为容器内的 `app.py`。访客独立工作区在临时目录中。
- 两端共用黑绿单页工作台、音乐星球、听感空间、主题河流和右侧歌曲/歌单区。
- 云端管理曲库提供歌单链接导入、QQ 二维码登录、读取“我喜欢”与个人歌单、资料补全、会话模型配置及连接测试，无 JSON 粘贴导入流程。
- QQ 连接基于 `qqmusic-api-python==0.7.3`，属于非官方适配；二维码和未登录轮询已测试，完整扫码与收藏读取需账号持有人完成验证。
- 导入的歌曲资料不包含音频；只有匹配演示库音频的歌曲可站内试听及参与听感分析。其他歌曲保留资料检索，不虚构听感数据。

## 准备演示曲库

先在本地版导入并分析歌曲。项目的 `artifacts/collection_plan.json` 应能引用真实本地音频；随后运行：

```powershell
.\.venv\Scripts\python.exe scripts/prepare_demo_library.py --project . --output demo_library
```

脚本复制音频、可用歌词与已准备的资料，改写部署文件为相对路径。`demo_library/` 被 Git 忽略。请在构建目录中准备数据后再执行部署，直接克隆仓库不会包含演示音频。

## 构建与部署

容器使用 Python 3.12，监听 7860，健康检查 `/_stcore/health`。不需要数据库，也不会在运行时下载分析模型。

```powershell
tcb cloudrun deploy --env-id YOUR_ENV_ID --region ap-shanghai --service-name musefolders-demo --source . --port 7860 --min-num 0 --max-num 1 --open-access-types PUBLIC --force
```

更新已有服务时 CLI 可能仍询问灰度部署；选择构建成功后自动切换流量。不要因 CLI 显示“提交完成”就认定上线成功，须检查版本状态为 normal、流量为 100%，并确认首页和健康检查 HTTP 200。

## 模型和访客状态

服务端默认模型使用 `DEEPSEEK_API_KEY`，可选 `MUSEFOLDERS_API_URL` 与 `MUSEFOLDERS_MODEL`，通过服务控制台注入。无密钥时使用基础检索。

“管理曲库 → AI 设置”允许访客输入兼容 Chat Completions 的模型配置，在本次会话中应用。新地址必须同时输入新密钥，已有服务器密钥不会被转发至访客更改的地址。凭据不回显、不写入仓库或数据文件；关闭会话或服务重启后可能丢失。

QQ 登录凭据仅保存在该访客的服务器会话中。断开连接清除凭据，收藏导入与资料更新不会直接修改 QQ 音乐账号的歌单。网页歌单可导出，长期保存和账号体系尚未实现。

页面插画使用约 0.55MB 的 WebP，原 PNG 约 3.7MB。副本数 0–1，可空闲缩容，因此首次访问存在冷启动；线上音频下载也可能慢于本地。
