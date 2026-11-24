import time
from azdata import table

TABLE = "longtermmemory"


def _pk(tenant, user):
    return f"{tenant}|{user}".replace("/", "_").replace("#", "_").replace("?", "_")[:60]


def remember(tenant, user, key, fact, source="session"):
    table(TABLE).upsert_entity({"PartitionKey": _pk(tenant, user), "RowKey": key, "fact": fact, "source": source, "ts": int(time.time())})


def recall(tenant, user):
    return [dict(e) for e in table(TABLE).query_entities("PartitionKey eq @u", parameters={"u": _pk(tenant, user)})]


def forget(tenant, user, key):
    table(TABLE).delete_entity(_pk(tenant, user), key)
