from paper_stop_reprice_guard import protective_exit_price_for_breached_paper_stop

def test_short_stop_reprice_above_current():
    d = protective_exit_price_for_breached_paper_stop(side="short", current_price=105, stop_price=103, previous_order_price=105, buffer_bps=10)
    assert d.applied is True
    assert d.repriced_order_price > 105

def test_long_stop_reprice_below_current():
    d = protective_exit_price_for_breached_paper_stop(side="long", current_price=95, stop_price=97, previous_order_price=95, buffer_bps=10)
    assert d.applied is True
    assert d.repriced_order_price < 95

def test_no_reprice_before_breach():
    d = protective_exit_price_for_breached_paper_stop(side="short", current_price=101, stop_price=103, previous_order_price=101, buffer_bps=10)
    assert d.applied is False
