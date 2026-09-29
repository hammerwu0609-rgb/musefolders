from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adapters import LocalFolderAdapter
from .reporting import write_validation_reports
from .service import analyze_library, load_plan
from .validation import run_validation


def _progress(done: int, total: int, name: str) -> None:
    print(f"[{done:>3}/{total}] {name}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(prog="musefolders", description="曲境：把音乐曲库编译成合乎心意的文件夹")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="只读分析并生成文件夹预览")
    analyze.add_argument("--source", type=Path, required=True)
    analyze.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    analyze.add_argument("--naming-mode", choices=["poetic", "quant"], default="poetic")
    analyze.add_argument("--scheme", choices=["agitation_brightness", "tempo_loudness", "tonality_agitation"], default="agitation_brightness")
    analyze.add_argument("--language", choices=["zh", "en"], default="zh")
    analyze.add_argument("--no-cache", action="store_true")

    apply_cmd = sub.add_parser("apply", help="根据已确认方案复制文件")
    apply_cmd.add_argument("--plan", type=Path, required=True)
    apply_cmd.add_argument("--output", type=Path, required=True)

    validate_cmd = sub.add_parser("validate", help="验证方案完整性、扩展边界与可撤销导出")
    validate_cmd.add_argument("--plan", type=Path, required=True)
    validate_cmd.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    validate_cmd.add_argument("--exercise-export", action="store_true")

    args = parser.parse_args()
    if args.command == "analyze":
        plan, evidence = analyze_library(
            args.source, args.artifacts, args.naming_mode, progress=_progress, use_cache=not args.no_cache,
            scheme_id=args.scheme, language=args.language,
        )
        reports = write_validation_reports(plan, evidence, args.artifacts)
        print(f"\n完成：{len(plan.tracks)} 首 → {len(plan.folders)} 个文件夹")
        for folder in plan.folders:
            print(f"- {folder.name}: {len(folder.track_ids)} 首，一致度 {folder.cohesion:.0f}/100")
        print("验证报告：")
        for report in reports:
            print(f"- {report}")
    elif args.command == "apply":
        plan = load_plan(args.plan)
        result = LocalFolderAdapter(args.output).apply(plan)
        print(f"已复制 {result['copied']} 首；清单：{result['manifest']}")
    elif args.command == "validate":
        plan = load_plan(args.plan)
        evidence = run_validation(plan, args.artifacts, exercise_export=args.exercise_export)
        print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

