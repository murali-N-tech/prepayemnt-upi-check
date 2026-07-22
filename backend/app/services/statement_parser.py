from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

import pandas as pd

# pdfplumber is the primary PDF extractor; pypdf kept as last-resort fallback
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False


# ═══════════════════════════════════════════════════════════════════════════
# 0. DOUBLE-STRUCK TEXT FIX
# Some statement generators (PhonePe among them) render every glyph twice,
# stacked, to fake bold text. pdfplumber then extracts each character twice
# in a row: "Transaction" -> "TTrraannssaaccttiioonn". We detect and fix.
# ═══════════════════════════════════════════════════════════════════════════

def _looks_double_struck(text: str) -> bool:
    sample = text[:3000]
    alnum_positions = [i for i, c in enumerate(sample[:-1]) if c.isalnum()]
    if len(alnum_positions) < 20:
        return False
    doubled = sum(1 for i in alnum_positions if sample[i] == sample[i + 1])
    return (doubled / len(alnum_positions)) > 0.4


def _fix_double_struck(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if i + 1 < n and text[i] == text[i + 1]:
            out.append(text[i])
            i += 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _normalize_text(text: str) -> str:
    if text and _looks_double_struck(text):
        return _fix_double_struck(text)
    return text


# ═══════════════════════════════════════════════════════════════════════════
# 1. PATTERNS
# ═══════════════════════════════════════════════════════════════════════════

_DATE_PATTERNS_STR = [
    r"\d{2}[-/]\d{2}[-/]\d{2,4}",       # 12-04-2024, 12/04/24
    r"\d{2}\s?[A-Za-z]{3,9}\s?\d{2,4}",  # 12 Apr 2024, 12Apr2024
    r"\d{4}[-/]\d{2}[-/]\d{2}",          # 2024-04-12
]
_DATE_RE = re.compile("(" + "|".join(_DATE_PATTERNS_STR) + ")")

_AMOUNT_RE = re.compile(
    r"(?<![\w.])[₹Rs\.]*\s*(-?\d+(?:,\d+)*(?:\.\d{1,2})?)\s*(Dr|Cr|DR|CR)?(?![\w])"
)
_UPI_REF_RE = re.compile(r"(\d{10,12})(?!\d)")
_VPA_RE = re.compile(r"\b[\w.]+@[a-zA-Z]{2,}\b")
_UPI_KEYWORDS_RE = re.compile(
    r"\bUPI\b|@ok[a-z]*|@yb[a-z]*|@paytm|@ibl|@sbi|@icici|@axis|@hdfc|@ptaxis|"
    r"@ptsbi|@apl|@axl|IMPS|NEFT|RTGS",
    re.IGNORECASE,
)
_DEBIT_HINTS = re.compile(r"\bdebit|withdraw|paid|sent|dr\b|debited", re.IGNORECASE)
_CREDIT_HINTS = re.compile(r"\bcredit|deposit|received|cr\b|credited", re.IGNORECASE)

# For the legacy line-based / provider-detection parsers (kept as fallback)
DATE_PATTERNS = [
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y %I:%M %p",
    "%d/%m/%Y %I:%M:%S %p", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M",
    "%d-%m-%Y %I:%M %p", "%d-%m-%Y %I:%M:%S %p", "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p", "%Y-%m-%d %I:%M:%S %p",
    "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d",
    "%d %b %Y %I:%M %p", "%d %b %Y %H:%M", "%d %B %Y %I:%M %p",
    "%d %B %Y %H:%M", "%d %b %Y", "%d %B %Y",
    "%b %d %Y %I:%M %p", "%B %d %Y %I:%M %p", "%b %d %Y", "%B %d %Y",
]
DATE_RE = re.compile(
    r"\b("
    r"\d{2}[/-]\d{2}[/-]\d{4}"
    r"|"
    r"\d{4}[/-]\d{2}[/-]\d{2}"
    r"|"
    r"\d{1,2}\s+(?:Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|September|Oct|October|Nov|November|Dec|December)\s+\d{4}"
    r"|"
    r"(?:Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|September|Oct|October|Nov|November|Dec|December)\s+\d{1,2},?\s+\d{4}"
    r")\b",
    re.IGNORECASE,
)
TIME_RE = re.compile(r"\b(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm)?)\b")
AMOUNT_RE = re.compile(r"(?:₹|Rs\.?|INR)?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
UPI_RE = re.compile(r"\b([A-Za-z0-9._-]{2,}@[A-Za-z]{2,})\b")
REF_RE = re.compile(
    r"(?i)\b(?:utr|ref(?:erence)?|txn(?: id)?|transaction(?: id)?|upi ref(?:erence)?(?: no)?|bank ref(?:erence)?(?: no)?|google transaction id|phonepe transaction id)\s*[:#-]?\s*([A-Za-z0-9-]{6,})\b"
)
STATUS_RE = re.compile(r"(?i)\b(success|successful|failed|failure|pending|declined)\b")
UPI_HINT_RE = re.compile(r"(?i)\b(upi|vpa|utr|txn|transaction|debited|credited|paid|received|payment)\b")


# ═══════════════════════════════════════════════════════════════════════════
# 2. INTERNAL TRANSACTION DATACLASS (used by pdfplumber extractors)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class _Transaction:
    date: Optional[str] = None
    description: str = ""
    debit: Optional[float] = None
    credit: Optional[float] = None
    balance: Optional[float] = None
    is_upi: bool = False
    upi_ref: Optional[str] = None
    vpa: Optional[str] = None
    txn_type: Optional[str] = None
    source_file: str = ""
    raw_line: str = ""


def _clean_amount(s: str) -> Optional[float]:
    if not s:
        return None
    s = s.replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date_plumber(s: str) -> Optional[str]:
    s = s.strip()
    fmts = [
        "%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y",
        "%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%d %B %Y",
        "%d-%b-%Y", "%d-%b-%y", "%b %d %Y", "%B %d %Y",
    ]
    for f in fmts:
        try:
            return datetime.strptime(s, f).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s


# ═══════════════════════════════════════════════════════════════════════════
# 3. PDFPLUMBER EXTRACTION STRATEGIES
# ═══════════════════════════════════════════════════════════════════════════

# 3a. TABLE-BASED EXTRACTION (most bank PDFs with real tables)

def _extract_from_tables(pdf: "pdfplumber.PDF", source_name: str) -> List[_Transaction]:
    txns: List[_Transaction] = []
    for page in pdf.pages:
        tables = page.extract_tables()
        for table in tables:
            if not table or len(table) < 2:
                continue
            table = [[_normalize_text(str(c) if c is not None else "") for c in row] for row in table]
            header = [str(c or "").strip().lower() for c in table[0]]

            date_idx = next((i for i, h in enumerate(header) if "date" in h), None)
            if date_idx is None:
                continue

            desc_idx = next((i for i, h in enumerate(header)
                              if any(k in h for k in ("narration", "description", "particular", "detail", "remark"))), None)
            debit_idx = next((i for i, h in enumerate(header)
                               if any(k in h for k in ("debit", "withdrawal"))), None)
            credit_idx = next((i for i, h in enumerate(header)
                                if any(k in h for k in ("credit", "deposit"))), None)
            balance_idx = next((i for i, h in enumerate(header) if "balance" in h), None)
            amount_idx = next((i for i, h in enumerate(header)
                                if "amount" in h and i not in (debit_idx, credit_idx)), None)
            type_idx = next((i for i, h in enumerate(header)
                              if h.strip() in ("type", "dr/cr", "cr/dr", "transaction type")), None)

            for row in table[1:]:
                if not row or all(c in (None, "") for c in row):
                    continue
                row = [str(c or "").strip() for c in row]

                raw_date = row[date_idx] if date_idx < len(row) else ""
                if not _DATE_RE.search(raw_date):
                    continue

                desc = row[desc_idx] if desc_idx is not None and desc_idx < len(row) else ""
                debit = _clean_amount(row[debit_idx]) if debit_idx is not None and debit_idx < len(row) else None
                credit = _clean_amount(row[credit_idx]) if credit_idx is not None and credit_idx < len(row) else None
                balance = _clean_amount(row[balance_idx]) if balance_idx is not None and balance_idx < len(row) else None

                if amount_idx is not None and debit is None and credit is None:
                    amt = _clean_amount(row[amount_idx]) if amount_idx < len(row) else None
                    ttype = row[type_idx].upper() if type_idx is not None and type_idx < len(row) else ""
                    if amt is not None:
                        if "CR" in ttype or "CREDIT" in ttype or _CREDIT_HINTS.search(desc):
                            credit = abs(amt)
                        else:
                            debit = abs(amt)

                full_line = " ".join(row)
                vpa_match = _VPA_RE.search(full_line)
                ref_match = _UPI_REF_RE.search(full_line)
                is_upi = bool(_UPI_KEYWORDS_RE.search(full_line))

                txn_type = None
                if debit and debit > 0:
                    txn_type = "DEBIT"
                elif credit and credit > 0:
                    txn_type = "CREDIT"

                txns.append(_Transaction(
                    date=_parse_date_plumber(raw_date),
                    description=desc,
                    debit=debit,
                    credit=credit,
                    balance=balance,
                    is_upi=is_upi,
                    upi_ref=(ref_match.group(1) if ref_match else None),
                    vpa=(vpa_match.group(0) if vpa_match else None),
                    txn_type=txn_type,
                    source_file=source_name,
                    raw_line=full_line,
                ))
    return txns


# 3b. TEXT-LINE EXTRACTION (PDFs with no real tables, one txn per line)

def _extract_from_text(pdf: "pdfplumber.PDF", source_name: str) -> List[_Transaction]:
    txns: List[_Transaction] = []
    for page in pdf.pages:
        text = _normalize_text(page.extract_text() or "")
        for line in text.split("\n"):
            line = line.strip()
            date_match = _DATE_RE.search(line)
            if not date_match:
                continue
            amounts = _AMOUNT_RE.findall(line)
            if not amounts:
                continue

            desc = line[date_match.end():].strip()
            vpa_match = _VPA_RE.search(line)
            ref_match = _UPI_REF_RE.search(line)
            is_upi = bool(_UPI_KEYWORDS_RE.search(line))

            debit = credit = balance = None
            nums = [(_clean_amount(a), tag.upper()) for a, tag in amounts if _clean_amount(a) is not None]

            if nums:
                balance = nums[-1][0]
                txn_amounts = nums[:-1] if len(nums) > 1 else nums
                for val, tag in txn_amounts:
                    if tag == "DR" or _DEBIT_HINTS.search(desc):
                        debit = abs(val)
                    elif tag == "CR" or _CREDIT_HINTS.search(desc):
                        credit = abs(val)
                if debit is None and credit is None and txn_amounts:
                    val = txn_amounts[0][0]
                    if _CREDIT_HINTS.search(desc):
                        credit = abs(val)
                    else:
                        debit = abs(val)

            txn_type = "DEBIT" if debit else ("CREDIT" if credit else None)

            txns.append(_Transaction(
                date=_parse_date_plumber(date_match.group(0)),
                description=desc,
                debit=debit,
                credit=credit,
                balance=balance,
                is_upi=is_upi,
                upi_ref=(ref_match.group(1) if ref_match else None),
                vpa=(vpa_match.group(0) if vpa_match else None),
                txn_type=txn_type,
                source_file=source_name,
                raw_line=line,
            ))
    return txns


# 3c. MULTI-LINE BLOCK EXTRACTION (PhonePe/GPay/Paytm app statements)

_BLOCK_DATE_RE = re.compile(r"^([A-Za-z]{3}\s\d{1,2},?\s\d{4})\b")
_BLOCK_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\s?[AP]M\b")
_BLOCK_TYPE_RE = re.compile(r"\b(DEBIT|CREDIT)\b", re.IGNORECASE)
_BLOCK_AMOUNT_RE = re.compile(r"₹\s?(-?\d[\d,]*\.?\d*)")
_BLOCK_TXNID_RE = re.compile(r"Transaction\s*ID[:\s]*([A-Za-z0-9]+)", re.IGNORECASE)
_BLOCK_UTR_RE = re.compile(r"UTR\s*No\.?[:\s]*([A-Za-z0-9]+)", re.IGNORECASE)
_BLOCK_ACCT_RE = re.compile(r"\b(?:Paid by|Credited to|Debited from|Paid from)[:\s]*([A-Za-z0-9]+)", re.IGNORECASE)
_BLOCK_PAIDTO_RE = re.compile(r"\b(?:Paid to|Received from|Paid by|Credited to|Debited from)\b", re.IGNORECASE)

_JUNK_LINE_RE = re.compile(
    r"^(Transaction\s+)?Statement\s+for\b"
    r"|^\d{1,2}\s[A-Za-z]{3},?\s\d{4}\s*-\s*\d{1,2}\s[A-Za-z]{3},?\s\d{4}$"
    r"|^Date\s+Transaction\s+Details?\s+Type\s+Amount$"
    r"|^Page\s+\d+\s+of\s+\d+$",
    re.IGNORECASE,
)


def _extract_from_app_blocks(pdf: "pdfplumber.PDF", source_name: str) -> List[_Transaction]:
    all_lines: List[str] = []
    for page in pdf.pages:
        raw = _normalize_text(page.extract_text() or "")
        for line in raw.split("\n"):
            line = line.strip()
            if not line or _JUNK_LINE_RE.match(line):
                continue
            all_lines.append(line)

    blocks: List[List[str]] = []
    current: List[str] = []
    for line in all_lines:
        if _BLOCK_DATE_RE.match(line):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append(current)

    txns: List[_Transaction] = []
    for block_lines in blocks:
        block_text = " ".join(block_lines)
        date_m = _BLOCK_DATE_RE.match(block_lines[0])
        type_m = _BLOCK_TYPE_RE.search(block_text)
        amount_m = _BLOCK_AMOUNT_RE.search(block_text)
        if not date_m or not type_m or not amount_m:
            continue

        amount = _clean_amount(amount_m.group(1))
        ttype = type_m.group(1).upper()
        debit = amount if ttype == "DEBIT" else None
        credit = amount if ttype == "CREDIT" else None

        txn_id_m = _BLOCK_TXNID_RE.search(block_text)
        utr_m = _BLOCK_UTR_RE.search(block_text)
        vpa_m = _VPA_RE.search(block_text)

        desc = block_text
        desc = _BLOCK_DATE_RE.sub("", desc, count=1)
        desc = _BLOCK_TIME_RE.sub("", desc)
        desc = _BLOCK_TYPE_RE.sub("", desc)
        desc = _BLOCK_AMOUNT_RE.sub("", desc)
        desc = _BLOCK_TXNID_RE.sub("", desc)
        desc = _BLOCK_UTR_RE.sub("", desc)
        desc = _BLOCK_ACCT_RE.sub("", desc)
        desc = _BLOCK_PAIDTO_RE.sub("", desc)
        desc = re.sub(r"\s+", " ", desc).strip(" .-")

        txns.append(_Transaction(
            date=_parse_date_plumber(date_m.group(1).replace(",", "")),
            description=desc,
            debit=debit,
            credit=credit,
            balance=None,
            is_upi=True,
            upi_ref=(txn_id_m.group(1) if txn_id_m else (utr_m.group(1) if utr_m else None)),
            vpa=(vpa_m.group(0) if vpa_m else None),
            txn_type=ttype,
            source_file=source_name,
            raw_line=block_text,
        ))
    return txns


# 3d. GOOGLE PAY BLOCK EXTRACTION (collapsed-space text)

_GPAY_DATE_RE = re.compile(r"^(\d{2}[A-Za-z]{3},\d{4})\b")
_GPAY_TXN_RE = re.compile(
    r"^\d{2}[A-Za-z]{3},\d{4}\s+(Paidto|Receivedfrom)(.+?)\s*₹\s?(-?[\d,]+\.?\d*)",
    re.IGNORECASE,
)
_GPAY_TXNID_RE = re.compile(r"UPITransactionID:?\s*(\w+)", re.IGNORECASE)

_GPAY_JUNK_RE = re.compile(
    r"^Transaction\s*statement$"
    r"|^\d{7,}.*@"
    r"|^Transactionstatementperiod"
    r"|^\d{2}[A-Za-z]{3,9}\d{4}\s*-\s*\d{2}[A-Za-z]{3,9}\d{4}"
    r"|^Date&time"
    r"|^Note:"
    r"|^received\."
    r"|GooglePay"
    r"|^Page\d+of\d+$",
    re.IGNORECASE,
)


def _extract_from_gpay_blocks(pdf: "pdfplumber.PDF", source_name: str) -> List[_Transaction]:
    all_lines: List[str] = []
    for page in pdf.pages:
        raw = _normalize_text(page.extract_text() or "")
        for line in raw.split("\n"):
            line = line.strip()
            if not line or _GPAY_JUNK_RE.search(line):
                continue
            all_lines.append(line)

    blocks: List[List[str]] = []
    current: List[str] = []
    for line in all_lines:
        if _GPAY_DATE_RE.match(line):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append(current)

    txns: List[_Transaction] = []
    for block_lines in blocks:
        block_text = " ".join(block_lines)
        m = _GPAY_TXN_RE.match(block_text)
        date_m = _GPAY_DATE_RE.match(block_lines[0])
        if not m or not date_m:
            continue

        direction = m.group(1).lower()
        name = re.sub(r"\s+", " ", m.group(2)).strip()
        amount = _clean_amount(m.group(3))
        ttype = "DEBIT" if direction == "paidto" else "CREDIT"
        debit = amount if ttype == "DEBIT" else None
        credit = amount if ttype == "CREDIT" else None

        txn_id_m = _GPAY_TXNID_RE.search(block_text)

        # "01Apr,2026" -> "01 Apr 2026"
        date_norm = re.sub(r"^(\d{2})([A-Za-z]{3}),(\d{4})$", r"\1 \2 \3", date_m.group(1))

        txns.append(_Transaction(
            date=_parse_date_plumber(date_norm),
            description=name,
            debit=debit,
            credit=credit,
            balance=None,
            is_upi=True,
            upi_ref=(txn_id_m.group(1) if txn_id_m else None),
            vpa=None,
            txn_type=ttype,
            source_file=source_name,
            raw_line=block_text,
        ))
    return txns


# ═══════════════════════════════════════════════════════════════════════════
# 4. CONVERT _Transaction -> dict (match existing API format)
# ═══════════════════════════════════════════════════════════════════════════

def _txn_to_dict(t: _Transaction) -> dict[str, Any]:
    """Convert internal dataclass to the dict format expected by the rest of the app."""
    amount = 0.0
    if t.debit and t.debit > 0:
        amount = t.debit
    elif t.credit and t.credit > 0:
        amount = t.credit

    # Build timestamp: date + optional time
    timestamp = t.date or datetime.utcnow().strftime("%Y-%m-%d")
    if "T" not in timestamp and len(timestamp) == 10:
        timestamp += "T12:00:00"

    return {
        "timestamp": _normalize_timestamp(timestamp),
        "amount": amount,
        "merchant": t.description[:80] if t.description else "UNKNOWN_MERCHANT",
        "upi_id": t.vpa,
        "status": "SUCCESS",
        "reference_number": t.upi_ref,
        "raw_line": t.raw_line,
        "txn_type": t.txn_type,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5. PDFPLUMBER DRIVER — tries all strategies, picks the best
# ═══════════════════════════════════════════════════════════════════════════

def _parse_pdf_with_pdfplumber(content: bytes, source_name: str = "statement.pdf") -> dict[str, Any]:
    """Main pdfplumber-based PDF parser. Tries four extraction strategies."""
    import tempfile, os

    # pdfplumber needs a file path or file-like object
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    warnings: list[str] = []
    try:
        pdf = pdfplumber.open(tmp_path)
    except Exception as e:
        return {
            "source_type": "pdf",
            "transactions": [],
            "warnings": [f"Could not open PDF with pdfplumber: {e}"],
        }

    try:
        n_pages = len(pdf.pages)

        # Run all four strategies
        table_txns = _extract_from_tables(pdf, source_name)
        text_txns = _extract_from_text(pdf, source_name) if len(table_txns) < 2 else []
        block_txns = _extract_from_app_blocks(pdf, source_name)
        gpay_txns = _extract_from_gpay_blocks(pdf, source_name)

        print(f"  [pdfplumber] pages={n_pages} | table={len(table_txns)} | text={len(text_txns)} | blocks={len(block_txns)} | gpay={len(gpay_txns)}")

        # Pick whichever found the most transactions
        best_txns = max((table_txns, text_txns, block_txns, gpay_txns), key=len)

        # Determine which strategy won
        strategy = "unknown"
        if best_txns is table_txns:
            strategy = "table"
        elif best_txns is text_txns:
            strategy = "text-line"
        elif best_txns is block_txns:
            strategy = "app-block"
        elif best_txns is gpay_txns:
            strategy = "gpay-block"

        if best_txns:
            print(f"  [pdfplumber] Using strategy: {strategy} ({len(best_txns)} transactions)")

        # De-duplicate
        seen: set[tuple] = set()
        unique: list[_Transaction] = []
        for t in best_txns:
            key = (t.date, t.description, t.debit, t.credit, t.balance)
            if key not in seen:
                seen.add(key)
                unique.append(t)

        # Convert to output dict format
        transactions = [_txn_to_dict(t) for t in unique]

        if not transactions:
            warnings.append(
                f"pdfplumber extracted text from {n_pages} pages but no extraction strategy matched any transactions."
            )

        return {
            "source_type": f"pdf_pdfplumber_{strategy}",
            "transactions": transactions,
            "warnings": warnings,
        }
    finally:
        pdf.close()
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# 6. LEGACY PYPDF FALLBACK (kept from original code)
# ═══════════════════════════════════════════════════════════════════════════

PROVIDER_SIGNATURES: dict[str, tuple[str, ...]] = {
    "phonepe": ("phonepe", "phone pe", "phonepe private limited"),
    "google_pay": ("google pay", "gpay", "tez"),
    "paytm": ("paytm", "paytm payments bank", "paytm upi"),
    "bhim": ("bhim", "bharat interface for money", "npci bhim"),
    "sbi": ("state bank of india", "sbi", "yono", "sbipg"),
    "bank_of_baroda": ("bank of baroda", "bob world", "baroda"),
    "hdfc": ("hdfc bank", "hdfc"),
    "icici": ("icici bank", "icici"),
    "axis": ("axis bank", "axis mobile", "axis"),
}

PROVIDER_LABELS = {
    "phonepe": "PhonePe",
    "google_pay": "Google Pay",
    "paytm": "Paytm",
    "bhim": "BHIM",
    "sbi": "State Bank of India",
    "bank_of_baroda": "Bank of Baroda",
    "hdfc": "HDFC Bank",
    "icici": "ICICI Bank",
    "axis": "Axis Bank",
}


def _parse_pdf_with_pypdf(content: bytes) -> dict[str, Any]:
    """Legacy pypdf-based parser (kept as fallback)."""
    reader = PdfReader(io.BytesIO(content))
    text_fragments: list[str] = []

    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text.strip():
            text_fragments.append(page_text)

    full_text = "\n".join(text_fragments)
    warnings: list[str] = []

    if not full_text.strip():
        return {
            "source_type": "pdf",
            "transactions": [],
            "warnings": [
                "No extractable text found in the PDF. If this is a scanned statement, add OCR tooling such as Tesseract."
            ],
        }

    lines = [line.strip() for line in full_text.splitlines() if line.strip()]
    provider = _detect_pdf_provider(full_text)
    transactions: list[dict[str, Any]] = []

    if provider is not None:
        transactions = _extract_provider_transactions(provider, lines, full_text)
        if not transactions:
            warnings.append(
                f"Detected a {PROVIDER_LABELS.get(provider, provider)} style statement but the provider-specific extractor did not find any complete rows. Falling back to the generic parser."
            )

    if not transactions:
        transactions = _extract_transactions_from_lines(lines)
    if not transactions:
        transactions = _extract_transactions_from_blocks(lines)

    if not transactions:
        warnings.append(
            "The PDF text was read, but no transaction rows matched the generic parser. A provider-specific extractor may be needed."
        )

    return {
        "source_type": f"pdf_{provider}" if provider is not None else "pdf",
        "transactions": transactions,
        "warnings": warnings,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 7. PUBLIC API — parse_statement_file / generate_behavior_profile
# ═══════════════════════════════════════════════════════════════════════════

def parse_statement_file(filename: str, content: bytes) -> dict[str, Any]:
    ext = Path(filename).suffix.lower()

    if ext == ".csv":
        transactions = _parse_csv_statement(content)
        return {
            "source_type": "csv",
            "transactions": transactions,
            "warnings": [],
        }

    if ext == ".pdf":
        # Strategy 1: pdfplumber (robust, handles most formats)
        if HAS_PDFPLUMBER:
            result = _parse_pdf_with_pdfplumber(content, source_name=filename)
            if result["transactions"]:
                return result
            # If pdfplumber found nothing, fall through to pypdf
            print("  [pdfplumber] No transactions found, trying pypdf fallback...")

        # Strategy 2: pypdf legacy fallback
        if HAS_PYPDF:
            result = _parse_pdf_with_pypdf(content)
            if result["transactions"]:
                return result

        # Both failed
        return {
            "source_type": "pdf",
            "transactions": [],
            "warnings": [
                "Neither pdfplumber nor pypdf could extract transactions from this PDF. "
                "It may be a scanned/image-based document requiring OCR."
            ],
        }

    raise ValueError("Unsupported file type. Upload a PDF or CSV statement.")


# ═══════════════════════════════════════════════════════════════════════════
# CSV PARSER (unchanged from original)
# ═══════════════════════════════════════════════════════════════════════════

def _parse_csv_statement(content: bytes) -> list[dict[str, Any]]:
    decoded = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(decoded))
    rows = list(reader)

    if not rows:
        return []

    records: list[dict[str, Any]] = []
    for row in rows:
        normalized = {str(k).strip().lower(): v for k, v in row.items() if k}

        date_value = None
        for k in normalized.keys():
            if any(x in k for x in ["date", "time", "timestamp"]):
                date_value = normalized[k]
                break
                
        amount_value = None
        for k in normalized.keys():
            if any(x in k for x in ["amount", "debit", "credit", "withdrawal", "deposit"]):
                amount_value = normalized[k]
                break

        merchant = "UNKNOWN_MERCHANT"
        for k in normalized.keys():
            if any(x in k for x in ["merchant", "payee", "description", "particulars", "narration", "receiver", "details"]):
                merchant = normalized[k]
                break

        upi_id = None
        for k in normalized.keys():
            if any(x in k for x in ["upi", "vpa"]):
                upi_id = normalized[k]
                break
                
        status = normalized.get("status") or "SUCCESS"
        reference = None
        for k in normalized.keys():
            if any(x in k for x in ["reference", "utr", "txn", "transaction_id"]):
                reference = normalized[k]
                break

        if not amount_value:
            continue

        records.append(
            {
                "timestamp": _normalize_timestamp(date_value),
                "amount": _normalize_amount(amount_value),
                "merchant": str(merchant).strip(),
                "upi_id": _clean_optional(upi_id),
                "status": str(status).upper(),
                "reference_number": _clean_optional(reference),
                "raw_line": str(row),
            }
        )

    return [tx for tx in records if tx["amount"] is not None]


# ═══════════════════════════════════════════════════════════════════════════
# LEGACY PYPDF HELPER FUNCTIONS (kept for fallback path)
# ═══════════════════════════════════════════════════════════════════════════

def _detect_pdf_provider(full_text: str) -> str | None:
    normalized = full_text.lower()
    for provider, signatures in PROVIDER_SIGNATURES.items():
        if any(signature in normalized for signature in signatures):
            return provider
    return None


def _extract_provider_transactions(
    provider: str,
    lines: list[str],
    full_text: str,
) -> list[dict[str, Any]]:
    extractor_map = {
        "phonepe": _extract_phonepe_transactions,
        "google_pay": _extract_google_pay_transactions,
        "paytm": _extract_paytm_transactions,
        "bhim": _extract_bhim_transactions,
        "sbi": _extract_sbi_transactions,
        "bank_of_baroda": _extract_bank_of_baroda_transactions,
        "hdfc": _extract_hdfc_transactions,
        "icici": _extract_icici_transactions,
        "axis": _extract_axis_transactions,
    }
    extractor = extractor_map.get(provider)
    if extractor is None:
        return []
    return extractor(lines, full_text)


def _extract_phonepe_transactions(lines: list[str], full_text: str) -> list[dict[str, Any]]:
    keyword_groups = (
        ("phonepe", "phone pe", "paid to", "received from", "utr", "transaction id", "to", "from"),
    )
    return _extract_wallet_transactions(lines, keyword_groups, provider_name="PhonePe")


def _extract_google_pay_transactions(lines: list[str], full_text: str) -> list[dict[str, Any]]:
    keyword_groups = (
        ("google pay", "gpay", "paid to", "received from", "upi transaction id", "google transaction id", "to", "from"),
    )
    return _extract_wallet_transactions(lines, keyword_groups, provider_name="Google Pay")


def _extract_paytm_transactions(lines: list[str], full_text: str) -> list[dict[str, Any]]:
    keyword_groups = (
        ("paytm", "paytm upi", "paytm payments bank", "paid to", "money sent to", "upi ref", "to"),
    )
    return _extract_wallet_transactions(lines, keyword_groups, provider_name="Paytm")


def _extract_bhim_transactions(lines: list[str], full_text: str) -> list[dict[str, Any]]:
    keyword_groups = (
        ("bhim", "bharat interface for money", "npci", "paid to", "received from", "vpa", "utr"),
    )
    return _extract_wallet_transactions(lines, keyword_groups, provider_name="BHIM")


def _extract_sbi_transactions(lines: list[str], full_text: str) -> list[dict[str, Any]]:
    return _extract_bank_transactions(
        lines,
        bank_name="SBI",
        hint_keywords=("upi", "to transfer", "yono", "imps", "merchant"),
    )


def _extract_bank_of_baroda_transactions(lines: list[str], full_text: str) -> list[dict[str, Any]]:
    return _extract_bank_transactions(
        lines,
        bank_name="Bank of Baroda",
        hint_keywords=("upi", "bob", "transfer", "merchant", "mobile banking"),
    )


def _extract_hdfc_transactions(lines: list[str], full_text: str) -> list[dict[str, Any]]:
    return _extract_bank_transactions(
        lines,
        bank_name="HDFC",
        hint_keywords=("upi", "vpa", "merchant", "transfer", "neft"),
    )


def _extract_icici_transactions(lines: list[str], full_text: str) -> list[dict[str, Any]]:
    return _extract_bank_transactions(
        lines,
        bank_name="ICICI",
        hint_keywords=("upi", "merchant", "mobile banking", "imps", "transfer"),
    )


def _extract_axis_transactions(lines: list[str], full_text: str) -> list[dict[str, Any]]:
    return _extract_bank_transactions(
        lines,
        bank_name="Axis",
        hint_keywords=("upi", "merchant", "axis mobile", "transfer", "imps"),
    )


def _extract_wallet_transactions(
    lines: list[str],
    keyword_groups: tuple[tuple[str, ...], ...],
    provider_name: str,
) -> list[dict[str, Any]]:
    blocks = _build_provider_blocks(lines, keyword_groups)
    transactions: list[dict[str, Any]] = []
    for block in blocks:
        merged = " | ".join(block)
        tx = _transaction_from_text(merged)
        if tx is None:
            continue
        transactions.append(tx)
    return _dedupe_transactions(transactions)


def _extract_bank_transactions(
    lines: list[str],
    bank_name: str,
    hint_keywords: tuple[str, ...],
) -> list[dict[str, Any]]:
    transactions: list[dict[str, Any]] = []
    for line in lines:
        normalized = re.sub(r"\s+", " ", line).strip()
        if not DATE_RE.search(normalized):
            continue
        lower = normalized.lower()
        if hint_keywords and not any(keyword in lower for keyword in hint_keywords):
            continue
        tx = _transaction_from_bank_line(normalized, bank_name)
        if tx is not None:
            transactions.append(tx)

    if transactions:
        return _dedupe_transactions(transactions)

    block_keywords = (hint_keywords,)
    for block in _build_provider_blocks(lines, block_keywords):
        merged = " | ".join(block)
        tx = _transaction_from_bank_line(merged, bank_name)
        if tx is not None:
            transactions.append(tx)
    return _dedupe_transactions(transactions)


def _build_provider_blocks(
    lines: list[str],
    keyword_groups: tuple[tuple[str, ...], ...],
) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []

    def is_anchor(line: str) -> bool:
        lowered = line.lower()
        if DATE_RE.search(line):
            return True
        return any(any(keyword in lowered for keyword in keywords) for keywords in keyword_groups)

    def has_strong_signal(line: str) -> bool:
        lowered = line.lower()
        return (
            STATUS_RE.search(line) is not None
            or REF_RE.search(line) is not None
            or UPI_RE.search(line) is not None
            or _extract_amount_from_line(line) is not None
            or any(keyword in lowered for keywords in keyword_groups for keyword in keywords)
        )

    for idx, line in enumerate(lines):
        if is_anchor(line) and current:
            blocks.append(current)
            current = []
        if is_anchor(line) or current:
            current.append(line)
        if current and has_strong_signal(line):
            next_line_is_anchor = idx + 1 < len(lines) and is_anchor(lines[idx + 1])
            if next_line_is_anchor or len(current) >= 8:
                blocks.append(current)
                current = []
    if current:
        blocks.append(current)
    return blocks


def _transaction_from_text(text: str) -> dict[str, Any] | None:
    timestamp = _extract_timestamp_from_line(text)
    amount = _extract_amount_from_line(text)
    upi_id = _extract_upi_id_from_line(text)
    reference = _extract_reference_from_line(text)
    if timestamp is None or amount is None:
        return None
    if not _looks_like_transaction(text, upi_id, reference):
        return None
    status = _extract_status_from_line(text)
    merchant = _extract_merchant_from_line(text, upi_id, reference, status)
    return {
        "timestamp": timestamp,
        "amount": amount,
        "merchant": merchant,
        "upi_id": upi_id,
        "status": status,
        "reference_number": reference,
        "raw_line": text,
    }


def _transaction_from_bank_line(line: str, bank_name: str) -> dict[str, Any] | None:
    timestamp = _extract_timestamp_from_line(line)
    amount = _extract_bank_amount(line)
    if timestamp is None or amount is None:
        return None
    upi_id = _extract_upi_id_from_line(line)
    reference = _extract_reference_from_line(line) or _extract_bank_reference(line)
    status = _extract_status_from_line(line)
    merchant = _extract_bank_merchant(line, bank_name, upi_id, reference)
    if merchant == "UNKNOWN_MERCHANT" and upi_id is None and reference is None:
        return None
    return {
        "timestamp": timestamp,
        "amount": amount,
        "merchant": merchant,
        "upi_id": upi_id,
        "status": status,
        "reference_number": reference,
        "raw_line": line,
    }


def _extract_transactions_from_lines(lines: list[str]) -> list[dict[str, Any]]:
    transactions: list[dict[str, Any]] = []
    for line in lines:
        if not DATE_RE.search(line):
            continue
        amount = _extract_amount_from_line(line)
        if amount is None:
            continue
        timestamp = _extract_timestamp_from_line(line)
        upi_id = _extract_upi_id_from_line(line)
        reference = _extract_reference_from_line(line)
        status = _extract_status_from_line(line)
        merchant = _extract_merchant_from_line(line, upi_id, reference, status)
        candidate = {
            "timestamp": timestamp,
            "amount": amount,
            "merchant": merchant,
            "upi_id": upi_id,
            "status": status,
            "reference_number": reference,
            "raw_line": line,
        }
        if _looks_like_transaction(candidate["raw_line"], candidate["upi_id"], candidate["reference_number"]):
            transactions.append(candidate)
    return _dedupe_transactions(transactions)


def _extract_transactions_from_blocks(lines: list[str]) -> list[dict[str, Any]]:
    transactions: list[dict[str, Any]] = []
    candidate_blocks = _build_candidate_blocks(lines, include_sliding_windows=False)

    for block in candidate_blocks:
        merged = " | ".join(block)
        amount = _extract_amount_from_line(merged)
        timestamp = _extract_timestamp_from_line(merged)
        if amount is None or timestamp is None:
            continue
        upi_id = _extract_upi_id_from_line(merged)
        reference = _extract_reference_from_line(merged)
        status = _extract_status_from_line(merged)
        merchant = _extract_merchant_from_line(merged, upi_id, reference, status)
        if not _looks_like_transaction(merged, upi_id, reference):
            continue
        transactions.append({
            "timestamp": timestamp,
            "amount": amount,
            "merchant": merchant,
            "upi_id": upi_id,
            "status": status,
            "reference_number": reference,
            "raw_line": merged,
        })

    if not transactions:
        for block in _build_candidate_blocks(lines, include_sliding_windows=True):
            merged = " | ".join(block)
            amount = _extract_amount_from_line(merged)
            timestamp = _extract_timestamp_from_line(merged)
            if amount is None or timestamp is None:
                continue
            upi_id = _extract_upi_id_from_line(merged)
            reference = _extract_reference_from_line(merged)
            status = _extract_status_from_line(merged)
            merchant = _extract_merchant_from_line(merged, upi_id, reference, status)
            if not _looks_like_transaction(merged, upi_id, reference):
                continue
            transactions.append({
                "timestamp": timestamp,
                "amount": amount,
                "merchant": merchant,
                "upi_id": upi_id,
                "status": status,
                "reference_number": reference,
                "raw_line": merged,
            })
    return _dedupe_transactions(transactions)


def _build_candidate_blocks(lines: list[str], include_sliding_windows: bool) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []

    for idx, line in enumerate(lines):
        starts_new = bool(DATE_RE.search(line))
        if starts_new and current:
            blocks.append(current)
            current = []
        if starts_new or current:
            current.append(line)
        if current and (
            STATUS_RE.search(line)
            or REF_RE.search(line)
            or UPI_RE.search(line)
            or _extract_amount_from_line(line) is not None
        ):
            next_has_date = idx + 1 < len(lines) and bool(DATE_RE.search(lines[idx + 1]))
            if next_has_date:
                blocks.append(current)
                current = []
        if len(current) >= 6:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)

    if include_sliding_windows:
        for start in range(len(lines)):
            window = lines[start:start + 4]
            if not window:
                continue
            merged = " ".join(window)
            if DATE_RE.search(merged) and _extract_amount_from_line(merged) is not None:
                blocks.append(window)
    return blocks


def _extract_timestamp_from_line(line: str) -> str | None:
    date_match = DATE_RE.search(line)
    time_match = TIME_RE.search(line)
    if not date_match:
        return None
    date_part = date_match.group(1)
    value = f"{date_part} {time_match.group(1)}" if time_match else date_part
    return _normalize_timestamp(value)


def _extract_amount_from_line(line: str) -> float | None:
    candidates = list(AMOUNT_RE.finditer(line))
    if not candidates:
        return None

    date_spans = [match.span(1) for match in DATE_RE.finditer(line)]
    time_spans = [match.span(1) for match in TIME_RE.finditer(line)]

    best_value: float | None = None
    best_score = float("-inf")

    for match in candidates:
        amount_text = match.group(1)
        amount_value = _normalize_amount(amount_text)
        if amount_value is None:
            continue

        start, end = match.span(1)
        if _span_overlaps((start, end), date_spans) or _span_overlaps((start, end), time_spans):
            continue

        context = line[max(0, start - 18):min(len(line), end + 18)]
        left_context = line[max(0, start - 12):start].lower()
        score = 0

        if re.search(r"(₹|rs\.?|inr)", context, re.IGNORECASE):
            score += 12
        if re.search(r"(?i)\b(amount|debited|credited|paid|received)\b", context):
            score += 7
        if re.search(r"(?i)\b(utr|ref|reference|txn|transaction)\b", left_context):
            score -= 10
        if len(amount_text.replace(",", "").split(".")[0]) >= 6:
            score -= 8
        if "." in amount_text:
            score += 3
        if 1 <= amount_value <= 500000:
            score += 2

        if score > best_score:
            best_score = score
            best_value = amount_value

    return best_value


def _extract_upi_id_from_line(line: str) -> str | None:
    match = UPI_RE.search(line)
    return match.group(1) if match else None


def _extract_reference_from_line(line: str) -> str | None:
    match = REF_RE.search(line)
    return match.group(1) if match else None


def _extract_status_from_line(line: str) -> str:
    match = STATUS_RE.search(line)
    if not match:
        return "SUCCESS"
    status = match.group(1).upper()
    if status == "SUCCESSFUL":
        return "SUCCESS"
    if status == "FAILURE":
        return "FAILED"
    return status


def _extract_merchant_from_line(
    line: str,
    upi_id: str | None,
    reference: str | None,
    status: str,
) -> str:
    labeled = _extract_labeled_merchant(line)
    if labeled is not None:
        return labeled

    cleaned = line
    for regex in (DATE_RE, TIME_RE, AMOUNT_RE, STATUS_RE, UPI_RE, REF_RE):
        cleaned = regex.sub(" ", cleaned)

    cleaned = re.sub(
        r"(?i)\b(debit|debited|credit|credited|paid to|received from|upi|transfer|payment|from|to|status|ref|reference|utr|txn|transaction)\b",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -|,")
    cleaned = cleaned.replace("|", " ").replace(":", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -|,")

    if cleaned:
        return cleaned[:80]
    if upi_id:
        return upi_id.split("@")[0]
    if reference:
        return f"REF_{reference[-6:]}"
    return "UNKNOWN_MERCHANT"


def _extract_labeled_merchant(line: str) -> str | None:
    patterns = [
        r"(?i)(?:paid to|received from|money sent to|merchant|beneficiary|to|from|name)\s*[:\-]?\s*([A-Za-z0-9 &._/-]{3,80})",
    ]
    for pattern in patterns:
        match = re.search(pattern, line)
        if match is None:
            continue
        candidate = match.group(1)
        candidate = re.split(r"(?i)\b(?:status|utr|ref(?:erence)?|txn(?: id)?|transaction(?: id)?|amount|vpa|upi)\b", candidate)[0]
        candidate = candidate.replace("|", " ").strip(" -|,:")
        candidate = re.sub(r"\s+", " ", candidate)
        if candidate and not UPI_RE.fullmatch(candidate):
            return candidate[:80]
    return None


def _extract_bank_amount(line: str) -> float | None:
    tokens = re.split(r"\s{2,}|\|", line)
    amount_like_tokens = [token.strip() for token in tokens if _normalize_amount(token) is not None]

    if len(amount_like_tokens) >= 3:
        debit = _normalize_amount(amount_like_tokens[-3])
        credit = _normalize_amount(amount_like_tokens[-2])
        if debit and debit > 0:
            return debit
        if credit and credit > 0:
            return credit

    if len(amount_like_tokens) >= 2:
        first = _normalize_amount(amount_like_tokens[-2])
        second = _normalize_amount(amount_like_tokens[-1])
        if first and first > 0:
            return first
        if second and second > 0:
            return second

    return _extract_amount_from_line(line)


def _extract_bank_reference(line: str) -> str | None:
    match = re.search(r"(?i)\b(?:upi|imps|neft|rrn|txn|ref)[/ :#-]*([A-Za-z0-9-]{6,})\b", line)
    return match.group(1) if match else None


def _extract_bank_merchant(
    line: str,
    bank_name: str,
    upi_id: str | None,
    reference: str | None,
) -> str:
    if upi_id:
        return upi_id.split("@")[0]

    cleaned = re.sub(DATE_RE, " ", line)
    cleaned = re.sub(TIME_RE, " ", cleaned)
    cleaned = re.sub(r"(?i)\b(?:upi|to transfer|by transfer|imps|neft|debit|credit|withdrawal|deposit|merchant|txn|transaction|ref|reference|rrn|mob|mb|dr|cr)\b", " ", cleaned)
    cleaned = re.sub(r"(?:₹|Rs\.?|INR)?\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?", " ", cleaned)
    cleaned = cleaned.replace("|", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -|,:")

    if cleaned and cleaned.lower() not in {bank_name.lower(), "upi"}:
        return cleaned[:80]

    if reference:
        return f"{bank_name}_REF_{reference[-6:]}"

    return "UNKNOWN_MERCHANT"


# ═══════════════════════════════════════════════════════════════════════════
# BEHAVIOR PROFILE GENERATOR (unchanged)
# ═══════════════════════════════════════════════════════════════════════════

def generate_behavior_profile(transactions: list[dict[str, Any]]) -> dict[str, Any]:
    if not transactions:
        return {
            "transaction_count": 0,
            "avg_amount": 0,
            "max_amount": 0,
            "min_amount": 0,
            "most_active_hour": None,
            "night_transactions": 0,
            "weekend_transactions": 0,
            "favorite_merchants": [],
            "average_daily_transactions": 0,
            "failed_transactions": 0,
            "known_upi_ids": [],
            "merchant_frequency": {},
            "hourly_distribution": {},
            "monthly_totals": {},
        }

    df = pd.DataFrame(transactions).copy()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["merchant"] = df["merchant"].fillna("UNKNOWN_MERCHANT")
    df["status"] = df["status"].fillna("UNKNOWN").str.upper()
    df["upi_id"] = df["upi_id"].fillna("")

    valid_ts = df["timestamp"].dropna()
    if valid_ts.empty:
        most_active_hour = None
        night_transactions = 0
        weekend_transactions = 0
        average_daily_transactions = float(len(df))
        hourly_distribution: dict[str, int] = {}
        monthly_totals: dict[str, float] = {}
    else:
        hours = df.loc[df["timestamp"].notna(), "timestamp"].dt.hour
        most_active_hour = int(hours.mode().iloc[0]) if not hours.empty else None
        night_transactions = int(((hours < 6) | (hours >= 22)).sum())
        weekend_transactions = int(
            (df.loc[df["timestamp"].notna(), "timestamp"].dt.weekday >= 5).sum()
        )
        daily_counts = (
            df.loc[df["timestamp"].notna()]
            .groupby(df.loc[df["timestamp"].notna(), "timestamp"].dt.date)
            .size()
        )
        average_daily_transactions = float(round(daily_counts.mean(), 2)) if not daily_counts.empty else float(len(df))
        hourly_distribution = (
            df.loc[df["timestamp"].notna()]
            .groupby(df.loc[df["timestamp"].notna(), "timestamp"].dt.hour)
            .size()
            .astype(int)
            .to_dict()
        )
        monthly_totals = (
            df.loc[df["timestamp"].notna()]
            .groupby(df.loc[df["timestamp"].notna(), "timestamp"].dt.strftime("%Y-%m"))["amount"]
            .sum()
            .round(2)
            .to_dict()
        )

    favorite_merchants = (
        df["merchant"].value_counts().head(5).index.tolist()
    )
    merchant_frequency = df["merchant"].value_counts().head(10).astype(int).to_dict()
    known_upi_ids = sorted([upi for upi in df["upi_id"].unique().tolist() if upi])

    return {
        "transaction_count": int(len(df)),
        "avg_amount": float(round(df["amount"].mean(), 2)),
        "max_amount": float(round(df["amount"].max(), 2)),
        "min_amount": float(round(df["amount"].min(), 2)),
        "most_active_hour": most_active_hour,
        "night_transactions": night_transactions,
        "weekend_transactions": weekend_transactions,
        "favorite_merchants": favorite_merchants,
        "average_daily_transactions": average_daily_transactions,
        "failed_transactions": int((df["status"] == "FAILED").sum()),
        "known_upi_ids": known_upi_ids,
        "merchant_frequency": merchant_frequency,
        "hourly_distribution": {str(k): int(v) for k, v in hourly_distribution.items()},
        "monthly_totals": monthly_totals,
    }


# ═══════════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def _normalize_timestamp(value: Any) -> str:
    if value is None:
        return datetime.utcnow().isoformat()

    text = str(value).strip()
    if not text:
        return datetime.utcnow().isoformat()

    for pattern in DATE_PATTERNS:
        try:
            return datetime.strptime(text, pattern).isoformat()
        except ValueError:
            continue

    text = text.replace(",", "")
    parsed = pd.to_datetime(text, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return datetime.utcnow().isoformat()
    return parsed.isoformat()


def _normalize_amount(value: Any) -> float | None:
    text = str(value).replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _join_values(date_value: Any, time_value: Any) -> str | None:
    if date_value and time_value:
        return f"{date_value} {time_value}"
    return date_value or time_value


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _looks_like_transaction(raw_text: str, upi_id: str | None, reference: str | None) -> bool:
    text = raw_text.strip()
    if not text:
        return False
    if upi_id or reference:
        return True
    if UPI_HINT_RE.search(text) and DATE_RE.search(text) and _extract_amount_from_line(text) is not None:
        return True
    return False


def _dedupe_transactions(transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    deduped: list[dict[str, Any]] = []
    for tx in transactions:
        key = (
            tx.get("timestamp"),
            tx.get("amount"),
            tx.get("reference_number"),
            tx.get("upi_id"),
            tx.get("merchant"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(tx)
    return deduped


def _span_overlaps(span: tuple[int, int], other_spans: list[tuple[int, int]]) -> bool:
    start, end = span
    for other_start, other_end in other_spans:
        if start < other_end and end > other_start:
            return True
    return False
