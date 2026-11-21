"""兼容原规则评测命令，测试目录不再承载正式实验实现。"""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from miniagent.experiments.rules import evaluate, main


if __name__ == "__main__":
    main()
