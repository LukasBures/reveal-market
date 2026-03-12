"""Minimal Alertmanager → Discord webhook bridge with severity-based colors."""

import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse


def _validated_webhook_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("DISCORD_WEBHOOK must be an https URL")
    return value


DISCORD_WEBHOOK =<REDACTED>
COLORS = {"critical": 0xE74C3C, "warning": 0xF39C12, "watchdog": 0x2ECC71}
DEFAULT_COLOR = 0x95A5A6


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        embeds = []
        for alert in body.get("alerts", []):
            severity = alert.get("labels", {}).get("severity", "")
            status = alert.get("status", "firing")
            color = COLORS.get(severity, DEFAULT_COLOR)
            title = alert.get("annotations", {}).get("summary", alert.get("labels", {}).get("alertname", "Alert"))
            desc = alert.get("annotations", {}).get("description", "")
            tag = f"[{status.upper()}]"
            embeds.append({"title": f"{tag} {title}", "description": desc, "color": color})
        if embeds:
            data = json.dumps({"embeds": embeds}).encode()
            req = urllib.request.Request(  # noqa: S310 - validated above to require an https Discord webhook
                DISCORD_WEBHOOK,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(req, timeout=10)  # noqa: S310
            except Exception as exc:
                print(f"discord post failed: {exc}")
        self.send_response(200)
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # suppress request logs


if __name__ == "__main__":
    port = int(os.environ.get("LISTEN_PORT", "9094"))
    print(f"alertmanager-discord bridge listening on :{port}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()  # noqa: S104 - container listener
