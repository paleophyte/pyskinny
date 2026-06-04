"""Tests for tools.phone HTTP URL building."""

from tools.phone import _request_urls


def test_request_urls_http_only_by_default():
    urls = _request_urls("10.0.0.1", "/CGI/Execute")
    assert urls == ["http://10.0.0.1/CGI/Execute"]


def test_request_urls_https_only():
    urls = _request_urls("10.0.0.1", "/CGI/Execute", use_https=True)
    assert urls == ["https://10.0.0.1/CGI/Execute"]


def test_request_urls_try_https_fallback():
    urls = _request_urls("10.0.0.1", "/CGI/Execute", try_https_fallback=True)
    assert urls == [
        "http://10.0.0.1/CGI/Execute",
        "https://10.0.0.1/CGI/Execute",
    ]


def test_execute_uses_form_encoding(monkeypatch):
    captured = {}

    def fake_post(urls, data=None, headers=None, auth=None, timeout=6, verify=False):
        captured["data"] = data
        captured["headers"] = headers or {}

        class R:
            status_code = 200
            text = ""

        return R()

    monkeypatch.setattr("tools.phone._try_post", fake_post)
    from tools.phone import _execute

    _execute("10.0.0.1", ["Key:Soft2"], auth=("u", "p"))
    assert captured["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert captured["data"].startswith(b"XML=")
    assert b"CiscoIPPhoneExecute" in captured["data"]
