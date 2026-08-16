from lambda_handlers.engine import lambda_handler


class Context:
    aws_request_id = "request-1"


def test_smoke_test_remains_paper_only():
    result = lambda_handler({"smoke_test": True}, Context())
    assert result["ok"] is True
    assert result["mode"] == "PAPER"
    assert result["live_trading_enabled"] is False
    assert result["request_id"] == "request-1"


def test_unknown_operation_fails_closed():
    result = lambda_handler({"operation": "LIVE_TRADE"}, Context())
    assert result["ok"] is False
    assert result["status"] == "DATA_ERROR"
    assert result["error_code"] == "UNSUPPORTED_OPERATION"
    assert result["live_trading_enabled"] is False
