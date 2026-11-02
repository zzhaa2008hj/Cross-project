from datetime import date

from app.services import buffer as buffer_service


def test_workday_window_and_80_20_rule():
    """2026-11-02 ~ 2026-11-13：W=10，B=2，内部目标 2026-11-11。"""
    result = buffer_service.derive_buffer(date(2026, 11, 2), date(2026, 11, 13), "内部")
    assert result["status"] == "ok"
    assert result["window_workdays"] == 10
    assert result["buffer_days"] == 2
    assert result["internal_target"] == "2026-11-11"
    assert result["consumable"] is True


def test_buffer_days_rounding():
    assert buffer_service.buffer_days(10) == 2
    assert buffer_service.buffer_days(3) == 1
    assert buffer_service.buffer_days(1) == 1
    assert buffer_service.buffer_days(0) == 1


def test_external_buffer_not_consumable():
    result = buffer_service.derive_buffer(date(2026, 11, 2), date(2026, 11, 13), "外部资源")
    assert result["status"] == "ok"
    assert result["consumable"] is False
    assert result["internal_target"] is None
    assert "外部" in result["reason"]


def test_missing_dates_are_pending_not_faked():
    result = buffer_service.derive_buffer(None, date(2026, 11, 13), "内部")
    assert result["status"] == "待确认"
    assert result["window_workdays"] is None
    assert result["internal_target"] is None


def test_start_after_commit_is_flagged():
    result = buffer_service.derive_buffer(date(2026, 11, 20), date(2026, 11, 13), "内部")
    assert result["start_after_commit"] is True
    assert result["status"] == "待确认"


def test_weekend_commit_warning():
    result = buffer_service.derive_buffer(date(2026, 11, 2), date(2026, 11, 14), "内部")
    assert result["commit_on_weekend"] is True
    assert result["warnings"]


def test_window_insufficient_when_internal_target_before_start():
    # 2026-11-09 ~ 2026-11-10 -> W=2, B=1 -> 目标 2026-11-09，等于开始日，窗口刚好
    result = buffer_service.derive_buffer(date(2026, 11, 10), date(2026, 11, 10), "内部")
    assert result["status"] == "窗口不足"
    assert result["consumable"] is False
    assert result["internal_target"] == "2026-11-09"


def test_workday_override_is_used():
    result = buffer_service.derive_buffer(
        date(2026, 11, 2), date(2026, 11, 13), "内部", workday_override=20
    )
    assert result["window_workdays"] == 20
    assert result["buffer_days"] == 4
