from __future__ import annotations

from pathlib import Path
from copy import deepcopy

from .models import CollectionPlan
from .schemes import compile_scheme
from .taxonomy import key_tag_value


def write_validation_reports(plan: CollectionPlan, evidence: dict, artifacts: Path) -> list[Path]:
    """Record measured outcomes, product behavior, and unresolved integration work."""
    artifacts.mkdir(parents=True, exist_ok=True)
    schemes = {}
    for scheme in ("agitation_brightness", "tempo_loudness", "tonality_agitation"):
        folders, _ = compile_scheme(deepcopy(plan.tracks), scheme, language="zh")
        schemes[scheme] = (len(folders), sum(len(folder.track_ids) for folder in folders))
    genre_count = sum(track.genre_status == "verified" for track in plan.tracks)
    beat_uncertain = sum(track.tags.get("tempo") == "unsteady" for track in plan.tracks)
    key_uncertain = sum(key_tag_value(track.acoustic) == "uncertain" for track in plan.tracks)
    technical = f"""# 第一轮：技术可行性验证

状态：PASS（本地可解码音频和只读分析）；专业流派与云端写入未验证。

- 可分析文件：{evidence['discovered']}；成功：{evidence['analyzed']}；失败：{evidence['failed']}；受保护/不支持：{evidence['unsupported']}。
- 缓存命中：{evidence['cache_hits']}；本轮耗时：{evidence['elapsed_s']} 秒；源音乐哈希变化：{evidence['source_mutations']}。
- 每首歌均记录 BPM（节奏）、采样 RMS dBFS（响度代理）、调/式及区分度（调性估计）。
- 三套规则对 {len(plan.tracks)} 首歌的覆盖：躁动度×音色 {schemes['agitation_brightness'][0]} 组 / {schemes['agitation_brightness'][1]} 首；节奏×响度 {schemes['tempo_loudness'][0]} 组 / {schemes['tempo_loudness'][1]} 首；调式×躁动度 {schemes['tonality_agitation'][0]} 组 / {schemes['tonality_agitation'][1]} 首。
- 节拍证据不足：{beat_uncertain} 首（归“节拍待定”）；调性证据不足：{key_uncertain} 首（调性与调式标签归“待确定”）。
- 已核实的专业流派：{genre_count} 首。样本批量 Genre=Blues 不作为可信结论。

边界：BPM 可能存在半拍/倍拍误差；RMS 不是 LUFS；片段调性估计不是人工乐理鉴定。
"""
    product = f"""# 第二轮：产品交互与体验验证

状态：工程流程 PASS；“文件夹是否合乎心意”的真人验收仍待完成。

当前流程：只读扫描和打标 → 预览多套分类方案 → 用户勾选 1–2 个标签或选预设 → 确认方案 → 试听/改名/单曲纠正 → 预览复制 → 再次确认生成 → 可撤销副本。

本轮方案 `{plan.scheme_id}` 生成 {len(plan.folders)} 个文件夹，覆盖 {sum(len(f.track_ids) for f in plan.folders)} 首歌。中文/英文界面共用同一组语言无关标签编码。

设计依据：One Tagger 把自动标签与人工 Quick Tag 决策分开；beets 的 smartplaylist 使用可复用查询规则生成歌单。本产品采用可解释的有限标签组合，避免组合爆炸和无证据的专业流派命名。

真人验收建议：让目标用户尝试找一个最想打开的文件夹、改一个名字、纠正一首歌，记录完成时间与满意度；算法相近度不能替代用户喜欢程度。
"""
    iteration = """# 第三轮：迭代可能性验证

状态：本地扩展边界 PASS；QQ 音乐真实联调 PENDING。

- TrackEncoding 保存音频测量、原始元数据、分离的流派状态及可组合标签。
- CollectionPlan 保存 scheme_id、tag_keys、language、文件夹与曲目映射；切换方案不必重解码音频。
- CollectionOutputAdapter 把蓝图投影到本地副本；QQMusicAdapter 目前只预演，不调用非官方接口。
- 正式流派来源可后接 MusicBrainz/授权目录；需先做录音身份匹配与来源留痕。搜索同名歌曲不能自动视为确证。
- 官方 API 到位后须验证鉴权、曲目 ID 映射、幂等创建、失败恢复与限流；目前没有实现真实云端写入。

通俗解释：适配器就是“翻译层”，让同一套分类蓝图能转换成本地文件夹或未来的云歌单操作；幂等指重试不会重复创建歌单或曲目。
"""
    paths = []
    for filename, content in (
        ("01_技术可行性验证.md", technical),
        ("02_产品交互体验验证.md", product),
        ("03_迭代可能性验证.md", iteration),
    ):
        path = artifacts / filename
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    return paths
