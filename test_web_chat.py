import os
import tempfile
import unittest
from unittest.mock import patch

import auth
from config import CONFIG
from events import list_events
from tools import ToolExecution
from web import app, _save_history_turns


class TestWebChatFlow(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = auth.DB_PATH
        self.original_admin_password = CONFIG.get("admin_password")
        self.original_auto_extract = CONFIG.get("auto_extract_facts", True)
        auth.DB_PATH = os.path.join(self.temp_dir.name, "jarvis-test.db")
        CONFIG["admin_password"] = "changeme2026!"
        CONFIG["auto_extract_facts"] = False
        auth.init_db()
        self.client.set_cookie("jarvis_token", "test-token")

    def tearDown(self):
        auth.DB_PATH = self.original_db_path
        CONFIG["admin_password"] = self.original_admin_password
        CONFIG["auto_extract_facts"] = self.original_auto_extract
        self.temp_dir.cleanup()

    def _history_rows(self):
        db = auth.get_db()
        rows = db.execute(
            "SELECT role, content, session_id, channel, thread_id, message_id FROM history ORDER BY id"
        ).fetchall()
        db.close()
        return rows

    @patch("auth.get_user_by_token", return_value={"id": 1, "username": "brian", "role": "admin", "must_change_password": 0})
    @patch("web.get_facts", return_value=[])
    @patch("web.ask_llm_chat", return_value="LLM response")
    def test_chat_returns_envelope_and_persists_events(self, mock_ask, mock_get_facts, mock_get_user):
        response = self.client.post(
            "/api/chat",
            json={
                "message": "hello there",
                "channel": "syncforge",
                "thread_id": "deploy-123",
                "session_id": "syncforge:deploy-123",
                "metadata": {"source": "unit-test"},
                "tts": False,
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["response"], "LLM response")
        self.assertEqual(body["session"]["channel"], "syncforge")
        self.assertEqual(body["session"]["thread_id"], "deploy-123")
        self.assertEqual(body["session"]["session_id"], "syncforge:deploy-123")
        self.assertTrue(body["session"]["message_id"].startswith("msg-"))
        self.assertTrue(body["session"]["reply_to"].startswith("msg-"))
        mock_ask.assert_called_once()

        rows = self._history_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["session_id"], "syncforge:deploy-123")
        self.assertEqual(rows[0]["channel"], "syncforge")
        self.assertEqual(rows[0]["thread_id"], "deploy-123")

        events = list_events(session_id="syncforge:deploy-123")
        event_types = [event["event_type"] for event in events]
        self.assertEqual(event_types, ["user_message_received", "assistant_message_sent"])
        self.assertEqual(events[0]["payload"]["metadata"], {"source": "unit-test"})

    @patch("auth.get_user_by_token", return_value={"id": 1, "username": "brian", "role": "admin", "must_change_password": 0})
    @patch("web.build_system_prompt", return_value="SYSTEM")
    @patch("web.ask_llm_chat", return_value="scoped response")
    def test_chat_uses_session_scoped_history(self, mock_ask, mock_system_prompt, mock_get_user):
        _save_history_turns(
            1,
            "old session one",
            "answer one",
            session_id="syncforge:one",
            channel="syncforge",
            thread_id="one",
            user_message_id="msg-one-user",
            assistant_message_id="msg-one-assistant",
        )
        _save_history_turns(
            1,
            "old session two",
            "answer two",
            session_id="syncforge:two",
            channel="syncforge",
            thread_id="two",
            user_message_id="msg-two-user",
            assistant_message_id="msg-two-assistant",
        )

        response = self.client.post(
            "/api/chat",
            json={
                "message": "new question",
                "channel": "syncforge",
                "thread_id": "one",
                "session_id": "syncforge:one",
                "tts": False,
            },
        )

        self.assertEqual(response.status_code, 200)
        messages = mock_ask.call_args.args[0]
        serialized = [item["content"] for item in messages]
        self.assertIn("old session one", serialized)
        self.assertIn("answer one", serialized)
        self.assertNotIn("old session two", serialized)
        self.assertNotIn("answer two", serialized)

    @patch("auth.get_user_by_token", return_value={"id": 1, "username": "brian", "role": "admin", "must_change_password": 0})
    @patch("web.ask_llm_chat")
    @patch("web.dispatch_tool_message", return_value=ToolExecution(tool_id="ping", label="Ping", args={"target": "app.example.com"}, output="PING for app.example.com:\n```ok\n```"))
    def test_chat_executes_registered_tool_and_logs_tool_events(self, mock_dispatch, mock_ask, mock_get_user):
        response = self.client.post(
            "/api/chat",
            json={
                "message": "ping app.example.com",
                "channel": "syncforge",
                "thread_id": "ops",
                "session_id": "syncforge:ops",
                "tts": False,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("PING for app.example.com", response.get_json()["response"])
        mock_dispatch.assert_called_once()
        mock_ask.assert_not_called()

        events = list_events(session_id="syncforge:ops")
        event_types = [event["event_type"] for event in events]
        self.assertEqual(
            event_types,
            ["user_message_received", "tool_invoked", "tool_result", "assistant_message_sent"],
        )
        self.assertEqual(events[1]["tool_name"], "ping")


if __name__ == "__main__":
    unittest.main()
