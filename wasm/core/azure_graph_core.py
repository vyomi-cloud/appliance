# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Microsoft Graph core — the Azure peer of GCP's resourcemanager/iam REST cores, backing
Microsoft Entra ID (Azure AD): users, groups (+members), app registrations (applications),
enterprise applications (servicePrincipals), verified domains, administrative units, the
tenant (organization) record, and a directory audit log that the simulator appends to on
every mutation (the native console's "Audit logs" page, driven by real activity rather than
sample data).

NO fastapi / azure-sdk / socket imports → loads under Pyodide. State lives in a
self-contained in-memory `GraphStore` (no external seam — the resource model is Graph-
specific, parallel to core/azure_cosmos_core.py's CosmosStore).

Wire is Microsoft Graph v1.0 JSON (collections as {"value": [...]}, singletons as a bare
object). Routed by the `/v1.0/...` (or `/beta/...`) path prefix — core/aws_wire_router.py's
_azure_service() sends anything under that prefix here before any other Azure data-plane
check runs, so it can never collide with ARM / Blob / Cosmos / Key Vault paths.

  GET/POST          /v1.0/users                                  list / create
  GET/PATCH/DELETE  /v1.0/users/{id}
  GET/POST          /v1.0/groups                                 list / create
  GET/PATCH/DELETE  /v1.0/groups/{id}
  GET               /v1.0/groups/{id}/members
  POST              /v1.0/groups/{id}/members/$ref                add ({"@odata.id": ".../users/{id}"})
  DELETE            /v1.0/groups/{id}/members/{id}/$ref           remove
  GET               /v1.0/users/{id}/memberOf                     groups the user belongs to
  GET/POST          /v1.0/applications                            list / create (app registration)
  GET/PATCH/DELETE  /v1.0/applications/{id}
  POST              /v1.0/applications/{id}/addPassword           -> {secretText, keyId, ...}
  POST              /v1.0/applications/{id}/removePassword
  GET/POST          /v1.0/servicePrincipals                       list / create (enterprise app)
  GET/DELETE        /v1.0/servicePrincipals/{id}
  GET/POST          /v1.0/domains                                 list / add custom domain
  DELETE            /v1.0/domains/{name}
  GET/POST          /v1.0/directory/administrativeUnits           list / create
  GET/DELETE        /v1.0/directory/administrativeUnits/{id}
  GET/PATCH         /v1.0/organization/{id}                        tenant record (Properties page)
  GET               /v1.0/organization                             -> {"value": [the one tenant]}
  GET/DELETE        /v1.0/devices/{id}
  GET               /v1.0/devices                                  every registered device, any owner
  GET/POST          /v1.0/users/{id}/registeredDevices             a user's own devices / register one
                                                                     (Vyomi has no OS-level join client,
                                                                     so this admin-facing POST stands in
                                                                     for the real device-registration
                                                                     service — the resulting object is a
                                                                     real device/{id}, not stored config)
  GET               /v1.0/auditLogs/directoryAudits                real, appended on every mutation
  GET               /v1.0/auditLogs/signIns                        real: every /oauth2/v2.0/token call
                                                                     below appends a row (service
                                                                     principal sign-ins only — Vyomi has
                                                                     no interactive browser sign-in flow)
  POST              /{tenant}/oauth2/v2.0/token                    client_credentials grant: validates
                                                                     the caller's real client secret
                                                                     (core/azure_graph_core.py's own
                                                                     store, set by addPassword/
                                                                     removePassword) -> access_token or
                                                                     invalid_client, never synthetic
  GET/PATCH         /v1.0/policies/identitySecurityDefaultsEnforcementPolicy
                                                                     stored/returned as set, not enforced

Errors: Graph-shaped JSON {"error": {"code": ..., "message": ...}} with the matching HTTP
status (400 Request_BadRequest, 403 Authorization_RequestDenied, 404 Request_ResourceNotFound,
409 Request_Conflict). 403 is raised for security-group / application creation when the
matching "User settings" toggle (directory_settings) disables it. The OAuth2 token endpoint
returns AAD's own shape instead: {"error": "invalid_client", "error_description": ...}.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Response:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


DEFAULT_TENANT_ID = "00000000-0000-0000-0000-cloudlearn01"
DEFAULT_DOMAIN = "vyomilearn.onmicrosoft.com"


def _guid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _json(status: int, obj: dict) -> Response:
    return Response(status=status, body=json.dumps(obj).encode("utf-8"))


def _err(status: int, code: str, message: str) -> Response:
    return Response(status=status, body=json.dumps({"error": {"code": code, "message": message}}).encode("utf-8"))


def _collection(items: list) -> Response:
    return _json(200, {"value": items})


# ── store ────────────────────────────────────────────────────────────────────
class GraphStore:
    """Self-contained in-memory directory. Every dict is keyed by object id (a GUID)
    except `domains`, keyed by the domain name itself."""

    def __init__(self) -> None:
        self.users: dict[str, dict] = {}
        self.groups: dict[str, dict] = {}
        self.group_members: dict[str, set] = {}     # group id -> set of member ids (users or groups)
        self.applications: dict[str, dict] = {}
        self.service_principals: dict[str, dict] = {}
        self.domains: dict[str, dict] = {
            DEFAULT_DOMAIN: {"id": DEFAULT_DOMAIN, "isDefault": True, "isVerified": True,
                             "isInitial": True, "authenticationType": "Managed",
                             "supportedServices": ["Email", "OfficeCommunicationsOnline"]},
        }
        self.administrative_units: dict[str, dict] = {}
        self.devices: dict[str, dict] = {}
        # keyId -> {"appId": ..., "secret": plaintext}. Separate from the application's own
        # passwordCredentials (which only ever expose the 3-char "hint", matching real Graph)
        # so the oauth2/v2.0/token endpoint can validate a real caller-supplied secret without
        # ever returning it again. Removed on removePassword — a revoked secret stops signing in.
        self.app_secrets: dict[str, dict] = {}
        self.organization: dict = {
            "id": DEFAULT_TENANT_ID,
            "displayName": "Default Directory",
            "verifiedDomains": [{"name": DEFAULT_DOMAIN, "isDefault": True, "isInitial": True, "capabilities": "Email, OfficeCommunicationsOnline"}],
            "technicalNotificationMails": [],
            "privacyProfile": {"contactEmail": "", "statementUrl": ""},
            "createdDateTime": _now(),
        }
        # User settings (Default Directory | User settings). usersCanCreateSecurityGroups
        # and usersCanRegisterApplications are ENFORCED (azure.entra.directory_settings:
        # limited) — see _create_group / _create_application. The real console only applies
        # them to non-admin members; Vyomi has no signed-in-identity model to tell members
        # from admins apart, so the toggle gates every caller tenant-wide. The remaining
        # toggles (guest access, tenant creation, admin-center access, LinkedIn, keep-signed-
        # in) are stored and returned exactly as set but have no subsystem to enforce them
        # against.
        self.directory_settings: dict = {
            "usersCanRegisterApplications": True,
            "usersCanRegisterAgentIdentityBlueprints": True,
            "restrictNonAdminUsersFromCreatingTenants": False,
            "usersCanCreateSecurityGroups": True,
            "guestUserAccess": "Guest users have the same access as members (most inclusive)",
            "restrictAccessToAdminCenter": False,
            "linkedInConnections": "Yes",
            "showKeepUserSignedIn": True,
        }
        self.audit_logs: list[dict] = []
        self.sign_in_logs: list[dict] = []
        # Security defaults (Entra ID | Properties' "Manage security defaults" panel,
        # azure.entra.security_defaults): a real Graph policy document, stored and
        # returned exactly as set — Vyomi has no interactive sign-in flow to enforce the
        # MFA/legacy-auth requirements it describes against.
        self.security_defaults: dict = {
            "id": "00000000-0000-0000-0000-securitydflt",
            "displayName": "Security Defaults",
            "description": "Security defaults is a set of basic identity security mechanisms recommended by Microsoft.",
            "isEnabled": True,
        }

    def persist(self) -> None:
        """Write-through hook (no-op in-memory; a backed subclass overrides it)."""

    def audit(self, activity: str, category: str, target: str, result: str = "success") -> None:
        self.audit_logs.insert(0, {
            "id": _guid(), "activityDateTime": _now(), "activityDisplayName": activity,
            "category": category, "loggedByService": "Core Directory",
            "result": result, "resultReason": "",
            "initiatedBy": {"user": {"displayName": "Vyomi Console", "userPrincipalName": "console@" + DEFAULT_DOMAIN}},
            "targetResources": [{"displayName": target, "type": category}],
        })

    def sign_in(self, app: dict | None, app_id: str, success: bool, error_code: int, failure_reason: str | None) -> None:
        """Append a real "Service principal sign-ins" row — called only from the
        oauth2/v2.0/token client_credentials grant below, so every entry here reflects an
        actual client-secret check (never sample/random data)."""
        self.sign_in_logs.insert(0, {
            "id": _guid(), "createdDateTime": _now(),
            "userDisplayName": None, "userPrincipalName": None,
            "appDisplayName": (app or {}).get("displayName") or "Unknown application",
            "appId": app_id,
            "ipAddress": "127.0.0.1", "location": {"city": None, "state": None, "countryOrRegion": None},
            "clientAppUsed": "Other clients",
            "signInEventTypes": ["servicePrincipal"],
            "isInteractive": False,
            "conditionalAccessStatus": "notApplied",
            "authenticationRequirement": "singleFactorAuthentication",
            "status": {"errorCode": 0 if success else error_code, "failureReason": None if success else failure_reason, "additionalDetails": None},
        })


# ── users ────────────────────────────────────────────────────────────────────
def _user_view(u: dict) -> dict:
    return {k: v for k, v in u.items() if not k.startswith("_")}


def _create_user(store: GraphStore, body: dict) -> Response:
    upn = body.get("userPrincipalName") or ""
    if not upn or not body.get("displayName"):
        return _err(400, "Request_BadRequest", "userPrincipalName and displayName are required.")
    if any(u["userPrincipalName"].lower() == upn.lower() for u in store.users.values()):
        return _err(409, "Request_Conflict", f"Another object with the same value for property userPrincipalName already exists.")
    uid = _guid()
    pwd = body.get("passwordProfile") or {}
    user = {
        "id": uid,
        "displayName": body["displayName"],
        "userPrincipalName": upn,
        "mailNickname": body.get("mailNickname") or upn.split("@")[0],
        "accountEnabled": body.get("accountEnabled", True),
        "userType": body.get("userType", "Member"),
        "givenName": body.get("givenName"),
        "surname": body.get("surname"),
        "jobTitle": body.get("jobTitle"),
        "companyName": body.get("companyName"),
        "department": body.get("department"),
        "mail": body.get("mail"),
        "mobilePhone": body.get("mobilePhone"),
        "usageLocation": body.get("usageLocation"),
        "onPremisesSyncEnabled": None,
        "creationType": None if body.get("userType") != "Guest" else "Invitation",
        "isAgent": False,
        "createdDateTime": _now(),
        "passwordProfile": {"forceChangePasswordNextSignIn": pwd.get("forceChangePasswordNextSignIn", True)},
    }
    store.users[uid] = user
    store.audit("Add user", "UserManagement", user["displayName"])
    return _json(201, _user_view(user))


def _list_users(store: GraphStore) -> Response:
    return _collection([_user_view(u) for u in store.users.values()])


def _get_user(store: GraphStore, uid: str) -> Response:
    u = store.users.get(uid) or next((x for x in store.users.values()
                                      if x["userPrincipalName"].lower() == uid.lower() or x["displayName"].lower() == uid.lower()), None)
    if not u:
        return _err(404, "Request_ResourceNotFound", f"Resource '{uid}' does not exist.")
    return _json(200, _user_view(u))


def _patch_user(store: GraphStore, uid: str, body: dict) -> Response:
    u = store.users.get(uid)
    if not u:
        return _err(404, "Request_ResourceNotFound", f"Resource '{uid}' does not exist.")
    u.update({k: v for k, v in body.items() if k not in ("id",)})
    store.audit("Update user", "UserManagement", u["displayName"])
    return Response(status=204)


def _delete_user(store: GraphStore, uid: str) -> Response:
    u = store.users.pop(uid, None)
    if not u:
        return _err(404, "Request_ResourceNotFound", f"Resource '{uid}' does not exist.")
    for members in store.group_members.values():
        members.discard(uid)
    store.audit("Delete user", "UserManagement", u["displayName"])
    return Response(status=204)


def _member_of(store: GraphStore, uid: str) -> Response:
    groups = [g for gid, g in store.groups.items() if uid in store.group_members.get(gid, set())]
    return _collection([{"id": g["id"], "displayName": g["displayName"], "@odata.type": "#microsoft.graph.group"} for g in groups])


# ── groups ───────────────────────────────────────────────────────────────────
def _group_view(g: dict) -> dict:
    return {k: v for k, v in g.items() if not k.startswith("_")}


def _create_group(store: GraphStore, body: dict) -> Response:
    name = body.get("displayName")
    if not name:
        return _err(400, "Request_BadRequest", "displayName is required.")
    unified = "Unified" in (body.get("groupTypes") or [])
    if not unified and not store.directory_settings.get("usersCanCreateSecurityGroups", True):
        return _err(403, "Authorization_RequestDenied",
                     "Insufficient privileges to complete the operation. "
                     "Security group creation is disabled by the 'Users can create security groups' tenant setting.")
    gid = _guid()
    mail_nickname = body.get("mailNickname") or re.sub(r"[^a-zA-Z0-9-]", "", name).lower() or gid[:8]
    group = {
        "id": gid,
        "displayName": name,
        "description": body.get("description"),
        "mailNickname": mail_nickname,
        "mailEnabled": bool(body.get("mailEnabled", unified)),
        "securityEnabled": bool(body.get("securityEnabled", not unified)),
        "groupTypes": body.get("groupTypes") or [],
        "isAssignableToRole": body.get("isAssignableToRole", False),
        "membershipType": "Dynamic" if body.get("membershipRule") else "Assigned",
        "mail": (mail_nickname + "@" + DEFAULT_DOMAIN) if unified else None,
        "onPremisesSyncEnabled": None,
        "createdDateTime": _now(),
    }
    store.groups[gid] = group
    store.group_members[gid] = set(body.get("_initial_members") or [])
    store.audit("Add group", "GroupManagement", group["displayName"])
    return _json(201, _group_view(group))


def _list_groups(store: GraphStore) -> Response:
    return _collection([_group_view(g) for g in store.groups.values()])


def _get_group(store: GraphStore, gid: str) -> Response:
    g = store.groups.get(gid) or next((x for x in store.groups.values() if x["displayName"].lower() == gid.lower()), None)
    if not g:
        return _err(404, "Request_ResourceNotFound", f"Resource '{gid}' does not exist.")
    return _json(200, _group_view(g))


def _delete_group(store: GraphStore, gid: str) -> Response:
    g = store.groups.pop(gid, None)
    if not g:
        return _err(404, "Request_ResourceNotFound", f"Resource '{gid}' does not exist.")
    store.group_members.pop(gid, None)
    store.audit("Delete group", "GroupManagement", g["displayName"])
    return Response(status=204)


def _list_members(store: GraphStore, gid: str) -> Response:
    if gid not in store.groups:
        return _err(404, "Request_ResourceNotFound", f"Resource '{gid}' does not exist.")
    ids = store.group_members.get(gid, set())
    out = []
    for mid in ids:
        if mid in store.users:
            out.append({**_user_view(store.users[mid]), "@odata.type": "#microsoft.graph.user"})
        elif mid in store.groups:
            out.append({**_group_view(store.groups[mid]), "@odata.type": "#microsoft.graph.group"})
    return _collection(out)


def _add_member(store: GraphStore, gid: str, body: dict) -> Response:
    if gid not in store.groups:
        return _err(404, "Request_ResourceNotFound", f"Resource '{gid}' does not exist.")
    ref = body.get("@odata.id", "")
    mid = ref.rstrip("/").rsplit("/", 1)[-1]
    if not mid or (mid not in store.users and mid not in store.groups):
        return _err(400, "Request_BadRequest", "@odata.id must reference an existing directoryObject.")
    store.group_members.setdefault(gid, set()).add(mid)
    return Response(status=204)


def _remove_member(store: GraphStore, gid: str, mid: str) -> Response:
    if gid not in store.group_members or mid not in store.group_members[gid]:
        return _err(404, "Request_ResourceNotFound", "Member not found.")
    store.group_members[gid].discard(mid)
    return Response(status=204)


# ── applications (app registrations) + service principals (enterprise apps) ──
def _app_view(a: dict) -> dict:
    return {k: v for k, v in a.items() if not k.startswith("_")}


def _create_application(store: GraphStore, body: dict) -> Response:
    name = body.get("displayName")
    if not name:
        return _err(400, "Request_BadRequest", "displayName is required.")
    if not store.directory_settings.get("usersCanRegisterApplications", True):
        return _err(403, "Authorization_RequestDenied",
                     "Insufficient privileges to complete the operation. "
                     "Application registration is disabled by the 'Users can register applications' tenant setting.")
    oid, app_id, tenant = _guid(), _guid(), DEFAULT_TENANT_ID
    app = {
        "id": oid,
        "appId": app_id,
        "displayName": name,
        "signInAudience": body.get("signInAudience", "AzureADMyOrg"),
        "web": body.get("web") or {"redirectUris": []},
        "spa": body.get("spa") or {"redirectUris": []},
        "publicClient": body.get("publicClient") or {"redirectUris": []},
        "identifierUris": body.get("identifierUris") or [],
        "passwordCredentials": [],
        "requiredResourceAccess": [{
            "resourceAppId": "00000003-0000-0000-c000-000000000000",   # Microsoft Graph
            "resourceAccess": [{"id": "e1fe6dd8-ba31-4d61-89e7-88639da4683d", "type": "Scope"}],   # User.Read
        }],
        "createdDateTime": _now(),
    }
    store.applications[oid] = app
    sp_id = _guid()
    store.service_principals[sp_id] = {
        "id": sp_id, "appId": app_id, "displayName": name,
        "homepage": (body.get("web") or {}).get("homePageUrl"),
        "servicePrincipalType": "Application", "accountEnabled": True,
        "appOwnerOrganizationId": tenant, "tags": [],
        "createdDateTime": _now(),
    }
    store.audit("Add application", "ApplicationManagement", name)
    return _json(201, _app_view(app))


def _list_applications(store: GraphStore) -> Response:
    return _collection([_app_view(a) for a in store.applications.values()])


def _get_application(store: GraphStore, oid: str) -> Response:
    a = store.applications.get(oid) or next((x for x in store.applications.values() if x["displayName"].lower() == oid.lower()), None)
    if not a:
        return _err(404, "Request_ResourceNotFound", f"Resource '{oid}' does not exist.")
    return _json(200, _app_view(a))


def _patch_application(store: GraphStore, oid: str, body: dict) -> Response:
    a = store.applications.get(oid)
    if not a:
        return _err(404, "Request_ResourceNotFound", f"Resource '{oid}' does not exist.")
    a.update({k: v for k, v in body.items() if k not in ("id", "appId", "passwordCredentials")})
    store.audit("Update application", "ApplicationManagement", a["displayName"])
    return Response(status=204)


def _delete_application(store: GraphStore, oid: str) -> Response:
    a = store.applications.pop(oid, None)
    if not a:
        return _err(404, "Request_ResourceNotFound", f"Resource '{oid}' does not exist.")
    for sid, sp in list(store.service_principals.items()):
        if sp.get("appId") == a["appId"]:
            store.service_principals.pop(sid, None)
    for c in a.get("passwordCredentials", []):
        store.app_secrets.pop(c["keyId"], None)
    store.audit("Delete application", "ApplicationManagement", a["displayName"])
    return Response(status=204)


def _add_password(store: GraphStore, oid: str, body: dict) -> Response:
    a = store.applications.get(oid)
    if not a:
        return _err(404, "Request_ResourceNotFound", f"Resource '{oid}' does not exist.")
    cred = body.get("passwordCredential") or {}
    key_id = _guid()
    secret = uuid.uuid4().hex + uuid.uuid4().hex[:10]
    entry = {
        "keyId": key_id, "displayName": cred.get("displayName") or "",
        "startDateTime": _now(), "endDateTime": cred.get("endDateTime") or "",
        "hint": secret[:3],
    }
    a["passwordCredentials"].append(entry)
    store.app_secrets[key_id] = {"appId": a["appId"], "secret": secret}
    store.audit("Add application password", "ApplicationManagement", a["displayName"])
    return _json(200, {**entry, "secretText": secret})


def _remove_password(store: GraphStore, oid: str, body: dict) -> Response:
    a = store.applications.get(oid)
    if not a:
        return _err(404, "Request_ResourceNotFound", f"Resource '{oid}' does not exist.")
    key_id = body.get("keyId")
    a["passwordCredentials"] = [c for c in a["passwordCredentials"] if c["keyId"] != key_id]
    store.app_secrets.pop(key_id, None)   # revoked — oauth2/v2.0/token rejects it from now on
    return Response(status=204)


def _list_service_principals(store: GraphStore) -> Response:
    return _collection(list(store.service_principals.values()))


def _get_service_principal(store: GraphStore, sid: str) -> Response:
    sp = store.service_principals.get(sid)
    if not sp:
        return _err(404, "Request_ResourceNotFound", f"Resource '{sid}' does not exist.")
    return _json(200, sp)


def _delete_service_principal(store: GraphStore, sid: str) -> Response:
    if store.service_principals.pop(sid, None) is None:
        return _err(404, "Request_ResourceNotFound", f"Resource '{sid}' does not exist.")
    return Response(status=204)


# ── domains ──────────────────────────────────────────────────────────────────
def _list_domains(store: GraphStore) -> Response:
    return _collection(list(store.domains.values()))


def _add_domain(store: GraphStore, body: dict) -> Response:
    name = body.get("id")
    if not name:
        return _err(400, "Request_BadRequest", "id (the domain name) is required.")
    if name in store.domains:
        return _err(409, "Request_Conflict", f"Domain '{name}' already exists.")
    d = {"id": name, "isDefault": False, "isVerified": False, "isInitial": False,
         "authenticationType": "Managed", "supportedServices": []}
    store.domains[name] = d
    store.audit("Add domain", "DirectoryManagement", name)
    return _json(201, d)


def _delete_domain(store: GraphStore, name: str) -> Response:
    d = store.domains.get(name)
    if not d:
        return _err(404, "Request_ResourceNotFound", f"Resource '{name}' does not exist.")
    if d.get("isInitial"):
        return _err(400, "Request_BadRequest", "The initial (default) domain cannot be removed.")
    store.domains.pop(name)
    store.audit("Remove domain", "DirectoryManagement", name)
    return Response(status=204)


# ── administrative units ─────────────────────────────────────────────────────
def _create_au(store: GraphStore, body: dict) -> Response:
    name = body.get("displayName")
    if not name:
        return _err(400, "Request_BadRequest", "displayName is required.")
    auid = _guid()
    au = {"id": auid, "displayName": name, "description": body.get("description"),
          "membershipType": "Dynamic" if body.get("membershipRule") else "Assigned",
          "isMemberManagementRestricted": bool(body.get("isMemberManagementRestricted", False))}
    store.administrative_units[auid] = au
    store.audit("Add administrative unit", "DirectoryManagement", name)
    return _json(201, au)


def _list_aus(store: GraphStore) -> Response:
    return _collection(list(store.administrative_units.values()))


def _delete_au(store: GraphStore, auid: str) -> Response:
    au = store.administrative_units.pop(auid, None)
    if not au:
        return _err(404, "Request_ResourceNotFound", f"Resource '{auid}' does not exist.")
    store.audit("Delete administrative unit", "DirectoryManagement", au["displayName"])
    return Response(status=204)


# ── devices (Devices blade; a user's own "Devices" tab registers/lists them) ──
# Real Entra ID devices self-register through an OS-level join client (Azure AD Join,
# Hybrid Join, workplace join) or the AADLoginForWindows/AADSSHLoginForLinux VM
# extension — Vyomi has no OS or VM client to drive that protocol. What IS reasonable to
# model directly: Microsoft Graph's own device object (POST /devices is real, used by
# sync/MDM agents) and its owner relationship, so a real device/{id} exists, is listed,
# and is deletable — not stored config, an actual directory object other calls can see.
def _device_view(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_")}


def _create_device(store: GraphStore, uid: str, body: dict) -> Response:
    owner = store.users.get(uid)
    if not owner:
        return _err(404, "Request_ResourceNotFound", f"Resource '{uid}' does not exist.")
    name = body.get("displayName")
    os_name = body.get("operatingSystem")
    if not name or not os_name:
        return _err(400, "Request_BadRequest", "displayName and operatingSystem are required.")
    did = _guid()
    now = _now()
    device = {
        "id": did, "deviceId": str(uuid.uuid4()),
        "displayName": name, "operatingSystem": os_name,
        "operatingSystemVersion": body.get("operatingSystemVersion") or "",
        "trustType": body.get("trustType") or "AzureAd",
        "profileType": "RegisteredDevice", "accountEnabled": True,
        "isCompliant": bool(body.get("isCompliant", False)),
        "isManaged": bool(body.get("isManaged", False)),
        "registrationDateTime": now, "approximateLastSignInDateTime": now,
        "registeredOwnerId": uid,
    }
    store.devices[did] = device
    store.audit("Register device", "DeviceManagement", name)
    return _json(201, _device_view(device))


def _list_devices(store: GraphStore) -> Response:
    return _collection([_device_view(d) for d in store.devices.values()])


def _list_registered_devices(store: GraphStore, uid: str) -> Response:
    if uid not in store.users:
        return _err(404, "Request_ResourceNotFound", f"Resource '{uid}' does not exist.")
    return _collection([_device_view(d) for d in store.devices.values() if d["registeredOwnerId"] == uid])


def _get_device(store: GraphStore, did: str) -> Response:
    d = store.devices.get(did)
    if not d:
        return _err(404, "Request_ResourceNotFound", f"Resource '{did}' does not exist.")
    return _json(200, _device_view(d))


def _delete_device(store: GraphStore, did: str) -> Response:
    d = store.devices.pop(did, None)
    if not d:
        return _err(404, "Request_ResourceNotFound", f"Resource '{did}' does not exist.")
    store.audit("Delete device", "DeviceManagement", d["displayName"])
    return Response(status=204)


# ── organization (tenant) ─────────────────────────────────────────────────────
def _get_organization(store: GraphStore) -> Response:
    return _collection([store.organization])


def _patch_organization(store: GraphStore, body: dict) -> Response:
    org = store.organization
    for k in ("displayName", "technicalNotificationMails"):
        if k in body:
            org[k] = body[k]
    if "privacyProfile" in body:
        org["privacyProfile"] = {**org["privacyProfile"], **body["privacyProfile"]}
    store.audit("Update company information", "DirectoryManagement", org["displayName"])
    return Response(status=204)


# ── directory settings (User settings page) ───────────────────────────────────
def _get_directory_settings(store: GraphStore) -> Response:
    return _json(200, store.directory_settings)


def _patch_directory_settings(store: GraphStore, body: dict) -> Response:
    store.directory_settings.update(body)
    store.audit("Update user settings", "DirectoryManagement", "Default Directory")
    return Response(status=204)


# ── security defaults policy (Properties | Security defaults panel) ──────────
def _get_security_defaults(store: GraphStore) -> Response:
    return _json(200, store.security_defaults)


def _patch_security_defaults(store: GraphStore, body: dict) -> Response:
    if "isEnabled" in body:
        store.security_defaults["isEnabled"] = bool(body["isEnabled"])
    store.audit("Update security defaults", "Policy", "Security Defaults")
    return Response(status=204)


# ── audit / sign-in logs ───────────────────────────────────────────────────────
def _list_audit_logs(store: GraphStore) -> Response:
    return _collection(store.audit_logs)


def _list_sign_in_logs(store: GraphStore) -> Response:
    return _collection(store.sign_in_logs)   # real rows, appended by _token() below


# ── oauth2 token endpoint (POST /{tenant}/oauth2/v2.0/token) ─────────────────
# The one piece of real authentication Vyomi can model without an interactive browser:
# an app proving it holds a REAL client secret (the one addPassword returned) to get an
# access token, the "service principal sign-in" telemetry real Entra ID also records for
# this grant. Every outcome below — success, wrong secret, revoked secret, disabled
# enterprise app, unknown client — both decides the HTTP response AND appends the sign-in
# log row; nothing here is sample data layered on top of a stored flag.
def _oauth_err(status: int, code: str, description: str) -> Response:
    return _json(status, {"error": code, "error_description": description})


def _token(store: GraphStore, method: str, body: bytes) -> Response:
    if method != "POST":
        return _err(405, "Request_UnsupportedQuery", method)
    from urllib.parse import parse_qs
    form = {k: v[0] for k, v in parse_qs((body or b"").decode("utf-8")).items()}
    client_id = form.get("client_id", "")
    if form.get("grant_type") != "client_credentials":
        return _oauth_err(400, "unsupported_grant_type", "Vyomi only simulates the client_credentials grant.")
    app = next((a for a in store.applications.values() if a["appId"] == client_id), None)
    if not app:
        store.sign_in(None, client_id, False, 700016, "Application not found in the directory.")
        return _oauth_err(400, "invalid_client", f"AADSTS700016: Application with identifier '{client_id}' was not found in the directory.")
    sp = next((s for s in store.service_principals.values() if s["appId"] == client_id), None)
    if sp is not None and not sp.get("accountEnabled", True):
        store.sign_in(app, client_id, False, 700016, "The enterprise application is disabled.")
        return _oauth_err(400, "unauthorized_client", "AADSTS700016: The application is disabled.")
    client_secret = form.get("client_secret", "")
    live_key_ids = {c["keyId"] for c in app.get("passwordCredentials", [])}
    valid = bool(client_secret) and any(
        kid in live_key_ids and entry.get("secret") == client_secret
        for kid, entry in store.app_secrets.items() if entry.get("appId") == client_id
    )
    if not valid:
        store.sign_in(app, client_id, False, 7000215, "Invalid client secret is provided.")
        return _oauth_err(401, "invalid_client", "AADSTS7000215: Invalid client secret is provided.")
    store.sign_in(app, client_id, True, 0, None)
    token = "vyomi." + uuid.uuid4().hex + uuid.uuid4().hex
    return _json(200, {"token_type": "Bearer", "expires_in": 3599, "ext_expires_in": 3599,
                        "access_token": token, "scope": form.get("scope", "")})


# ── dispatch ────────────────────────────────────────────────────────────────
def dispatch(store: GraphStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> Response:
    method = (method or "GET").upper()
    p = path.split("?", 1)[0]
    # oauth2/v2.0/token carries no /v1.0 or /beta prefix (it's not a Graph path at all in
    # real Azure — a different host, login.microsoftonline.com — but this relay routes by
    # path shape alone), so it's checked before the Graph-version prefix is stripped below.
    raw_segs = [s for s in p.split("/") if s != ""]
    if raw_segs and raw_segs[-1] == "token" and "oauth2" in raw_segs:
        return _token(store, method, body)
    if p.startswith("/v1.0"):
        p = p[len("/v1.0"):]
    elif p.startswith("/beta"):
        p = p[len("/beta"):]
    segs = [s for s in p.split("/") if s != ""]
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        payload = {}

    if not segs:
        return _err(404, "Request_ResourceNotFound", f"Unknown path: {path}")

    head = segs[0].lower()

    if head == "users":
        if len(segs) == 1:
            return _list_users(store) if method == "GET" else _create_user(store, payload) if method == "POST" else _err(405, "Request_UnsupportedQuery", method)
        if len(segs) == 2:
            uid = segs[1]
            if method == "GET":
                return _get_user(store, uid)
            if method == "PATCH":
                return _patch_user(store, uid, payload)
            if method == "DELETE":
                return _delete_user(store, uid)
        if len(segs) == 3 and segs[2] == "memberOf" and method == "GET":
            return _member_of(store, segs[1])
        if len(segs) == 3 and segs[2] == "registeredDevices":
            if method == "GET":
                return _list_registered_devices(store, segs[1])
            if method == "POST":
                return _create_device(store, segs[1], payload)

    if head == "devices":
        if len(segs) == 1 and method == "GET":
            return _list_devices(store)
        if len(segs) == 2:
            if method == "GET":
                return _get_device(store, segs[1])
            if method == "DELETE":
                return _delete_device(store, segs[1])

    if head == "groups":
        if len(segs) == 1:
            return _list_groups(store) if method == "GET" else _create_group(store, payload) if method == "POST" else _err(405, "Request_UnsupportedQuery", method)
        if len(segs) == 2:
            gid = segs[1]
            if method == "GET":
                return _get_group(store, gid)
            if method == "DELETE":
                return _delete_group(store, gid)
        if len(segs) == 3 and segs[2] == "members" and method == "GET":
            return _list_members(store, segs[1])
        if len(segs) == 4 and segs[2] == "members" and segs[3] == "$ref" and method == "POST":
            return _add_member(store, segs[1], payload)
        if len(segs) == 5 and segs[2] == "members" and segs[4] == "$ref" and method == "DELETE":
            return _remove_member(store, segs[1], segs[3])

    if head == "applications":
        if len(segs) == 1:
            return _list_applications(store) if method == "GET" else _create_application(store, payload) if method == "POST" else _err(405, "Request_UnsupportedQuery", method)
        if len(segs) == 2:
            oid = segs[1]
            if method == "GET":
                return _get_application(store, oid)
            if method == "PATCH":
                return _patch_application(store, oid, payload)
            if method == "DELETE":
                return _delete_application(store, oid)
        if len(segs) == 3 and segs[2] == "addPassword" and method == "POST":
            return _add_password(store, segs[1], payload)
        if len(segs) == 3 and segs[2] == "removePassword" and method == "POST":
            return _remove_password(store, segs[1], payload)

    if head == "serviceprincipals":
        if len(segs) == 1:
            return _list_service_principals(store) if method == "GET" else _err(405, "Request_UnsupportedQuery", method)
        if len(segs) == 2:
            sid = segs[1]
            if method == "GET":
                return _get_service_principal(store, sid)
            if method == "DELETE":
                return _delete_service_principal(store, sid)

    if head == "domains":
        if len(segs) == 1:
            return _list_domains(store) if method == "GET" else _add_domain(store, payload) if method == "POST" else _err(405, "Request_UnsupportedQuery", method)
        if len(segs) == 2 and method == "DELETE":
            return _delete_domain(store, segs[1])

    if head == "directory" and len(segs) >= 2 and segs[1].lower() == "administrativeunits":
        if len(segs) == 2:
            return _list_aus(store) if method == "GET" else _create_au(store, payload) if method == "POST" else _err(405, "Request_UnsupportedQuery", method)
        if len(segs) == 3 and method == "DELETE":
            return _delete_au(store, segs[2])

    if head == "organization":
        if len(segs) == 1 and method == "GET":
            return _get_organization(store)
        if len(segs) == 2 and method == "PATCH":
            return _patch_organization(store, payload)

    if head == "settings" and len(segs) == 2 and segs[1].lower() == "directory":
        if method == "GET":
            return _get_directory_settings(store)
        if method == "PATCH":
            return _patch_directory_settings(store, payload)

    if head == "policies" and len(segs) == 2 and segs[1].lower() == "identitysecuritydefaultsenforcementpolicy":
        if method == "GET":
            return _get_security_defaults(store)
        if method == "PATCH":
            return _patch_security_defaults(store, payload)

    if head == "auditlogs" and len(segs) == 2:
        if segs[1].lower() == "directoryaudits" and method == "GET":
            return _list_audit_logs(store)
        if segs[1].lower() == "signins" and method == "GET":
            return _list_sign_in_logs(store)

    return _err(404, "Request_ResourceNotFound", f"Unsupported {method} {path}")
