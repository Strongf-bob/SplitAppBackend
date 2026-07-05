from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_next_pwa_requests_device_permissions_from_active_client() -> None:
    page_source = (ROOT / "web" / "src" / "app" / "page.tsx").read_text()

    assert "isIosDevice" in page_source
    assert "Add to Home Screen" in page_source
    assert "navigator.mediaDevices.getUserMedia" in page_source
    assert "Notification.requestPermission" in page_source
    assert "serviceWorker.ready" in page_source
    assert "pushManager.subscribe" in page_source
    assert "navigator.contacts.select" in page_source
    assert 'type="file"' in page_source
    assert 'accept="image/*"' in page_source


def test_manifest_has_ios_and_maskable_png_icons() -> None:
    manifest = json.loads((ROOT / "web" / "public" / "manifest.webmanifest").read_text())
    icon_sources = {icon["src"] for icon in manifest["icons"]}

    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/app"
    assert "/assets/icon-192.png" in icon_sources
    assert "/assets/icon-512.png" in icon_sources
    assert "/assets/apple-touch-icon.png" in icon_sources

    for icon in manifest["icons"]:
        if icon["src"].endswith(".png"):
            assert (ROOT / "web" / "public" / icon["src"].lstrip("/")).exists()


def test_service_worker_handles_web_push_events() -> None:
    service_worker = (ROOT / "web" / "public" / "sw.js").read_text()

    assert 'addEventListener("push"' in service_worker
    assert 'addEventListener("notificationclick"' in service_worker
    assert "showNotification" in service_worker
