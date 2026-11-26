from azure.mgmt.web import WebSiteManagementClient
from azure.mgmt.web.models import StringDictionary
from azlab import arm, RG
from azdata import FUNCTION_APP
import rag_design

web = arm(WebSiteManagementClient)
settings = dict(web.web_apps.list_application_settings(RG, FUNCTION_APP).properties or {})
settings["RAG_TOP_K"] = str(rag_design.top_k())
web.web_apps.update_application_settings(RG, FUNCTION_APP, StringDictionary(properties=settings))
print("kb-search now returns", web.web_apps.list_application_settings(RG, FUNCTION_APP).properties["RAG_TOP_K"], "passages")
