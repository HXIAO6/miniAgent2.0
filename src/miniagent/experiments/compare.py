"""比较同条件的多版本实验；原始文本仅保留本地，远程出口只允许统计白名单。"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]

VARIANTS = {"original_rag_reconstructed", "framework_only", "permissions_only", "full",
            "without_permissions", "without_injection", "without_output"}
METRICS = {"planned", "valid", "errors", "injection_valid", "exact_attack_successes", "exact_attack_success_rate",
           "injection_marker_occurrences", "benign_valid", "benign_false_refusals", "benign_false_refusal_rate",
           "benign_keyword_answers", "benign_retrieval_hits", "unauthorized_retrievals", "synthetic_leaks",
           "leakage_valid", "poison_claims", "model_calls", "elapsed_ms"}
METRICS |= {"injection_context_exposures", "usage_complete_rows", "total_estimated_cost"}


def safe_summary(report):
    """数据集原文、原回答、任意标签不能随报告导出；有限非负统计值才进入云端。"""
    import math
    return {variant: {key: value for key, value in values.items() if key in METRICS
                      and type(value) in {int, float} and math.isfinite(value) and value >= 0}
            for variant, values in report["summary"].items() if variant in VARIANTS}


def compare(before, after, before_manifest, after_manifest):
    """比较前验证数据、配置、模型、后端、embedding 和重排条件，拒绝模拟与真实混比。"""
    for key in ("dataset_sha256", "config_sha256", "backend", "model", "embedding", "reranker"):
        if before_manifest[key] != after_manifest[key]:
            raise ValueError("实验条件不同，拒绝直接比较：" + key)
    left, right = safe_summary(before), safe_summary(after)
    if set(left) != set(right):
        raise ValueError("实验版本集合不同。")
    return {variant: {key: dict(before=left[variant][key], after=right[variant][key],
                                delta=right[variant][key] - left[variant][key])
                       for key in METRICS & left[variant].keys() & right[variant].keys()}
            for variant in sorted(left)}


def export(report, config=None, client_factory=None):
    """复用显式 LangSmith 开关；不自动上传数据集、原始结果或本机运行环境。"""
    from miniagent.config import settings
    from datetime import datetime, timezone
    import uuid
    config = config or settings
    # 关闭时不会构建客户端；每个固定版本导出一个统计根运行。
    if not config.langsmith_export_enabled:
        raise ValueError("LangSmith 导出未开启。")
    from urllib.parse import urlsplit
    endpoint = urlsplit(config.langsmith_endpoint)
    if endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.password or not config.langsmith_api_key:
        raise ValueError("LangSmith 配置无效。")
    if client_factory is None:
        from langsmith import Client
        client_factory = Client
    if report.get("backend") not in {"live", "simulated"}:
        raise ValueError("实验后端标识无效。")
    client = client_factory(api_url=config.langsmith_endpoint, api_key=config.langsmith_api_key,
                            auto_batch_tracing=False, omit_traced_runtime_info=True, timeout_ms=3000)
    try:
        for variant, values in safe_summary(report).items():
            now = datetime.now(timezone.utc)
            client.create_run(id=str(uuid.uuid4()), name="miniagent-security-" + variant, run_type="chain",
                              project_name="miniagent-experiments-sanitized",
                              inputs={"variant": variant, "backend": report["backend"]}, outputs=values,
                              start_time=now, end_time=now)
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    difference = commands.add_parser("compare")
    difference.add_argument("before", type=Path)
    difference.add_argument("after", type=Path)
    difference.add_argument("--output", type=Path, required=True)
    upload = commands.add_parser("export")
    upload.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    if args.command == "export":
        try:
            export(json.loads((args.run_dir / "report.json").read_text(encoding="utf-8")))
        except Exception:
            parser.exit(1, "导出失败：请核对显式导出开关、摘要、账号及网络，未输出 SDK 异常正文。\n")
        print("统计摘要已提交至 miniagent-experiments-sanitized。")
        return
    try:
        result = compare(*(json.loads((directory / name).read_text(encoding="utf-8")) for name in
                           ("report.json", "manifest.json") for directory in (args.before, args.after)))
    except ValueError as error:
        parser.exit(1, str(error) + "\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    print(args.output)


if __name__ == "__main__":
    main()
