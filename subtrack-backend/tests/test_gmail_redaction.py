import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.gmail.redaction import owner_terms, redact, redact_owner  # noqa: E402
from app.gmail.scanner import _excerpt, _to_candidate  # noqa: E402


class RedactionTests(unittest.TestCase):
    def assert_removed(self, text: str, *secrets: str) -> str:
        result = redact(text)
        for secret in secrets:
            self.assertNotIn(secret, result)
        return result

    def test_contact_details_are_removed(self):
        result = self.assert_removed(
            "Questions? Email jane.citizen@gmail.com or call 0412 345 678 or +61 2 9876 5432",
            "jane.citizen@gmail.com", "0412 345 678", "9876 5432",
        )
        self.assertIn("[email]", result)
        self.assertIn("[phone]", result)

    def test_greeting_names_are_removed(self):
        self.assertEqual(redact("Hi Jane Citizen, thanks for your payment"), "Hi [name], thanks for your payment")
        self.assertEqual(redact("Dear Mr Smith:"), "Dear [name],")

    def test_card_fragments_are_removed(self):
        for text in (
            "Charged to Visa ending in 4242",
            "Mastercard •••• 4242",
            "Card number: **** **** **** 4242",
            "Paid with card last 4 digits 4242",
        ):
            with self.subTest(text=text):
                self.assert_removed(text, "4242")

    def test_addresses_are_removed(self):
        result = self.assert_removed(
            "Service address: 12/34 Example Street Sydney NSW 2000",
            "12/34 Example Street", "NSW 2000",
        )
        self.assertIn("[removed]", result)
        self.assert_removed("Delivered to 7 Harbour View Road, Manly", "7 Harbour View Road")
        self.assert_removed("Property 90/2-6 Sample St Kensington", "90/2-6 Sample St")

    def test_account_and_reference_numbers_are_removed(self):
        self.assert_removed("Account number: 1234 5678 9012", "1234 5678 9012")
        self.assert_removed("Customer ID: AB-778899", "778899")
        self.assert_removed("Invoice INV-00456789 is ready", "00456789")
        self.assert_removed("BSB: 062-000", "062-000")

    def test_links_are_removed(self):
        self.assert_removed(
            "Manage at https://billing.example.com/u/abc123?token=secret",
            "abc123", "token=secret",
        )

    def test_product_amount_and_dates_survive(self):
        text = "Your Apple Music Individual plan renews on 24/10/2026 for A$12.99 per month"
        self.assertEqual(redact(text), text)
        self.assertEqual(redact("Netflix Standard with ads - $7.99/month"), "Netflix Standard with ads - $7.99/month")
        self.assertEqual(redact("Trial ends 2026-10-01"), "Trial ends 2026-10-01")
        self.assertIn("1,148.00", redact("Car insurance annual premium $1,148.00 due 18 Oct"))

    def test_empty_text_is_unchanged(self):
        self.assertEqual(redact(""), "")


class ScannerRedactionTests(unittest.TestCase):
    def test_excerpt_is_redacted_before_it_leaves_the_scanner(self):
        body = (
            "Hi Jane,\n"
            "Thanks for renewing iCloud+ 2TB.\n"
            "Billed to jane@example.com, Visa ending 4242.\n"
            "Total: A$14.99\n"
        )
        excerpt = _excerpt(body)
        self.assertIn("iCloud+ 2TB", excerpt)
        self.assertIn("A$14.99", excerpt)
        for secret in ("Jane", "jane@example.com", "4242"):
            self.assertNotIn(secret, excerpt)

    def test_candidate_keeps_amount_but_redacts_subject_and_excerpt(self):
        import base64

        body = "Hello Jane Citizen,\nYour Spotify Premium receipt.\nTotal A$13.99\nCard ending 4242\n"
        message = {
            "id": "m1",
            "internalDate": "1790000000000",
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "From", "value": "Spotify <no-reply@spotify.com>"},
                    {"name": "Subject", "value": "Jane, your receipt from Spotify (jane@example.com)"},
                ],
                "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()},
            },
        }
        candidate = _to_candidate(message)
        self.assertEqual(candidate.amount, 13.99)
        self.assertIn("Spotify Premium", candidate.excerpt)
        for field in (candidate.subject, candidate.excerpt):
            self.assertNotIn("jane@example.com", field)
            self.assertNotIn("4242", field)
            self.assertNotIn("Citizen", field)


class OwnerRedactionTests(unittest.TestCase):
    def test_owner_terms_come_from_the_mailbox_address(self):
        self.assertEqual(owner_terms("jane.citizen99@gmail.com"), ["citizen", "jane"])
        self.assertEqual(owner_terms(None), [])
        self.assertEqual(owner_terms("jo@x.com"), [])

    def test_owner_name_is_removed_but_sender_brand_is_kept(self):
        from app.gmail.scanner import ReceiptCandidate

        candidates = [
            ReceiptCandidate(
                message_id="1", sender_domain="spotify.com", merchant="Spotify",
                subject="Jane, your Spotify receipt", date="2026-09-01",
                amount=13.99, currency="AUD", confidence="high",
                excerpt="Thanks Jane Citizen | Spotify Premium Individual",
            ),
            ReceiptCandidate(
                message_id="2", sender_domain="netflix.com", merchant="Netflix",
                subject="Your Netflix bill", date="2026-09-02",
                amount=25.99, currency="AUD", confidence="high",
                excerpt="Netflix Premium",
            ),
        ]
        redact_owner(candidates, "jane.citizen@gmail.com")
        self.assertEqual(candidates[0].subject, "[name], your Spotify receipt")
        self.assertNotIn("Jane", candidates[0].excerpt)
        self.assertNotIn("Citizen", candidates[0].excerpt)
        self.assertIn("Spotify Premium", candidates[0].excerpt)

        brand_owner = [candidates[1]]
        redact_owner(brand_owner, "netflix.fan@gmail.com")
        self.assertEqual(brand_owner[0].excerpt, "Netflix Premium")


if __name__ == "__main__":
    unittest.main()
