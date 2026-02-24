from __future__ import annotations

import sys
from pathlib import Path
import unittest

WORKER_ROOT = Path(__file__).resolve().parents[1]
if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))

from app.llm.openai_client import extract_chat_message_text  # noqa: E402


class OpenAIClientTests(unittest.TestCase):
    def test_extract_chat_message_text_supports_string(self) -> None:
        self.assertEqual(extract_chat_message_text('{"ok":1}'), '{"ok":1}')

    def test_extract_chat_message_text_supports_content_parts(self) -> None:
        content = [
            {"type": "text", "text": '{"lead_profile":"x"'},
            {"type": "text", "text": ',"quick_wins":[]}'},
        ]
        self.assertEqual(extract_chat_message_text(content), '{"lead_profile":"x","quick_wins":[]}')

    def test_extract_chat_message_text_ignores_unknown(self) -> None:
        self.assertEqual(extract_chat_message_text([{"type": "image"}]), "")


if __name__ == "__main__":
    unittest.main()

