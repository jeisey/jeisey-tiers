"""Network-free tests for the Phase-0 source probe.

These cover the parts of the probe that interpret responses, because a probe that
misclassifies evidence is worse than no probe: it would let Phase 1 build on a false
"verified" record. Live network behaviour is exercised separately by
`tests/integration/test_live_sources.py` (opt-in, `-m live`).
"""

from __future__ import annotations

import json

import polars as pl
import pytest
import source_probe as sp


class _FakeProxyError(Exception):
    pass


def test_classify_proxy_denial_is_not_a_source_outage():
    exc = _FakeProxyError(
        "HTTPSConnectionPool(host='api.sleeper.app', port=443): Max retries exceeded "
        "(Caused by ProxyError('Unable to connect to proxy', "
        "OSError('Tunnel connection failed: 403 Forbidden')))"
    )
    status, detail = sp.classify_request_exception(exc)
    assert status == sp.BLOCKED_EGRESS
    assert "403" in detail


def test_classify_generic_network_failure():
    status, _ = sp.classify_request_exception(TimeoutError("read timeout"))
    assert status == sp.NETWORK_ERROR


def test_dtype_summary_reports_null_fraction():
    frame = pl.DataFrame({"gsis_id": ["00-1", None, "00-3", None], "season": [2024] * 4})
    summary = {entry["name"]: entry for entry in sp.dtype_summary(frame)}
    assert summary["gsis_id"]["null_fraction"] == 0.5
    assert summary["season"]["dtype"].startswith("Int")


def test_dtype_summary_on_empty_frame_omits_null_fraction():
    frame = pl.DataFrame({"season": []})
    assert sp.dtype_summary(frame) == [{"name": "season", "dtype": "Null"}]


def test_frame_sample_is_capped_and_json_safe():
    frame = pl.DataFrame({"season": [2019, 2020, 2021], "when": [None, None, None]})
    sample = sp.frame_sample(frame)
    assert len(sample) == sp.MAX_SAMPLE_ROWS
    json.dumps(sample)  # must not raise


def test_numeric_coverage_reports_range_and_distinct():
    frame = pl.DataFrame({"season": [2019, 2020, 2020, None]})
    assert sp.numeric_coverage(frame, "season") == {
        "season_min": 2019,
        "season_max": 2020,
        "season_distinct": 2,
    }


def test_numeric_coverage_missing_column_is_empty():
    assert sp.numeric_coverage(pl.DataFrame({"a": [1]}), "week") == {}


def test_mfl_record_extraction_handles_nested_envelope():
    payload = {
        "version": "1.0",
        "adp": {
            "timestamp": "1750000000",
            "player": [
                {"id": "13593", "averagePick": "1.35", "draftsSelectedIn": "900"},
                {"id": "14801", "averagePick": "2.10", "draftsSelectedIn": "880"},
            ],
        },
    }
    records = sp._mfl_records(payload)
    assert [r["id"] for r in records] == ["13593", "14801"]


def test_mfl_record_extraction_handles_single_player_dict():
    payload = {"adp": {"player": {"id": "1", "averagePick": "1.0"}}}
    assert sp._mfl_records(payload) == [{"id": "1", "averagePick": "1.0"}]


def test_mfl_record_extraction_on_unexpected_shape_returns_empty():
    assert sp._mfl_records({"error": "no data"}) == []
    assert sp._mfl_records(["not", "a", "dict"]) == []


def test_record_field_union_merges_heterogeneous_keys():
    records = [{"id": "1", "adp": 1.5}, {"id": "2", "team": "KC"}]
    assert sp._record_field_union(records) == [
        {"name": "adp", "dtype": "float"},
        {"name": "id", "dtype": "str"},
        {"name": "team", "dtype": "str"},
    ]


def test_keyword_excerpts_strips_markup_and_caps_length():
    html = (
        "<html><style>p{color:red}</style><body><p>Our data may be used for "
        "non-commercial purposes only.</p></body></html>"
    )
    excerpts = sp.keyword_excerpts(html, ["non-commercial"], window=60)
    assert len(excerpts) == 1
    assert "non-commercial" in excerpts[0]
    assert "<p>" not in excerpts[0]
    assert "color:red" not in excerpts[0]


def test_keyword_excerpts_returns_empty_when_absent():
    assert sp.keyword_excerpts("nothing relevant here", ["commercial"]) == []


def test_gsis_coverage_ignores_placeholder_ids():
    records = [{"gsis_id": "00-1"}, {"gsis_id": ""}, {"gsis_id": "0"}, {}]
    assert sp.gsis_coverage(records, "gsis_id") == {
        "gsis_id_present": 1,
        "gsis_id_total": 4,
        "gsis_id_fraction": 0.25,
    }


def _adp_year_finding(year: int, *, status: str, records: int) -> sp.Finding:
    return sp.Finding(
        check_id=f"mfl_adp_year_{year}",
        source_id="myfantasyleague_adp",
        kind="http",
        target="https://example.invalid",
        status=status,
        record_count=records,
    )


