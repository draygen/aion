import unittest
from unittest.mock import patch

from config import CONFIG
from tools import is_authorized_target, handle_ops_command


class TestTools(unittest.TestCase):
    def setUp(self):
        self._authorized = list(CONFIG.get("authorized_network_targets") or [])
        self._enabled = CONFIG.get("network_ops_enabled", True)
        CONFIG["authorized_network_targets"] = ["localhost", "127.0.0.1", "*.example.internal", "app.example.com"]
        CONFIG["network_ops_enabled"] = True

    def tearDown(self):
        CONFIG["authorized_network_targets"] = self._authorized
        CONFIG["network_ops_enabled"] = self._enabled

    def test_authorizes_private_and_explicit_targets(self):
        self.assertTrue(is_authorized_target("127.0.0.1"))
        self.assertTrue(is_authorized_target("app.example.com"))
        self.assertTrue(is_authorized_target("db.example.internal"))

    def test_blocks_unknown_public_targets(self):
        self.assertFalse(is_authorized_target("google.com"))
        self.assertFalse(is_authorized_target("8.8.8.8"))
        self.assertTrue(is_authorized_target("10.0.0.5"))

    def test_authorizes_cidr_targets(self):
        CONFIG["authorized_network_targets"] = ["203.0.113.0/24"]
        self.assertTrue(is_authorized_target("203.0.113.10"))
        self.assertFalse(is_authorized_target("203.0.114.10"))

    @patch("tools.run_ping", return_value="ok")
    def test_routes_ping_command(self, mock_ping):
        result = handle_ops_command("ping app.example.com", "1.2.3.4")
        self.assertIn("PING for app.example.com", result)
        mock_ping.assert_called_once_with("app.example.com")

    @patch("tools.run_nmap_service_scan", return_value="scan result")
    def test_routes_nmap_command(self, mock_nmap):
        result = handle_ops_command("scan app.example.com", "1.2.3.4")
        self.assertIn("Nmap service scan", result)
        mock_nmap.assert_called_once_with("app.example.com")

    def test_returns_none_when_disabled(self):
        CONFIG["network_ops_enabled"] = False
        self.assertIsNone(handle_ops_command("ping app.example.com", "1.2.3.4"))


if __name__ == "__main__":
    unittest.main()
