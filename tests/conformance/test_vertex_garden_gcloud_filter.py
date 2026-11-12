"""gcloud ai model-garden models list sends filter=is_hf_wildcard(false) [AND (model_user_id=~"(?i).*x.*" OR display_name=~...)]
on publishers/*/models; it must list the catalogue (it used to return an empty list)."""
import json
from core import gcp_vertex_core as g


def _n(q):
    b = g._model_garden("GET", "*", None, q).body
    return len((json.loads(b) if isinstance(b, (str, bytes)) else b)["publisherModels"])


def run():
    assert _n({}) == _n({"filter": "is_hf_wildcard(false)"}) > 0
    assert 0 < _n({"filter": 'is_hf_wildcard(false) AND (model_user_id=~"(?i).*qwen.*" OR display_name=~"(?i).*qwen.*")'}) < _n({})
    print("GCLOUD GARDEN FILTER OK")


if __name__ == "__main__":
    run()
