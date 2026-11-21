"""保留原比较命令，核心实现统一位于 miniagent.experiments。"""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from miniagent.experiments.compare import safe_summary, compare, export, main


if __name__ == "__main__":
    main()
