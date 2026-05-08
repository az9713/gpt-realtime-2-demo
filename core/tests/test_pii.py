from cockpit_core.guardrails.pii import PIIRedactor


def test_redacts_emails():
    r = PIIRedactor()
    out = r.redact("contact me at jane.doe+sales@example.com please")
    assert "[email]" in out
    assert "jane.doe" not in out


def test_redacts_phone_numbers():
    r = PIIRedactor()
    cases = [
        "call (512) 555-0102",
        "phone 512-555-0102",
        "+1 512.555.0102",
    ]
    for c in cases:
        out = r.redact(c)
        assert "[phone]" in out, c


def test_redacts_ssn_and_card():
    r = PIIRedactor()
    out = r.redact("ssn 123-45-6789 card 4111 1111 1111 1111")
    assert "[ssn]" in out
    assert "[card]" in out


def test_has_pii_detects_any():
    r = PIIRedactor()
    assert r.has_pii("hi jane@x.com") is True
    assert r.has_pii("nothing here") is False
