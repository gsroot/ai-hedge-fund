from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / ".agents" / "skills" / "predict" / "scripts" / "provider_readiness.py"
SPEC = importlib.util.spec_from_file_location("provider_readiness", MODULE_PATH)
provider_readiness = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = provider_readiness
SPEC.loader.exec_module(provider_readiness)


class ProviderReadinessTests(unittest.TestCase):
    def test_http_failures_are_structured(self):
        self.assertEqual(provider_readiness.classify_http_status(401), "auth_failed")
        self.assertEqual(provider_readiness.classify_http_status(403), "auth_failed")
        self.assertEqual(provider_readiness.classify_http_status(408), "timeout")
        self.assertEqual(provider_readiness.classify_http_status(429), "quota_exceeded")
        self.assertEqual(provider_readiness.classify_http_status(503), "unavailable")
        self.assertEqual(provider_readiness.classify_http_status(200), "ready")

    def test_missing_credentials_are_names_not_secret_values(self):
        missing = provider_readiness.missing_credentials(
            ["DART_API_KEY", "NAVER_CLIENT_ID"],
            {"DART_API_KEY": "configured-secret"},
        )
        self.assertEqual(missing, ["NAVER_CLIENT_ID"])
        self.assertNotIn("configured-secret", repr(missing))

    def test_empty_sample_is_not_a_valid_numeric_zero(self):
        status, missing = provider_readiness.assess_sample(
            {}, required_fields=["value"], rows=0
        )
        self.assertEqual(status, "empty_sample")
        self.assertEqual(missing, ["value"])

    def test_schema_mismatch_lists_missing_fields(self):
        status, missing = provider_readiness.assess_sample(
            {"meta": {"symbol": "AAPL"}},
            required_fields=["meta.symbol", "timestamp"],
            rows=1,
        )
        self.assertEqual(status, "schema_mismatch")
        self.assertEqual(missing, ["timestamp"])

    def test_valid_sample_can_contain_numeric_zero(self):
        status, missing = provider_readiness.assess_sample(
            {"value": 0}, required_fields=["value"], rows=1
        )
        self.assertEqual(status, "ready")
        self.assertEqual(missing, [])

    def test_stale_sample_is_not_ready_or_numeric_zero(self):
        result = provider_readiness.apply_staleness(
            {"status": "ready", "data_as_of": "2026-07-01"},
            requested_as_of="2026-08-27",
            max_lag_days=7,
        )
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["error"]["kind"], "stale")
        self.assertGreater(result["error"]["lag_days"], 7)

    def test_inventory_covers_krx_and_sp500_runtime_sources(self):
        provider_ids = {
            item["provider_id"] for item in provider_readiness.PROVIDER_INVENTORY
        }
        self.assertEqual(
            provider_ids,
            {
                "dart",
                "krx_open_api",
                "finance_data_reader",
                "pykrx",
                "naver_news",
                "yahoo_chart",
                "wikipedia_sp500",
            },
        )

    def test_missing_readiness_is_explicit_not_numeric_neutral(self):
        policy = provider_readiness.build_provider_readiness_policy(
            None, market_scope="krx", analysis_date="2026-08-28"
        )
        self.assertEqual(policy["mode"], "not_provided")
        self.assertFalse(policy["all_samples_ready"])
        self.assertEqual(
            policy["ranking_policy"],
            "missing_evidence_requires_prior_or_explanation_only",
        )

    def test_readiness_policy_rejects_future_sample(self):
        with self.assertRaisesRegex(ValueError, "cannot exceed analysis_date"):
            provider_readiness.build_provider_readiness_policy(
                {
                    "schema_version": 1,
                    "contract_id": "provider_readiness_v1",
                    "requested_as_of": "2026-08-29",
                    "samples": [],
                },
                market_scope="krx",
                analysis_date="2026-08-28",
            )


if __name__ == "__main__":
    unittest.main()
