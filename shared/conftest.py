"""Make ``shared/`` importable so ``import ftn_blueprint`` works when running pytest."""

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

FIXTURES = _HERE / "tests" / "fixtures"
