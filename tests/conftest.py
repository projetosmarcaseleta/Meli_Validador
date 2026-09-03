import sys
from pathlib import Path

ML_EXPORTER = Path(__file__).resolve().parents[1] / "ml_exporter"
if str(ML_EXPORTER) not in sys.path:
    sys.path.insert(0, str(ML_EXPORTER))
