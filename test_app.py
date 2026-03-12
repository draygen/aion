import unittest
from unittest.mock import patch, MagicMock
import sys

from app import build_prompt, handle_set, main
from config import CONFIG

class TestApp(unittest.TestCase):

    def setUp(self):
        # Reset CONFIG to default for tests
        CONFIG["model"] = "mistral"
        CONFIG["backend"] = "ollama"
        CONFIG["retrieval"] = "embed"
        CONFIG["embed_backend"] = "tfidf"
        CONFIG["facts_files"] = []
        CONFIG["openai_api_key"] = "sk-xxxx"
        CONFIG["TTS_ENABLED"] = False

    @patch("app.get_facts")
    def test_build_prompt_with_facts(self, mock_get_facts):
        mock_get_facts.return_value = ["fact1", "fact2"]
        prompt = build_prompt("test query")
        self.assertIn("Context (up to 12 snippets):\n- fact1\n- fact2", prompt)
        self.assertIn("User: test query\nAssistant:", prompt)
        self.assertIn("You are AION, Brian's personal AI assistant.", prompt)

    @patch("app.get_facts")
    def test_build_prompt_no_facts(self, mock_get_facts):
        mock_get_facts.return_value = []
        prompt = build_prompt("test query")
        self.assertNotIn("Context", prompt)
        self.assertIn("User: test query\nAssistant:", prompt)

    def test_handle_set_valid(self):
        result = handle_set("model=gpt-4")
        self.assertEqual(CONFIG["model"], "gpt-4")
        self.assertEqual(result, "Set model = gpt-4")

    def test_handle_set_invalid_format(self):
        result = handle_set("model:gpt-4")
        self.assertNotEqual(CONFIG["model"], "gpt-4")
        self.assertEqual(result, "Usage: /set key=value (e.g., /set model=mistral)")

    def test_handle_set_empty_key(self):
        result = handle_set("=value")
        self.assertEqual(result, "Invalid key.")

    @patch("app.speak")
    @patch("builtins.input", side_effect=["n", "exit"])
    @patch("builtins.print")
    def test_main_exit_command(self, mock_print, mock_input, mock_speak):
        with self.assertRaises(SystemExit) as cm:
            main()
        self.assertEqual(cm.exception.code, 0)
        mock_print.assert_any_call("Aion: Goodbye.")

    @patch("app.speak")
    @patch("builtins.input", side_effect=["n", "/help", "exit"])
    @patch("builtins.print")
    @patch("app.help_text", return_value="Help text")
    def test_main_help_command(self, mock_help_text, mock_print, mock_input, mock_speak):
        with self.assertRaises(SystemExit):
            main()
        mock_help_text.assert_called_once()
        mock_print.assert_any_call("Help text")

    @patch("app.speak")
    @patch("builtins.input", side_effect=["n", "/set model=test_model", "exit"])
    @patch("builtins.print")
    def test_main_set_command(self, mock_print, mock_input, mock_speak):
        with self.assertRaises(SystemExit):
            main()
        self.assertEqual(CONFIG["model"], "test_model")
        mock_print.assert_any_call("Set model = test_model")

    @patch("app.speak")
    @patch("builtins.input", side_effect=["n", "hello", "exit"])
    @patch("builtins.print")
    @patch("app.ask_llm", return_value="LLM response")
    @patch("app.build_prompt", return_value="LLM prompt")
    def test_main_normal_conversation(self, mock_build_prompt, mock_ask_llm, mock_print, mock_input, mock_speak):
        with self.assertRaises(SystemExit):
            main()
        mock_build_prompt.assert_called_once_with("hello")
        mock_ask_llm.assert_called_once_with("LLM prompt")
        mock_print.assert_any_call("Aion: LLM response")

    @patch("app.speak")
    @patch("builtins.input", side_effect=["n", "test", "exit"])
    @patch("builtins.print")
    @patch("app.ask_llm", side_effect=Exception("LLM error"))
    def test_main_llm_error_handling(self, mock_ask_llm, mock_print, mock_input, mock_speak):
        with self.assertRaises(SystemExit):
            main()
        mock_print.assert_any_call("Aion (error): An error occurred while communicating with the LLM: LLM error")

if __name__ == '__main__':
    unittest.main()
