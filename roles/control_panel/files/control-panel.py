#!/usr/bin/python3
# A small website to start and stop selected services.
# A polkit rule makes sure if has only limited access to the system.

import html
import os
import subprocess
from collections import namedtuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Set in the systemd service.
PORT = int(os.environ["CONTROL_PANEL_PORT"])

Action = namedtuple("Action", ["verb", "unit"])

# Maps request paths to the systemctl command that is run for them.
ACTIONS = {
    "/ledfx/start": Action(verb="start", unit="ledfx.service"),
    "/ledfx/stop": Action(verb="stop", unit="ledfx.service"),
}


def unit_status(unit):
    # Prints e.g. "active", "inactive" or "activating". Reading the status needs no permissions.
    result = subprocess.run(
        ["systemctl", "is-active", unit], capture_output=True, text=True, timeout=10
    )
    return result.stdout.strip()


def render_page():
    status = unit_status("ledfx.service")
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width">
    <title>Control Panel</title>
  </head>
  <body>
    <h1>Control Panel</h1>
    <h3>LedFx</h3>
    <p>Status: {html.escape(status)}</p>
    <form method="post" action="/ledfx/start"><button>Start</button></form>
    <form method="post" action="/ledfx/stop"><button>Stop</button></form>
  </body>
</html>
""".encode()


class Handler(BaseHTTPRequestHandler):
    # Used by the base class as socket timeout, so that slow clients don't block a thread forever.
    timeout = 10

    def do_GET(self):
        if self.path != "/":
            self.send_error(404)
            return
        body = render_page()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        action = ACTIONS.get(self.path)
        if action is None:
            self.send_error(404)
            return
        result = subprocess.run(
            ["systemctl", "--no-ask-password", action.verb, action.unit],
            stdin=subprocess.DEVNULL,
            timeout=60,
        )
        if result.returncode != 0:
            self.send_error(500)
            return
        # Redirect so that reloading the page doesn't submit the form again.
        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header("Content-Length", "0")
        self.end_headers()


ThreadingHTTPServer(("", PORT), Handler).serve_forever()
