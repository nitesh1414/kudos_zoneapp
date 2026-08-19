import os
import unittest

from app.auth import decrypt_credentials, encrypt_credentials, hash_password, verify_password
from app.brokers.registry import broker_types, make_broker


class AuthTests(unittest.TestCase):
    def setUp(self):
        os.environ["ZONEAPP_API_KEY"] = "unit-test-key"
        os.environ.pop("ZONEAPP_ENCRYPTION_KEY", None)

    def test_password_hash_round_trip(self):
        encoded = hash_password("a-strong-password")
        self.assertTrue(verify_password("a-strong-password", encoded))
        self.assertFalse(verify_password("wrong-password", encoded))
        self.assertNotIn("a-strong-password", encoded)

    def test_credentials_are_encrypted(self):
        source = {"client_id": "client", "access_token": "very-secret"}
        stored = encrypt_credentials(source)
        self.assertNotIn("very-secret", str(stored))
        self.assertEqual(source, decrypt_credentials(stored))


class BrokerRegistryTests(unittest.TestCase):
    def test_fyers_is_discoverable_and_constructible(self):
        available = {item["key"] for item in broker_types()}
        self.assertIn("fyers", available)
        adapter = make_broker("fyers", {"client_id": "id", "access_token": "token"})
        self.assertEqual("fyers", adapter.name)

    def test_unknown_broker_is_rejected(self):
        with self.assertRaises(ValueError):
            make_broker("unknown", {})


if __name__ == "__main__":
    unittest.main()
