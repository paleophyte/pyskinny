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


def test_request_urls_custom_port():
    urls = _request_urls("10.0.0.1", "/CGI/Screenshot", port=8080)
    assert urls == ["http://10.0.0.1:8080/CGI/Screenshot"]
