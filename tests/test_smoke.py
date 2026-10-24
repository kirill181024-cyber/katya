"""
Fast, offline smoke tests for Katya 2.11.0.

Run:
    python -m unittest discover -s tests -v

No GUI, microphone, network or Ollama is required.
"""

from __future__ import annotations

import time
import unittest
from pathlib import Path

import config
from core.brain import Brain, SelfEvolution, _ALLOWED_MODULES
from core.echo_guard import EchoGuard
from core.tts import sanitize_for_speech
from skills.marvel_protocols import BossKeyProtocol, OverclockProtocol


class ConfigTests(unittest.TestCase):
    def test_version_and_models(self) -> None:
        self.assertEqual(config.APP_VERSION, "2.11.0")
        self.assertIn("qwen2.5:7b", config.MODEL_FAST)
        self.assertTrue(config.MODEL_LIGHT)
        self.assertTrue(config.MODEL_VISION)

    def test_no_hardcoded_github_token(self) -> None:
        source = (config.ROOT_DIR / "config.py").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"ghp_[A-Za-z0-9]{20,}")
        self.assertIn('os.getenv("GITHUB_TOKEN"', source)

    def test_settings_roundtrip(self) -> None:
        settings = config.load_settings()
        self.assertEqual(settings["version"], config.APP_VERSION)
        self.assertIn(settings["provider"], config.PROVIDERS)


class EchoGuardTests(unittest.TestCase):
    def test_gate_and_fingerprint(self) -> None:
        guard = EchoGuard(cooldown_seconds=0.4)
        guard.reset()
        guard.begin_speech("Катя, у тебя два кулдауна в запасе")
        self.assertTrue(guard.is_speaking)
        self.assertTrue(guard.should_ignore("у тебя два кулдауна в запасе"))
        self.assertFalse(guard.should_ignore("совершенно другой текст"))
        guard.end_speech()
        self.assertTrue(guard.is_mic_gated())
        time.sleep(0.45)
        self.assertFalse(guard.is_mic_gated())
        guard.reset()


class TextTests(unittest.TestCase):
    def test_tts_sanitizer(self) -> None:
        clean = sanitize_for_speech("**Привет**, `код` https://example.com 😀")
        self.assertNotIn("**", clean)
        self.assertNotIn("https://", clean)
        self.assertIn("Привет", clean)

    def test_brain_provider_build(self) -> None:
        brain = Brain()
        provider = brain._build_provider("local")
        self.assertEqual(provider.kind, "ollama")
        self.assertEqual(provider.model, config.MODEL_FAST)


class ProtocolTests(unittest.TestCase):
    def test_reports_are_safe_read_only(self) -> None:
        overclock = OverclockProtocol()
        boss = BossKeyProtocol()
        self.assertIn("boosted_processes", overclock.report())
        self.assertIn("hotkey", boss.report())
        self.assertFalse(overclock.active)
        self.assertFalse(boss.active)


class SelfEvolutionTests(unittest.TestCase):
    def test_allowlist(self) -> None:
        evolution = SelfEvolution()
        self.assertNotIn("core.echo_guard", evolution.list_modules())
        self.assertTrue(all(module in _ALLOWED_MODULES for module in evolution.list_modules()))

    def test_heal_is_offline(self) -> None:
        report = SelfEvolution().heal()
        self.assertEqual(report["checked"], len(_ALLOWED_MODULES))
        self.assertTrue(report["ok"], report)


class PathTests(unittest.TestCase):
    def test_vosk_short_path(self) -> None:
        from core.stt import vosk_compatible_path

        value = vosk_compatible_path(Path(config.ROOT_DIR))
        self.assertIsInstance(value, str)
        self.assertTrue(value)


if __name__ == "__main__":
    unittest.main()
