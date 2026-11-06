from app.services.sensitive_data import redact_text, redact_value


def test_redacts_email_phone_valid_iban_and_valid_card():
    text = (
        "Contact: alice@example.com, téléphone +33 6 12 34 56 78, "
        "IBAN GB82 WEST 1234 5698 7654 32, carte 4111 1111 1111 1111."
    )
    redacted = redact_text(text)

    assert "alice@example.com" not in redacted
    assert "+33 6 12 34 56 78" not in redacted
    assert "GB82 WEST 1234 5698 7654 32" not in redacted
    assert "4111 1111 1111 1111" not in redacted
    assert all(token in redacted for token in ("[EMAIL]", "[PHONE]", "[IBAN]", "[CARD]"))


def test_does_not_mask_invalid_iban_or_card_numbers():
    text = "Référence 4111 1111 1111 1112, code GB82 WEST 1234 5698 7654 33."
    assert redact_text(text) == text


def test_redacts_nested_llm_messages_without_mutating_input():
    messages = [{"role": "user", "content": "E-mail: alice@example.com"}]
    redacted = redact_value(messages)

    assert redacted == [{"role": "user", "content": "E-mail: [EMAIL]"}]
    assert messages[0]["content"] == "E-mail: alice@example.com"
