from scripts.shadow_operator_summary import build_operator_summary, render_markdown


def _core(*, ok=True, fills=0, armed=0, violation=False):
    return {
        "ok": ok,
        "session_date_et": "2026-08-20",
        "session_phase": "POST_SESSION",
        "diagnosis": "NO_GENUINE_STRATEGY_EVENT_RECEIVED",
        "zero_trade_status": "FINAL_AT_AWS_BOUNDARY",
        "total_session_fills": fills,
        "total_armed": armed,
        "accounts": {
            "PAPER_SHADOW_V24": {"open_count": 0},
            "PAPER_SHADOW_V25": {"open_count": 0},
        },
        "safety": {
            "trading_authorized": False,
            "live_trading_enabled": False,
            "violations": ["BROKEN"] if violation else [],
        },
    }


def _evidence(*, replay_status="PASS", replay_diagnosis="SCHEDULER_HEALTHY"):
    return {
        "core": _core(),
        "contract": {"ok": True, "status": "PASS", "diagnosis": "NO_DRIFT"},
        "replay_scheduler": {
            "status": replay_status,
            "diagnosis": replay_diagnosis,
        },
        "transport": {"ok": True, "status": "PASS"},
        "universe": {"ok": True, "status": "PASS"},
        "liquidity": {"ok": True, "status": "PASS"},
        "source_diagnostic": {"status": "PASS", "diagnosis": "SOURCE_COMPLETE"},
    }


def test_operator_summary_is_healthy_without_manual_workaround():
    summary = build_operator_summary(_evidence())
    rendered = render_markdown(summary)

    assert summary["overall_status"] == "HEALTHY"
    assert summary["hard_failures"] == []
    assert summary["pending_controls"] == []
    assert summary["ci_gate_status"] == "PASS"
    assert summary["ci_blocking_failures"] == []
    assert "Operator action:** NONE" in rendered
    assert "no manual TradingView or CloudShell step" in rendered
    assert "Automation notification gate:** `PASS`" in rendered
    assert "TradingView:** frozen" in rendered
    assert "trading_authorized=false" in rendered
    assert "live_trading_enabled=false" in rendered
    assert "ACTION NEEDED FROM SHANNON" not in rendered


def test_expected_scheduler_activation_pending_does_not_request_manual_action():
    evidence = _evidence(
        replay_status="PENDING",
        replay_diagnosis="REPLAY_SCHEDULER_ACTIVATION_PENDING",
    )
    evidence["source_diagnostic"] = {
        "status": "PENDING",
        "diagnosis": "SH24_SOURCE_DIAGNOSTIC_NOT_DUE",
    }

    summary = build_operator_summary(evidence)
    rendered = render_markdown(summary)

    assert summary["overall_status"] == "AUTOMATION_PENDING"
    assert summary["pending_controls"] == ["replay_scheduler", "source_diagnostic"]
    assert summary["ci_gate_status"] == "PASS_WITH_EVIDENCE_WARNINGS"
    assert summary["ci_blocking_failures"] == []
    assert "waiting for its next technically eligible evidence window" in rendered
    assert "ACTION NEEDED FROM SHANNON" not in rendered


def test_source_diagnostic_failure_stays_fail_closed_without_red_ci_noise():
    evidence = _evidence()
    evidence["source_diagnostic"] = {
        "ok": False,
        "status": "FAIL",
        "diagnosis": "SH24_SOURCE_DIAGNOSTIC_PUBLICATION_MISSING",
    }

    summary = build_operator_summary(evidence)
    rendered = render_markdown(summary)

    assert summary["overall_status"] == "FAIL_CLOSED"
    assert summary["hard_failures"] == ["source_diagnostic"]
    assert summary["ci_gate_status"] == "PASS_WITH_EVIDENCE_WARNINGS"
    assert summary["ci_blocking_failures"] == []
    assert summary["ci_nonblocking_findings"] == ["source_diagnostic"]
    assert "Automation notification gate:** `PASS_WITH_EVIDENCE_WARNINGS`" in rendered


def test_replay_failure_without_armed_records_is_warning_only():
    evidence = _evidence(
        replay_status="FAIL",
        replay_diagnosis="REPLAY_SCHEDULER_TICK_MISSING",
    )

    summary = build_operator_summary(evidence)

    assert summary["overall_status"] == "FAIL_CLOSED"
    assert summary["hard_failures"] == ["replay_scheduler"]
    assert summary["ci_gate_status"] == "PASS_WITH_EVIDENCE_WARNINGS"
    assert summary["ci_blocking_failures"] == []
    assert summary["ci_nonblocking_findings"] == ["replay_scheduler"]


def test_replay_failure_with_armed_record_is_ci_blocking():
    evidence = _evidence(
        replay_status="FAIL",
        replay_diagnosis="REPLAY_SCHEDULER_TICK_MISSING",
    )
    evidence["core"] = _core(armed=1)

    summary = build_operator_summary(evidence)

    assert summary["overall_status"] == "FAIL_CLOSED"
    assert summary["ci_gate_status"] == "FAIL"
    assert summary["ci_blocking_failures"] == ["replay_scheduler"]


def test_fail_closed_transport_failure_remains_ci_blocking():
    evidence = _evidence()
    evidence["transport"] = {"ok": False, "status": "FAIL", "diagnosis": "INGRESS_DOWN"}

    summary = build_operator_summary(evidence)
    rendered = render_markdown(summary)

    assert summary["overall_status"] == "FAIL_CLOSED"
    assert summary["hard_failures"] == ["transport"]
    assert summary["ci_gate_status"] == "FAIL"
    assert summary["ci_blocking_failures"] == ["transport"]
    assert "do not edit TradingView or run CloudShell as a routine workaround" in rendered
    assert "ACTION NEEDED FROM SHANNON" not in rendered


def test_unknown_critical_control_is_ci_blocking():
    evidence = _evidence()
    evidence["liquidity"] = {}

    summary = build_operator_summary(evidence)

    assert summary["overall_status"] == "EVIDENCE_INCOMPLETE"
    assert summary["unknown_controls"] == ["liquidity"]
    assert summary["ci_gate_status"] == "FAIL"
    assert summary["ci_blocking_failures"] == ["liquidity:UNKNOWN"]


def test_core_safety_violation_forces_fail_closed_summary_and_ci_failure():
    evidence = _evidence()
    evidence["core"] = _core(ok=False, violation=True)

    summary = build_operator_summary(evidence)

    assert summary["overall_status"] == "FAIL_CLOSED"
    assert "core" in summary["hard_failures"]
    assert "safety_evidence" in summary["hard_failures"]
    assert summary["ci_gate_status"] == "FAIL"
    assert "core" in summary["ci_blocking_failures"]
    assert "safety_evidence" in summary["ci_blocking_failures"]