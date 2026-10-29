import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch


AVATAR_DEFAULTS = {
    "XFYUN_AVATAR_LINGXIAOCHAN_ID": "111322001",
    "XFYUN_AVATAR_WUCHANSHI_ID": "111182004",
    "XFYUN_AVATAR_XUANZANG_ID": "111140001",
    "XFYUN_AVATAR_ZHAOPUCHU_ID": "111286001",
    "XFYUN_AVATAR_XIAOWAN_ID": "111259001",
}


class AvatarSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.environment = patch.dict(os.environ, {}, clear=True)
        cls.environment.start()
        cls.dotenv = patch("pydantic_settings.sources.read_env_file", return_value={})
        cls.dotenv.start()
        config_path = Path(__file__).resolve().parents[1] / "app" / "config.py"
        spec = importlib.util.spec_from_file_location("public_release_config", config_path)
        assert spec is not None and spec.loader is not None
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.dotenv.stop()
        cls.environment.stop()

    def test_unset_avatar_ids_use_safe_defaults(self) -> None:
        settings = self.module.Settings(_env_file=None)

        for name, expected in AVATAR_DEFAULTS.items():
            with self.subTest(name=name):
                self.assertEqual(getattr(settings, name), expected)

    def test_blank_avatar_ids_use_safe_defaults(self) -> None:
        for name, expected in AVATAR_DEFAULTS.items():
            for blank in ("", "   \t"):
                with self.subTest(name=name, blank=repr(blank)):
                    settings = self.module.Settings(_env_file=None, **{name: blank})
                    self.assertEqual(getattr(settings, name), expected)

    def test_explicit_avatar_ids_are_preserved(self) -> None:
        overrides = {name: f"custom-{index}" for index, name in enumerate(AVATAR_DEFAULTS)}

        settings = self.module.Settings(_env_file=None, **overrides)

        for name, expected in overrides.items():
            with self.subTest(name=name):
                self.assertEqual(getattr(settings, name), expected)


if __name__ == "__main__":
    unittest.main()
