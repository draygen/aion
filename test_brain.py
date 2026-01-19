import unittest
import os
import json
from unittest.mock import patch, mock_open, MagicMock
from io import StringIO

from brain import load_facts, add_fact, get_facts, memory, _format_snippet
from config import CONFIG

class TestBrain(unittest.TestCase):

    def setUp(self):
        # Clear memory before each test
        memory.clear()
        # Reset CONFIG to default for tests
        CONFIG["facts_files"] = [
            "data/profile.jsonl",
            "data/brian_facts.jsonl",
            "data/fb_qa_pairs.jsonl",
        ]
        CONFIG["retrieval"] = "embed"
        CONFIG["embed_backend"] = "tfidf"

    @patch("brain.os.path.exists")
    def test_load_facts_empty_files(self, mock_exists):
        mock_exists.return_value = False
        count = load_facts(files=["nonexistent.jsonl"])
        self.assertEqual(count, 0)
        self.assertEqual(len(memory), 0)

    @patch("brain.os.path.exists")
    @patch("builtins.open")
    def test_load_facts_valid_jsonl(self, mock_file, mock_exists):
        mock_exists.return_value = True
        file_content = (
            json.dumps({"question": "q1", "answer": "a1"}) + "\n" +
            json.dumps({"text": "t1"}) + "\n"
        )
        mock_file.return_value.__enter__.return_value = StringIO(file_content)

        count = load_facts(files=["dummy.jsonl"])
        self.assertEqual(count, 2)
        self.assertEqual(len(memory), 2)
        self.assertEqual(memory[0]["input"], "q1")
        self.assertEqual(memory[0]["output"], "a1")
        self.assertNotIn("input", memory[1])
        self.assertEqual(memory[1]["output"], "t1")

    @patch("brain.os.path.exists")
    @patch("builtins.open")
    def test_load_facts_invalid_jsonl(self, mock_file, mock_exists):
        mock_exists.return_value = True
        file_content = (
            "invalid json\n" +
            json.dumps({"question": "q1", "answer": "a1"}) + "\n"
        )
        mock_file.return_value.__enter__.return_value = StringIO(file_content)

        count = load_facts(files=["dummy.jsonl"])
        self.assertEqual(count, 1)
        self.assertEqual(len(memory), 1)

    @patch("brain._append_jsonl")
    def test_add_fact(self, mock_append_jsonl):
        initial_memory_len = len(memory)
        add_fact("new question", "new answer")
        self.assertEqual(len(memory), initial_memory_len + 1)
        self.assertEqual(memory[0]["input"], "new question")
        self.assertEqual(memory[0]["output"], "new answer")
        mock_append_jsonl.assert_called_once()

    def test_format_snippet(self):
        # Test that _format_snippet replaces newlines with spaces
        fact = {"input": "test question", "output": "test answer"}
        result = _format_snippet(fact)
        self.assertEqual(result, "Q: test question A: test answer")

    def test_get_facts_lexical_fallback(self):
        # Ensure TF-IDF is disabled
        CONFIG["retrieval"] = "lexical"

        # Populate memory for testing
        memory.append({"input": "apple pie", "output": "delicious"})
        memory.append({"input": "banana bread", "output": "tasty"})
        memory.append({"input": "apple juice", "output": "refreshing"})

        facts = get_facts("apple", k=2)

        self.assertEqual(len(facts), 2)
        # _format_snippet replaces \n with space
        self.assertIn("Q: apple pie A: delicious", facts)
        self.assertIn("Q: apple juice A: refreshing", facts)

    @patch("brain._ensure_tfidf")
    def test_get_facts_tfidf_with_memory(self, mock_ensure_tfidf):
        # Test TF-IDF path by mocking the globals
        import brain

        # Populate memory
        memory.append({"input": "fact1", "output": "output1"})
        memory.append({"input": "fact2", "output": "output2"})
        memory.append({"input": "fact3", "output": "output3"})

        # Create mock vectorizer and matrix
        mock_vectorizer = MagicMock()
        mock_matrix = MagicMock()

        # Mock transform to return something
        mock_query_vec = MagicMock()
        mock_vectorizer.transform.return_value = mock_query_vec

        # Patch the globals and sklearn import
        with patch.object(brain, '_tfidf_vectorizer', mock_vectorizer):
            with patch.object(brain, '_tfidf_matrix', mock_matrix):
                with patch('sklearn.metrics.pairwise.cosine_similarity') as mock_cosine:
                    # Mock cosine similarity scores
                    mock_cosine.return_value.ravel.return_value = [0.9, 0.1, 0.5]

                    CONFIG["retrieval"] = "embed"
                    facts = get_facts("test query", k=2)

                    mock_ensure_tfidf.assert_called_once()
                    # Should return top 2 by score (indices 0 and 2)
                    self.assertEqual(len(facts), 2)

if __name__ == '__main__':
    unittest.main()
