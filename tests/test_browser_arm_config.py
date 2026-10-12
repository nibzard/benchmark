import os
import unittest

from browsers import provider_arm_config, steel
from run_framework_eval import _browser_arm_fields

# Env vars that define a Steel "arm"; saved/restored per test for isolation.
STEEL_ENV_VARS = (
    "STEEL_SOLVE_CAPTCHA",
    "STEEL_USE_STEALTH",
    "STEEL_REGION",
    "STEEL_PROXY_COUNTRY",
    "STEEL_PROXY_STATE",
    "STEEL_PROXY_CITY",
)


class SteelArmConfigTest(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in STEEL_ENV_VARS}
        for k in STEEL_ENV_VARS:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_defaults_solver_on_stealth_off(self):
        cfg = steel.arm_config()
        # Steel's captcha solver defaults ON; stealth defaults OFF.
        self.assertTrue(cfg["solver_state"])
        self.assertFalse(cfg["stealth"])
        self.assertIsNone(cfg["region"])
        self.assertIsNone(cfg["proxy"])

    def test_solver_disabled_is_reflected(self):
        os.environ["STEEL_SOLVE_CAPTCHA"] = "false"
        cfg = steel.arm_config()
        self.assertFalse(cfg["solver_state"])

    def test_full_arm_snapshot(self):
        os.environ["STEEL_SOLVE_CAPTCHA"] = "false"
        os.environ["STEEL_USE_STEALTH"] = "true"
        os.environ["STEEL_REGION"] = "iad"
        os.environ["STEEL_PROXY_COUNTRY"] = "US"
        self.assertEqual(
            steel.arm_config(),
            {
                "solver_state": False,
                "stealth": True,
                "region": "iad",
                "proxy": {"country": "US", "state": None, "city": None},
            },
        )

    def test_proxy_partial_geolocation(self):
        os.environ["STEEL_PROXY_COUNTRY"] = "US"
        os.environ["STEEL_PROXY_STATE"] = "NY"
        cfg = steel.arm_config()
        self.assertEqual(
            cfg["proxy"], {"country": "US", "state": "NY", "city": None}
        )


class ProviderArmConfigTest(unittest.TestCase):
    def test_passthrough_matches_provider_module(self):
        os.environ["STEEL_SOLVE_CAPTCHA"] = "true"
        try:
            self.assertEqual(provider_arm_config("steel"), steel.arm_config())
        finally:
            os.environ.pop("STEEL_SOLVE_CAPTCHA", None)

    def test_integrated_browser_returns_empty(self):
        # "browser-use-cloud" is the native path, not a registered provider.
        self.assertEqual(provider_arm_config("browser-use-cloud"), {})

    def test_provider_without_arm_config_returns_empty(self):
        # A real provider that does not opt into arm_config().
        self.assertEqual(provider_arm_config("local_headless"), {})

    def test_unknown_provider_returns_empty(self):
        self.assertEqual(provider_arm_config("does-not-exist"), {})


class BrowserArmFieldsTest(unittest.TestCase):
    def test_steel_solver_state_surfaces_top_level(self):
        os.environ["STEEL_SOLVE_CAPTCHA"] = "false"
        try:
            fields = _browser_arm_fields("steel")
        finally:
            os.environ.pop("STEEL_SOLVE_CAPTCHA", None)
        self.assertIn("browser_config", fields)
        self.assertIn("solver_state", fields)
        self.assertFalse(fields["solver_state"])
        self.assertFalse(fields["browser_config"]["solver_state"])

    def test_provider_without_arm_has_empty_snapshot(self):
        fields = _browser_arm_fields("local_headless")
        self.assertEqual(fields["browser_config"], {})
        self.assertIsNone(fields["solver_state"])


if __name__ == "__main__":
    unittest.main()
