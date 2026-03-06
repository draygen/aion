import unittest
from unittest.mock import patch

from config import CONFIG
from extractor import extract_and_save, _extract_worker


class TestExtractor(unittest.TestCase):
    def setUp(self):
        self._mode = CONFIG.get("auto_extract_mode")

    def tearDown(self):
        CONFIG["auto_extract_mode"] = self._mode

    @patch("extractor.threading.Thread")
    def test_extract_and_save_skips_thread_when_disabled(self, mock_thread):
        CONFIG["auto_extract_mode"] = "off"
        extract_and_save("user", "assistant", "brian")
        mock_thread.assert_not_called()

    @patch("extractor.add_fact")
    @patch("extractor.ask_llm_chat", return_value='["Brian likes black coffee"]')
    def test_extract_worker_queues_pending_facts_by_default(self, mock_ask, mock_add_fact):
        CONFIG["auto_extract_mode"] = "pending"
        _extract_worker("I like black coffee", "Noted", "brian", "brian")

        mock_add_fact.assert_called_once()
        _, fact_text = mock_add_fact.call_args.args[:2]
        self.assertEqual(fact_text, "Brian likes black coffee")
        self.assertEqual(mock_add_fact.call_args.kwargs["destination"], "pending")
        self.assertEqual(mock_add_fact.call_args.kwargs["metadata"]["status"], "pending")
        self.assertEqual(mock_add_fact.call_args.kwargs["user_scope"], "brian")


if __name__ == "__main__":
    unittest.main()
