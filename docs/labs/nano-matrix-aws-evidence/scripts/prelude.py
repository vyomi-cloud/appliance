import botocore.httpsession as _hs
_o = _hs.URLLib3Session.send
def _s(self, req):
    if req.body is not None and not isinstance(req.body, (str, bytes)) and hasattr(req.body, "read"):
        req.body = req.body.read()
    return _o(self, req)
_hs.URLLib3Session.send = _s
