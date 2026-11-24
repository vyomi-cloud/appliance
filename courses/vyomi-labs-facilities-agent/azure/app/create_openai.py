from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
from azlab import arm, ensure_rg, pick_models, RG, LOC, OPENAI_ACCOUNT, CHAT, EMBED

ensure_rg()
cs = arm(CognitiveServicesManagementClient)
cs.accounts.begin_create(RG, OPENAI_ACCOUNT, {"location": LOC, "kind": "OpenAI", "sku": {"name": "S0"},
                                              "properties": {"customSubDomainName": OPENAI_ACCOUNT}}).result()
chat_model, embed_model = pick_models()
for name, model in ((CHAT, chat_model), (EMBED, embed_model)):
    cs.deployments.begin_create_or_update(RG, OPENAI_ACCOUNT, name, {"sku": {"name": "Standard", "capacity": 1},
        "properties": {"model": model}}).result()
print("deployments:", sorted(d.name for d in cs.deployments.list(RG, OPENAI_ACCOUNT)))
