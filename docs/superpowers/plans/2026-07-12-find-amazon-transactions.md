# find_amazon_transactions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `find-amazon-transactions` MCP tool that matches YNAB transactions against real Amazon order/transaction history and proposes categorization matches with confidence/reasoning, without writing anything back to YNAB.

**Architecture:** A fail-soft `AmazonSettings` config (only registers the tool when Amazon credentials are present), an `amazon_client.py` factory that never triggers interactive login, a pure `amazon_matching.py` algorithm module with zero I/O (fixture-testable), and a `tools/find_amazon_transactions.py` tool that wires YNAB's existing `list_transactions()` together with the `amazon-orders` library's `AmazonTransactions`/`AmazonOrders` clients through the matcher.

**Tech Stack:** Python 3.13, `fastmcp` v3, `ynab` SDK v4, `amazon-orders` PyPI library, `pytest` + `pytest-mock`.

## Global Constraints

- `requires-python = ">=3.13.5,<3.14"` (from `pyproject.toml`) — `amazon-orders` requires only `>=3.9`, so no conflict.
- Add dependency as `amazon-orders>=4.4.4` (latest on PyPI as of 2026-07-12) in `[project.dependencies]`, not a dev dependency.
- Every new/modified `src/` and `tests/` file must pass `make lint` (black --check, ruff, mypy with `disallow_untyped_defs=true`) and `make tests`.
- Numpy-style docstrings on every public function/class, matching the existing `tools/*.py` / `config.py` / `client.py` / `errors.py` style.
- `scripts/` is **not** covered by `mypy`'s `files = ["src", "tests"]` and has no existing test precedent (see `scripts/apply_repo_settings.py`) — `scripts/amazon_login.py` gets type hints for readability but no dedicated unit test; it's a manual, interactive script.
- No live Amazon (or YNAB) API calls in any unit test — everything mocked or pure-fixture.
- `ynab.TransactionDetail`'s date field is the Python attribute `var_date` (pydantic alias `date`), and `amount` is a signed integer in milliunits (negative = outflow). Confirmed via `ynab.TransactionDetail.model_fields`.
- `amazon-orders` entity/exception import paths (confirmed against the library source):
  - `from amazonorders.session import AmazonSession`
  - `from amazonorders.orders import AmazonOrders`
  - `from amazonorders.transactions import AmazonTransactions`
  - `from amazonorders.entity.order import Order`
  - `from amazonorders.entity.transaction import Transaction`
  - `from amazonorders.exception import AmazonOrdersError, AmazonOrdersAuthError`
  - `AmazonTransactions.get_transactions(days: int = 365, ...) -> list[Transaction]`
  - `Transaction` fields: `completed_date: date`, `grand_total: float`, `payment_method: str`, `order_number: str`, `is_refund: bool`, `seller: str`
  - `AmazonOrders.get_order(order_id: str) -> Order`; `Order.items: list[Item]`; `Item.title: str`
  - `AmazonSession(username=..., password=..., otp_secret_key=...)` — env vars override constructor args, but this plan always passes them explicitly (matches `build_api_client`'s pattern of taking values from `Settings`, not re-reading `os.environ`).

---

### Task 1: Add `amazon-orders` dependency and document Amazon env vars

**Files:**
- Modify: `pyproject.toml`
- Modify: `.env.example`

**Interfaces:**
- Produces: the installed `amazonorders` package, importable by every later task. No code interfaces.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, change:

```toml
dependencies = [
    "fastmcp>=3.4.4",
    "pydantic>=2.12",
    "python-dotenv>=1.2",
    "ynab>=4.2.0",
]
```

to:

```toml
dependencies = [
    "amazon-orders>=4.4.4",
    "fastmcp>=3.4.4",
    "pydantic>=2.12",
    "python-dotenv>=1.2",
    "ynab>=4.2.0",
]
```

- [ ] **Step 2: Sync dependencies**

Run: `uv sync --dev`
Expected: `amazon-orders` (and its transitive deps) appear in the resolved lock, install succeeds with exit code 0.

- [ ] **Step 3: Document the new env vars**

Append to `.env.example` (after the existing `YNAB_READ_ONLY` block):

```
# Optional: Amazon credentials for the find-amazon-transactions tool. Leave
# unset to run a YNAB-only server (the tool is simply not registered).
# First-time login requires solving any CAPTCHA/2FA challenge interactively,
# which can't happen inside an MCP tool call -- run this once (and again if
# the session expires) before using the tool:
#   uv run python scripts/amazon_login.py
AMAZON_USERNAME=
AMAZON_PASSWORD=

# Optional: TOTP secret key, only needed if your account uses OTP-based 2FA.
AMAZON_OTP_SECRET_KEY=
```

- [ ] **Step 4: Verify the package imports**

Run: `uv run python -c "from amazonorders.session import AmazonSession; from amazonorders.orders import AmazonOrders; from amazonorders.transactions import AmazonTransactions; from amazonorders.entity.order import Order; from amazonorders.entity.transaction import Transaction; from amazonorders.exception import AmazonOrdersError, AmazonOrdersAuthError; print('ok')"`
Expected: prints `ok` with no import errors.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock .env.example
git commit -m "build: add amazon-orders dependency and document Amazon env vars"
```

---

### Task 2: `amazon_matching.py` — pure matching algorithm

**Files:**
- Create: `src/ynab_mcp/amazon_matching.py`
- Test: `tests/test_amazon_matching.py`

**Interfaces:**
- Produces:
  - `YnabCandidate(transaction_id: str, amount: int, txn_date: date)` — frozen dataclass.
  - `AmazonCandidate(transaction_ref: str, order_number: str, amount: int, txn_date: date)` — frozen dataclass. `transaction_ref` is a caller-assigned unique id for one Amazon `Transaction` record (distinct even when two legs of the same order tie on amount+date).
  - `Match(ynab_transaction_id: str, amazon_transaction_ref: str, order_number: str, classification: str, same_day: bool, split_group: list[str])` — frozen dataclass. `classification` is one of `"exact"`, `"near-date"`, `"split-shipment"`.
  - `AmbiguousMatch(ynab_transaction_id: str, candidate_refs: list[str])` — frozen dataclass.
  - `MatchResult(matches: list[Match], ambiguous: list[AmbiguousMatch], unmatched: list[str])` — frozen dataclass. `unmatched` holds YNAB transaction ids.
  - `match_transactions(ynab_transactions: list[YnabCandidate], amazon_transactions: list[AmazonCandidate], date_window_days: int = 3) -> MatchResult` — pure function, no I/O.
- Consumes: nothing (this task has no dependency on any other task; it can be built and fully tested standalone).

This task has no dependency on Task 1 beyond `uv sync` having run (it imports nothing from `amazonorders`) — it can be implemented and reviewed independently/in parallel with Tasks 3–6.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_amazon_matching.py`:

```python
"""Tests for ynab_mcp.amazon_matching."""

from datetime import date

from ynab_mcp.amazon_matching import (
    AmazonCandidate,
    YnabCandidate,
    match_transactions,
)


def test_exact_same_day_amount_and_date_match() -> None:
    """A single Amazon transaction with the same amount and date is exact."""
    ynab_txns = [YnabCandidate("y1", -25990, date(2026, 6, 1))]
    amazon_txns = [AmazonCandidate("a1:0", "111-1111111", -25990, date(2026, 6, 1))]

    result = match_transactions(ynab_txns, amazon_txns)

    assert len(result.matches) == 1
    match = result.matches[0]
    assert match.ynab_transaction_id == "y1"
    assert match.amazon_transaction_ref == "a1:0"
    assert match.order_number == "111-1111111"
    assert match.classification == "exact"
    assert match.same_day is True
    assert match.split_group == []
    assert result.ambiguous == []
    assert result.unmatched == []


def test_near_date_match_within_window_but_not_same_day() -> None:
    """A same-amount match a few days off (within the window) is near-date."""
    ynab_txns = [YnabCandidate("y1", -10000, date(2026, 6, 5))]
    amazon_txns = [AmazonCandidate("a1:0", "111-2222222", -10000, date(2026, 6, 3))]

    result = match_transactions(ynab_txns, amazon_txns, date_window_days=3)

    assert len(result.matches) == 1
    assert result.matches[0].classification == "near-date"
    assert result.matches[0].same_day is False


def test_date_outside_window_is_no_match() -> None:
    """A same-amount charge outside the date window doesn't count."""
    ynab_txns = [YnabCandidate("y1", -10000, date(2026, 6, 10))]
    amazon_txns = [AmazonCandidate("a1:0", "111-3333333", -10000, date(2026, 6, 1))]

    result = match_transactions(ynab_txns, amazon_txns, date_window_days=3)

    assert result.matches == []
    assert result.unmatched == ["y1"]


def test_split_shipment_groups_multiple_legs_of_one_order() -> None:
    """Two YNAB transactions each uniquely matching legs of one order group."""
    ynab_txns = [
        YnabCandidate("y1", -5000, date(2026, 6, 1)),
        YnabCandidate("y2", -7500, date(2026, 6, 2)),
    ]
    amazon_txns = [
        AmazonCandidate("a1:0", "222-0000000", -5000, date(2026, 6, 1)),
        AmazonCandidate("a1:1", "222-0000000", -7500, date(2026, 6, 2)),
    ]

    result = match_transactions(ynab_txns, amazon_txns)

    assert len(result.matches) == 2
    by_id = {m.ynab_transaction_id: m for m in result.matches}
    assert by_id["y1"].classification == "split-shipment"
    assert by_id["y2"].classification == "split-shipment"
    assert by_id["y1"].split_group == ["y2"]
    assert by_id["y2"].split_group == ["y1"]
    assert result.ambiguous == []
    assert result.unmatched == []


def test_ambiguous_when_two_amazon_candidates_tie_for_one_ynab_transaction() -> None:
    """Two equally-good Amazon candidates for one YNAB transaction are ambiguous."""
    ynab_txns = [YnabCandidate("y1", -3000, date(2026, 6, 5))]
    amazon_txns = [
        AmazonCandidate("a1:0", "333-1111111", -3000, date(2026, 6, 4)),
        AmazonCandidate("a2:0", "333-2222222", -3000, date(2026, 6, 6)),
    ]

    result = match_transactions(ynab_txns, amazon_txns, date_window_days=3)

    assert result.matches == []
    assert len(result.ambiguous) == 1
    ambiguous = result.ambiguous[0]
    assert ambiguous.ynab_transaction_id == "y1"
    assert set(ambiguous.candidate_refs) == {"a1:0", "a2:0"}
    assert result.unmatched == []


def test_ambiguous_when_one_amazon_candidate_ties_between_two_ynab_transactions() -> None:
    """One Amazon candidate tying between two YNAB transactions is ambiguous for both."""
    ynab_txns = [
        YnabCandidate("y1", -4000, date(2026, 6, 5)),
        YnabCandidate("y2", -4000, date(2026, 6, 5)),
    ]
    amazon_txns = [AmazonCandidate("a1:0", "444-1111111", -4000, date(2026, 6, 5))]

    result = match_transactions(ynab_txns, amazon_txns)

    assert result.matches == []
    assert len(result.ambiguous) == 2
    ynab_ids = {a.ynab_transaction_id for a in result.ambiguous}
    assert ynab_ids == {"y1", "y2"}
    for ambiguous in result.ambiguous:
        assert ambiguous.candidate_refs == ["a1:0"]


def test_no_match_when_no_amazon_candidate_in_range() -> None:
    """An Amazon-like YNAB transaction with nothing nearby is unmatched."""
    ynab_txns = [YnabCandidate("y1", -9999, date(2026, 6, 1))]
    amazon_txns: list[AmazonCandidate] = []

    result = match_transactions(ynab_txns, amazon_txns)

    assert result.matches == []
    assert result.ambiguous == []
    assert result.unmatched == ["y1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_amazon_matching.py -v`
Expected: `ModuleNotFoundError: No module named 'ynab_mcp.amazon_matching'` (collection error).

- [ ] **Step 3: Write the implementation**

Create `src/ynab_mcp/amazon_matching.py`:

```python
"""Pure merge-key algorithm joining YNAB transactions to Amazon charges.

No I/O and no dependency on the ``ynab`` or ``amazon-orders`` SDKs -- both
sides are pre-converted by the caller into the small dataclasses below, so
this module is fully testable with plain fixtures.
"""

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class YnabCandidate:
    """A YNAB transaction being considered for an Amazon match.

    Parameters
    ----------
    transaction_id : str
        The YNAB transaction's id.
    amount : int
        The transaction amount in milliunits (negative for outflows),
        matching YNAB's own sign convention.
    txn_date : datetime.date
        The transaction's date.
    """

    transaction_id: str
    amount: int
    txn_date: date


@dataclass(frozen=True)
class AmazonCandidate:
    """An Amazon charge/refund record being considered for a YNAB match.

    Parameters
    ----------
    transaction_ref : str
        A caller-assigned unique identifier for this specific Amazon
        transaction record -- distinct even when two shipments of the same
        order tie on amount and date.
    order_number : str
        The Amazon order this charge belongs to. Multiple
        ``AmazonCandidate``s can share an ``order_number`` for
        split-shipment orders.
    amount : int
        The charge amount in milliunits, sign-aligned with
        ``YnabCandidate.amount`` (negative, since it's an outflow).
    txn_date : datetime.date
        The date the charge completed.
    """

    transaction_ref: str
    order_number: str
    amount: int
    txn_date: date


@dataclass(frozen=True)
class Match:
    """A confident, uniquely-resolved match between one YNAB and one Amazon transaction.

    Parameters
    ----------
    ynab_transaction_id : str
        The matched YNAB transaction's id.
    amazon_transaction_ref : str
        The matched Amazon transaction's ``transaction_ref``.
    order_number : str
        The Amazon order this charge belongs to.
    classification : {"exact", "near-date", "split-shipment"}
        How confident the match is.
    same_day : bool
        Whether the YNAB and Amazon dates were identical.
    split_group : list[str]
        Sibling YNAB transaction ids sharing this ``order_number``, when
        ``classification`` is ``"split-shipment"``; empty otherwise.
    """

    ynab_transaction_id: str
    amazon_transaction_ref: str
    order_number: str
    classification: str
    same_day: bool
    split_group: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AmbiguousMatch:
    """A YNAB transaction with more than one equally-good Amazon candidate.

    Parameters
    ----------
    ynab_transaction_id : str
        The ambiguous YNAB transaction's id.
    candidate_refs : list[str]
        The tied Amazon transactions' ``transaction_ref`` values.
    """

    ynab_transaction_id: str
    candidate_refs: list[str]


@dataclass(frozen=True)
class MatchResult:
    """The full output of :func:`match_transactions`.

    Parameters
    ----------
    matches : list[Match]
        Confidently, uniquely resolved matches.
    ambiguous : list[AmbiguousMatch]
        YNAB transactions with multiple tied Amazon candidates (or vice
        versa), surfaced for a human to disambiguate rather than guessed.
    unmatched : list[str]
        YNAB transaction ids with no Amazon candidate in range.
    """

    matches: list[Match]
    ambiguous: list[AmbiguousMatch]
    unmatched: list[str]


def match_transactions(
    ynab_transactions: list[YnabCandidate],
    amazon_transactions: list[AmazonCandidate],
    date_window_days: int = 3,
) -> MatchResult:
    """Join YNAB transactions to Amazon charges on exact amount + date window.

    Two passes: pass 1 buckets each YNAB transaction by how many Amazon
    candidates tie for it (and vice versa) into ``no-match`` / ``ambiguous``
    / a uniquely-resolved pair. Pass 2 regroups uniquely-resolved pairs by
    ``order_number``: any order with more than one resolved leg is a
    split-shipment order, and every leg's classification becomes
    ``"split-shipment"``.

    Parameters
    ----------
    ynab_transactions : list[YnabCandidate]
        Candidate YNAB transactions (already pre-filtered to Amazon-like
        payees by the caller).
    amazon_transactions : list[AmazonCandidate]
        Candidate Amazon transactions (already pre-filtered to exclude
        refunds/Whole Foods by the caller).
    date_window_days : int, optional
        Maximum number of days apart (inclusive, either direction) a YNAB
        and Amazon date may be and still count as a match, by default
        ``3``.

    Returns
    -------
    MatchResult
        The classified matches, ambiguous ties, and unmatched transactions.
    """
    ynab_to_amazon: dict[str, list[AmazonCandidate]] = {}
    amazon_to_ynab: dict[str, list[str]] = {}
    for ynab_txn in ynab_transactions:
        candidates = [
            amazon_txn
            for amazon_txn in amazon_transactions
            if amazon_txn.amount == ynab_txn.amount
            and abs((amazon_txn.txn_date - ynab_txn.txn_date).days) <= date_window_days
        ]
        ynab_to_amazon[ynab_txn.transaction_id] = candidates
        for amazon_txn in candidates:
            amazon_to_ynab.setdefault(amazon_txn.transaction_ref, []).append(
                ynab_txn.transaction_id
            )

    ambiguous: list[AmbiguousMatch] = []
    unmatched: list[str] = []
    unique_pairs: list[tuple[YnabCandidate, AmazonCandidate]] = []

    for ynab_txn in ynab_transactions:
        candidates = ynab_to_amazon[ynab_txn.transaction_id]
        if not candidates:
            unmatched.append(ynab_txn.transaction_id)
        elif len(candidates) > 1:
            ambiguous.append(
                AmbiguousMatch(
                    ynab_transaction_id=ynab_txn.transaction_id,
                    candidate_refs=[c.transaction_ref for c in candidates],
                )
            )
        else:
            candidate = candidates[0]
            if len(amazon_to_ynab[candidate.transaction_ref]) > 1:
                ambiguous.append(
                    AmbiguousMatch(
                        ynab_transaction_id=ynab_txn.transaction_id,
                        candidate_refs=[candidate.transaction_ref],
                    )
                )
            else:
                unique_pairs.append((ynab_txn, candidate))

    groups: dict[str, list[tuple[YnabCandidate, AmazonCandidate]]] = {}
    for ynab_txn, amazon_txn in unique_pairs:
        groups.setdefault(amazon_txn.order_number, []).append((ynab_txn, amazon_txn))

    matches: list[Match] = []
    for order_number, pairs in groups.items():
        is_split = len(pairs) > 1
        for ynab_txn, amazon_txn in pairs:
            same_day = ynab_txn.txn_date == amazon_txn.txn_date
            classification = (
                "split-shipment" if is_split else ("exact" if same_day else "near-date")
            )
            matches.append(
                Match(
                    ynab_transaction_id=ynab_txn.transaction_id,
                    amazon_transaction_ref=amazon_txn.transaction_ref,
                    order_number=order_number,
                    classification=classification,
                    same_day=same_day,
                    split_group=(
                        [
                            other.transaction_id
                            for other, _ in pairs
                            if other.transaction_id != ynab_txn.transaction_id
                        ]
                        if is_split
                        else []
                    ),
                )
            )

    # Preserve input ordering for deterministic, readable output.
    order_index = {t.transaction_id: i for i, t in enumerate(ynab_transactions)}
    matches.sort(key=lambda m: order_index[m.ynab_transaction_id])
    ambiguous.sort(key=lambda a: order_index[a.ynab_transaction_id])
    unmatched.sort(key=lambda tid: order_index[tid])

    return MatchResult(matches=matches, ambiguous=ambiguous, unmatched=unmatched)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_amazon_matching.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Lint**

Run: `uv run black --check src/ynab_mcp/amazon_matching.py tests/test_amazon_matching.py && uv run ruff check src/ynab_mcp/amazon_matching.py tests/test_amazon_matching.py && uv run mypy`
Expected: no errors. If black reports formatting differences, run `uv run black src/ynab_mcp/amazon_matching.py tests/test_amazon_matching.py` and re-check.

- [ ] **Step 6: Commit**

```bash
git add src/ynab_mcp/amazon_matching.py tests/test_amazon_matching.py
git commit -m "feat: add pure Amazon/YNAB transaction matching algorithm"
```

---

### Task 3: `config.py` — `AmazonSettings`

**Files:**
- Modify: `src/ynab_mcp/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `AmazonSettings(amazon_username: str, amazon_password: str, amazon_otp_secret_key: str | None)` frozen dataclass with `AmazonSettings.from_env() -> AmazonSettings | None`.
- Consumes: nothing new (uses the same `os`/`load_dotenv` already imported in `config.py`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
from ynab_mcp.config import AmazonSettings, Settings


def test_amazon_settings_from_env_reads_all_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All three Amazon env vars are read when present."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("AMAZON_USERNAME", "user@example.com")
    monkeypatch.setenv("AMAZON_PASSWORD", "hunter2")
    monkeypatch.setenv("AMAZON_OTP_SECRET_KEY", "otp-secret")

    settings = AmazonSettings.from_env()

    assert settings is not None
    assert settings.amazon_username == "user@example.com"
    assert settings.amazon_password == "hunter2"
    assert settings.amazon_otp_secret_key == "otp-secret"


def test_amazon_settings_from_env_defaults_otp_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing AMAZON_OTP_SECRET_KEY defaults to None."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("AMAZON_USERNAME", "user@example.com")
    monkeypatch.setenv("AMAZON_PASSWORD", "hunter2")
    monkeypatch.delenv("AMAZON_OTP_SECRET_KEY", raising=False)

    settings = AmazonSettings.from_env()

    assert settings is not None
    assert settings.amazon_otp_secret_key is None


def test_amazon_settings_from_env_returns_none_when_username_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing AMAZON_USERNAME means Amazon integration is unconfigured."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("AMAZON_USERNAME", raising=False)
    monkeypatch.setenv("AMAZON_PASSWORD", "hunter2")

    assert AmazonSettings.from_env() is None


def test_amazon_settings_from_env_returns_none_when_password_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing AMAZON_PASSWORD means Amazon integration is unconfigured."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("AMAZON_USERNAME", "user@example.com")
    monkeypatch.delenv("AMAZON_PASSWORD", raising=False)

    assert AmazonSettings.from_env() is None


def test_amazon_settings_from_env_returns_none_when_both_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Amazon env vars at all still returns None, not an error."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("AMAZON_USERNAME", raising=False)
    monkeypatch.delenv("AMAZON_PASSWORD", raising=False)

    assert AmazonSettings.from_env() is None
```

Also change the existing `from ynab_mcp.config import Settings` import line at the top of `tests/test_config.py` to `from ynab_mcp.config import AmazonSettings, Settings` (remove the duplicate import added above once merged in).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: `ImportError: cannot import name 'AmazonSettings' from 'ynab_mcp.config'`.

- [ ] **Step 3: Write the implementation**

In `src/ynab_mcp/config.py`, append after the existing `Settings` class:

```python
@dataclass(frozen=True)
class AmazonSettings:
    """Amazon credentials for the find-amazon-transactions tool.

    Parameters
    ----------
    amazon_username : str
        The Amazon account email/username used to authenticate.
    amazon_password : str
        The Amazon account password used to authenticate.
    amazon_otp_secret_key : str | None
        The TOTP secret key for automatic OTP-based 2FA solving, if the
        account has 2FA enabled.
    """

    amazon_username: str
    amazon_password: str
    amazon_otp_secret_key: str | None

    @classmethod
    def from_env(cls) -> "AmazonSettings | None":
        """Build ``AmazonSettings`` from the process environment.

        Loads `.env` first (safe to call even if ``Settings.from_env()``
        already did, so this also works when called standalone from
        ``scripts/amazon_login.py``), then reads ``AMAZON_USERNAME``,
        ``AMAZON_PASSWORD``, and ``AMAZON_OTP_SECRET_KEY``.

        Returns
        -------
        AmazonSettings | None
            The parsed Amazon configuration, or ``None`` if
            ``AMAZON_USERNAME`` or ``AMAZON_PASSWORD`` is unset. Unlike
            ``Settings.from_env``, this does not raise -- Amazon
            integration is optional server-wide functionality.
        """
        load_dotenv()

        username = os.environ.get("AMAZON_USERNAME", "").strip()
        password = os.environ.get("AMAZON_PASSWORD", "").strip()
        if not username or not password:
            return None

        otp_secret_key = os.environ.get("AMAZON_OTP_SECRET_KEY", "").strip() or None

        return cls(
            amazon_username=username,
            amazon_password=password,
            amazon_otp_secret_key=otp_secret_key,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: all tests PASS (existing `Settings` tests + the 5 new `AmazonSettings` tests).

- [ ] **Step 5: Lint**

Run: `uv run black --check src/ynab_mcp/config.py tests/test_config.py && uv run ruff check src/ynab_mcp/config.py tests/test_config.py && uv run mypy`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/ynab_mcp/config.py tests/test_config.py
git commit -m "feat: add fail-soft AmazonSettings config"
```

---

### Task 4: `errors.py` — `translate_amazon_exception`

**Files:**
- Modify: `src/ynab_mcp/errors.py`
- Test: `tests/test_errors.py`

**Interfaces:**
- Produces: `translate_amazon_exception(exc: AmazonOrdersError) -> ToolError`.
- Consumes: `amazonorders.exception.AmazonOrdersError`, `amazonorders.exception.AmazonOrdersAuthError` (installed by Task 1).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_errors.py`:

```python
from amazonorders.exception import AmazonOrdersAuthError, AmazonOrdersError

from ynab_mcp.errors import translate_amazon_exception


def test_translate_amazon_exception_auth_error_points_to_login_script() -> None:
    """An auth failure tells the user to re-run the login script."""
    exc = AmazonOrdersAuthError("session expired")

    result = translate_amazon_exception(exc)

    assert isinstance(result, ToolError)
    assert "scripts/amazon_login.py" in str(result)


def test_translate_amazon_exception_generic_error_includes_message() -> None:
    """A non-auth error still surfaces the underlying message."""
    exc = AmazonOrdersError("something broke")

    result = translate_amazon_exception(exc)

    assert isinstance(result, ToolError)
    assert "something broke" in str(result)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_errors.py -v`
Expected: `ImportError: cannot import name 'translate_amazon_exception' from 'ynab_mcp.errors'`.

- [ ] **Step 3: Write the implementation**

In `src/ynab_mcp/errors.py`, add the import at the top (alongside the existing `import ynab`):

```python
from amazonorders.exception import AmazonOrdersAuthError, AmazonOrdersError
```

Then append after `translate_api_exception`:

```python
def translate_amazon_exception(exc: AmazonOrdersError) -> ToolError:
    """Convert an ``amazon-orders`` exception into a FastMCP ``ToolError``.

    Parameters
    ----------
    exc : amazonorders.exception.AmazonOrdersError
        The exception raised by an ``amazon-orders`` library call.

    Returns
    -------
    fastmcp.exceptions.ToolError
        A ``ToolError`` describing the failure. Authentication failures get
        a remediation hint pointing at ``scripts/amazon_login.py``, since
        that's the only way to re-establish a session -- this tool never
        attempts an interactive login itself.
    """
    if isinstance(exc, AmazonOrdersAuthError):
        logger.error("Amazon session is missing or expired: %s", exc)
        return ToolError(
            "Amazon session is missing or expired. Run "
            "`uv run python scripts/amazon_login.py` to log in again."
        )
    logger.error("Amazon orders request failed: %s", exc)
    return ToolError(f"Amazon orders request failed: {exc}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_errors.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Lint**

Run: `uv run black --check src/ynab_mcp/errors.py tests/test_errors.py && uv run ruff check src/ynab_mcp/errors.py tests/test_errors.py && uv run mypy`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/ynab_mcp/errors.py tests/test_errors.py
git commit -m "feat: translate amazon-orders exceptions into ToolError"
```

---

### Task 5: `amazon_client.py` — session and client factories

**Files:**
- Create: `src/ynab_mcp/amazon_client.py`
- Test: `tests/test_amazon_client.py`

**Interfaces:**
- Produces:
  - `build_amazon_session(settings: AmazonSettings) -> AmazonSession`
  - `build_amazon_orders(session: AmazonSession) -> AmazonOrders`
  - `build_amazon_transactions(session: AmazonSession) -> AmazonTransactions`
- Consumes: `AmazonSettings` (Task 3), `amazonorders.session.AmazonSession`, `amazonorders.orders.AmazonOrders`, `amazonorders.transactions.AmazonTransactions` (Task 1).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_amazon_client.py`:

```python
"""Tests for ynab_mcp.amazon_client."""

from pytest_mock import MockerFixture

from ynab_mcp.amazon_client import (
    build_amazon_orders,
    build_amazon_session,
    build_amazon_transactions,
)
from ynab_mcp.config import AmazonSettings


def _settings() -> AmazonSettings:
    return AmazonSettings(
        amazon_username="user@example.com",
        amazon_password="hunter2",
        amazon_otp_secret_key="otp-secret",
    )


def test_build_amazon_session_passes_credentials_and_never_logs_in(
    mocker: MockerFixture,
) -> None:
    """The session is built from settings; .login() is never called here."""
    session_cls = mocker.patch("ynab_mcp.amazon_client.AmazonSession")

    session = build_amazon_session(_settings())

    session_cls.assert_called_once_with(
        username="user@example.com",
        password="hunter2",
        otp_secret_key="otp-secret",
    )
    assert session is session_cls.return_value
    session_cls.return_value.login.assert_not_called()


def test_build_amazon_orders_wraps_session(mocker: MockerFixture) -> None:
    """AmazonOrders is constructed from the given session."""
    orders_cls = mocker.patch("ynab_mcp.amazon_client.AmazonOrders")
    session = mocker.Mock()

    orders = build_amazon_orders(session)

    orders_cls.assert_called_once_with(session)
    assert orders is orders_cls.return_value


def test_build_amazon_transactions_wraps_session(mocker: MockerFixture) -> None:
    """AmazonTransactions is constructed from the given session."""
    transactions_cls = mocker.patch("ynab_mcp.amazon_client.AmazonTransactions")
    session = mocker.Mock()

    transactions = build_amazon_transactions(session)

    transactions_cls.assert_called_once_with(session)
    assert transactions is transactions_cls.return_value
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_amazon_client.py -v`
Expected: `ModuleNotFoundError: No module named 'ynab_mcp.amazon_client'`.

- [ ] **Step 3: Write the implementation**

Create `src/ynab_mcp/amazon_client.py`:

```python
"""Amazon session construction and order/transaction client factories."""

from amazonorders.orders import AmazonOrders
from amazonorders.session import AmazonSession
from amazonorders.transactions import AmazonTransactions

from ynab_mcp.config import AmazonSettings


def build_amazon_session(settings: AmazonSettings) -> AmazonSession:
    """Construct an ``AmazonSession`` from Amazon settings.

    Deliberately never calls ``.login()`` -- an MCP stdio tool call has no
    way to handle an interactive CAPTCHA/OTP challenge mid-request. The
    session loads any existing persisted cookies automatically; the first
    login must happen out of band via ``scripts/amazon_login.py``.

    Parameters
    ----------
    settings : AmazonSettings
        The server's parsed Amazon configuration.

    Returns
    -------
    amazonorders.session.AmazonSession
        A session that will reuse a previously persisted login, if any.
    """
    return AmazonSession(
        username=settings.amazon_username,
        password=settings.amazon_password,
        otp_secret_key=settings.amazon_otp_secret_key,
    )


def build_amazon_orders(session: AmazonSession) -> AmazonOrders:
    """Construct an ``AmazonOrders`` client from a session.

    Parameters
    ----------
    session : amazonorders.session.AmazonSession
        A configured Amazon session.

    Returns
    -------
    amazonorders.orders.AmazonOrders
        A client for fetching Amazon order history and detail.
    """
    return AmazonOrders(session)


def build_amazon_transactions(session: AmazonSession) -> AmazonTransactions:
    """Construct an ``AmazonTransactions`` client from a session.

    Parameters
    ----------
    session : amazonorders.session.AmazonSession
        A configured Amazon session.

    Returns
    -------
    amazonorders.transactions.AmazonTransactions
        A client for fetching Amazon per-charge transaction history.
    """
    return AmazonTransactions(session)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_amazon_client.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 5: Lint**

Run: `uv run black --check src/ynab_mcp/amazon_client.py tests/test_amazon_client.py && uv run ruff check src/ynab_mcp/amazon_client.py tests/test_amazon_client.py && uv run mypy`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/ynab_mcp/amazon_client.py tests/test_amazon_client.py
git commit -m "feat: add Amazon session/client factories"
```

---

### Task 6: `scripts/amazon_login.py` — one-time interactive login

**Files:**
- Create: `scripts/amazon_login.py`

**Interfaces:**
- Consumes: `AmazonSettings.from_env()` (Task 3), `build_amazon_session()` (Task 5).
- Produces: nothing importable — this is a standalone entry point, not tested by `make tests` (see Global Constraints).

- [ ] **Step 1: Write the script**

Create `scripts/amazon_login.py`:

```python
"""One-time interactive Amazon login.

Run this manually (and again whenever the session expires) so the
find-amazon-transactions tool can reuse a persisted session without ever
attempting an interactive login itself:

    uv run python scripts/amazon_login.py
"""

import sys

from ynab_mcp.amazon_client import build_amazon_session
from ynab_mcp.config import AmazonSettings


def main() -> None:
    """Log into Amazon interactively and persist the session to disk."""
    settings = AmazonSettings.from_env()
    if settings is None:
        print(
            "AMAZON_USERNAME and AMAZON_PASSWORD must be set in .env before "
            "logging in.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    session = build_amazon_session(settings)
    session.login()
    print("Amazon login succeeded; session persisted for the MCP server to reuse.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `uv run python -c "import ast; ast.parse(open('scripts/amazon_login.py').read())"`
Expected: no output, exit code 0 (syntax is valid; this does not execute `main()`, since that requires real credentials and network access).

- [ ] **Step 3: Commit**

```bash
git add scripts/amazon_login.py
git commit -m "feat: add one-time interactive Amazon login script"
```

---

### Task 7: `tools/find_amazon_transactions.py` — the tool

**Files:**
- Create: `src/ynab_mcp/tools/find_amazon_transactions.py`
- Test: `tests/test_tools_find_amazon_transactions.py`

**Interfaces:**
- Consumes: `list_transactions()` (`tools/transactions.py`, existing), `match_transactions`, `YnabCandidate`, `AmazonCandidate` (Task 2), `translate_amazon_exception` (Task 4), `resolve_budget_id` (`client.py`, existing), `Settings` (`config.py`, existing), `amazonorders.exception.AmazonOrdersError`, `amazonorders.orders.AmazonOrders`, `amazonorders.transactions.AmazonTransactions`, `amazonorders.entity.order.Order`, `amazonorders.entity.transaction.Transaction` (Task 1).
- Produces:
  - `find_amazon_transactions(ynab_client, amazon_transactions_client, amazon_orders_client, budget_id, since_date=None, until_date=None, date_window_days=3) -> dict[str, object]`
  - `register(mcp, ynab_client, amazon_transactions_client, amazon_orders_client, settings) -> None` — registers the `find-amazon-transactions` tool.

This is the join point: it cannot start until Tasks 2, 4, and 5 are done (it imports from all three), so it must run after them.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tools_find_amazon_transactions.py`:

```python
"""Tests for ynab_mcp.tools.find_amazon_transactions."""

from datetime import date
from types import SimpleNamespace

from amazonorders.exception import AmazonOrdersAuthError
from fastmcp.exceptions import ToolError
from pytest import raises
from pytest_mock import MockerFixture

from ynab_mcp.tools.find_amazon_transactions import find_amazon_transactions


def _ynab_txn(mocker: MockerFixture, id_: str, amount: int, txn_date: date, payee: str):
    txn = mocker.Mock()
    txn.id = id_
    txn.amount = amount
    txn.var_date = txn_date
    txn.payee_name = payee
    txn.model_dump.return_value = {"id": id_, "amount": amount, "payee_name": payee}
    return txn


def _amazon_txn(
    order_number: str,
    grand_total: float,
    completed_date: date,
    seller: str = "Amazon.com",
    is_refund: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        order_number=order_number,
        grand_total=grand_total,
        completed_date=completed_date,
        payment_method="Visa ...1234",
        seller=seller,
        is_refund=is_refund,
    )


def _order(titles: list[str]) -> SimpleNamespace:
    return SimpleNamespace(items=[SimpleNamespace(title=t) for t in titles])


def test_find_amazon_transactions_returns_exact_match_with_reasoning(
    mocker: MockerFixture,
) -> None:
    """An exact amount+date pair comes back in matches with item detail."""
    ynab_client = mocker.Mock()
    list_transactions = mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions"
    )
    list_transactions.return_value = [
        _ynab_txn(mocker, "y1", -259900, date(2026, 6, 1), "Amazon.com"),
    ]
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.return_value = [
        _amazon_txn("111-1111111", -259.90, date(2026, 6, 1)),
    ]
    amazon_orders_client = mocker.Mock()
    amazon_orders_client.get_order.return_value = _order(["Widget"])

    result = find_amazon_transactions(
        ynab_client, amazon_transactions_client, amazon_orders_client, "budget-1"
    )

    assert len(result["matches"]) == 1
    match = result["matches"][0]
    assert match["ynab_transaction"] == {
        "id": "y1",
        "amount": -259900,
        "payee_name": "Amazon.com",
    }
    assert match["order_number"] == "111-1111111"
    assert match["classification"] == "exact"
    assert match["same_day"] is True
    assert "Widget" in match["reasoning"]
    assert match["amazon_transaction"]["grand_total"] == -259.90
    assert result["ambiguous"] == []
    assert result["unmatched"] == []
    amazon_orders_client.get_order.assert_called_once_with("111-1111111")


def test_find_amazon_transactions_excludes_refunds_and_whole_foods(
    mocker: MockerFixture,
) -> None:
    """Refunds and Whole Foods charges never become match candidates."""
    ynab_client = mocker.Mock()
    list_transactions = mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions"
    )
    list_transactions.return_value = [
        _ynab_txn(mocker, "y1", -5000, date(2026, 6, 1), "Amazon.com"),
    ]
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.return_value = [
        _amazon_txn("111-1111111", 50.00, date(2026, 6, 1), is_refund=True),
        _amazon_txn(
            "222-2222222", -50.00, date(2026, 6, 1), seller="Whole Foods Market"
        ),
    ]
    amazon_orders_client = mocker.Mock()

    result = find_amazon_transactions(
        ynab_client, amazon_transactions_client, amazon_orders_client, "budget-1"
    )

    assert result["matches"] == []
    assert result["unmatched"][0]["ynab_transaction"]["id"] == "y1"
    amazon_orders_client.get_order.assert_not_called()


def test_find_amazon_transactions_ignores_non_amazon_payees(
    mocker: MockerFixture,
) -> None:
    """A payee that doesn't look like Amazon never reaches the matcher."""
    ynab_client = mocker.Mock()
    list_transactions = mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions"
    )
    list_transactions.return_value = [
        _ynab_txn(mocker, "y1", -5000, date(2026, 6, 1), "Local Grocery Store"),
    ]
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.return_value = []
    amazon_orders_client = mocker.Mock()

    result = find_amazon_transactions(
        ynab_client, amazon_transactions_client, amazon_orders_client, "budget-1"
    )

    assert result["matches"] == []
    assert result["ambiguous"] == []
    assert result["unmatched"] == []


def test_find_amazon_transactions_surfaces_ambiguous_candidates(
    mocker: MockerFixture,
) -> None:
    """Tied Amazon candidates are surfaced, not silently resolved."""
    ynab_client = mocker.Mock()
    list_transactions = mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions"
    )
    list_transactions.return_value = [
        _ynab_txn(mocker, "y1", -30000, date(2026, 6, 5), "Amazon.com"),
    ]
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.return_value = [
        _amazon_txn("333-1111111", -30.00, date(2026, 6, 4)),
        _amazon_txn("333-2222222", -30.00, date(2026, 6, 6)),
    ]
    amazon_orders_client = mocker.Mock()

    result = find_amazon_transactions(
        ynab_client, amazon_transactions_client, amazon_orders_client, "budget-1"
    )

    assert result["matches"] == []
    assert len(result["ambiguous"]) == 1
    ambiguous = result["ambiguous"][0]
    assert ambiguous["ynab_transaction"]["id"] == "y1"
    assert len(ambiguous["candidates"]) == 2
    order_numbers = {c["order_number"] for c in ambiguous["candidates"]}
    assert order_numbers == {"333-1111111", "333-2222222"}


def test_find_amazon_transactions_translates_auth_error(mocker: MockerFixture) -> None:
    """An expired Amazon session surfaces as a ToolError with remediation."""
    ynab_client = mocker.Mock()
    mocker.patch(
        "ynab_mcp.tools.find_amazon_transactions.list_transactions",
        return_value=[_ynab_txn(mocker, "y1", -3000, date(2026, 6, 5), "Amazon.com")],
    )
    amazon_transactions_client = mocker.Mock()
    amazon_transactions_client.get_transactions.side_effect = AmazonOrdersAuthError(
        "expired"
    )
    amazon_orders_client = mocker.Mock()

    with raises(ToolError, match="scripts/amazon_login.py"):
        find_amazon_transactions(
            ynab_client, amazon_transactions_client, amazon_orders_client, "budget-1"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_find_amazon_transactions.py -v`
Expected: `ModuleNotFoundError: No module named 'ynab_mcp.tools.find_amazon_transactions'`.

- [ ] **Step 3: Write the implementation**

Create `src/ynab_mcp/tools/find_amazon_transactions.py`:

```python
"""find-amazon-transactions tool: match YNAB transactions to Amazon orders."""

from datetime import date

import ynab
from amazonorders.entity.order import Order
from amazonorders.entity.transaction import Transaction
from amazonorders.exception import AmazonOrdersError
from amazonorders.orders import AmazonOrders
from amazonorders.transactions import AmazonTransactions
from fastmcp import FastMCP

from ynab_mcp.amazon_matching import AmazonCandidate, YnabCandidate, match_transactions
from ynab_mcp.client import resolve_budget_id
from ynab_mcp.config import Settings
from ynab_mcp.errors import translate_amazon_exception
from ynab_mcp.tools.transactions import list_transactions

_AMAZON_PAYEE_MARKERS = ("amazon", "amzn")
_WHOLE_FOODS_MARKER = "whole foods"
_DEFAULT_LOOKBACK_DAYS = 365


def _is_amazon_like_payee(payee_name: str | None) -> bool:
    """Return whether a YNAB payee name looks like an Amazon charge."""
    if payee_name is None:
        return False
    lowered = payee_name.lower()
    return any(marker in lowered for marker in _AMAZON_PAYEE_MARKERS)


def _is_whole_foods_transaction(transaction: Transaction) -> bool:
    """Return whether an Amazon transaction is a Whole Foods charge."""
    return _WHOLE_FOODS_MARKER in transaction.seller.lower()


def _amount_to_milliunits(grand_total: float) -> int:
    """Convert an Amazon dollar amount into signed YNAB milliunits.

    The ``amazon-orders`` library already signs ``grand_total`` to match
    YNAB's own convention: negative for a purchase/charge (an outflow),
    positive for a refund. No sign flip is needed here -- only unit
    conversion (dollars to milliunits), routed through a cents-rounding
    intermediate to avoid float imprecision.
    """
    cents = round(grand_total * 100)
    return cents * 10


def _lookback_days(since_date: date | None, date_window_days: int) -> int:
    """Compute how many days of Amazon transaction history to fetch.

    Note: ``until_date`` is not used to bound this Amazon-side fetch --
    only ``since_date`` is. When ``since_date`` is unset, the default
    365-day Amazon lookback may miss older Amazon-payee YNAB transactions.
    """
    if since_date is None:
        return _DEFAULT_LOOKBACK_DAYS
    elapsed = (date.today() - since_date).days + date_window_days
    return max(elapsed, 1)


def _build_reasoning(
    classification: str,
    order_number: str,
    order: Order | None,
    date_window_days: int,
    same_day: bool,
) -> str:
    """Build a human-readable reasoning string for a match."""
    item_titles = ", ".join(item.title for item in order.items[:3]) if order else ""
    suffix = f" ({item_titles})" if item_titles else ""
    if classification == "exact":
        return f"Exact amount+date match against Amazon order #{order_number}{suffix}."
    if classification == "near-date":
        return (
            f"Amount match against Amazon order #{order_number} within "
            f"{date_window_days} days{suffix}."
        )
    same_day_desc = "same-day" if same_day else "on a nearby date"
    return (
        f"One leg of a split-shipment Amazon order #{order_number}, "
        f"charged {same_day_desc}{suffix}."
    )


def _serialize_amazon_transaction(transaction: Transaction) -> dict[str, object]:
    """Serialize an Amazon transaction into a JSON-safe dict."""
    return {
        "order_number": transaction.order_number,
        "completed_date": transaction.completed_date.isoformat(),
        "grand_total": transaction.grand_total,
        "payment_method": transaction.payment_method,
        "seller": transaction.seller,
        "is_refund": transaction.is_refund,
    }


def find_amazon_transactions(
    ynab_client: ynab.ApiClient,
    amazon_transactions_client: AmazonTransactions,
    amazon_orders_client: AmazonOrders,
    budget_id: str,
    since_date: date | None = None,
    until_date: date | None = None,
    date_window_days: int = 3,
) -> dict[str, object]:
    """Match YNAB transactions against Amazon order/transaction history.

    Parameters
    ----------
    ynab_client : ynab.ApiClient
        A configured YNAB API client.
    amazon_transactions_client : amazonorders.transactions.AmazonTransactions
        A configured Amazon transactions client.
    amazon_orders_client : amazonorders.orders.AmazonOrders
        A configured Amazon orders client, used to enrich matches with
        item-level detail.
    budget_id : str
        The YNAB budget id.
    since_date : datetime.date | None, optional
        Only consider YNAB transactions on or after this date, by default
        ``None``.
    until_date : datetime.date | None, optional
        Only consider YNAB transactions on or before this date, by default
        ``None``.
    date_window_days : int, optional
        Maximum number of days apart a YNAB and Amazon date may be and
        still count as a match, by default ``3``.

    Returns
    -------
    dict[str, object]
        ``{"matches": [...], "ambiguous": [...], "unmatched": [...]}``. No
        categorization is written back to YNAB -- this tool only proposes.

    Raises
    ------
    fastmcp.exceptions.ToolError
        If the Amazon session is missing/expired or another
        ``amazon-orders`` request fails, or if the YNAB API request fails.
    """
    ynab_transactions = list_transactions(
        ynab_client, budget_id, since_date=since_date, until_date=until_date
    )
    amazon_like_txns = [t for t in ynab_transactions if _is_amazon_like_payee(t.payee_name)]
    ynab_by_id = {t.id: t for t in amazon_like_txns}
    ynab_candidates = [
        YnabCandidate(transaction_id=t.id, amount=t.amount, txn_date=t.var_date)
        for t in amazon_like_txns
    ]

    try:
        raw_amazon_transactions = amazon_transactions_client.get_transactions(
            days=_lookback_days(since_date, date_window_days)
        )
    except AmazonOrdersError as exc:
        raise translate_amazon_exception(exc) from exc

    filtered_amazon_transactions = [
        t
        for t in raw_amazon_transactions
        if not t.is_refund and not _is_whole_foods_transaction(t)
    ]
    amazon_by_ref = {
        f"{t.order_number}:{i}": t for i, t in enumerate(filtered_amazon_transactions)
    }
    amazon_candidates = [
        AmazonCandidate(
            transaction_ref=ref,
            order_number=t.order_number,
            amount=_amount_to_milliunits(t.grand_total),
            txn_date=t.completed_date,
        )
        for ref, t in amazon_by_ref.items()
    ]

    result = match_transactions(ynab_candidates, amazon_candidates, date_window_days)

    orders_cache: dict[str, Order] = {}

    def _order_for(order_number: str) -> Order:
        if order_number not in orders_cache:
            try:
                orders_cache[order_number] = amazon_orders_client.get_order(order_number)
            except AmazonOrdersError as exc:
                raise translate_amazon_exception(exc) from exc
        return orders_cache[order_number]

    matches_out: list[dict[str, object]] = []
    for match in result.matches:
        order = _order_for(match.order_number)
        matches_out.append(
            {
                "ynab_transaction": ynab_by_id[match.ynab_transaction_id].model_dump(
                    mode="json"
                ),
                "amazon_transaction": _serialize_amazon_transaction(
                    amazon_by_ref[match.amazon_transaction_ref]
                ),
                "order_number": match.order_number,
                "classification": match.classification,
                "reasoning": _build_reasoning(
                    match.classification,
                    match.order_number,
                    order,
                    date_window_days,
                    match.same_day,
                ),
                "same_day": match.same_day,
                "split_group": match.split_group,
            }
        )

    ambiguous_out: list[dict[str, object]] = []
    for ambiguous in result.ambiguous:
        candidates_out = [
            {
                "amazon_transaction": _serialize_amazon_transaction(amazon_by_ref[ref]),
                "order_number": amazon_by_ref[ref].order_number,
            }
            for ref in ambiguous.candidate_refs
        ]
        ambiguous_out.append(
            {
                "ynab_transaction": ynab_by_id[ambiguous.ynab_transaction_id].model_dump(
                    mode="json"
                ),
                "candidates": candidates_out,
                "reasoning": (
                    f"{len(candidates_out)} Amazon transaction(s) tie for this "
                    "amount within the date window."
                ),
            }
        )

    unmatched_out: list[dict[str, object]] = []
    for transaction_id in result.unmatched:
        unmatched_out.append(
            {
                "ynab_transaction": ynab_by_id[transaction_id].model_dump(mode="json"),
                "reasoning": "No Amazon transaction found in range.",
            }
        )

    return {
        "matches": matches_out,
        "ambiguous": ambiguous_out,
        "unmatched": unmatched_out,
    }


def register(
    mcp: FastMCP,
    ynab_client: ynab.ApiClient,
    amazon_transactions_client: AmazonTransactions,
    amazon_orders_client: AmazonOrders,
    settings: Settings,
) -> None:
    """Register the ``find-amazon-transactions`` tool on ``mcp``.

    Parameters
    ----------
    mcp : fastmcp.FastMCP
        The server to register the tool on.
    ynab_client : ynab.ApiClient
        A configured YNAB API client.
    amazon_transactions_client : amazonorders.transactions.AmazonTransactions
        A configured Amazon transactions client.
    amazon_orders_client : amazonorders.orders.AmazonOrders
        A configured Amazon orders client.
    settings : Settings
        The server's parsed configuration, used to resolve a default budget
        id when the caller omits one.
    """

    @mcp.tool(name="find-amazon-transactions")
    def find_amazon_transactions_tool(
        budget_id: str | None = None,
        since_date: date | None = None,
        until_date: date | None = None,
        date_window_days: int = 3,
    ) -> dict[str, object]:
        """Match YNAB transactions against Amazon order/transaction history.

        Proposes matches with confidence/reasoning; never writes a
        categorization back to YNAB.

        Parameters
        ----------
        budget_id : str | None, optional
            The YNAB budget id, by default ``None`` (falls back to
            ``YNAB_DEFAULT_BUDGET_ID``).
        since_date : datetime.date | None, optional
            Only consider YNAB transactions on or after this date, by
            default ``None``.
        until_date : datetime.date | None, optional
            Only consider YNAB transactions on or before this date, by
            default ``None``.
        date_window_days : int, optional
            Maximum number of days apart a YNAB and Amazon date may be and
            still count as a match, by default ``3``.
        """
        resolved_budget_id = resolve_budget_id(budget_id, settings)
        return find_amazon_transactions(
            ynab_client,
            amazon_transactions_client,
            amazon_orders_client,
            resolved_budget_id,
            since_date=since_date,
            until_date=until_date,
            date_window_days=date_window_days,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_find_amazon_transactions.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Lint**

Run: `uv run black --check src/ynab_mcp/tools/find_amazon_transactions.py tests/test_tools_find_amazon_transactions.py && uv run ruff check src/ynab_mcp/tools/find_amazon_transactions.py tests/test_tools_find_amazon_transactions.py && uv run mypy`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/ynab_mcp/tools/find_amazon_transactions.py tests/test_tools_find_amazon_transactions.py
git commit -m "feat: add find-amazon-transactions tool"
```

---

### Task 8: `server.py` — conditional registration

**Files:**
- Modify: `src/ynab_mcp/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `AmazonSettings` (Task 3), `build_amazon_session`/`build_amazon_orders`/`build_amazon_transactions` (Task 5), `find_amazon_transactions.register` (Task 7).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_server.py`:

```python
def test_build_server_registers_find_amazon_transactions_when_configured(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    """The Amazon tool is registered when Amazon credentials are set."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("YNAB_PAT", "test-token")
    monkeypatch.setenv("YNAB_DEFAULT_BUDGET_ID", "budget-123")
    monkeypatch.setenv("AMAZON_USERNAME", "user@example.com")
    monkeypatch.setenv("AMAZON_PASSWORD", "hunter2")
    monkeypatch.delenv("AMAZON_OTP_SECRET_KEY", raising=False)
    mocker.patch("ynab_mcp.server.build_amazon_session")
    mocker.patch("ynab_mcp.server.build_amazon_orders")
    mocker.patch("ynab_mcp.server.build_amazon_transactions")

    mcp = build_server()

    tool_names = _list_tool_names(mcp)
    assert "find-amazon-transactions" in tool_names


def test_build_server_omits_find_amazon_transactions_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Amazon tool is absent when Amazon credentials are unset."""
    monkeypatch.setattr("ynab_mcp.config.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("YNAB_PAT", "test-token")
    monkeypatch.setenv("YNAB_DEFAULT_BUDGET_ID", "budget-123")
    monkeypatch.delenv("AMAZON_USERNAME", raising=False)
    monkeypatch.delenv("AMAZON_PASSWORD", raising=False)

    mcp = build_server()

    tool_names = _list_tool_names(mcp)
    assert "find-amazon-transactions" not in tool_names
```

Add `from pytest_mock import MockerFixture` to `tests/test_server.py`'s imports if not already present.

Also update the existing `test_build_server_registers_all_other_tools` test's final assertion set — it currently asserts an exact `tool_names ==` set. Since that test doesn't set Amazon env vars, `find-amazon-transactions` will correctly stay absent and the existing assertion doesn't need to change, but double check by re-reading `tests/test_server.py` after this edit that no Amazon env vars leak in from a prior test in the same process (pytest-xdist runs tests in separate workers/processes per file typically, but `monkeypatch` already scopes env vars per-test regardless).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_server.py -v`
Expected: `test_build_server_registers_find_amazon_transactions_when_configured` FAILS (tool not found); `test_build_server_omits_find_amazon_transactions_when_unconfigured` currently PASSES vacuously (tool doesn't exist yet at all) but will be a meaningful regression guard once Task 8 Step 3 lands.

- [ ] **Step 3: Write the implementation**

In `src/ynab_mcp/server.py`, update the imports:

```python
from fastmcp import FastMCP

from ynab_mcp.amazon_client import (
    build_amazon_orders,
    build_amazon_session,
    build_amazon_transactions,
)
from ynab_mcp.client import build_api_client
from ynab_mcp.config import AmazonSettings, Settings
from ynab_mcp.tools import (
    accounts,
    budgets,
    categories,
    find_amazon_transactions,
    lookup,
    months,
    payees,
    transactions,
)
```

And update `build_server()`:

```python
def build_server() -> FastMCP:
    """Build and wire the YNAB MCP server.

    Reads configuration from the environment, constructs a shared YNAB API
    client, and registers every read-only tool. ``list-budgets`` is
    registered only when no default budget is configured.
    ``find-amazon-transactions`` is registered only when Amazon credentials
    (``AMAZON_USERNAME``/``AMAZON_PASSWORD``) are configured.

    Returns
    -------
    fastmcp.FastMCP
        A fully configured server, ready to run over stdio.

    Raises
    ------
    RuntimeError
        If ``YNAB_PAT`` is not configured.
    """
    settings = Settings.from_env()
    client = build_api_client(settings)
    mcp = FastMCP("ynab-mcp")

    if settings.ynab_default_budget_id is None:
        budgets.register(mcp, client)
    accounts.register(mcp, client, settings)
    categories.register(mcp, client, settings)
    transactions.register(mcp, client, settings)
    months.register(mcp, client, settings)
    payees.register(mcp, client, settings)
    lookup.register(mcp, client, settings)

    amazon_settings = AmazonSettings.from_env()
    if amazon_settings is not None:
        amazon_session = build_amazon_session(amazon_settings)
        amazon_orders_client = build_amazon_orders(amazon_session)
        amazon_transactions_client = build_amazon_transactions(amazon_session)
        find_amazon_transactions.register(
            mcp, client, amazon_transactions_client, amazon_orders_client, settings
        )

    return mcp
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_server.py -v`
Expected: all tests PASS, including both new Amazon-related tests.

- [ ] **Step 5: Lint**

Run: `uv run black --check src/ynab_mcp/server.py tests/test_server.py && uv run ruff check src/ynab_mcp/server.py tests/test_server.py && uv run mypy`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/ynab_mcp/server.py tests/test_server.py
git commit -m "feat: conditionally register find-amazon-transactions on the server"
```

---

### Task 9: Full verification pass

**Files:** none (verification only).

**Interfaces:** none.

- [ ] **Step 1: Run the full lint + test gate**

Run: `make pr_check`
Expected: exit code 0 — black/ruff/mypy clean, all tests (including the pre-existing 46 plus every new test added in Tasks 2–8) pass.

- [ ] **Step 2: Run coverage**

Run: `make coverage`
Expected: exit code 0, coverage stays at or above the 80% gate.

- [ ] **Step 3: Run bandit security scan**

Run: `make security`
Expected: exit code 0, no new findings introduced by `amazon_client.py`, `amazon_matching.py`, or `tools/find_amazon_transactions.py`.

- [ ] **Step 4: Spot-check the server still builds YNAB-only when Amazon is unconfigured**

Run: `uv run python -c "
import os
os.environ['YNAB_PAT'] = 'fake-token-for-smoke-test'
os.environ.pop('AMAZON_USERNAME', None)
os.environ.pop('AMAZON_PASSWORD', None)
from ynab_mcp.server import build_server
mcp = build_server()
print('server built OK, no Amazon credentials required')
"`
Expected: prints the success message with no exception.

No commit for this task — it's a verification checkpoint. If any step fails, return to the relevant earlier task and fix it via a new failing test (TDD RED), not by patching code without a test.
