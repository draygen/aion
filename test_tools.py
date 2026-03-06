import unittest
from unittest.mock import patch

from config import CONFIG
from tools import available_tool_status, is_authorized_target, handle_ops_command


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

    @patch("tools.run_nmap_service_scan", return_value="scan result")
    def test_routes_web_scan_url(self, mock_nmap):
        result = handle_ops_command("web scan https://app.example.com:5000/health", "1.2.3.4")
        self.assertIn("Nmap service scan", result)
        mock_nmap.assert_called_once_with("app.example.com")

    @patch("tools.run_httpx", return_value="ok")
    def test_routes_httpx_url(self, mock_httpx):
        result = handle_ops_command("httpx https://app.example.com/login", "1.2.3.4")
        self.assertIn("httpx for app.example.com", result)
        mock_httpx.assert_called_once_with("https://app.example.com/login")

    @patch("tools._tool_installed", side_effect=lambda name: name in {"ping", "nmap"})
    @patch("tools._first_installed", return_value=None)
    def test_available_tool_status(self, mock_first, mock_installed):
        tools = available_tool_status()
        labels = {tool["label"]: tool["installed"] for tool in tools}
        self.assertTrue(labels["Ping"])
        self.assertTrue(labels["Nmap"])
        self.assertFalse(labels["OWASP ZAP"])

    def test_returns_none_when_disabled(self):
        CONFIG["network_ops_enabled"] = False
        self.assertIsNone(handle_ops_command("ping app.example.com", "1.2.3.4"))

    def test_returns_help_for_unsupported_command(self):
        result = handle_ops_command("run authorized check", "1.2.3.4")
        self.assertIn("Unsupported command.", result)


if __name__ == "__main__":
    unittest.main()
