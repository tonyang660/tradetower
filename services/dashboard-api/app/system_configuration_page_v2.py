from __future__ import annotations

from typing import Any

from bootstrap import get_bootstrap_system_health
from configuration import get_bootstrap_configuration
from time_utils import iso_now

SYSTEM_CONFIGURATION_PAGE_V2_VERSION = "phase7_step14_system_configuration_page_v2"


def get_system_health_page_v2(account_id: int) -> dict[str, Any]:
    payload = get_bootstrap_system_health(account_id)
    errors = payload.get("errors", []) if isinstance(payload, dict) else []

    if not isinstance(payload, dict):
        return {
            "ok": False,
            "partial": True,
            "system_configuration_page_v2_version": SYSTEM_CONFIGURATION_PAGE_V2_VERSION,
            "account_id": account_id,
            "generated_at": iso_now(),
            "error": "non_dict_system_health_payload",
            "errors": [{"source": "system_health_bootstrap", "error": payload}],
        }

    return {
        **payload,
        "partial": len(errors) > 0,
        "system_configuration_page_v2_version": SYSTEM_CONFIGURATION_PAGE_V2_VERSION,
        "v2": {
            "source": "bootstrap/system-health",
            "compatibility_mode": True,
            "page_owner": "system-health",
            "notes": [
                "System Health page layout is preserved.",
                "This V2 route keeps the existing shape and adds partial/version metadata.",
            ],
        },
    }


def get_configuration_page_v2() -> dict[str, Any]:
    payload = get_bootstrap_configuration()
    errors = payload.get("errors", []) if isinstance(payload, dict) else []

    if not isinstance(payload, dict):
        return {
            "ok": False,
            "partial": True,
            "system_configuration_page_v2_version": SYSTEM_CONFIGURATION_PAGE_V2_VERSION,
            "generated_at": iso_now(),
            "error": "non_dict_configuration_payload",
            "errors": [{"source": "configuration_bootstrap", "error": payload}],
        }

    return {
        **payload,
        "partial": len(errors) > 0,
        "system_configuration_page_v2_version": SYSTEM_CONFIGURATION_PAGE_V2_VERSION,
        "v2": {
            "source": "bootstrap/configuration",
            "compatibility_mode": True,
            "page_owner": "configuration",
            "write_paths_preserved": [
                "/configuration/validate-symbol",
                "/configuration/symbol-universe",
                "/configuration/auto-loop",
            ],
            "notes": [
                "Configuration page layout and write actions are preserved.",
                "This V2 route keeps the existing shape and adds partial/version metadata.",
            ],
        },
    }
