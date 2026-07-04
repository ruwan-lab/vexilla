"""Tests for classify.py — active/background classification heuristic."""

from vexilla.collector.classify import classify


class TestClassify:
    def test_firefox_active(self):
        """Firefox is a known interactive app."""
        is_bg, evidence = classify("firefox", "/usr/lib/firefox/firefox", 1000)
        assert is_bg == 0
        assert "interactive" in evidence
        assert "firefox" in evidence

    def test_root_is_background(self):
        """Process running as root (uid=0) is background."""
        is_bg, evidence = classify("some-process", "/usr/bin/some-process", 0)
        assert is_bg == 1
        assert "root process" in evidence

    def test_system_daemon_background(self):
        """systemd-resolved is a known daemon."""
        is_bg, evidence = classify("systemd-resolved", "/usr/lib/systemd/systemd-resolved", 1000)
        assert is_bg == 1
        assert "system daemon" in evidence

    def test_apt_background(self):
        """apt is a known background updater."""
        is_bg, evidence = classify("apt", "/usr/bin/apt", 0)
        assert is_bg == 1
        assert "root process" in evidence or "system daemon" in evidence

    def test_sbin_path_background(self):
        """Process with /usr/sbin/ exe path is system binary."""
        is_bg, evidence = classify("custom-daemon", "/usr/sbin/custom-daemon", 1000)
        assert is_bg == 1
        assert "system binary" in evidence

    def test_unknown_process_default_active(self):
        """Unknown process defaults to active (conservative)."""
        is_bg, evidence = classify("my-custom-app", "/home/user/my-custom-app", 1000)
        assert is_bg == 0
        assert "default active" in evidence

    def test_slack_active(self):
        """Slack is a known interactive app."""
        is_bg, evidence = classify("slack", "/usr/lib/slack/slack", 1000)
        assert is_bg == 0
        assert "interactive" in evidence

    def test_NetworkManager_background(self):
        """NetworkManager is background."""
        is_bg, evidence = classify("NetworkManager", "/usr/sbin/NetworkManager", 1000)
        assert is_bg == 1
        assert "system daemon" in evidence or "system binary" in evidence
