"""Model Armor template facilities-guardrail, created once and reused by chapters 11 and 2 (create-or-get)."""
from google.api_core import exceptions as gex
from google.cloud import modelarmor_v1 as ma

import gcp

TEMPLATE_ID = "facilities-guardrail"
TEMPLATE = f"{gcp.PARENT}/templates/{TEMPLATE_ID}"


def client():
    return gcp.rest(ma.ModelArmorClient)


def ensure_template():
    try:
        return client().create_template(request={"parent": gcp.PARENT, "template_id": TEMPLATE_ID, "template": {"filter_config": {
            "pi_and_jailbreak_filter_settings": {"filter_enforcement": "ENABLED", "confidence_level": "MEDIUM_AND_ABOVE"},
            "rai_settings": {"rai_filters": [{"filter_type": "DANGEROUS", "confidence_level": "MEDIUM_AND_ABOVE"}]},
            "sdp_settings": {"basic_config": {"filter_enforcement": "ENABLED"}}}}}).name
    except gex.Conflict:      # 409: already created by the other chapter
        return client().get_template(request={"name": TEMPLATE}).name


def match(result):
    return result.sanitization_result.filter_match_state == ma.FilterMatchState.MATCH_FOUND
