import unittest
from unittest.mock import patch

from config import CONFIG
from web import app


class TestWebSecurity(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self._config_snapshot = {
            "cookie_secure": CONFIG.get("cookie_secure"),
            "cookie_samesite": CONFIG.get("cookie_samesite"),
            "memory_browser_requires_auth": CONFIG.get("memory_browser_requires_auth"),
        }
        CONFIG["cookie_secure"] = False
        CONFIG["cookie_samesite"] = "Lax"
        CONFIG["memory_browser_requires_auth"] = True

    def tearDown(self):
        CONFIG.update(self._config_snapshot)

    @patch("web.create_token", return_value="test-token")
    @patch("web.verify_login", return_value={"id": 1, "username": "brian", "role": "admin"})
    def test_login_cookie_marks_secure_for_https_proxy(self, mock_verify_login, mock_create_token):
        response = self.client.post(
            "/api/login",
            json={"username": "brian", "password": "secret"},
            headers={"X-Forwarded-Proto": "https"},
        )

        self.assertEqual(response.status_code, 200)
        cookie_header = response.headers.get("Set-Cookie", "")
        self.assertIn("Secure", cookie_header)
        self.assertIn("HttpOnly", cookie_header)
        self.assertIn("SameSite=Lax", cookie_header)

    @patch("web.create_token", return_value="test-token")
    @patch("web.verify_login", return_value={"id": 1, "username": "brian", "role": "admin", "must_change_password": 1})
    def test_login_reports_password_change_required(self, mock_verify_login, mock_create_token):
        response = self.client.post(
            "/api/login",
            json={"username": "brian", "password": "changeme2026"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["requires_password_change"])

    def test_memory_browse_requires_auth_by_default(self):
        response = self.client.get("/api/memory/browse")
        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.get_json()["login_required"])

    def test_memory_browse_can_be_opened_explicitly(self):
        CONFIG["memory_browser_requires_auth"] = False
        response = self.client.get("/api/memory/browse")
        self.assertEqual(response.status_code, 200)
        self.assertIn("categories", response.get_json())

    @patch("web.get_facts", return_value=["fact"])
    def test_build_system_prompt_scopes_memory_to_username(self, mock_get_facts):
        from web import build_system_prompt

        build_system_prompt("Who is my family?", username="alice")
        mock_get_facts.assert_called_once_with("Who is my family?", k=15, user_scope="alice")

    @patch("auth.get_user_by_token", return_value={"id": 1, "username": "brian", "role": "admin", "must_change_password": 0})
    def test_admin_can_read_network_config(self, mock_get_user):
        self.client.set_cookie("jarvis_token", "test-token")
        response = self.client.get("/api/admin/network/config")
        self.assertEqual(response.status_code, 200)
        self.assertIn("authorized_network_targets", response.get_json())

    @patch("web.handle_ops_command", return_value="PING for app.example.com:\n```ok```")
    @patch("auth.get_user_by_token", return_value={"id": 1, "username": "brian", "role": "admin", "must_change_password": 0})
    def test_admin_can_run_network_command(self, mock_get_user, mock_handle):
        self.client.set_cookie("jarvis_token", "test-token")
        response = self.client.post("/api/admin/network/run", json={"command": "ping app.example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        mock_handle.assert_called_once()

    @patch("auth.get_user_by_token", return_value={"id": 1, "username": "brian", "role": "admin", "must_change_password": 1})
    def test_chat_blocked_until_password_changed(self, mock_get_user):
        self.client.set_cookie("jarvis_token", "test-token")
        response = self.client.post("/api/chat", json={"message": "hello"})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.get_json()["requires_password_change"])

    @patch("web.change_password", return_value=None)
    @patch("auth.get_user_by_token", return_value={"id": 1, "username": "brian", "role": "admin", "must_change_password": 1})
    def test_change_password_allowed_while_flagged(self, mock_get_user, mock_change_password):
        self.client.set_cookie("jarvis_token", "test-token")
        response = self.client.post(
            "/api/change-password",
            json={"current_password": "changeme2026", "new_password": "something-better-2026"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        mock_change_password.assert_called_once_with(1, "changeme2026", "something-better-2026")


if __name__ == "__main__":
    unittest.main()
