from azure.ai.contentsafety import ContentSafetyClient
from azure.ai.contentsafety.models import AnalyzeTextOptions
from azure.core.credentials import AzureKeyCredential
from azlab import ENDPOINT

client = ContentSafetyClient(ENDPOINT, AzureKeyCredential("vyomi-local"))


def screen(text):
    return {x.category: x.severity for x in client.analyze_text(AnalyzeTextOptions(text=text)).categories_analysis}


ok = screen("What is the SOP when boiler pressure exceeds 30 psi?")
bad = screen("I am going to kill and torture you")
print("benign question flagged:", any(v for v in ok.values()))
print("threat flagged:", any(v and v > 0 for v in bad.values()), "| categories:", {k: v for k, v in bad.items() if v})
