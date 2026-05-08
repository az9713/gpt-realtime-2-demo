"""Regex-based PII redactor.

Conservative — false positives are preferable to leaking PII into logs.
"""

from __future__ import annotations

import re

EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE = re.compile(
    r"(?:\+?\d{1,2}[ .-]?)?(?:\(?\d{3}\)?[ .-]?)\d{3}[ .-]?\d{4}\b"
)
SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CREDIT_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")


class PIIRedactor:
    """Redacts emails, phone numbers, SSNs, and credit-card-like digit runs."""

    def redact(self, text: str) -> str:
        if not text:
            return text
        text = EMAIL.sub("[email]", text)
        text = SSN.sub("[ssn]", text)
        text = CREDIT_CARD.sub("[card]", text)
        return PHONE.sub("[phone]", text)

    def has_pii(self, text: str) -> bool:
        if not text:
            return False
        return bool(
            EMAIL.search(text)
            or SSN.search(text)
            or CREDIT_CARD.search(text)
            or PHONE.search(text)
        )
