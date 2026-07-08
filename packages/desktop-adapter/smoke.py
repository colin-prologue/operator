"""Manual smoke test for the desktop adapter. Run after every Claude
Desktop update:

    uv run python packages/desktop-adapter/smoke.py

Exercises: (1) open() prefills a chat via claude://, (2) after a pause for
the app to focus, send() issues the final Enter. Verify by eye that the
message actually sent. Requires the Accessibility grant for the terminal
(System Settings > Privacy & Security > Accessibility)."""

import time

from operator_desktop_adapter import adapter

if __name__ == "__main__":
    adapter.open("claude://claude.ai/new?q=smoke%20test%20from%20operator")
    print("deep link fired; waiting 5s for Claude Desktop to focus…")
    time.sleep(5)
    adapter.send()
    print("Enter sent. Check Claude Desktop: the message should be sent.")
