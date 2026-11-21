"""安全规则对照实验：公开漏检，指标仅表示合成文本是否进入上下文，不等于模型攻击成功率。"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
from miniagent.security.policy import SecurityPolicy, inspect_text
from miniagent.security.output import output_findings


def evaluate(output_dir):
    """不访问正式库、不调用模型、不实际执行攻击；仅比较确定性安全边界。"""
    dataset_path = ROOT / "evaluations/datasets/phase4_security.json"
    raw = dataset_path.read_bytes()
    dataset = json.loads(raw)
    rows = []
    for case in dataset["cases"]:
        hit = dict(id=case["id"], source=case["id"] + ".md", text=case["text"])
        rows.append(dict(case, findings=inspect_text(case["text"]),
                         baseline_exposed=bool(SecurityPolicy(scan_documents=False).filter_hits([hit])),
                         protected_exposed=bool(SecurityPolicy().filter_hits([hit]))))
    attacks = [row for row in rows if row["category"] == "injection"]
    benign = [row for row in rows if row["category"] == "benign"]
    started = time.perf_counter()
    for row in rows:
        inspect_text(row["text"])
    report = dict(
        dataset=dataset_path.name, dataset_sha256=hashlib.sha256(raw).hexdigest(),
        policy=asdict(SecurityPolicy()), rows=rows,
        metrics=dict(injection_cases=len(attacks),
                     baseline_context_exposure=sum(row["baseline_exposed"] for row in attacks),
                     protected_context_exposure=sum(row["protected_exposed"] for row in attacks),
                     detected_injections=sum(not row["protected_exposed"] for row in attacks),
                     benign_cases=len(benign), false_positives=sum(not row["protected_exposed"] for row in benign),
                     benign_retained=sum(row["protected_exposed"] for row in benign),
                     factual_poisoning_detected=sum(not row["protected_exposed"] for row in rows if row["category"] == "factual_poisoning"),
                     scan_batch_ms=round((time.perf_counter() - started) * 1000, 3)),
        boundaries=dict(write_tool_allowed=SecurityPolicy().permits_tool("write_local_file"),
                        denied_source_visible=bool(SecurityPolicy(denied_sources=("private.md",)).filter_hits([
                            dict(source="private.md", text="合成私密内容")])),
                        synthetic_key_output_blocked=bool(output_findings("sk-syntheticcredential1234567890"))),
        limitations=["Synthetic regression dataset; cases overlap rule design and are not an independent benchmark.",
                     "Context exposure is not model attack success rate; no model or tool execution occurs in this experiment.",
                     "Paraphrase and factual poisoning misses are deliberately retained; no claim of comprehensive protection."])
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "security-report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False))
    print(path)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, help="指定实验报告目录，Windows 推荐 D 盘。")
    evaluate(parser.parse_args().output_dir)


if __name__ == "__main__":
    main()
