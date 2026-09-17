"""The trained pickle must survive a numpy major-version change.

Background
----------
scikit-learn leaves a ``np.random.Generator`` on a fitted
HistGradientBoostingClassifier as ``_feature_subsample_rng``. It is used only
while fitting -- predict never reads it -- but it pickles as a PCG64 bit
generator, and numpy changed how bit generators pickle between 1.x and 2.x.
A model trained under numpy 2 therefore failed to load under numpy 1 with:

    <class 'numpy.random._pcg64.PCG64'> is not a known BitGenerator module

which took the whole Transaction Scoring page down whenever the interpreter
that trained the model was not the interpreter that served it. Nothing about
the learned weights is version specific; only that leftover RNG was.

These tests fail against the version that shipped the defect.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.train_model import _strip_fit_only_rng

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = [ROOT / "models" / "risk_model.pkl", ROOT / "models" / "isolation_forest.pkl"]

# Every bit generator numpy ships. Any of them in a dumped artifact ties that
# artifact to one numpy major version.
BIT_GENERATORS = (b"PCG64", b"MT19937", b"Philox", b"SFC64")


class _Nested:
    def __init__(self) -> None:
        self._feature_subsample_rng = np.random.default_rng(0)
        self.coef_ = np.zeros(3)


class _Holder:
    def __init__(self) -> None:
        self.estimators = [_Nested(), _Nested()]
        self.by_name = {"a": _Nested()}
        self.plain = 7


def test_strip_removes_generators_at_every_depth():
    holder = _Holder()
    removed = _strip_fit_only_rng(holder)
    assert removed == 3
    for est in holder.estimators:
        assert not hasattr(est, "_feature_subsample_rng")
    assert not hasattr(holder.by_name["a"], "_feature_subsample_rng")


def test_strip_leaves_everything_else_alone():
    holder = _Holder()
    _strip_fit_only_rng(holder)
    assert holder.plain == 7
    assert holder.estimators[0].coef_.shape == (3,)
    assert set(holder.by_name) == {"a"}


def test_strip_survives_reference_cycles():
    a, b = _Nested(), _Nested()
    a.peer, b.peer = b, a          # cycle: must terminate, not recurse forever
    assert _strip_fit_only_rng(a) == 2


def test_strip_is_idempotent():
    holder = _Holder()
    assert _strip_fit_only_rng(holder) == 3
    assert _strip_fit_only_rng(holder) == 0


@pytest.mark.parametrize("path", ARTIFACTS, ids=lambda p: p.name)
def test_dumped_artifact_carries_no_bit_generator(path: Path):
    """The regression itself: read the bytes on disk, not the loaded object.

    A bit generator anywhere in the file means the artifact only loads on the
    numpy major that wrote it.
    """
    if not path.exists():
        pytest.skip(f"{path.name} not built here; run python backend/train_model.py")
    raw = path.read_bytes()
    found = [name.decode() for name in BIT_GENERATORS if name in raw]
    assert not found, (
        f"{path.name} contains {found}, so it will not load across numpy "
        "majors. train_model.py must strip fit-only RNGs before dumping."
    )
