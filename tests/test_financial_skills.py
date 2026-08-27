from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PREDICT_SCRIPTS = ROOT / ".agents" / "skills" / "predict" / "scripts"
PORTFOLIO_REPORT_SCRIPTS = (
    ROOT / ".agents" / "skills" / "portfolio-report" / "scripts"
)
INVESTOR_ANALYSIS_SCRIPTS = (
    ROOT / ".agents" / "skills" / "investor-analysis" / "scripts"
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if str(PREDICT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PREDICT_SCRIPTS))
if str(PORTFOLIO_REPORT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PORTFOLIO_REPORT_SCRIPTS))

backtest = load_module(
    "financial_skill_backtest",
    ROOT / ".agents" / "skills" / "backtesting" / "scripts" / "backtest.py",
)
portfolio_report = load_module(
    "financial_skill_portfolio_report",
    ROOT / ".agents" / "skills" / "portfolio-report" / "scripts" / "generate_portfolio_report.py",
)
market_regime = load_module(
    "market_regime",
    PORTFOLIO_REPORT_SCRIPTS / "market_regime.py",
)
risk_builder = load_module(
    "financial_skill_risk_builder",
    ROOT / ".agents" / "skills" / "portfolio-report" / "scripts" / "build_risk_snapshot.py",
)
walk_forward = load_module(
    "financial_skill_walk_forward",
    ROOT / ".agents" / "skills" / "backtesting" / "scripts" / "walk_forward.py",
)
sec_point_in_time = load_module(
    "financial_skill_sec_point_in_time",
    PREDICT_SCRIPTS / "sec_point_in_time.py",
)
multifactor_walk_forward = load_module(
    "financial_skill_multifactor_walk_forward",
    ROOT
    / ".agents"
    / "skills"
    / "backtesting"
    / "scripts"
    / "multifactor_walk_forward.py",
)
ridge_walk_forward = load_module(
    "financial_skill_ridge_walk_forward",
    ROOT
    / ".agents"
    / "skills"
    / "backtesting"
    / "scripts"
    / "ridge_walk_forward.py",
)
predict_data = load_module(
    "financial_skill_predict_data",
    PREDICT_SCRIPTS / "data_fetcher.py",
)
korean_data = load_module(
    "financial_skill_korean_data",
    PREDICT_SCRIPTS / "korean_data_fetcher.py",
)
news_sentiment = load_module(
    "financial_skill_news_sentiment",
    INVESTOR_ANALYSIS_SCRIPTS / "analyze_news_sentiment.py",
)
news_enrichment = load_module(
    "financial_skill_news_enrichment",
    PREDICT_SCRIPTS / "news_sentiment_enrichment.py",
)
factor_scoring = load_module(
    "financial_skill_factor_scoring",
    PREDICT_SCRIPTS / "factor_scoring.py",
)
predict_analysis = load_module(
    "financial_skill_predict_analysis",
    PREDICT_SCRIPTS / "analysis.py",
)
factor_evidence_policy = load_module(
    "financial_skill_factor_evidence_policy",
    PREDICT_SCRIPTS / "factor_evidence.py",
)
factor_evidence_validation = load_module(
    "financial_skill_factor_evidence_validation",
    ROOT / ".agents" / "skills" / "backtesting" / "scripts" / "factor_evidence.py",
)


def rich_news_classification(
    article_index: int,
    sentiment: str,
    confidence: float,
    *,
    relevance: str = "relevant",
    event_type: str = "other",
    surprise: str = "unknown",
    impact_horizon: str = "short",
    abstain: bool = False,
    reasoning: str = "test classification",
):
    return {
        "article_index": article_index,
        "relevance": relevance,
        "event_type": event_type,
        "sentiment": sentiment,
        "surprise": surprise,
        "impact_horizon": impact_horizon,
        "confidence": confidence,
        "abstain": abstain,
        "reasoning": reasoning,
    }


def passing_news_validation():
    return {
        "schema_version": 2,
        "classifier_policy_id": "news_event_v2",
        "validation_decision": {
            "accuracy_validated": True,
            "evidence_grade": "strong",
            "gates": {
                "semantic": {
                    "gold_sample_size": 120,
                    "macro_f1": 0.75,
                    "class_recalls": {
                        "positive": 0.75,
                        "negative": 0.72,
                        "neutral": 0.74,
                    },
                },
                "predictive": {
                    "directional_event_count": 100,
                    "wilson_lower_bound": 0.51,
                    "positive_mean_abnormal_return": 0.01,
                    "negative_mean_abnormal_return": -0.01,
                    "long_short_abnormal_return": 0.02,
                    "beats_neutral_baseline_5d": True,
                    "beats_neutral_baseline_20d": True,
                },
                "portfolio": {
                    "independent_holdout_windows": 2,
                    "net_excess_return_delta": 0.01,
                    "sharpe_delta": 0.1,
                },
            },
        },
    }


def passing_sentiment_factor_policy():
    return {
        "schema_version": 1,
        "factor_spec_id": "predict_factor_v1",
        "mode": "evidence_shrunk",
        "validity": {
            "point_in_time": True,
            "signal_before_execution": True,
            "execution_before_label_end": True,
            "independent_holdout": True,
        },
        "factors": {
            "sentiment": {
                "grade": "robust",
                "metrics": {
                    "data_coverage": 1.0,
                    "oos_periods": 40,
                    "mean_rank_ic": 0.08,
                    "rank_ic_ci_low": 0.02,
                    "positive_ic_rate": 0.65,
                    "net_top_vs_universe_total_return": 0.12,
                    "ablation_net_total_return_delta": 0.03,
                },
            }
        },
    }


