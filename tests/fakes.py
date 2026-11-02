import json as _json


class FakeResponse:
    def __init__(self, status=200, data=None, headers=None, content=None):
        self.status_code = status
        self._data = data if data is not None else {}
        self.headers = headers or {}
        self.content = content if content is not None else _json.dumps(self._data).encode()
        self.text = self.content.decode(errors="replace")

    def json(self):
        return self._data


class FakeSession:
    """Routes (method, path-suffix) to responses or callables; records every call."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, url, params=None, json=None, data=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "params": params, "json": json})
        for (m, suffix), resp in self.routes.items():
            if m == method and url.split("?")[0].endswith(suffix):
                out = resp(params, json) if callable(resp) else resp
                if isinstance(out, list):
                    return out.pop(0)
                return out if isinstance(out, FakeResponse) else FakeResponse(200, out)
        raise AssertionError(f"Unexpected request {method} {url}")