def test_arbitrage_feasibility_requires_five_dense_history_years():
    findings = [
        sp.Finding(
            check_id="mfl_adp_current_default",
            source_id="myfantasyleague_adp",
            kind="http",
            target="https://example.invalid",
            status=sp.OK,
            record_count=500,
        ),
        *[_adp_year_finding(y, status=sp.OK, records=400) for y in range(2019, 2024)],
    ]
    decisions = sp.derive_decisions(findings)
    assert decisions["current_market_source_viable"] is True
    assert decisions["arbitrage_ml_historical_feasible"] is True
    assert decisions["mfl_historical_years_with_data"] == ["2019", "2020", "2021", "2022", "2023"]


def test_arbitrage_feasibility_false_when_history_is_thin():
    findings = [
        sp.Finding(
            check_id="mfl_adp_current_default",
            source_id="myfantasyleague_adp",
            kind="http",
            target="https://example.invalid",
            status=sp.OK,
            record_count=500,
        ),
        *[_adp_year_finding(y, status=sp.OK, records=400) for y in (2023, 2024)],
        *[_adp_year_finding(y, status=sp.EMPTY, records=0) for y in (2019, 2020, 2021)],
    ]
    decisions = sp.derive_decisions(findings)
    assert decisions["arbitrage_ml_historical_feasible"] is False
    assert decisions["mfl_historical_years_with_data"] == ["2023", "2024"]


def test_sparse_years_do_not_count_as_coverage():
    findings = [_adp_year_finding(y, status=sp.OK, records=12) for y in range(2019, 2026)]
    assert sp.derive_decisions(findings)["arbitrage_ml_historical_feasible"] is False


def test_decisions_flag_locally_blocked_sources():
    findings = [
        sp.Finding(
            check_id="sleeper_state_nfl",
            source_id="sleeper",
            kind="http",
            target="https://example.invalid",
            status=sp.BLOCKED_EGRESS,
        )
    ]
    decisions = sp.derive_decisions(findings)
    assert decisions["blocked_by_local_egress"] == ["sleeper"]
    assert decisions["current_market_source_viable"] is False
    assert decisions["current_market_source_status"] == "missing"


def test_finding_serialisation_omits_empty_and_marks_non_redistributable():
    finding = sp.Finding(
        check_id="nflverse_ff_rankings_draft",
        source_id="fantasypros_ecr_via_dynastyprocess",
        kind="loader",
        target="nflreadpy.load_ff_rankings",
        status=sp.OK,
        record_count=1000,
        redistributable=False,
    )
    payload = finding.to_dict()
    assert payload["redistributable"] is False
    assert "sample_rows" not in payload
    assert "coverage" not in payload


def test_build_report_orders_findings_and_embeds_run_metadata():
    findings = [
        sp.Finding("z_check", "sleeper", "http", "t", sp.OK),
        sp.Finding("a_check", "nflreadpy", "loader", "t", sp.OK),
    ]
    report = sp.build_report(
        findings, started_at="2026-08-17T00:00:00Z", finished_at="2026-08-17T00:05:00Z"
    )
    assert [f["check_id"] for f in report["findings"]] == ["a_check", "z_check"]
    assert report["probe_schema_version"] == sp.PROBE_SCHEMA_VERSION
    assert report["run"]["user_agent"].startswith("jeisey-tiers-source-probe/")
    assert "arbitrage_ml_historical_feasible" in report["decisions"]


def test_render_summary_mentions_every_check():
    findings = [
        sp.Finding("check_one", "sleeper", "http", "t", sp.OK, record_count=3),
        sp.Finding("check_two", "nflreadpy", "loader", "t", sp.BLOCKED_EGRESS),
    ]
    report = sp.build_report(findings, started_at="s", finished_at="f")
    summary = sp.render_summary(report)
    assert "`check_one`" in summary
    assert "`check_two`" in summary
    assert "arbitrage_ml_historical_feasible" in summary


def test_write_fixtures_only_writes_ok_allowlisted_checks(tmp_path):
    findings = [
        sp.Finding(
            "sleeper_state_nfl",
            "sleeper",
            "http",
            "t",
            sp.OK,
            record_count=1,
            coverage={"season": "2026"},
        ),
        sp.Finding("sleeper_trending_add", "sleeper", "http", "t", sp.OK, record_count=25),
        sp.Finding("mfl_adp_current_default", "myfantasyleague_adp", "http", "t", sp.EMPTY),
    ]
    written = sp.write_fixtures(findings, tmp_path)
    assert [p.name for p in written] == ["sleeper_state_nfl.schema.json"]
    payload = json.loads(written[0].read_text())
    assert payload["coverage"] == {"season": "2026"}


def test_write_fixtures_suppresses_rows_for_non_redistributable_sources(tmp_path):
    finding = sp.Finding(
        "mfl_adp_current_default",
        "myfantasyleague_adp",
        "http",
        "t",
        sp.OK,
        record_count=2,
        sample_rows=[{"id": "1"}],
        redistributable=False,
    )
    written = sp.write_fixtures([finding], tmp_path)
    assert json.loads(written[0].read_text())["sample_rows"] == []


@pytest.mark.parametrize(
    "params,expected",
    [
        ({"TYPE": "adp", "JSON": 1}, "TYPE=adp&JSON=1"),
        ({}, ""),
    ],
)
def test_query_string_rendering_is_stable(params, expected):
    assert sp._qs(params) == expected