class PointInTimeTests(unittest.TestCase):
    def test_agent_and_claude_skill_mirrors_match(self):
        relative_paths = (
            Path("predict/scripts/korean_data_fetcher.py"),
            Path("portfolio-report/scripts/build_risk_snapshot.py"),
            Path("portfolio-report/scripts/generate_portfolio_report.py"),
            Path("predict/scripts/news_sentiment_enrichment.py"),
            Path("predict/scripts/analysis.py"),
            Path("predict/scripts/analyze_stocks.py"),
            Path("predict/scripts/config.py"),
            Path("predict/scripts/factor_evidence.py"),
            Path("predict/SKILL.md"),
            Path("predict/references/news_validation_contract.md"),
            Path("backtesting/scripts/factor_evidence.py"),
            Path("backtesting/SKILL.md"),
            Path("backtesting/references/factor_evidence_contract.md"),
            Path("investor-analysis/scripts/analyze_news_sentiment.py"),
            Path("investor-analysis/SKILL.md"),
            Path("investor-analysis/references/analyst_personas.md"),
        )

        for relative_path in relative_paths:
            with self.subTest(path=str(relative_path)):
                agent_path = ROOT / ".agents" / "skills" / relative_path
                claude_path = ROOT / ".claude" / "skills" / relative_path
                self.assertEqual(agent_path.read_bytes(), claude_path.read_bytes())

    def test_api_modules_load_project_root_dotenv_without_override(self):
        module_paths = (
            PREDICT_SCRIPTS / "korean_data_fetcher.py",
            PREDICT_SCRIPTS / "financial_datasets_api.py",
            PREDICT_SCRIPTS / "sec_point_in_time.py",
        )

        for index, module_path in enumerate(module_paths):
            with self.subTest(module=module_path.name):
                with patch("dotenv.load_dotenv") as mocked_load:
                    load_module(f"dotenv_probe_{index}", module_path)
                mocked_load.assert_called_once_with(ROOT / ".env", override=False)

    def test_news_sentiment_prepares_work_for_active_skill_llm(self):
        news = {
            "company_news": [
                {"title": "already classified", "sentiment": "positive"},
                *[
                    {"title": f"headline {index}", "date": f"2025-01-{index + 1:02d}"}
                    for index in range(8)
                ],
            ]
        }

        prepared = news_sentiment.prepare_news_for_llm(news, "TEST")

        self.assertEqual(prepared["classification_source"], "active_skill_llm")
        self.assertEqual(len(prepared["articles"]), 5)
        self.assertEqual(
            [article["article_index"] for article in prepared["articles"]],
            [0, 1, 2, 3, 4],
        )
        self.assertIn("외부 모델 API를 호출", prepared["instruction"])
        schema = prepared["response_schema"]["classifications"][0]
        self.assertIn("relevance", schema)
        self.assertIn("event_type", schema)
        self.assertIn("impact_horizon", schema)
        self.assertIn("abstain", schema)

    def test_news_sentiment_deduplicates_headlines_and_links_before_llm(self):
        news = {
            "company_news": [
                {"title": "같은 기사", "link": "https://news.test/a?tracking=1"},
                {"title": "같은 기사!", "link": "https://news.test/b"},
                {"title": "다른 제목", "link": "https://news.test/a?tracking=2"},
                {"title": "고유 기사", "link": "https://news.test/c"},
            ]
        }

        prepared = news_sentiment.prepare_news_for_llm(news, "TEST")

        self.assertEqual(prepared["duplicates_removed"], 2)
        self.assertEqual(
            [article["article_index"] for article in prepared["articles"]],
            [0, 3],
        )

    def test_news_sentiment_aggregates_active_llm_classifications(self):
        news = {
            "company_news": [
                {"title": "existing positive", "sentiment": "positive"},
                {"title": "good news"},
                {"title": "bad news"},
                {"title": "unclear news"},
                {"title": "stock price rose today"},
            ]
        }
        classifications = [
            rich_news_classification(
                0,
                "positive",
                85,
                event_type="other",
                surprise="unknown",
                reasoning="rechecked legacy label",
            ),
            rich_news_classification(
                1,
                "positive",
                90,
                event_type="contract",
                surprise="positive",
                reasoning="positive catalyst",
            ),
            rich_news_classification(
                2,
                "negative",
                80,
                event_type="legal_regulatory",
                surprise="negative",
                reasoning="negative catalyst",
            ),
            {
                "article_index": 3,
                "sentiment": "invalid",
                "confidence": 100,
            },
            rich_news_classification(
                4,
                "positive",
                95,
                event_type="market_price_recap",
                surprise="none",
                impact_horizon="intraday",
            ),
        ]

        result = news_sentiment.analyze_news_sentiment(
            news,
            "TEST",
            classifications,
        )

        self.assertEqual(result["signal"], "bullish")
        self.assertEqual(result["metrics"]["bullish_articles"], 2)
        self.assertEqual(result["metrics"]["bearish_articles"], 1)
        self.assertEqual(result["metrics"]["articles_classified_by_llm"], 4)
        self.assertEqual(result["metrics"]["actionable_llm_articles"], 3)
        self.assertEqual(result["metrics"]["excluded_llm_articles"], 1)
        self.assertEqual(result["metrics"]["articles_pending_llm"], 1)
        self.assertEqual(result["metrics"]["legacy_sentiment_labels_ignored"], 1)
        self.assertEqual(result["decision_use"], "risk_and_explanation_only")
        self.assertEqual(len(result["risk_flags"]), 1)

    def test_news_sentiment_has_no_external_model_dependency(self):
        source = (
            INVESTOR_ANALYSIS_SCRIPTS / "analyze_news_sentiment.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("OPENAI_API_KEY", source)
        self.assertNotIn("gpt-4o-mini", source)
        self.assertNotIn("from openai import", source)
        self.assertNotIn("chat.completions.create", source)

        enrichment_source = (
            PREDICT_SCRIPTS / "news_sentiment_enrichment.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("OPENAI_API_KEY", enrichment_source)
        self.assertNotIn("from openai import", enrichment_source)

    def test_keyword_sentiment_uses_coverage_and_has_no_tie_bias(self):
        sparse_positive = [{"title": "record profit"}] + [
            {"title": f"일반 뉴스 {index}"}
            for index in range(9)
        ]
        balanced = [
            {"title": "record profit"},
            {"title": "fraud investigation"},
        ]

        sparse_score, _ = factor_scoring.calculate_sentiment_score(sparse_positive)
        balanced_score, _ = factor_scoring.calculate_sentiment_score(balanced)

        self.assertAlmostEqual(sparse_score, 5.3)
        self.assertEqual(balanced_score, 5.0)

    def test_keyword_sentiment_prefers_existing_classification(self):
        score, factors = factor_scoring.calculate_sentiment_score(
            [
                {"title": "fraud investigation", "sentiment": "positive"},
                {"title": "일반 기사", "sentiment": "neutral"},
            ]
        )

        self.assertEqual(score, 6.5)
        self.assertTrue(any("coverage: 2/2" in factor for factor in factors))

    def test_unvalidated_keyword_sentiment_is_rank_neutral(self):
        self.assertEqual(predict_analysis.ranking_sentiment_score(9.5), 5.0)
        self.assertEqual(predict_analysis.ranking_sentiment_score(1.0), 5.0)
        self.assertEqual(
            predict_analysis.ranking_sentiment_score(
                9.5,
                accuracy_validated=True,
            ),
            9.5,
        )

    def test_default_factor_policy_preserves_prior_relative_weights(self):
        priors = {
            "value": 0.25,
            "growth": 0.20,
            "quality": 0.20,
            "momentum": 0.10,
            "safety": 0.10,
            "sentiment": 0.08,
            "insider": 0.07,
        }

        result = factor_evidence_policy.default_factor_weight_policy(priors)

        self.assertEqual(result["mode"], "prior_only")
        self.assertEqual(result["effective_weights"], priors)
        self.assertTrue(
            all(
                item["grade"] == "unvalidated" and item["multiplier"] == 0.5
                for item in result["factors"].values()
            )
        )

    def test_factor_evidence_recomputes_grades_and_shrinks_relative_weights(self):
        priors = {
            "value": 0.25,
            "growth": 0.20,
            "quality": 0.20,
            "momentum": 0.10,
            "safety": 0.10,
            "sentiment": 0.08,
            "insider": 0.07,
        }
        robust_metrics = {
            "data_coverage": 1.0,
            "oos_periods": 40,
            "mean_rank_ic": 0.08,
            "rank_ic_ci_low": 0.02,
            "positive_ic_rate": 0.65,
            "net_top_vs_universe_total_return": 0.12,
            "ablation_net_total_return_delta": 0.03,
        }
        contradicted_metrics = {
            "data_coverage": 1.0,
            "oos_periods": 40,
            "mean_rank_ic": -0.05,
            "rank_ic_ci_low": -0.10,
            "positive_ic_rate": 0.35,
            "net_top_vs_universe_total_return": -0.08,
            "ablation_net_total_return_delta": -0.02,
        }
        evidence = {
            "schema_version": 1,
            "factor_spec_id": "predict_factor_v1",
            "validation_end": "2025-12-31",
            "applicability": {
                "market_scope": "krx",
                "indices": ["krx"],
                "universe_id": "historical_krx",
            },
            "validity": {
                "point_in_time": True,
                "signal_before_execution": True,
                "execution_before_label_end": True,
                "independent_holdout": True,
            },
            "factors": {
                "value": {"metrics": robust_metrics},
                "growth": {
                    "metrics": contradicted_metrics,
                    "assessment": {"grade": "robust"},
                },
            },
        }

        result = factor_evidence_policy.build_factor_weight_policy(
            priors,
            evidence,
            market_scope="krx",
            index="krx",
            analysis_date="2026-01-02",
        )

        self.assertEqual(result["factors"]["value"]["grade"], "robust")
        self.assertEqual(result["factors"]["growth"]["grade"], "contradicted")
        self.assertEqual(result["effective_weights"]["growth"], 0.0)
        self.assertGreater(result["effective_weights"]["value"], priors["value"])
        self.assertAlmostEqual(sum(result["effective_weights"].values()), 1.0)

    def test_factor_evidence_rejects_wrong_scope_or_future_labels(self):
        priors = {factor: 1 / 7 for factor in factor_evidence_policy.FACTOR_NAMES}
        evidence = {
            "schema_version": 1,
            "factor_spec_id": "predict_factor_v1",
            "validation_end": "2026-01-02",
            "applicability": {
                "market_scope": "us",
                "indices": ["sp500"],
            },
            "validity": {
                "point_in_time": True,
                "signal_before_execution": True,
                "execution_before_label_end": True,
                "independent_holdout": False,
            },
            "factors": {},
        }

        with self.assertRaisesRegex(ValueError, "market_scope"):
            factor_evidence_policy.build_factor_weight_policy(
                priors,
                evidence,
                market_scope="krx",
                index="krx",
                analysis_date="2026-01-03",
            )
        with self.assertRaisesRegex(ValueError, "precede"):
            factor_evidence_policy.build_factor_weight_policy(
                priors,
                evidence,
                market_scope="us",
                index="sp500",
                analysis_date="2026-01-02",
            )

    def test_factor_panel_rejects_lookahead_timing(self):
        rows = []
        for index in range(5):
            row = {
                "signal_date": "2025-01-02",
                "execution_date": "2025-01-02",
                "label_end_date": "2025-02-03",
                "ticker": f"T{index}",
                "forward_return": 0.01 * index,
            }
            row.update({factor: index for factor in factor_evidence_policy.FACTOR_NAMES})
            rows.append(row)

        with self.assertRaisesRegex(ValueError, "signal_date"):
            factor_evidence_validation.validate_factor_panel(pd.DataFrame(rows))

    def test_unified_factor_evidence_finds_synthetic_point_in_time_signal(self):
        rows = []
        execution_dates = pd.date_range("2022-01-03", periods=36, freq="MS")
        for execution_date in execution_dates:
            for ticker_index in range(10):
                row = {
                    "signal_date": execution_date - pd.offsets.BDay(1),
                    "execution_date": execution_date,
                    "label_end_date": execution_date + pd.offsets.MonthBegin(1),
                    "ticker": f"T{ticker_index}",
                    "forward_return": (ticker_index - 4.5) * 0.002,
                    "value": float(ticker_index),
                }
                row.update(
                    {
                        factor: 0.0
                        for factor in factor_evidence_policy.FACTOR_NAMES
                        if factor != "value"
                    }
                )
                rows.append(row)
        priors = {factor: 1 / 7 for factor in factor_evidence_policy.FACTOR_NAMES}

        result = factor_evidence_validation.build_factor_evidence(
            pd.DataFrame(rows),
            priors,
            market_scope="krx",
            applicable_indices=["krx"],
            universe_id="synthetic_historical_krx",
            round_trip_cost_bps=10,
            independent_holdout=True,
            bootstrap_samples=200,
        )

        self.assertTrue(result["validity"]["point_in_time"])
        self.assertEqual(result["methodology"]["round_trip_cost_bps"], 10)
        self.assertEqual(result["factors"]["value"]["assessment"]["grade"], "robust")
        self.assertGreater(
            result["factors"]["value"]["metrics"]["mean_rank_ic"],
            0.9,
        )
        json.dumps(result, allow_nan=False)

    def test_factor_score_accepts_run_specific_effective_weights(self):
        scores = {factor: 1.0 for factor in factor_evidence_policy.FACTOR_NAMES}
        scores["value"] = 9.0
        weights = {factor: 0.0 for factor in factor_evidence_policy.FACTOR_NAMES}
        weights["value"] = 1.0

        self.assertEqual(
            predict_analysis.calculate_weighted_factor_score(scores, weights),
            9.0,
        )

    def test_news_enrichment_prepares_only_top_candidate_pool(self):
        predict_payload = {
            "analysis_date": "2025-01-02",
            "index": "krx",
            "rankings": [
                {"ticker": "A", "rank": 1},
                {"ticker": "B", "rank": 2},
                {"ticker": "C", "rank": 3},
            ],
        }
        news = [{"title": "호실적", "date": "2025-01-02"}]

        with patch.object(news_enrichment, "get_company_news", return_value=news) as fetch:
            tasks = news_enrichment.prepare_candidate_tasks(
                predict_payload,
                candidate_pool=2,
                article_limit=1,
            )

        self.assertEqual([task["ticker"] for task in tasks["tasks"]], ["A", "B"])
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(tasks["schema_version"], 2)
        self.assertEqual(tasks["classifier_policy_id"], "news_event_v2")

    def test_news_enrichment_is_evidence_only_without_passing_validation(self):
        predict_payload = {
            "analysis_date": "2025-01-02",
            "index": "krx",
            "strategy": "hybrid",
            "methodology": "base",
            "factor_weights": {"sentiment": 0.08},
            "factor_weight_policy": passing_sentiment_factor_policy(),
            "rankings": [
                {
                    "ticker": "B",
                    "rank": 1,
                    "total_score": 6.03,
                    "signal": "buy",
                    "score_implied_return_pct": 10.6,
                    "scores": {"sentiment": 5.0, "fundamental": 6.0},
                    "investor_scores": {
                        "buffett": 5.0,
                        "graham": 5.0,
                        "druckenmiller": 5.0,
                    },
                    "factors": [],
                },
                {
                    "ticker": "A",
                    "rank": 2,
                    "total_score": 6.0,
                    "signal": "buy",
                    "score_implied_return_pct": 10.5,
                    "scores": {"sentiment": 5.0, "fundamental": 6.0},
                    "investor_scores": {
                        "buffett": 5.0,
                        "graham": 5.0,
                        "druckenmiller": 5.0,
                    },
                    "factors": [],
                },
            ],
        }
        task_payload = {
            "schema_version": 2,
            "classifier_policy_id": "news_event_v2",
            "analysis_date": "2025-01-02",
            "index": "krx",
            "candidate_pool": 2,
            "tasks": [
                {
                    "ticker": "A",
                    "articles": [
                        {"article_index": 0, "headline": "호실적"},
                        {"article_index": 1, "headline": "수주 확대"},
                    ],
                }
            ],
        }
        classifications = {
            "schema_version": 2,
            "classifier_policy_id": "news_event_v2",
            "analysis_date": "2025-01-02",
            "source": "active_skill_llm",
            "results": [
                {
                    "ticker": "A",
                    "classifications": [
                        rich_news_classification(
                            0,
                            "positive",
                            100,
                            event_type="earnings_surprise",
                            surprise="positive",
                        ),
                        rich_news_classification(
                            1,
                            "positive",
                            100,
                            event_type="contract",
                            surprise="positive",
                        ),
                    ],
                }
            ],
        }

        enriched = news_enrichment.apply_news_sentiment_enrichment(
            predict_payload,
            task_payload,
            classifications,
        )

        self.assertEqual(enriched["rankings"][0]["ticker"], "B")
        self.assertEqual(enriched["rankings"][1]["scores"]["sentiment"], 5.0)
        self.assertAlmostEqual(enriched["rankings"][1]["total_score"], 6.0)
        self.assertEqual(
            enriched["rankings"][1]["sentiment_analysis"]["source"],
            "active_skill_llm",
        )
        self.assertFalse(
            enriched["rankings"][1]["sentiment_analysis"][
                "ranking_contribution_applied"
            ]
        )
        self.assertEqual(
            enriched["news_sentiment_enrichment"]["ranking_policy"],
            "risk_and_explanation_only",
        )
        self.assertFalse(
            enriched["news_sentiment_policy"]["ranking_contribution_applied"]
        )
        self.assertFalse(enriched["news_sentiment_enrichment"]["accuracy_validated"])

    def test_news_enrichment_reranks_only_after_all_validation_gates_pass(self):
        predict_payload = {
            "analysis_date": "2025-01-02",
            "index": "krx",
            "strategy": "hybrid",
            "methodology": "base",
            "factor_weights": {"sentiment": 0.08},
            "factor_weight_policy": passing_sentiment_factor_policy(),
            "rankings": [
                {
                    "ticker": "B",
                    "rank": 1,
                    "total_score": 6.03,
                    "signal": "buy",
                    "score_implied_return_pct": 10.6,
                    "scores": {"sentiment": 5.0, "fundamental": 6.0},
                    "investor_scores": {
                        "buffett": 5.0,
                        "graham": 5.0,
                        "druckenmiller": 5.0,
                    },
                    "factors": [],
                },
                {
                    "ticker": "A",
                    "rank": 2,
                    "total_score": 6.0,
                    "signal": "buy",
                    "score_implied_return_pct": 10.5,
                    "scores": {"sentiment": 5.0, "fundamental": 6.0},
                    "investor_scores": {
                        "buffett": 5.0,
                        "graham": 5.0,
                        "druckenmiller": 5.0,
                    },
                    "factors": [],
                },
            ],
        }
        task_payload = {
            "schema_version": 2,
            "classifier_policy_id": "news_event_v2",
            "analysis_date": "2025-01-02",
            "index": "krx",
            "candidate_pool": 2,
            "tasks": [
                {
                    "ticker": "A",
                    "articles": [
                        {"article_index": 0, "headline": "호실적"},
                        {"article_index": 1, "headline": "수주 확대"},
                    ],
                }
            ],
        }
        classifications = {
            "schema_version": 2,
            "classifier_policy_id": "news_event_v2",
            "analysis_date": "2025-01-02",
            "source": "active_skill_llm",
            "results": [
                {
                    "ticker": "A",
                    "classifications": [
                        rich_news_classification(
                            0,
                            "positive",
                            100,
                            event_type="earnings_surprise",
                            surprise="positive",
                        ),
                        rich_news_classification(
                            1,
                            "positive",
                            100,
                            event_type="contract",
                            surprise="positive",
                        ),
                    ],
                }
            ],
        }

        enriched = news_enrichment.apply_news_sentiment_enrichment(
            predict_payload,
            task_payload,
            classifications,
            passing_news_validation(),
        )

        self.assertEqual(enriched["rankings"][0]["ticker"], "A")
        self.assertEqual(enriched["rankings"][0]["scores"]["sentiment"], 8.0)
        self.assertAlmostEqual(enriched["rankings"][0]["total_score"], 6.07)
        self.assertTrue(
            enriched["news_sentiment_enrichment"]["ranking_contribution_applied"]
        )
        self.assertFalse(enriched["news_sentiment_enrichment"]["calibrated"])
        self.assertTrue(
            enriched["news_sentiment_enrichment"]["validated_for_ranking"]
        )
        self.assertEqual(
            enriched["news_sentiment_policy"]["ranking_policy"],
            "validated_signal",
        )
        self.assertTrue(enriched["news_sentiment_enrichment"]["accuracy_validated"])

    def test_news_validation_gate_rejects_bare_accuracy_flag(self):
        gate = news_enrichment.evaluate_ranking_validation_gate(
            {
                "schema_version": 2,
                "classifier_policy_id": "news_event_v2",
                "validation_decision": {
                    "accuracy_validated": True,
                    "evidence_grade": "strong",
                },
            }
        )

        self.assertFalse(gate["passed"])
        self.assertIn("semantic_gold_sample_below_90", gate["failure_reasons"])
        self.assertIn(
            "portfolio_net_excess_return_not_improved",
            gate["failure_reasons"],
        )

    def test_news_ranking_requires_common_sentiment_factor_evidence(self):
        gate = news_enrichment.evaluate_ranking_validation_gate(
            passing_news_validation()
        )

        self.assertFalse(gate["passed"])
        self.assertIn("factor_evidence_not_applied", gate["failure_reasons"])
        self.assertIn(
            "sentiment_factor_evidence_below_promising",
            gate["failure_reasons"],
        )

    def test_naver_search_news_excludes_future_and_unverifiable_dates(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "items": [
                {
                    "title": "past",
                    "description": "past article",
                    "pubDate": "Tue, 31 Dec 2024 10:00:00 +0900",
                },
                {
                    "title": "cutoff",
                    "description": "cutoff article",
                    "pubDate": "Wed, 01 Jan 2025 23:59:00 +0900",
                },
                {
                    "title": "future",
                    "description": "future article",
                    "pubDate": "Thu, 02 Jan 2025 00:01:00 +0900",
                },
                {
                    "title": "unknown",
                    "description": "unknown date",
                    "pubDate": "not-a-date",
                },
            ]
        }

        with patch.dict(
            "os.environ",
            {"NAVER_CLIENT_ID": "client", "NAVER_CLIENT_SECRET": "secret"},
        ), patch.object(korean_data.requests, "get", return_value=response):
            news = korean_data._fetch_naver_news_api(
                "테스트",
                "2025-01-01",
                limit=30,
            )

        self.assertEqual([item["title"] for item in news], ["past", "cutoff"])
        self.assertTrue(all(item["date"][:10] <= "2025-01-01" for item in news))

    def test_naver_search_auth_failure_disables_repeated_requests(self):
        response = Mock(status_code=401)
        response.raise_for_status.side_effect = korean_data.requests.HTTPError(
            "unauthorized",
            response=response,
        )
        original_disabled = korean_data._naver_search_api_disabled
        korean_data._naver_search_api_disabled = False
        try:
            with patch.dict(
                "os.environ",
                {"NAVER_CLIENT_ID": "client", "NAVER_CLIENT_SECRET": "secret"},
            ), patch.object(
                korean_data.requests,
                "get",
                return_value=response,
            ) as mocked_get, redirect_stdout(io.StringIO()):
                first = korean_data._fetch_naver_news_api("테스트", "2025-01-01")
                second = korean_data._fetch_naver_news_api("테스트", "2025-01-01")

            self.assertEqual(first, [])
            self.assertEqual(second, [])
            mocked_get.assert_called_once()
        finally:
            korean_data._naver_search_api_disabled = original_disabled

    def test_current_korean_valuation_falls_back_to_naver(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "totalInfos": [
                {"code": "per", "value": "11.98배"},
                {"code": "pbr", "value": "3.10배"},
                {"code": "eps", "value": "22,292원"},
                {"code": "bps", "value": "86,052원"},
                {"code": "dividendYieldRatio", "value": "0.63%"},
            ]
        }
        today = korean_data.datetime.now().strftime("%Y-%m-%d")

        with patch.object(korean_data.requests, "get", return_value=response):
            snapshot = korean_data._get_naver_valuation_snapshot("005930", today)

        self.assertEqual(snapshot["price_to_earnings_ratio"], 11.98)
        self.assertEqual(snapshot["price_to_book_ratio"], 3.10)
        self.assertEqual(snapshot["earnings_per_share"], 22292.0)
        self.assertEqual(snapshot["book_value_per_share"], 86052.0)
        self.assertAlmostEqual(snapshot["dividend_yield"], 0.0063)

    def test_historical_korean_valuation_does_not_use_current_naver_data(self):
        with patch.object(korean_data.requests, "get") as mocked_get:
            snapshot = korean_data._get_naver_valuation_snapshot(
                "005930",
                "2020-01-02",
            )

        self.assertTrue(all(value is None for value in snapshot.values()))
        mocked_get.assert_not_called()

    def test_korean_financial_metrics_fall_back_to_krx_market_cap(self):
        pykrx_snapshot = {
            **korean_data._empty_valuation_snapshot(),
            "market_cap": None,
        }
        with patch.object(
            korean_data,
            "_get_pykrx_fundamental",
            return_value=pykrx_snapshot,
        ), patch.object(
            korean_data,
            "_get_naver_valuation_snapshot",
            return_value=korean_data._empty_valuation_snapshot(),
        ), patch.object(
            korean_data,
            "_derive_metrics_from_dart",
            return_value={},
        ), patch.object(
            korean_data,
            "get_market_cap_kr",
            return_value=123_000_000.0,
        ) as mocked_market_cap, patch.object(
            korean_data,
            "_get_company_name",
            return_value="테스트",
        ):
            metrics = korean_data.get_financial_metrics_kr("005930", "2026-08-27")

        self.assertEqual(metrics["market_cap"], 123_000_000.0)
        mocked_market_cap.assert_called_once_with("005930", "2026-08-27")

    def test_naver_finance_fallback_excludes_future_news(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [
            {
                "items": [
                    {"title": "past", "datetime": "202412311200"},
                    {"title": "cutoff", "datetime": "202501012359"},
                    {"title": "future", "datetime": "202501020001"},
                    {"title": "unknown", "datetime": "bad-date"},
                ]
            }
        ]

        with patch.object(korean_data.requests, "get", return_value=response):
            news = korean_data._fetch_naver_finance_news(
                "005930",
                "2025-01-01",
                limit=20,
            )

        self.assertEqual([item["title"] for item in news], ["past", "cutoff"])
        self.assertTrue(all(item["date"][:10] <= "2025-01-01" for item in news))

    def test_price_snapshot_excludes_future_rows(self):
        dates = pd.date_range("2024-01-01", periods=5, freq="D")
        frame = pd.DataFrame(
            {"Open": [10, 11, 12, 13, 14], "Close": [10, 11, 12, 1000, 2000]},
            index=dates,
        )

        snapshot = backtest.slice_price_frame_as_of(frame, "2024-01-03")

        self.assertEqual(snapshot.index.max(), pd.Timestamp("2024-01-03"))
        self.assertEqual(snapshot["Close"].tolist(), [10, 11, 12])

    def test_historical_us_metrics_do_not_call_current_snapshot(self):
        with patch.object(
            predict_data,
            "_fetch_financial_metrics_yf",
            side_effect=AssertionError("current snapshot must not be called"),
        ):
            result = predict_data.get_financial_metrics(
                "AAPL",
                "2020-01-02",
            )

        self.assertEqual(result, [])

    def test_historical_dow_membership_changes_on_effective_date(self):
        before = walk_forward.dow_members_as_of("2018-06-25")
        after = walk_forward.dow_members_as_of("2018-06-26")

        self.assertEqual(len(before), 30)
        self.assertEqual(len(after), 30)
        self.assertIn("GE", before)
        self.assertNotIn("WBA", before)
        self.assertNotIn("GE", after)
        self.assertIn("WBA", after)

    def test_walk_forward_signal_ignores_prices_after_signal_date(self):
        dates = pd.bdate_range("2016-01-01", "2018-02-02")
        members = sorted(walk_forward.dow_members_as_of("2018-01-31"))
        values = {
            ticker: np.linspace(100.0, 100.0 + index * 20.0, len(dates))
            for index, ticker in enumerate(members, start=1)
        }
        closes = pd.DataFrame(values, index=dates)
        opens = closes.copy()
        params = walk_forward.StrategyParams(252, 0, 5)
        weights_before, _ = walk_forward.target_weights_for_date(
            opens, closes, pd.Timestamp("2018-01-31"), pd.Timestamp("2018-02-01"), params, 0.9
        )

        closes.loc[pd.Timestamp("2018-02-02"), members[0]] = 1_000_000.0
        weights_after, _ = walk_forward.target_weights_for_date(
            opens, closes, pd.Timestamp("2018-01-31"), pd.Timestamp("2018-02-01"), params, 0.9
        )

        self.assertEqual(weights_before, weights_after)

    def test_walk_forward_folds_are_non_overlapping_and_forward_only(self):
        folds = walk_forward.make_folds("2018-01-01", "2020-12-31", 3)

        self.assertEqual(len(folds), 3)
        for index, fold in enumerate(folds):
            self.assertLess(fold["train_end"], fold["test_start"])
            if index:
                self.assertLess(folds[index - 1]["test_end"], fold["test_start"])

    def test_paired_bootstrap_preserves_identical_series(self):
        returns = pd.Series(
            np.tile([0.01, -0.005, 0.002], 30),
            index=pd.bdate_range("2020-01-01", periods=90),
        )

        result = walk_forward.paired_block_bootstrap_cagr_difference(
            returns, returns, samples=100
        )

        self.assertAlmostEqual(result["low"], 0.0)
        self.assertAlmostEqual(result["median"], 0.0)
        self.assertAlmostEqual(result["high"], 0.0)
        self.assertEqual(result["probability_greater_than_zero"], 0.0)

    def test_sec_snapshot_excludes_restatement_filed_after_cutoff(self):
        payload = {
            "cik": 1,
            "entityName": "Synthetic",
            "facts": {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {
                            "USD": [
                                {
                                    "start": "2019-01-01",
                                    "end": "2019-12-31",
                                    "val": 100.0,
                                    "filed": "2020-02-15",
                                    "form": "10-K",
                                    "fp": "FY",
                                },
                                {
                                    "start": "2019-01-01",
                                    "end": "2019-12-31",
                                    "val": 999.0,
                                    "filed": "2022-02-15",
                                    "form": "10-K/A",
                                    "fp": "FY",
                                },
                            ]
                        }
                    }
                }
            },
        }

        snapshot = sec_point_in_time.fundamental_snapshot(
            payload, "2021-01-01", raw_market_price=10.0
        )

        self.assertEqual(snapshot["values"]["revenue"], 100.0)
        self.assertTrue(all(date <= "2021-01-01" for date in snapshot["filed_dates_used"]))

    def test_sec_cik_mapping_switches_at_legal_entity_change(self):
        self.assertEqual(sec_point_in_time.cik_for_ticker("DD", "2017-08-31"), 30554)
        self.assertEqual(sec_point_in_time.cik_for_ticker("DD", "2017-09-01"), 1666700)
        self.assertEqual(sec_point_in_time.cik_for_ticker("DIS", "2019-03-19"), 1001039)
        self.assertEqual(sec_point_in_time.cik_for_ticker("DIS", "2019-03-20"), 1744489)
        self.assertEqual(sec_point_in_time.cik_for_ticker("GOOGL", "2026-06-29"), 1652044)

    def test_multifactor_allocator_never_breaks_name_cap(self):
        weights = multifactor_walk_forward._capped_allocation(
            {f"T{index}": 10.0 - index for index in range(10)}, 1.0, cap=0.15
        )

        self.assertLessEqual(max(weights.values()), 0.15 + 1e-12)
        self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_multifactor_equal_weight_baseline_uses_available_members(self):
        panel = pd.DataFrame(
            {
                "execution_date": [pd.Timestamp("2020-01-02")] * 3,
                "signal_date": [pd.Timestamp("2019-12-31")] * 3,
                "ticker": ["A", "B", "C"],
            }
        )

        schedule = multifactor_walk_forward.equal_weight_schedule(
            panel, "2020-01-01", "2020-01-31"
        )
        weights = schedule[pd.Timestamp("2020-01-02")]["weights"]

        self.assertEqual(set(weights), {"A", "B", "C"})
        self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_universe_coverage_exposes_missing_historical_member(self):
        panel = pd.DataFrame(
            {
                "execution_date": (
                    [pd.Timestamp("2020-01-02")] * 30
                    + [pd.Timestamp("2020-02-03")] * 29
                ),
                "ticker": [f"T{index}" for index in range(30)]
                + [f"T{index}" for index in range(29)],
            }
        )

        coverage = multifactor_walk_forward.universe_coverage_summary(panel)

        self.assertAlmostEqual(coverage["minimum"], 29 / 30)
        self.assertEqual(coverage["incomplete_months"], 1)
        self.assertEqual(coverage["incomplete_dates"]["2020-02-03"], 29)

    def test_short_independent_edge_is_promising_evidence_not_a_capital_gate(self):
        strategy = {
            "total_return": 0.30,
            "max_drawdown": -0.08,
            "years_observed": 1,
        }
        dia = {"total_return": 0.12, "max_drawdown": -0.10}
        equal = {"total_return": 0.13, "max_drawdown": -0.09}
        paired = {"low": -0.01, "probability_greater_than_zero": 0.93}

        evidence = multifactor_walk_forward.assess_evidence(
            strategy,
            dia,
            equal,
            paired,
            paired,
            {"minimum": 1.0},
            independent_holdout=True,
            oos_observations=160,
        )

        self.assertEqual(evidence["grade"], "promising")
        self.assertEqual(
            evidence["portfolio_construction_effect"],
            "informational-only-does-not-block-output",
        )
        self.assertNotIn("live_capital_allowed", evidence)

    def test_underperforming_candidate_has_weak_evidence(self):
        strategy = {
            "total_return": 0.05,
            "max_drawdown": -0.08,
            "years_observed": 3,
        }
        benchmark = {"total_return": 0.10, "max_drawdown": -0.10}
        paired = {"low": -0.02, "probability_greater_than_zero": 0.40}

        evidence = multifactor_walk_forward.assess_evidence(
            strategy,
            benchmark,
            benchmark,
            paired,
            paired,
            {"minimum": 1.0},
            independent_holdout=True,
            oos_observations=756,
        )

        self.assertEqual(evidence["grade"], "weak")
        self.assertNotIn("decision", evidence)

    def test_portfolio_candidate_keeps_full_model_weights(self):
        model_weights = {f"T{index}": 0.09375 for index in range(8)}
        evidence = {"grade": "promising"}
        regime = {"target_cash_weight": 0.25, "target_equity_weight": 0.75}

        payload = multifactor_walk_forward.portfolio_construction_payload(
            model_weights, evidence, regime
        )

        self.assertEqual(payload["status"], "portfolio-ready")
        self.assertTrue(payload["portfolio_construction_eligible"])
        self.assertEqual(payload["target_total_portfolio_fraction"], 1.0)
        self.assertAlmostEqual(sum(payload["weights"].values()), 0.75)
        self.assertAlmostEqual(payload["cash_weight"], 0.25)
        self.assertEqual(payload["market_regime"], regime)

    def test_supplemental_prices_fill_missing_without_overwriting_vendor_data(self):
        dates = pd.to_datetime(["2020-01-02", "2020-01-03"])
        opens = pd.DataFrame({"WBA": [10.0, np.nan]}, index=dates)
        closes = pd.DataFrame({"WBA": [11.0, np.nan]}, index=dates)
        raw_closes = pd.DataFrame(index=dates)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "WBA.csv"
            pd.DataFrame(
                {
                    "Date": dates,
                    "Open": [20.0, 30.0],
                    "Close": [22.0, 33.0],
                    "Adj Close": [11.0, 16.5],
                }
            ).to_csv(path, index=False)

            merged_open, merged_close, merged_raw, metadata = (
                multifactor_walk_forward.merge_supplemental_price_sources(
                    opens, closes, raw_closes, [f"WBA={path}"]
                )
            )

        self.assertEqual(merged_open.at[dates[0], "WBA"], 10.0)
        self.assertEqual(merged_close.at[dates[0], "WBA"], 11.0)
        self.assertEqual(merged_open.at[dates[1], "WBA"], 15.0)
        self.assertEqual(merged_close.at[dates[1], "WBA"], 16.5)
        self.assertEqual(merged_raw.at[dates[1], "WBA"], 33.0)
        self.assertEqual(metadata[0]["merge_policy"], "fill_missing_only_yahoo_wins")

    def test_multifactor_candidate_weights_respect_name_cap(self):
        params = multifactor_walk_forward.MultifactorParams(
            "balanced", 0.2, 0.2, 0.2, 0.2, 0.2, 252, 8, "equal"
        )
        tickers = [f"T{index}" for index in range(8)]
        panel = pd.DataFrame(
            {
                "execution_date": [pd.Timestamp("2020-01-02")] * 8,
                "signal_date": [pd.Timestamp("2019-12-31")] * 8,
                "ticker": tickers,
                "value_factor": np.linspace(1.0, 0.3, 8),
                "quality_factor": np.linspace(1.0, 0.3, 8),
                "growth_factor": np.linspace(1.0, 0.3, 8),
                "rank_momentum_252": np.linspace(1.0, 0.3, 8),
                "rank_low_volatility": np.linspace(1.0, 0.3, 8),
                "annualized_volatility": [0.2] * 8,
                "latest_filed_date": [pd.Timestamp("2019-11-01")] * 8,
            }
        )

        closes = pd.DataFrame(
            {"DIA": np.linspace(80.0, 120.0, 220)},
            index=pd.bdate_range(end="2019-12-31", periods=220),
        )
        schedule = multifactor_walk_forward.build_weight_schedule(
            panel, closes, "2020-01-01", "2020-01-31", params
        )
        weights = schedule[pd.Timestamp("2020-01-02")]["weights"]
        regime = schedule[pd.Timestamp("2020-01-02")]["detail"]["market_regime"]

        self.assertLessEqual(max(weights.values()), 0.15 + 1e-12)
        self.assertAlmostEqual(sum(weights.values()), regime["target_equity_weight"])
        self.assertGreater(regime["target_cash_weight"], 0.0)

    def test_ridge_labels_use_the_next_execution_open(self):
        dates = pd.to_datetime(["2020-01-02", "2020-02-03", "2020-03-02"])
        panel = pd.DataFrame(
            {
                "execution_date": dates,
                "ticker": ["TEST"] * 3,
                "value_factor": [0.5] * 3,
                "quality_factor": [0.5] * 3,
                "growth_factor": [0.5] * 3,
            }
        )
        opens = pd.DataFrame({"TEST": [100.0, 110.0, 99.0]}, index=dates)

        labeled = ridge_walk_forward.add_forward_returns(panel, opens)

        self.assertAlmostEqual(labeled.iloc[0]["forward_return"], 0.10)
        self.assertAlmostEqual(labeled.iloc[1]["forward_return"], -0.10)
        self.assertTrue(pd.isna(labeled.iloc[2]["forward_return"]))
        self.assertEqual(
            labeled.iloc[0]["label_end_date"], pd.Timestamp("2020-02-03")
        )

    def test_ridge_training_cutoff_excludes_labels_ending_in_oos(self):
        frame = pd.DataFrame(
            {
                "execution_date": pd.to_datetime(["2019-11-01", "2019-12-02"]),
                "label_end_date": pd.to_datetime(["2019-12-02", "2020-01-02"]),
            }
        )
        train_end = pd.Timestamp("2019-12-31")

        training = frame[frame["label_end_date"] <= train_end]

        self.assertEqual(training["execution_date"].tolist(), [pd.Timestamp("2019-11-01")])

    def test_ridge_prediction_allocator_never_breaks_name_cap(self):
        tickers = [f"T{index}" for index in range(12)]
        predictions = pd.DataFrame(
            {
                "execution_date": [pd.Timestamp("2020-02-03")] * 12,
                "signal_date": [pd.Timestamp("2020-01-31")] * 12,
                "ticker": tickers,
                "prediction": np.linspace(1.0, 0.1, 12),
                "annualized_volatility": [0.2] * 12,
            }
        )
        closes = pd.DataFrame(
            {"DIA": np.linspace(90.0, 110.0, 220)},
            index=pd.bdate_range(end="2020-01-31", periods=220),
        )
        config = ridge_walk_forward.RidgeConfig(
            alpha=1.0,
            top_n=8,
            weighting="score_inverse_vol",
            rebalance_months=1,
        )

        schedule = ridge_walk_forward.prediction_weight_schedule(
            predictions, closes, config
        )
        weights = schedule[pd.Timestamp("2020-02-03")]["weights"]
        regime = schedule[pd.Timestamp("2020-02-03")]["detail"]["market_regime"]

        self.assertLessEqual(max(weights.values()), 0.15 + 1e-12)
        self.assertAlmostEqual(sum(weights.values()), regime["target_equity_weight"])

    def test_ridge_quarterly_schedule_only_trades_calendar_quarters(self):
        predictions = pd.DataFrame(
            {
                "execution_date": pd.to_datetime(["2020-01-02", "2020-02-03"]),
                "signal_date": pd.to_datetime(["2019-12-31", "2020-01-31"]),
                "ticker": ["TEST", "TEST"],
                "prediction": [1.0, 1.0],
                "annualized_volatility": [0.2, 0.2],
            }
        )
        config = ridge_walk_forward.RidgeConfig(1.0, 8, "equal", 3)

        closes = pd.DataFrame(
            {"DIA": np.linspace(100.0, 105.0, 220)},
            index=pd.bdate_range(end="2020-01-31", periods=220),
        )

        schedule = ridge_walk_forward.prediction_weight_schedule(
            predictions, closes, config
        )

        self.assertEqual(list(schedule), [pd.Timestamp("2020-01-02")])

    def test_us_fundamental_backtest_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "point-in-time"):
            backtest.BacktestEngine(
                ["AAPL"],
                "2024-01-01",
                "2024-12-31",
                strategy="hybrid",
            )


