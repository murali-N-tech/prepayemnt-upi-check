"""A labelled UPI transaction dataset for training and evaluation.

Why this file exists
--------------------
The previous training script generated random numbers and then labelled them
with a hand-written rule:

    labels = (amount > 80000) | (rolling_txn_count > 7) | (time_gap < 50)

A classifier fitted on that can only relearn the rule it was given, over
features that carry no signal because they were drawn independently. Any
accuracy figure from it describes nothing.

What this does instead
----------------------
There is no public labelled UPI fraud dataset, so this simulates one - the
same approach PaySim takes for mobile money. The important property is that
**labels come from the generative process, not from a rule over the features**:
each fraud scenario is a distinct way of behaving, and the model has to learn
to recognise it from the same features the live system can actually compute.

Scenarios are deliberately built to OVERLAP with legitimate behaviour. Real
people do occasionally send a large amount to a payee they have never used.
A simulator without that overlap produces a separable problem and a
meaningless 0.99 AUC.

Swapping in real data
---------------------
`FEATURES` is the contract. Produce a DataFrame with those columns and an
`is_fraud` label from any source - a bank's labelled data, IEEE-CIS, PaySim -
and the training script works unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# The features the live system can compute at decision time. Nothing here
# requires knowing the outcome, which is the other way a fraud dataset goes
# wrong (leakage).
FEATURES: list[str] = [
    "amount",
    "amount_over_user_avg",
    "is_night",
    "hours_from_usual",
    "seconds_since_last_txn",
    "txns_last_hour",
    "txns_today_over_avg",
    "payee_is_new",
    "payee_age_days",
    "payee_distinct_payers",
    "payee_repeat_ratio",
]

LABEL = "is_fraud"

# The two halves of the feature set. Splitting them is what makes the
# project's central claim testable: can a model that sees only the payer's own
# behaviour catch fraud the payer themselves authorised?
PAYER_FEATURES: list[str] = [
    "amount",
    "amount_over_user_avg",
    "is_night",
    "hours_from_usual",
    "seconds_since_last_txn",
    "txns_last_hour",
    "txns_today_over_avg",
]

PAYEE_FEATURES: list[str] = [
    "payee_is_new",
    "payee_age_days",
    "payee_distinct_payers",
    "payee_repeat_ratio",
]


# payee_distinct_payers is a COUNT. The live system computes it as
# len(payers_of[payee]) - always a whole number - so the simulator has to round
# it too. It did not: the legitimate generator wrote int(np.clip(...)) while
# every fraud generator wrote float(np.clip(rng.gamma(...))), leaving a
# fractional part on 99.6% of fraud rows and none at all on legitimate ones. A
# single tree split on "is this a whole number?" then separated the classes
# perfectly - P(fraud | fractional) was 1.00 against a 1.2% base rate - so
# every figure the training script reported was measuring that artefact rather
# than fraud. _count() exists so the rounding cannot be forgotten again.


def _count(value: float, low: int, high: int) -> float:
    """A payer/transaction count: integral, like the value the live graph gives."""
    return float(int(round(float(np.clip(value, low, high)))))


# The NPCI per-transaction cap for P2P and standard merchant payments. The
# simulator must not generate an amount the network would refuse, and - the
# bigger problem - it must COVER the range the network allows.
#
# It did neither well. Amounts topped out around Rs 61,000: 3 rows in 120,000
# above Rs 50,000 and none at all above Rs 70,000, because typical_amount has a
# median of Rs 270 and the largest multiplier was 90. So the model never saw the
# top 30% of the legal range, and its prediction came out FLAT at 0.4034 from
# Rs 5,000 to Rs 1,00,000 - it could not tell a Rs 5,000 payment from a maxed-out
# Rs 1 lakh transfer, which is the single most important amount distinction in
# UPI fraud and the signature of an account-takeover drain. The bare
# `amount > 70000` rule in /predict was quietly doing that job instead.
#
# Both classes now reach the cap. That matters: if only fraud reached it,
# "amount near the ceiling" would become a near-perfect predictor and this file
# would be leaking the label again in a new shape (see the _count note above).
# Real people really do send a lakh - rent in a metro, tuition, a deposit, a
# medical bill.
UPI_PER_TXN_CAP = 100_000.0


def _amount(value: float, cap: float = UPI_PER_TXN_CAP) -> float:
    """An amount UPI could actually carry: positive, and at or under the cap."""
    return float(min(max(float(value), 1.0), cap))


@dataclass
class _User:
    typical_amount: float
    usual_hour: int
    daily_txns: float
    known_payees: int
    # Some people use UPI for rent, school fees, hospital bills and deposits;
    # most do not. Without this segment the only payments anywhere near the
    # Rs 1 lakh ceiling were fraudulent, which made "amount is large" a
    # near-perfect fraud rule - a property of the simulated population, not of
    # fraud. This is the group whose large payments are ordinary.
    pays_large: bool = False


def _make_users(rng: np.random.Generator, n: int) -> list[_User]:
    return [
        _User(
            # Real UPI spending is heavily right-skewed: mostly small, a long
            # tail. sigma was 0.8, which put 99% of users under Rs 1,750 a
            # payment and only 0.6% over Rs 2,000 - so essentially nobody in
            # the population could plausibly send Rs 70,000, and a legitimate
            # payment at the top of the UPI range became almost impossible to
            # generate. That is why P(fraud | amount > Rs 70,000) came out at
            # 0.90 in a dataset with a 1.2% base rate: not a property of fraud,
            # a property of a population with no one in it who pays rent.
            # 1.1 keeps the median at ~Rs 270 and gives 3.5% of users a typical
            # payment over Rs 2,000, which is the group that pays rent, fees and
            # hospital bills over UPI.
            typical_amount=float(np.exp(rng.normal(5.6, 1.1))),   # median ~270
            usual_hour=int(rng.integers(8, 22)),
            daily_txns=float(np.clip(rng.gamma(2.0, 1.4), 0.4, 12)),
            known_payees=int(rng.integers(5, 60)),
            pays_large=bool(rng.random() < 0.12),
        )
        for _ in range(n)
    ]


def _legit(rng: np.random.Generator, u: _User) -> dict[str, float]:
    """An ordinary payment.

    The hard part of this simulator is making honest behaviour messy enough.
    Real people pay new shops, send rent at 11pm, and occasionally transfer
    twenty times their usual amount. A generator where honest payments are
    always small, always familiar and always mid-afternoon produces a
    separable problem and a meaningless 0.99 AUC.
    """
    kind = rng.random()

    # A rent-and-fees payer makes large payments several times a month; everyone
    # else makes one occasionally.
    high_value_share = 0.14 if u.pays_large else 0.012

    if kind < high_value_share:
        # A genuinely large honest payment reaching into the top of the UPI
        # range: a metro rent, a semester's fees, a deposit, a hospital bill.
        #
        # Scaled to the payer's means, not drawn absolutely. A first version
        # drew this log-uniform across Rs 20,000 to the cap for everybody, which
        # made a person whose usual payment is Rs 270 send Rs 80,000 routinely -
        # a 296x multiple, as ordinary behaviour. Since there are ~2,960 of these
        # rows against ~187 social-engineering rows in test, they carpeted the
        # high-ratio region and destroyed amount_over_user_avg as a signal for
        # everyone. It is also simply not true: how large a person's large
        # payments are tracks what they can afford.
        # A rent payer's large payments genuinely reach the ceiling; for
        # everyone else the ceiling still tracks their means.
        ceiling = (
            UPI_PER_TXN_CAP if u.pays_large
            else float(np.clip(u.typical_amount * 60, 22_000, UPI_PER_TXN_CAP))
        )
        floor = 20_000.0 if u.pays_large else 15_000.0
        amount = _amount(np.exp(rng.uniform(np.log(floor), np.log(max(ceiling, floor * 1.2)))))
        new_payee = rng.random() < 0.5
        hour = int(np.clip(rng.normal(u.usual_hour, 5.0), 0, 23))
    elif kind < high_value_share + 0.10:
        # A big one-off: rent, tuition, a phone, a flight. Large, and often to
        # somebody the payer has never paid before.
        amount = _amount(u.typical_amount * float(np.clip(rng.gamma(3.0, 3.2), 1.5, 90)))
        new_payee = rng.random() < 0.55
        hour = int(np.clip(rng.normal(u.usual_hour, 5.5), 0, 23))
    elif kind < high_value_share + 0.16:
        # A quick run of small payments: a shop, then chai, then the auto home.
        amount = _amount(np.exp(rng.normal(np.log(u.typical_amount) - 0.6, 0.7)))
        new_payee = rng.random() < 0.30
        hour = int(np.clip(rng.normal(u.usual_hour, 3.0), 0, 23))
    else:
        amount = _amount(np.exp(rng.normal(np.log(u.typical_amount), 0.85)))
        new_payee = rng.random() < 0.18
        hour = int(np.clip(rng.normal(u.usual_hour, 3.6), 0, 23))

    if new_payee:
        # A payee new to THIS user is often established for everyone else -
        # but not always. New shops exist, and they look young in the network.
        if rng.random() < 0.55:
            payee_age = float(rng.gamma(3.0, 190))
            payers = _count(rng.gamma(2.4, 16), 1, 500)
            repeat = float(np.clip(rng.beta(2.6, 2.2), 0, 1))
        else:
            payee_age = float(np.clip(rng.gamma(1.3, 22), 0, 400))
            payers = _count(rng.gamma(1.8, 7), 1, 200)
            repeat = float(np.clip(rng.beta(1.3, 4.0), 0, 1))
    else:
        payee_age = float(rng.gamma(4.0, 190))
        payers = _count(rng.gamma(2.6, 18), 1, 500)
        repeat = float(np.clip(rng.beta(4.5, 1.6), 0, 1))

    burst = (high_value_share + 0.10) <= kind < (high_value_share + 0.16)
    return {
        "amount": amount,
        "amount_over_user_avg": amount / u.typical_amount,
        "is_night": float(hour < 6 or hour >= 22),
        "hours_from_usual": float(min(abs(hour - u.usual_hour), 24 - abs(hour - u.usual_hour))),
        "seconds_since_last_txn": float(
            np.clip(rng.exponential(150 if burst else 9000), 5, 400000)
        ),
        "txns_last_hour": float(rng.poisson(3.2 if burst else 0.4)),
        "txns_today_over_avg": float(
            np.clip(rng.gamma(5.0 if burst else 2.2, 0.6), 0.1, 12)
        ),
        "payee_is_new": float(new_payee),
        "payee_age_days": payee_age,
        "payee_distinct_payers": float(payers),
        "payee_repeat_ratio": repeat,
    }


def _account_takeover(rng: np.random.Generator, u: _User) -> dict[str, float]:
    """Someone else has the phone: a rapid burst to fresh payees, often at
    night, amounts pushed well above the user's normal."""
    # A third of takeovers are a drain: whoever has the phone sends as much as
    # the network will carry, so the amount sits just under the cap. That is the
    # real signature of this scenario, and the simulator could not express it
    # while its ceiling was Rs 61,000.
    if rng.random() < 0.34:
        amount = _amount(UPI_PER_TXN_CAP * float(rng.uniform(0.72, 1.0)))
    else:
        amount = _amount(u.typical_amount * float(np.clip(rng.gamma(3.0, 3.5), 0.6, 60)))
    hour = int(rng.choice([1, 2, 3, 4, 23, 0, 14, 15], p=[.16, .16, .16, .12, .12, .12, .08, .08]))

    # A quarter of takeovers drain to a payee the victim has used before, to
    # blend in. Without this, payee_is_new alone separates the classes and the
    # model never has to learn anything harder.
    to_known = rng.random() < 0.25
    return {
        "amount": amount,
        "amount_over_user_avg": amount / u.typical_amount,
        "is_night": float(hour < 6 or hour >= 22),
        "hours_from_usual": float(min(abs(hour - u.usual_hour), 24 - abs(hour - u.usual_hour))),
        "seconds_since_last_txn": float(np.clip(rng.exponential(120), 3, 5000)),
        "txns_last_hour": float(np.clip(rng.poisson(4.5), 0, 30)),
        "txns_today_over_avg": float(np.clip(rng.gamma(6.0, 0.9), 0.5, 20)),
        "payee_is_new": 0.0 if to_known else 1.0,
        "payee_age_days": float(np.clip(rng.gamma(4.0, 150 if to_known else 25), 0, 900)),
        "payee_distinct_payers": _count(rng.gamma(2.4, 16 if to_known else 9), 1, 300),
        "payee_repeat_ratio": float(
            np.clip(rng.beta(4.0, 2.0) if to_known else rng.beta(1.2, 6.0), 0, 1)
        ),
    }


