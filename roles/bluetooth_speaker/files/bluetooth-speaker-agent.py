#!/usr/bin/python3
# Lets devices pair without confirmation, so that the server can be used like a
# bluetooth speaker. The server has no display or keyboard, so new devices are only
# accepted while pairing mode is on (see bluetooth-pairing.service), which makes the
# adapter visible and pairable. Paired devices can always connect.

import os

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

# Set in the systemd service.
NAME = os.environ["BLUETOOTH_SPEAKER_NAME"]

AGENT_PATH = "/homeserver/bluetooth_speaker_agent"


class Rejected(dbus.DBusException):
    _dbus_error_name = "org.bluez.Error.Rejected"


def set_trusted(device):
    # Trusted devices can connect later on without asking the agent again.
    props = dbus.Interface(
        bus.get_object("org.bluez", device), "org.freedesktop.DBus.Properties"
    )
    props.Set("org.bluez.Device1", "Trusted", True)


def accept_new_device(device):
    if not adapter.Get("org.bluez.Adapter1", "Pairable"):
        print(f"Rejecting {device}, pairing mode is off", flush=True)
        raise Rejected("Pairing mode is off")
    print(f"Accepting {device}", flush=True)
    set_trusted(device)


class Agent(dbus.service.Object):
    @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
    def Release(self):
        pass

    # Called for "Just Works" pairing, which is used because the agent has no input
    # and output capabilities.
    @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        accept_new_device(device)

    @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        accept_new_device(device)

    # Called when an untrusted device connects. The kernel can accept "Just Works"
    # pairing on its own without asking the agent, so this is where such devices
    # are accepted or rejected.
    @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        accept_new_device(device)

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
# Bluetooth may remember these from before, so they are turned off explicitly.
adapter.Set("org.bluez.Adapter1", "Pairable", False)
adapter.Set("org.bluez.Adapter1", "Discoverable", False)

print("Waiting for devices", flush=True)
GLib.MainLoop().run()