class TradingCostTests(unittest.TestCase):
    def test_round_trip_records_costs_and_realized_pnl(self):
        portfolio = backtest.Portfolio(
            cash=1_000.0,
            commission_bps=10.0,
            slippage_bps=10.0,
            sell_tax_bps=5.0,
        )

        bought = portfolio.buy("TEST", 5, 100.0)
        sold = portfolio.sell("TEST", bought, 110.0)

        self.assertEqual(sold, 5)
        self.assertGreater(portfolio.transaction_costs, 0)
        self.assertGreater(portfolio.last_trade["realized_pnl"], 0)
        self.assertLess(portfolio.cash, 1_050.0)

    def test_engine_uses_prior_signal_date_and_real_trading_days(self):
        dates = pd.bdate_range("2023-11-01", "2024-04-30")
        closes = [100.0 * (1.01 ** index) for index in range(len(dates))]
        frame = pd.DataFrame({"Open": closes, "Close": closes}, index=dates)
        engine = backtest.BacktestEngine(
            ["TEST"],
            "2024-03-01",
            "2024-04-30",
            strategy="momentum",
            rebalance_frequency="monthly",
            benchmark="",
        )

        fixed_signal = {"TEST": {"action": backtest.Action.BUY, "confidence": 1.0, "score": 10.0}}
        with patch.object(engine, "_fetch_price_data", return_value=frame), patch.object(
            backtest, "get_benchmark_return", return_value=None
        ), patch.object(
            backtest, "generate_momentum_signals_from_prices", return_value=fixed_signal
        ):
            with redirect_stdout(io.StringIO()):
                result = engine.run()

        self.assertNotIn("error", result)
        self.assertEqual(result["validity"]["fundamental_data"], "not_used")
        self.assertTrue(result["trade_history"])
        for trade in result["trade_history"]:
            self.assertLess(trade["signal_date"], trade["date"])
        recorded_dates = [point["date"] for point in result["portfolio_values"]]
        self.assertNotIn("2024-03-02", recorded_dates)

    def test_short_entry_does_not_destroy_equity_by_margin_amount(self):
        portfolio = backtest.Portfolio(
            cash=10_000.0,
            commission_bps=0.0,
            slippage_bps=0.0,
            margin_requirement=0.5,
        )

        quantity = portfolio.short_open("TEST", 10, 100.0)

        self.assertEqual(quantity, 10)
        self.assertAlmostEqual(portfolio.get_total_value({"TEST": 100.0}), 10_000.0)
        self.assertAlmostEqual(portfolio.margin_used, 500.0)

    def test_short_sale_proceeds_cannot_create_unlimited_buying_power(self):
        portfolio = backtest.Portfolio(
            cash=10_000.0,
            commission_bps=0.0,
            slippage_bps=0.0,
            margin_requirement=0.5,
        )

        first_quantity = portfolio.short_open("TEST", 10_000, 100.0)
        second_quantity = portfolio.short_open("TEST", 10_000, 100.0)

        self.assertEqual(first_quantity, 200)
        self.assertEqual(second_quantity, 0)
        self.assertEqual(portfolio.get_available_cash(), 0.0)
        self.assertAlmostEqual(portfolio.get_total_value({"TEST": 100.0}), 10_000.0)

    def test_fixed_portfolio_weights_can_be_backtested_after_formation(self):
        dates = pd.bdate_range("2024-02-01", "2024-04-30")
        frame = pd.DataFrame({"Open": 100.0, "Close": 100.0}, index=dates)
        engine = backtest.BacktestEngine(
            ["TEST"],
            "2024-03-01",
            "2024-04-30",
            rebalance_frequency="monthly",
            benchmark="",
            target_weights={"TEST": 0.5},
            portfolio_formation_date="2024-02-29",
        )

        with patch.object(engine, "_fetch_price_data", return_value=frame), patch.object(
            backtest, "get_benchmark_return", return_value=None
        ), redirect_stdout(io.StringIO()):
            result = engine.run()

        self.assertTrue(result["trade_history"])
        self.assertEqual(result["validity"]["portfolio_formation_date"], "2024-02-29")
        self.assertEqual(result["trade_history"][0]["target_weight"], 0.5)


