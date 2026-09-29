# 随项目提供的声音模型

`musicnn_embedding.onnx` 是 MusiCNN 声音画像模型的 ONNX 文件；曲境在本机调用它，将可读音频转换为约 200 维向量，供相似曲、路径和地图布局使用。它不是歌词模型，也不提供可信的单曲“确切流派”。

| 项目 | 信息 |
| --- | --- |
| 文件 | `models/musicnn_embedding.onnx`（3,129,290 字节） |
| 获取位置 | [AudioMuse-AI 的 `v5.0.0-model` 模型发布](https://github.com/NeptuneHub/AudioMuse-AI/releases/tag/v5.0.0-model)，资产名 `musicnn_embedding.onnx` |
| 上游项目 | [Music Technology Group / Jordi Pons 的 musicnn](https://github.com/jordipons/musicnn) |
| SHA-256 | `A48AD887950A557AEFBB4DCDDF58AD4802213FF5FC6FB51EDA3507CD797BB9B0` |
| 模型许可 | [AudioMuse 的第三方模型说明](https://github.com/NeptuneHub/AudioMuse-AI/blob/main/LICENSE#L2537-L2554)将 MusiCNN 模型列为 ISC；[musicnn 原项目许可证](https://github.com/jordipons/musicnn/blob/master/LICENSE.md)亦为 ISC。上游版权归 Music Technology Group, Universitat Pompeu Fabra（2019），代码由 Jordi Pons 开发。项目附带 [ISC 版权与许可通知](./MUSICNN_LICENSE.txt)，再次分发时须保留。 |

曲境的地图、缓存、交互和推荐程序在本项目独立实现；AudioMuse 应用源代码的 AGPL 条款与上述独立标明的模型资产许可应分别核对。本说明记录的是当前取得的模型资产和来源，不代表已完成未来云端发行或应用商店上架前的全部许可审核。

## 可选的本地语言识别模型

语言地图可读取用户自行放置的 `models/lid.176.ftz`。该文件不随项目提交或分发，来源是 [fastText 官方语言识别页面](https://fasttext.cc/docs/en/language-identification)，页面标明 176 种语言、压缩模型约 917 KB、模型许可为 CC BY-SA 3.0。2026-09-26 本地验证取得的文件为 938,013 字节，SHA-256 `8F3472CFE8738A7B6099E8E999C3CBFAE0DCD15696AAC7D7738A8039DB603E83`。本地运行库采用 `fasttext-community==0.11.8`；旧 `fasttext-wheel==0.9.2` 与本项目的 NumPy 2 在预测时不兼容，已从依赖表移除。若未来打包或分发语言模型，须先核对并履行其署名、相同方式共享等许可义务。