def _social_engineering(rng: np.random.Generator, u: _User) -> dict[str, float]:
    """The hardest case, and the one this project is about. The genuine account
    holder is making the payment, at a normal hour, at normal speed. Nothing
    about the PAYER is wrong. The only signal is the payee."""
    # Half of these are small "verification fee" or "delivery charge" scams,
    # not life savings. Amount alone does not separate them.
    roll = rng.random()
    if roll < 0.5:
        amount = _amount(u.typical_amount * float(np.clip(rng.gamma(1.6, 1.1), 0.2, 12)))
    elif roll < 0.85:
        amount = _amount(u.typical_amount * float(np.clip(rng.gamma(4.0, 2.6), 0.8, 80)))
    else:
        # Persuaded to send a large sum outright - the "your account will be
        # frozen, transfer it to this safe account" variant.
        amount = _amount(np.exp(rng.uniform(np.log(25_000), np.log(UPI_PER_TXN_CAP))))
    hour = int(np.clip(rng.normal(u.usual_hour, 3.6), 0, 23))

    # A third of scammers collect through an aged account, bought or stolen,
    # precisely so the payee looks established.
    aged = rng.random() < 0.35
    return {
        "amount": amount,
        "amount_over_user_avg": amount / u.typical_amount,
        "is_night": float(hour < 6 or hour >= 22),
        "hours_from_usual": float(min(abs(hour - u.usual_hour), 24 - abs(hour - u.usual_hour))),
        "seconds_since_last_txn": float(np.clip(rng.exponential(7000), 30, 300000)),
        "txns_last_hour": float(rng.poisson(0.5)),
        "txns_today_over_avg": float(np.clip(rng.gamma(2.4, 0.5), 0.1, 6)),
        "payee_is_new": 1.0,
        "payee_age_days": float(
            np.clip(rng.gamma(3.0, 120) if aged else rng.gamma(1.1, 14), 0, 900)
        ),
        "payee_distinct_payers": _count(
            rng.gamma(3.0, 18) if aged else rng.gamma(2.0, 6), 1, 400
        ),
        "payee_repeat_ratio": float(
            np.clip(rng.beta(2.2, 3.0) if aged else rng.beta(1.0, 7.0), 0, 1)
        ),
    }


