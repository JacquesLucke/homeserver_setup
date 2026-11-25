#!/usr/bin/python3
# Makes the server visible via bluetooth and lets devices pair without confirmation,
# so that it can be used like a bluetooth speaker. The server has no display or
# keyboard, so everyone in range can pair with it.

import os

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

# Set in the systemd service.
NAME = os.environ["BLUETOOTH_SPEAKER_NAME"]

AGENT_PATH = "/homeserver/bluetooth_speaker_agent"


def set_trusted(device):
    # Trusted devices can connect later on without asking the agent again.
    props = dbus.Interface(
        bus.get_object("org.bluez", device), "org.freedesktop.DBus.Properties"
    )
    props.Set("org.bluez.Device1", "Trusted", True)


class Agent(dbus.service.Object):
    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Release(self):
        pass

    # Called for "Just Works" pairing, which is used because the agent has no input
    # and output capabilities.
    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        print(f"Pairing with {device}", flush=True)
        set_trusted(device)

    @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        print(f"Pairing with {device}", flush=True)
        set_trusted(device)

    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        print(f"Authorizing {uuid} for {device}", flush=True)

    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Cancel(self):
        pass


def find_adapter():
    manager = dbus.Interface(
        bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager"
    )
    for path, interfaces in manager.GetManagedObjects().items():
        if "org.bluez.Adapter1" in interfaces:
            return path
    raise RuntimeError("No bluetooth adapter found")


DBusGMainLoop(set_as_default=True)
bus = dbus.SystemBus()

agent = Agent(bus, AGENT_PATH)
agent_manager = dbus.Interface(
    bus.get_object("org.bluez", "/org/bluez"), "org.bluez.AgentManager1"
)
agent_manager.RegisterAgent(AGENT_PATH, "NoInputNoOutput")
agent_manager.RequestDefaultAgent(AGENT_PATH)

adapter = dbus.Interface(
    bus.get_object("org.bluez", find_adapter()), "org.freedesktop.DBus.Properties"
)
adapter.Set("org.bluez.Adapter1", "Alias", NAME)
adapter.Set("org.bluez.Adapter1", "Powered", True)
adapter.Set("org.bluez.Adapter1", "Pairable", True)
adapter.Set("org.bluez.Adapter1", "Discoverable", True)

print("Waiting for devices", flush=True)
GLib.MainLoop().run()
