"""
Phase 5 Step 11 — Paper Execution compatibility helpers.

These helpers are intentionally small and safe. They validate and normalize the
Risk Approval v2 entry payload before Paper Execution creates or fills an entry.
"""

RISK_APPROVAL_PAYLOAD_VERSION_V2 = "phase5_step10_risk_approval_payload_v2"
PAPER_RISK_COMPATIBILITY_VERSION = "phase5_step11_scheduler_paper_compatibility"


def normalize_order_type(payload: dict) -> str:
    value = payload.get("order_type") or payload.get("entry_order_type") or "limit"
    value = str(value).lower()
    if value not in ("limit", "market"):
        return "limit"
    return value


def is_risk_approved_entry_payload(payload: dict) -> bool:
    if payload.get("approved") is True:
        return True
    return str(payload.get("risk_decision") or "").lower() == "approved"


def missing_required_entry_fields(payload: dict) -> list[str]:
    required = [
        "account_id",
        "symbol",
        "position_side",
        "entry_price",
        "stop_loss",
        "size",
        "risk_amount",
        "tp1_price",
        "tp2_price",
        "tp3_price",
    ]

    return [
        field
        for field in required
        if payload.get(field) is None
    ]


def normalize_entry_payload(payload: dict) -> dict:
    result = dict(payload)
    result["order_type"] = normalize_order_type(result)

    if result.get("entry_order_type") is None:
        result["entry_order_type"] = result["order_type"]

    result["paper_risk_compatibility_version"] = PAPER_RISK_COMPATIBILITY_VERSION

    if result.get("risk_approval_payload_version") == RISK_APPROVAL_PAYLOAD_VERSION_V2:
        result["risk_payload_v2_accepted"] = True

    return result


def validate_entry_payload(payload: dict):
    if not is_risk_approved_entry_payload(payload):
        return False, "risk_payload_not_approved"

    missing = missing_required_entry_fields(payload)
    if missing:
        return False, f"missing_required_entry_fields:{','.join(missing)}"

    side = str(payload.get("position_side") or "").lower()
    if side not in ("long", "short"):
        return False, "invalid_position_side"

    order_type = normalize_order_type(payload)
    if order_type not in ("limit", "market"):
        return False, "invalid_order_type"

    return True, None
