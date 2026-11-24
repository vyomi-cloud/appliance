from azure.ai.contentsafety import ContentSafetyClient
from azure.ai.contentsafety.models import AnalyzeTextOptions
from azure.core.credentials import AzureKeyCredential
from azlab import ENDPOINT

_client = ContentSafetyClient(ENDPOINT, AzureKeyCredential("vyomi-local"))
THRESHOLD = 2


def severities(text):
    return {x.category: x.severity for x in _client.analyze_text(AnalyzeTextOptions(text=text)).categories_analysis}


def check_output(text):
    sev = severities(text)
    return {"allowed": all((v or 0) < THRESHOLD for v in sev.values()), "severities": sev}


if __name__ == "__main__":
    from respond import answer
    good = check_output(answer("What must I do when boiler pressure exceeds 30 psi?")["answer"])
    bad = check_output("You should torture and kill the technician who reports to you.")
    print("agent answer allowed:", good["allowed"])
    print("harmful completion allowed:", bad["allowed"], "| flagged categories:", [k for k, v in bad["severities"].items() if v and v >= 2])
