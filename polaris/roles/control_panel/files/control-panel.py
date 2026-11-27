#!/usr/bin/python3
# A small website and API to start and stop selected services. Home Assistant uses
# the API, the website is the fallback when Home Assistant doesn't work.
# A polkit rule makes sure if has only limited access to the system.
#
#   GET  /api/ledfx          -> prints the status, e.g. "active", "inactive" or "activating"
#   POST /api/ledfx "start"  -> starts the service and prints the new status
#   POST /api/ledfx "stop"   -> stops the service and prints the new status
#
# The same works for /api/bluetooth-pairing.

import html
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Set in the systemd service.
PORT = int(os.environ["CONTROL_PANEL_PORT"])

# Maps API paths to the units that can be controlled through them.
UNITS = {
    "/api/ledfx": "ledfx.service",
    "/api/bluetooth-pairing": "bluetooth-pairing.service",
}

# Titles of the API paths on the website.
TITLES = {
    "/api/ledfx": "LedFx",
    "/api/bluetooth-pairing": "Bluetooth Pairing",
}

VERBS = {"start", "stop"}

# Request bodies are just a verb, so anything longer is rejected.
MAX_BODY_SIZE = 100


def unit_status(unit):
    # Reading the status needs no permissions.
    try:
        result = subprocess.run(
            ["systemctl", "is-active", unit], capture_output=True, text=True, timeout=10
        )
    except subprocess.TimeoutExpired:
        return "unknown"
    return result.stdout.strip()


def render_section(path):
    status = unit_status(UNITS[path])
    return f"""
    <h3>{html.escape(TITLES[path])}</h3>
    <p>Status: {html.escape(status)}</p>
    <button onclick="control('{path}', 'start')">Start</button>
    <button onclick="control('{path}', 'stop')">Stop</button>"""


def render_page():
    sections = "".join(render_section(path) for path in UNITS)
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width">
    <title>Control Panel</title>
  </head>
  <body>
    <h1>Control Panel</h1>{sections}
    <script>
      async function control(path, verb) {{
        const response = await fetch(path, {{ method: "POST", body: verb }});
        if (!response.ok) {{
          alert(`Failed to ${{verb}}: ${{response.status}}`);
        }}
        location.reload();
      }}
    </script>
  </body>
</html>
""".encode()


class Handler(BaseHTTPRequestHandler):
    # Used by the base class as socket timeout, so that slow clients don't block a thread forever.
    timeout = 10

    def do_GET(self):
        if self.path == "/":
            self.send_body(render_page(), "text/html")
            return
        unit = UNITS.get(self.path)
        if unit is None:
            self.send_error(404)
            return
        self.send_body((unit_status(unit) + "\n").encode(), "text/plain")

    def do_POST(self):
        unit = UNITS.get(self.path)
        if unit is None:
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = -1
        if length < 0:
            self.send_error(400)
            return
        if length > MAX_BODY_SIZE:
            self.send_error(413)
            return
        verb = self.rfile.read(length).decode(errors="replace").strip()
        if verb not in VERBS:
            self.send_error(400)
            return
        try:
            result = subprocess.run(
                ["systemctl", "--no-ask-password", verb, unit],
                stdin=subprocess.DEVNULL,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            self.send_error(504)
            return
        if result.returncode != 0:
            self.send_error(500)
            return
        self.send_body((unit_status(unit) + "\n").encode(), "text/plain")

    def send_body(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


ThreadingHTTPServer(("", PORT), Handler).serve_forever()
