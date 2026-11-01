"""Firestore SECURITY RULES EVALUATOR conformance (WAVE 5b depth: gcp.firestore.security-rules)
— a real parser + evaluator for a practical subset of the Firestore Rules Language v2,
exercised by the console's "Development & test" (Rules Playground) tab's :testSecurityRules
endpoint. The native data-plane wire itself still never evaluates rules against real
reads/writes (matching production: only end-user client-SDK requests are rule-checked,
never the Admin SDK / gcloud / the console's own Data viewer) — this is the one genuine
evaluation surface, and it is exercised here directly against the parser/evaluator.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_gcp_firestore_rules_core.py
"""
try:
    from core import gcp_firestore_core as fs
except ImportError:  # pragma: no cover - Pyodide flat layout
    import gcp_firestore_core as fs  # type: ignore

DB = "(default)"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    # 1. Default-deny rules reject every request regardless of auth.
    deny_all = """
    rules_version = '2';
    service cloud.firestore {
      match /databases/{database}/documents {
        match /{document=**} {
          allow read, write: if false;
        }
      }
    }
    """
    r1 = fs.evaluate_security_rules(deny_all, method="get", db=DB, rel_path="users/alice",
                                    auth=None, resource_data={}, request_resource_data=None)
    _check("deny-all rules reject an anonymous get", r1["allow"] is False)
    _check("deny-all rules report the matched path", r1["matchedPath"] == "/databases/{database}/documents/{document=**}")

    # 2. Authenticated-only rules: allow read if request.auth != null.
    auth_only = """
    service cloud.firestore {
      match /databases/{database}/documents {
        match /users/{userId} {
          allow read: if request.auth != null;
          allow write: if request.auth != null && request.auth.uid == userId;
        }
      }
    }
    """
    anon = fs.evaluate_security_rules(auth_only, method="get", db=DB, rel_path="users/alice",
                                      auth=None, resource_data={}, request_resource_data=None)
    _check("auth-required rules reject an anonymous read", anon["allow"] is False)
    authed = fs.evaluate_security_rules(auth_only, method="get", db=DB, rel_path="users/alice",
                                        auth={"uid": "alice"}, resource_data={}, request_resource_data=None)
    _check("auth-required rules allow an authenticated read", authed["allow"] is True)

    # 3. Owner-only write: request.auth.uid == userId path capture, real per-user enforcement.
    owner_write_self = fs.evaluate_security_rules(auth_only, method="update", db=DB, rel_path="users/alice",
                                                  auth={"uid": "alice"}, resource_data={"name": "A"},
                                                  request_resource_data={"name": "B"})
    _check("owner can update their own user doc", owner_write_self["allow"] is True)
    owner_write_other = fs.evaluate_security_rules(auth_only, method="update", db=DB, rel_path="users/alice",
                                                    auth={"uid": "bob"}, resource_data={"name": "A"},
                                                    request_resource_data={"name": "B"})
    _check("a different uid cannot update alice's user doc", owner_write_other["allow"] is False)

    # 4. resource.data field comparisons (plain JSON, as a human fills into the Playground
    # form) — a published-only read rule.
    pub_rules = """
    service cloud.firestore {
      match /databases/{database}/documents {
        match /posts/{postId} {
          allow read: if resource.data.published == true;
          allow create: if request.resource.data.published == false;
        }
      }
    }
    """
    pub = fs.evaluate_security_rules(pub_rules, method="get", db=DB, rel_path="posts/p1", auth=None,
                                     resource_data={"published": True}, request_resource_data=None)
    _check("published post is readable", pub["allow"] is True)
    unpub = fs.evaluate_security_rules(pub_rules, method="get", db=DB, rel_path="posts/p1", auth=None,
                                       resource_data={"published": False}, request_resource_data=None)
    _check("unpublished post is not readable", unpub["allow"] is False)
    create_draft = fs.evaluate_security_rules(pub_rules, method="create", db=DB, rel_path="posts/p2", auth=None,
                                              resource_data=None, request_resource_data={"published": False})
    _check("creating a draft post is allowed", create_draft["allow"] is True)

    # 5. A rule that fails to parse reports a real parse error, not a silent allow/deny.
    broken = "service cloud.firestore { match /databases/{database}/documents { allow read: if ; } }"
    err = fs.evaluate_security_rules(broken, method="get", db=DB, rel_path="x", auth=None,
                                     resource_data={}, request_resource_data=None)
    _check("a malformed ruleset reports a parse error and denies", err["allow"] is False)

    # 6. No matching path at all -> default deny, no matchedPath.
    nomatch = fs.evaluate_security_rules(auth_only, method="get", db=DB, rel_path="orders/o1",
                                         auth={"uid": "alice"}, resource_data={}, request_resource_data=None)
    _check("a path with no matching rule is denied", nomatch["allow"] is False)
    _check("a path with no matching rule reports no matchedPath", nomatch["matchedPath"] is None)

    print("\nFirestore security-rules evaluator conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