def _mule_collection(rng: np.random.Generator, u: _User) -> dict[str, float]:
    """A payment into a collection account: young payee, many one-time payers."""
    amount = _amount(u.typical_amount * float(np.clip(rng.gamma(3.0, 1.9), 0.5, 40)))
    hour = int(np.clip(rng.normal(u.usual_hour, 4.5), 0, 23))
    return {
        "amount": amount,
        "amount_over_user_avg": amount / u.typical_amount,
        "is_night": float(hour < 6 or hour >= 22),
        "hours_from_usual": float(min(abs(hour - u.usual_hour), 24 - abs(hour - u.usual_hour))),
        "seconds_since_last_txn": float(np.clip(rng.exponential(6000), 20, 250000)),
        "txns_last_hour": float(rng.poisson(0.8)),
        "txns_today_over_avg": float(np.clip(rng.gamma(2.8, 0.6), 0.1, 8)),
        "payee_is_new": 1.0,
        "payee_age_days": float(np.clip(rng.gamma(1.4, 30), 0, 500)),
        "payee_distinct_payers": _count(rng.gamma(4.0, 8), 2, 400),
        "payee_repeat_ratio": float(np.clip(rng.beta(1.2, 8.0), 0, 1)),
    }


def _card_testing(rng: np.random.Generator, u: _User) -> dict[str, float]:
    """Tiny probe payments in quick succession to check the account works."""
    amount = _amount(rng.uniform(1, 25))
    hour = int(rng.integers(0, 24))
    return {
        "amount": amount,
        "amount_over_user_avg": amount / u.typical_amount,
        "is_night": float(hour < 6 or hour >= 22),
        "hours_from_usual": float(min(abs(hour - u.usual_hour), 24 - abs(hour - u.usual_hour))),
        "seconds_since_last_txn": float(np.clip(rng.exponential(35), 1, 900)),
        "txns_last_hour": float(np.clip(rng.poisson(7.0), 1, 40)),
        "txns_today_over_avg": float(np.clip(rng.gamma(7.0, 1.0), 1, 25)),
        "payee_is_new": 1.0,
        "payee_age_days": float(np.clip(rng.gamma(1.2, 20), 0, 300)),
        "payee_distinct_payers": _count(rng.gamma(2.0, 10), 1, 200),
        "payee_repeat_ratio": float(np.clip(rng.beta(1.3, 5.0), 0, 1)),
    }


