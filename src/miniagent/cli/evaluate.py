"""版本化安全实验入口：使用仓库合成集，记录代码/数据/环境指纹并比较结果。"""
import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import runpy
import subprocess
import sys
import uuid
from datetime import datetime, timezone

from miniagent.config import settings


def fingerprint(paths):
    """以相对文件名和内容计算指纹，工作区未提交的修改同样纳入版本识别。"""
    digest = hashlib.sha256()
    for name, path in sorted(paths):
        digest.update(name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def compare_reports(before, after):
    """仅比较同一数据集的确定性计数；计时不作为自动回归门槛。"""
    if before["dataset_sha256"] != after["dataset_sha256"]:
        raise ValueError("数据集指纹不同，拒绝直接比较指标。")
    keys = ("protected_context_exposure", "false_positives", "factual_poisoning_detected")
    return {key: {"before": before["metrics"][key], "after": after["metrics"][key],
                  "delta": after["metrics"][key] - before["metrics"][key]} for key in keys}


def run_experiment(output):
    """不碰正式知识库，只调用原有离线安全实验；每次创建新目录，避免覆盖成果。"""
    root = settings.project_dir
    run = Path(output) / ("security-" + uuid.uuid4().hex)
    run.mkdir(parents=True)
    module = runpy.run_path(str(root / "tests" / "evaluate_security.py"), run_name="miniagent_security_evaluation")
    report = module["evaluate"](run)
    files = [(str(path.relative_to(root)), path) for path in (root / "src" / "miniagent").rglob("*.py")]
    files += [(name, root / name) for name in ("tests/evaluate_security.py", "requirements.txt", "configs/security.json")]
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    manifest = dict(schema_version=1, created_at=datetime.now(timezone.utc).isoformat(),
                    experiment="synthetic-security-context-filter", git_commit=commit,
                    source_sha256=fingerprint(files), dataset_sha256=report["dataset_sha256"],
                    python=sys.version.split()[0], dependencies={name: version(name) for name in
                        ("langchain", "langgraph", "langsmith", "chromadb")},
                    model_called=False, production_data_used=False,
                    policy=report["policy"], report="security-report.json")
    (run / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--output-dir", required=True, type=Path)
    compare = commands.add_parser("compare")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
    compare.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.command == "run":
        print(run_experiment(arguments.output_dir))
    else:
        try:
            result = compare_reports(json.loads(arguments.before.read_text(encoding="utf-8")),
                                     json.loads(arguments.after.read_text(encoding="utf-8")))
        except ValueError as error:
            parser.exit(1, str(error) + "\n")
        # 比较产物也不覆盖用户已有文件。
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        with arguments.output.open("x", encoding="utf-8") as file:
            json.dump(result, file, ensure_ascii=False, indent=2)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
