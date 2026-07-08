from unittest.mock import patch

import pytest

from operator_desktop_adapter import adapter


def test_open_fires_the_os_url_handler():
    with patch("operator_desktop_adapter.adapter.subprocess.run") as run:
        adapter.open("claude://claude.ai/new?q=hello")
        run.assert_called_once_with(
            ["/usr/bin/open", "claude://claude.ai/new?q=hello"], check=True)


def test_open_rejects_non_claude_schemes():
    for bad in ("https://example.com", "file:///etc/passwd", "osascript://x"):
        with pytest.raises(ValueError):
            adapter.open(bad)


def test_module_import_does_not_require_quartz():
    # send() imports Quartz lazily; module import must succeed anywhere
    assert hasattr(adapter, "send")