SCENARIOS = {
    "account_takeover": _account_takeover,
    "social_engineering": _social_engineering,
    "mule_collection": _mule_collection,
    "card_testing": _card_testing,
}

# Roughly how UPI fraud complaints break down: most reported UPI fraud in
# India is social engineering, where the victim authorises the payment.
SCENARIO_MIX = {
    "social_engineering": 0.50,
    "mule_collection": 0.22,
    "account_takeover": 0.20,
    "card_testing": 0.08,
}


def generate(
    n_transactions: int = 120_000,
    fraud_rate: float = 0.012,
    n_users: int = 2_000,
    seed: int = 42,
) -> pd.DataFrame:
    """Build a labelled dataset.

    fraud_rate defaults to 1.2%, which is high for payments but keeps the
    positive class large enough to evaluate. The metrics that matter here
    (PR-AUC, recall at a fixed false-positive rate) are the ones that stay
    meaningful when the base rate changes.
    """
    rng = np.random.default_rng(seed)
    users = _make_users(rng, n_users)

    names = list(SCENARIO_MIX)
    weights = np.array([SCENARIO_MIX[n] for n in names], dtype=float)
    weights /= weights.sum()

    rows: list[dict[str, float]] = []
    labels: list[int] = []
    kinds: list[str] = []

    for _ in range(n_transactions):
        user = users[int(rng.integers(0, n_users))]
        if rng.random() < fraud_rate:
            kind = str(rng.choice(names, p=weights))
            rows.append(SCENARIOS[kind](rng, user))
            labels.append(1)
            kinds.append(kind)
        else:
            rows.append(_legit(rng, user))
            labels.append(0)
            kinds.append("legitimate")

    df = pd.DataFrame(rows, columns=FEATURES)
    df[LABEL] = labels
    df["scenario"] = kinds
    return df
