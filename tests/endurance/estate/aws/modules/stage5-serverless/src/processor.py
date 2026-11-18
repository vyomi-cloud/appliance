def handler(event, context):
    return {"processed": len(event.get("Records", []))}
