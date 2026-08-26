"""The generative signal model and the ground-truth log.

**Import boundary.** Nothing under ``wimsim.calibration`` or ``wimsim.edge`` may import this
package, directly or transitively. The estimator must be structurally incapable of reading ground
truth, and this is where ground truth lives. See ``tests/test_truth_isolation.py``.
"""

from wimsim.signal.generator import GeneratedBlock, SignalGenerator
from wimsim.signal.truth import TruthLog
from wimsim.signal.writer import RunResult, write_run

__all__ = ["GeneratedBlock", "RunResult", "SignalGenerator", "TruthLog", "write_run"]
