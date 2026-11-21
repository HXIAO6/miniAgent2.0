"""保留原实验命令，核心实现统一位于 miniagent.experiments。"""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from miniagent.experiments.matrix import Usage, grade, summarize, run, main


if __name__ == "__main__":
    main()
