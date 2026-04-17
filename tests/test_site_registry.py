import json
import os
from pathlib import Path
from datetime import date
import pytest
from unittest.mock import patch, MagicMock
from core.site_registry import SiteRegistry


def test_add_domain_and_is_known(tmp_path, monkeypatch):
    registry_path = tmp_path / "site_registry.json"
    monkeypatch.setattr("core.site_registry._REGISTRY_PATH", registry_path)

    reg = SiteRegistry()
    assert reg.is_known("example.com") is False
    reg.add_domain("example.com", source="manual", url="https://example.com/article")
    assert reg.is_known("example.com") is True


def test_all_domains(tmp_path, monkeypatch):
    monkeypatch.setattr("core.site_registry._REGISTRY_PATH", tmp_path / "reg.json")
    reg = SiteRegistry()
    reg.add_domain("a.com", "manual", "https://a.com/p1")
    reg.add_domain("b.com", "minimax_discovery", "https://b.com/p2")
    assert set(reg.all_domains()) == {"a.com", "b.com"}


def test_known_urls(tmp_path, monkeypatch):
    monkeypatch.setattr("core.site_registry._REGISTRY_PATH", tmp_path / "reg.json")
    reg = SiteRegistry()
    reg.add_domain("example.com", "manual", "https://example.com/article1")
    reg.add_url("example.com", "https://example.com/article2")
    urls = reg.known_urls("example.com")
    assert set(urls) == {"https://example.com/article1", "https://example.com/article2"}


def test_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr("core.site_registry._REGISTRY_PATH", tmp_path / "reg.json")
    reg1 = SiteRegistry()
    reg1.add_domain("example.com", "manual", "https://example.com/article")
    reg1.save()

    reg2 = SiteRegistry()
    assert reg2.is_known("example.com") is True