def candidate(ticker: str, sector: str, rank: int = 1, score: float = 10.0):
    return {
        "ticker": ticker,
        "sector": sector,
        "rank": rank,
        "raw_weight_score": score,
    }


class AllocationConstraintTests(unittest.TestCase):
    def test_all_twelve_investors_are_configured(self):
        self.assertEqual(len(portfolio_report.INVESTOR_CONFIG), 12)

    def test_name_cap_leaves_cash_when_only_five_names_exist(self):
        candidates = [candidate(f"T{i}", f"S{i}", i) for i in range(5)]

        included, excluded, cash = portfolio_report.allocate_weights(candidates)

        self.assertFalse(excluded)
        self.assertLessEqual(max(item["weight"] for item in included), 15.0)
        self.assertAlmostEqual(sum(item["weight"] for item in included), 75.0, places=1)
        self.assertAlmostEqual(cash, 25.0, places=1)

    def test_sector_cap_is_not_undone_by_renormalization(self):
        candidates = [candidate(f"T{i}", "Technology", i) for i in range(8)]

        included, _, cash = portfolio_report.allocate_weights(candidates)

        sector_weight = sum(item["weight"] for item in included)
        self.assertLessEqual(sector_weight, 35.0)
        self.assertAlmostEqual(sector_weight + cash, 100.0, places=1)

    def test_market_scores_move_cash_in_requested_directions(self):
        neutral = market_regime.cash_weight_from_scores(0.0, 0.0, 0.0)
        overheated = market_regime.cash_weight_from_scores(1.0, 0.0, 0.0)
        fearful = market_regime.cash_weight_from_scores(0.0, 1.0, 0.0)
        positive_outlook = market_regime.cash_weight_from_scores(0.0, 0.0, 1.0)
        negative_outlook = market_regime.cash_weight_from_scores(0.0, 0.0, -1.0)

        self.assertGreater(overheated, neutral)
        self.assertLess(fearful, neutral)
        self.assertLess(positive_outlook, neutral)
        self.assertGreater(negative_outlook, neutral)

    def test_market_cash_target_caps_stock_allocation(self):
        candidates = [candidate(f"T{i}", f"S{i}", i) for i in range(8)]

        included, excluded, cash = portfolio_report.allocate_weights(
            candidates, target_cash_weight=40.0
        )

        self.assertFalse(excluded)
        self.assertLessEqual(sum(item["weight"] for item in included), 60.0)
        self.assertGreaterEqual(cash, 40.0)
        self.assertAlmostEqual(
            sum(item["weight"] for item in included) + cash, 100.0, places=1
        )

    def test_risk_adjustment_penalizes_higher_volatility(self):
        candidates = [candidate("LOW", "A", 1), candidate("HIGH", "B", 2)]
        snapshot = {
            "annualized_volatility": {"LOW": 0.2, "HIGH": 0.4},
            "correlation": {"LOW": {"HIGH": 0.0}, "HIGH": {"LOW": 0.0}},
        }

        adjusted, excluded = portfolio_report.apply_risk_adjustment(candidates, snapshot)

        self.assertFalse(excluded)
        scores = {item["ticker"]: item["raw_weight_score"] for item in adjusted}
        self.assertGreater(scores["LOW"], scores["HIGH"])

    def test_risk_snapshot_is_point_in_time_and_complete(self):
        dates = pd.bdate_range("2023-09-01", periods=100)

        def price_rows(ticker, _start, _end):
            offset = 0.4 if ticker == "B" else 0.2
            return [
                {"date": date.strftime("%Y-%m-%d"), "close": 100 + index + ((-1) ** index) * offset}
                for index, date in enumerate(dates)
            ]

        with patch.object(risk_builder, "get_prices", side_effect=price_rows):
            snapshot = risk_builder.build_risk_snapshot(
                ["A", "B"], "2024-01-31", min_observations=60
            )

        self.assertEqual(snapshot["analysis_date"], "2024-01-31")
        self.assertEqual(set(snapshot["annualized_volatility"]), {"A", "B"})
        self.assertIn("B", snapshot["correlation"]["A"])
        self.assertIn("market_regime", snapshot)
        self.assertEqual(snapshot["market_regime"]["benchmark"], "SPY")

    def test_risk_snapshot_accepts_korean_time_price_key(self):
        dates = pd.bdate_range("2023-09-01", periods=100)

        def price_rows(ticker, _start, _end):
            offset = 0.4 if ticker == "B" else 0.2
            return [
                {"time": date.strftime("%Y-%m-%d"), "close": 100 + index + ((-1) ** index) * offset}
                for index, date in enumerate(dates)
            ]

        with patch.object(risk_builder, "get_prices", side_effect=price_rows):
            snapshot = risk_builder.build_risk_snapshot(
                ["A", "B"], "2024-01-31", min_observations=60
            )

        self.assertEqual(set(snapshot["annualized_volatility"]), {"A", "B"})
        self.assertIn("B", snapshot["correlation"]["A"])
        self.assertEqual(snapshot["market_regime"]["benchmark"], "SPY")

    def test_market_regime_ignores_prices_after_analysis_date(self):
        dates = pd.bdate_range("2023-01-02", periods=260)
        base = pd.Series(np.linspace(100.0, 120.0, len(dates)), index=dates)
        analysis_date = dates[229]
        with_future_crash = base.copy()
        with_future_crash.loc[dates[230:]] = np.linspace(80.0, 50.0, 30)

        before = market_regime.assess_market_regime(
            base, as_of_date=analysis_date
        )
        after = market_regime.assess_market_regime(
            with_future_crash, as_of_date=analysis_date
        )

        self.assertEqual(before["target_cash_weight"], after["target_cash_weight"])
        self.assertEqual(before["metrics"], after["metrics"])

    def test_market_regime_rejects_non_date_index_for_cutoff(self):
        closes = pd.Series([100.0] * 220, index=[str(i) for i in range(220)])

        with self.assertRaises(TypeError):
            market_regime.assess_market_regime(
                closes, benchmark="SPY", as_of_date="2026-08-25"
            )

    def test_independent_investor_results_are_required(self):
        stock = {
            "ticker": "AAPL",
            "rank": 1,
            "total_score": 8.0,
            "metrics": {},
            "market_cap": {"category": "mega", "display": "$1T"},
        }

        with self.assertRaisesRegex(ValueError, "독립 투자자 분석 누락"):
            portfolio_report.build_candidates(
                [stock],
                ["buffett"],
                {"AAPL": "Technology"},
                {},
            )

    def test_fetch_sector_uses_korean_yahoo_suffixes(self):
        def ticker_factory(symbol):
            info = {} if symbol.endswith(".KS") else {"sector": "Consumer Cyclical"}
            return type("TickerStub", (), {"info": info})()

        with patch.object(portfolio_report.yf, "Ticker", side_effect=ticker_factory) as mocked:
            sector = portfolio_report.fetch_sector("257720")

        self.assertEqual(sector, "Consumer Disc.")
        self.assertEqual(
            [call.args[0] for call in mocked.call_args_list],
            ["257720.KS", "257720.KQ"],
        )

    def test_investor_analysis_date_must_match_predict_date(self):
        payload = {
            "analysis_date": "2024-01-02",
            "analyses": {
                "AAPL": {
                    "buffett": {
                        "signal": "bullish",
                        "confidence": 80,
                        "reasoning": "quality",
                    }
                }
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "investors.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "기준일"):
                portfolio_report.load_investor_analyses(path, "2024-01-03")

    def test_workbook_includes_cash_without_breaking_constraints(self):
        stock = {
            "ticker": "AAPL",
            "company_name": "Apple",
            "rank": 1,
            "total_score": 8.0,
            "ensemble_score": 7.5,
            "signal": "strong_buy",
            "score_implied_return_pct": 17.5,
            "scores": {"fundamental": 8.0, "enhanced_momentum": 7.0},
            "metrics": {"pe": 25.0, "pb": 10.0, "roe": 40.0, "revenue_growth": 8.0, "peg": 2.0},
            "market_cap": {"category": "mega", "display": "$3T"},
            "investor_warnings": [],
            "investor_consensus": {"level": "high", "std": 1.0},
        }
        analyses = {
            "AAPL": {
                "buffett": {
                    "signal": "bullish",
                    "confidence": 80,
                    "reasoning": "quality",
                    "data_quality": "complete",
                }
            }
        }
        candidates, excluded = portfolio_report.build_candidates(
            [stock], ["buffett"], {"AAPL": "Technology"}, analyses
        )
        candidates, excluded_risk = portfolio_report.apply_risk_adjustment(
            candidates,
            {
                "annualized_volatility": {"AAPL": 0.25},
                "correlation": {"AAPL": {}},
            },
        )
        regime = {
            "benchmark": "SPY",
            "as_of_date": "2024-01-01",
            "regime": "risk_on",
            "target_cash_weight": 0.05,
            "target_equity_weight": 0.95,
            "scores": {"overheat": 0.1, "fear": 0.1, "outlook": 0.8},
        }
        included, excluded_weight, cash = portfolio_report.allocate_weights(
            candidates, target_cash_weight=5.0
        )
        summary = portfolio_report.summarize_portfolio(
            included, [stock], ["buffett"], cash, regime
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "portfolio.xlsx"
            weights_output = Path(temp_dir) / "portfolio.json"
            portfolio_report.write_workbook(
                output,
                "2024-01-01",
                "TEST",
                ["buffett"],
                candidates,
                included,
                summary,
                excluded + excluded_risk + excluded_weight,
            )
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 0)
            portfolio_report.write_portfolio_json(
                weights_output, "2024-01-01", included, cash, regime
            )
            weights_payload = json.loads(weights_output.read_text(encoding="utf-8"))
            self.assertAlmostEqual(
                sum(weights_payload["weights"].values()) + weights_payload["cash_weight"],
                1.0,
                places=6,
            )
            self.assertEqual(weights_payload["market_regime"]["regime"], "risk_on")
            self.assertEqual(
                weights_payload["constraints"]["market_cash_target"], 0.05
            )
        self.assertAlmostEqual(summary["invested_weight"] + summary["cash_weight"], 100.0, places=1)


if __name__ == "__main__":
    unittest.main()
