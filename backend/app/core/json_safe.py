"""Non-finite floats, at the edge where a response becomes JSON.

The pipeline uses NaN with a precise meaning: "this was not measurable". It is
the vocabulary that keeps an unknown payee's age distinct from an age of zero,
HistGradientBoostingClassifier reads it natively, and backend/ml/features.py
documents why nothing may quietly replace it with a number.

JSON has no NaN. `json.dumps` will write the bare token `NaN` if asked, which
is not JSON, and Starlette's JSONResponse - correctly - passes allow_nan=False
and raises instead:

    ValueError: Out of range float values are not JSON compliant

So POST /predict returned 500 for every payment to an address the store had
never seen, which is the commonest case there is, while the same value flowed
through the rest of the system without trouble. The bug was never in the
features; it was in publishing them as-is.

`json_safe` converts at the boundary and nowhere else. NaN and infinity become
null, which is JSON's own way of saying there is no value here, and every other
value is passed through untouched - including 0.0, which means something
different and must keep saying it.

What this is NOT: a global encoder setting. Nothing here changes how the app
serialises anything else, and no response class is swapped for one that emits
`NaN`. A caller receiving null knows the field was unavailable; a caller
receiving `NaN` has to guess what their parser did with it, and most JSON
parsers reject it outright.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def json_safe(value: Any) -> Any:
    """`value` with every non-finite float replaced by None, recursively.

    Handles what a response is actually built from: dicts, lists and tuples,
    plus numpy floats, which is what a feature vector holds. Anything else -
    ints, strings, bools, None - is returned exactly as given.
    """
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value
