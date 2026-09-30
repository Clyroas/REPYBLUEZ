#!/usr/bin/env python3
"""PyBluez example presence-alert.py

Bluetooth presence alarm.  Watch for specific Bluetooth devices and raise a
desktop notification plus a sound alert the moment one comes within range
(and, optionally, when it leaves again).

How it works
------------
Each cycle the script performs a classic Bluetooth inquiry -- the same thing
your phone's "searching for devices" screen does -- using
``bluetooth.discover_devices()`` and checks the result against your watch
list.  "Within range" therefore means "close enough to be discovered",
typically the same room or through a wall or two.

Notes
-----
* The watched device must be *discoverable* (phone: Bluetooth settings ->
  make device visible).  Pairing is not required, and pairing alone is not
  enough -- an invisible device cannot be seen by an inquiry.
* Inquiries are lossy: a device may be missed in individual scans.  To avoid
  false alarms a device must be seen in ``--hits`` consecutive scans to count
  as *arrived*, and must be missing for ``--misses`` consecutive scans before
  *left* is announced.  Defaults: 1 and 2.
* Sound and desktop notifications are best-effort and work out of the box on
  Linux (notify-send / paplay), macOS (osascript / afplay) and Windows
  (PowerShell toast / winsound).  The terminal bell is always rung, so the
  script also works over SSH.

Usage
-----
    # 1. find the MAC address / friendly name of nearby devices
    python3 presence-alert.py --list

    # 2. alert when your phone comes into range
    python3 presence-alert.py --address AA:BB:CC:DD:EE:FF

    # match by (partial) friendly name instead, with a faster scan
    python3 presence-alert.py --name Pixel --scan-duration 5

    # watch several devices, custom timing, ignore departures
    python3 presence-alert.py -a AA:BB:CC:DD:EE:FF -n "AirPods" \
        --scan-duration 8 --interval 2 --no-depart
"""

import argparse
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

log = logging.getLogger("presence-alert")


# --------------------------------------------------------------------------
# console output helpers
# --------------------------------------------------------------------------

class _C:
    """ANSI colors (disabled automatically when not supported)."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"


USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
if os.name == "nt" and USE_COLOR:
    os.system("")  # enable VT escape sequences on Windows 10+ terminals


def paint(text, color):
    return f"{color}{text}{_C.RESET}" if USE_COLOR else text


def ring_bell():
    """Always-available alert: the terminal bell (works even over SSH)."""
    sys.stdout.write("\a")
    sys.stdout.flush()


# --------------------------------------------------------------------------
# desktop notification (best-effort, cross-platform)
# --------------------------------------------------------------------------

def _notify_linux(title, message):
    if not shutil.which("notify-send"):
        return False
    try:
        subprocess.run(
            ["notify-send", "-a", "PyBluez", "-u", "critical",
             "-i", "bluetooth", title, message],
            check=True, timeout=10,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _notify_macos(title, message):
    if not shutil.which("osascript"):
        return False
    script = f'display notification "{message}" with title "{title}" sound name "Glass"'
    try:
        subprocess.run(["osascript", "-e", script], check=True, timeout=10)
        return True  # osascript already plays the alert sound for us
    except (OSError, subprocess.SubprocessError):
        return False


def _notify_windows(title, message):
    if not shutil.which("powershell"):
        return False
    ps = (
        "$ErrorActionPreference='SilentlyContinue';"
        "[void][Windows.UI.Notifications.ToastNotificationManager,"
        "Windows.UI.Notifications,ContentType=WindowsRuntime];"
        "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        f"$t.GetElementsByTagName('text').Item(0).AppendChild("
        f"$t.CreateTextNode('{title}'))|Out-Null;"
        f"$t.GetElementsByTagName('text').Item(1).AppendChild("
        f"$t.CreateTextNode('{message}'))|Out-Null;"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        "'PyBluez Presence').Show([Windows.UI.Notifications.ToastNotification]::new($t))"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       check=True, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def platform_name():
    """One of 'Linux', 'Darwin' or 'Windows'."""
    if sys.platform == "darwin":
        return "Darwin"
    if os.name == "nt":
        return "Windows"
    return "Linux"


def send_notification(title, message):
    """Push an OS notification.  Returns True if something was shown."""
    dispatchers = {"Linux": _notify_linux, "Darwin": _notify_macos,
                   "Windows": _notify_windows}
    dispatch = dispatchers.get(platform_name())
    if dispatch and dispatch(title, message):
        return True
    log.info("(no desktop notification backend available -- check the console)")
    return False


# --------------------------------------------------------------------------
# alert sound (best-effort, cross-platform)
# --------------------------------------------------------------------------

_LINUX_ARRIVE_SOUNDS = [
    "/usr/share/sounds/freedesktop/stereo/complete.oga",
    "/usr/share/sounds/freedesktop/stereo/dialog-information.oga",
    "/usr/share/sounds/gnome/default/alerts/glass.ogg",
]
_LINUX_DEPART_SOUNDS = [
    "/usr/share/sounds/freedesktop/stereo/bell.oga",
    "/usr/share/sounds/freedesktop/stereo/message.oga",
]
_LINUX_PLAYERS = ["paplay", "pw-play", "ffplay", "aplay", "play"]


def _sound_linux(event):
    player = next((p for p in _LINUX_PLAYERS if shutil.which(p)), None)
    if player is None:
        return False
    candidates = (_LINUX_ARRIVE_SOUNDS if event == "arrived"
                  else _LINUX_DEPART_SOUNDS)
    sound = next((s for s in candidates if os.path.isfile(s)), None)
    if sound is None:
        return False
    cmd = [player, sound]
    if player == "ffplay":
        cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", sound]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def _sound_macos(event):
    if not shutil.which("afplay"):
        return False
    name = {"arrived": "Glass", "departed": "Pop"}.get(event, "Tink")
    path = f"/System/Library/Sounds/{name}.aiff"
    try:
        subprocess.Popen(["afplay", path],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def _sound_windows(event):
    try:
        import winsound  # stdlib on Windows
    except ImportError:
        return False
    alias = {"arrived": "SystemExclamation", "departed": "SystemAsterisk"}.get(
        event, "SystemDefault")
    winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
    return True


def play_alert_sound(event, enabled=True):
    """Play a platform alert sound.  Returns True if something was played."""
    if not enabled:
        return False
    players = {"Linux": _sound_linux,
               "Darwin": _sound_macos,
               "Windows": _sound_windows}
    play = players.get(platform_name())
    if play and play(event):
        return True
    ring_bell()  # last resort, and also nice over SSH
    return False


# --------------------------------------------------------------------------
# bluetooth access (imported lazily so --help works without a native stack)
# --------------------------------------------------------------------------

def load_bluetooth():
    try:
        import bluetooth
        return bluetooth
    except ImportError as exc:
        sys.exit(
            "The PyBluez 'bluetooth' module could not be imported ({0}).\n"
            "Install this repository first, e.g.:\n"
            "    pip install .\n"
            "On Linux you also need the BlueZ headers/deps, e.g.:\n"
            "    sudo apt install bluez libbluetooth-dev".format(exc)
        )


# --------------------------------------------------------------------------
# presence tracking
# --------------------------------------------------------------------------

class TrackedDevice:
    """State of one device we are watching."""

    def __init__(self, address, label):
        self.address = address
        self.label = label
        self.present = False
        self.hits = 0          # consecutive scans in which it was seen
        self.misses = 0        # consecutive scans in which it was not seen
        self.last_seen = None  # datetime of the last sighting

    def __str__(self):
        state = paint("present", _C.GREEN) if self.present else paint("away", _C.YELLOW)
        seen = " (last seen {})".format(self.last_seen.strftime("%H:%M:%S")) \
            if self.last_seen else ""
        return "{} [{}]{}".format(self.label, state, seen)


class PresenceWatcher:
    """Matches inquiry results against the watch list and emits events."""

    def __init__(self, addresses=(), names=(), arrive_hits=1, depart_misses=2,
                 alert_any=False):
        self.arrive_hits = max(1, arrive_hits)
        self.depart_misses = max(1, depart_misses)
        self.alert_any = alert_any
        self.addresses = {a.strip().upper() for a in addresses}
        self.name_fragments = [n.lower() for n in names if n.strip()]
        self.tracked = {}          # address -> TrackedDevice
        self.known_any = {}        # for --any: all addresses ever seen
        self.scans = 0
        self.last_scan_count = 0

    def _matches(self, address, name):
        if address in self.addresses:
            return True
        if self.name_fragments and name:
            lowered = name.lower()
            return any(fragment in lowered for fragment in self.name_fragments)
        return False

    def process_scan(self, devices):
        """Feed one inquiry result in; returns a list of (event, device).

        ``devices`` is an iterable of (address, name) tuples, as returned by
        ``bluetooth.discover_devices(lookup_names=True)``.
        """
        self.scans += 1
        events = []
        seen = {addr.upper(): (name or "") for addr, name in devices}
        self.last_scan_count = len(seen)

        if self.alert_any:
            for addr, name in seen.items():
                if addr not in self.known_any:
                    self.known_any[addr] = name
                    events.append(("arrived", TrackedDevice(addr, name or addr)))

        # update (or create) tracked entries for watched devices seen now
        for addr, name in seen.items():
            entry = self.tracked.get(addr)
            if entry is None and self._matches(addr, name):
                entry = TrackedDevice(addr, name or addr)
                self.tracked[addr] = entry
            if entry is None:
                continue
            entry.hits += 1
            entry.misses = 0
            entry.last_seen = datetime.now()
            if name and (not entry.label or entry.label == entry.address):
                entry.label = name  # remember friendlier name
            if not entry.present and entry.hits >= self.arrive_hits:
                entry.present = True
                events.append(("arrived", entry))

        # age watched devices that were not seen in this scan
        for entry in self.tracked.values():
            if entry.address in seen:
                continue
            entry.misses += 1
            entry.hits = 0
            if entry.present and entry.misses >= self.depart_misses:
                entry.present = False
                events.append(("departed", entry))

        return events

    def summary(self):
        here = [e for e in self.tracked.values() if e.present]
        return "scan #{:03d}: {} device(s) nearby, {} watched present".format(
            self.scans, self.last_scan_count, len(here))


# --------------------------------------------------------------------------
# command line interface
# --------------------------------------------------------------------------

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Bluetooth presence alarm: notify + sound when a device "
                    "comes within range (PyBluez example).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    targets = parser.add_argument_group("watch list (at least one of these, "
                                        "or --any)")
    targets.add_argument("-a", "--address", action="append", default=[],
                         metavar="MAC",
                         help="Bluetooth address to watch; repeatable")
    targets.add_argument("-n", "--name", action="append", default=[],
                         metavar="TEXT",
                         help="device whose friendly name contains TEXT; "
                              "repeatable")
    targets.add_argument("--any", action="store_true",
                         help="alert for ANY newly seen device")

    scanning = parser.add_argument_group("scanning")
    scanning.add_argument("--scan-duration", type=float, default=8.0,
                          help="length of each inquiry in seconds")
    scanning.add_argument("--interval", type=float, default=3.0,
                          help="pause between inquiries in seconds")
    scanning.add_argument("--hits", type=int, default=1,
                          help="consecutive sightings before 'arrived'")
    scanning.add_argument("--misses", type=int, default=2,
                          help="consecutive misses before 'left'")
    scanning.add_argument("--list", action="store_true",
                          help="do a single scan, print devices and exit")

    alerts = parser.add_argument_group("alerts")
    alerts.add_argument("--no-sound", action="store_true",
                        help="do not play an alert sound")
    alerts.add_argument("--no-notify", action="store_true",
                        help="do not push a desktop notification")
    alerts.add_argument("--no-depart", action="store_true",
                        help="do not alert when a device leaves")
    return parser.parse_args(argv)


def safe_scan(bluetooth, duration):
    """One inquiry; returns [] or raises nothing, logs problems instead."""
    try:
        return bluetooth.discover_devices(duration=duration, lookup_names=True,
                                          flush_cache=True, lookup_class=False)
    except bluetooth.BluetoothError as exc:
        log.error("inquiry failed: %s (is the Bluetooth adapter up?)", exc)
    except OSError as exc:
        log.error("system error during inquiry: %s", exc)
    return []


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format=paint("%(asctime)s", _C.CYAN) + " %(message)s",
                        datefmt="%H:%M:%S")

    if not (args.address or args.name or args.any or args.list):
        sys.exit("Nothing to watch.  Give --address / --name / --any "
                 "(or use --list to discover devices).")

    bluetooth = load_bluetooth()

    if args.list:
        print(paint("Scanning for nearby Bluetooth devices...", _C.BOLD))
        devices = safe_scan(bluetooth, args.scan_duration)
        print(paint("Found {} device(s)".format(len(devices)), _C.BOLD))
        for addr, name in devices:
            try:
                print("   {} - {}".format(addr, name))
            except UnicodeEncodeError:
                print("   {} - {}".format(addr, name.encode("utf-8", "replace")))
        if not devices:
            print("   (make sure the target device is discoverable)")
        return

    watcher = PresenceWatcher(addresses=args.address, names=args.name,
                              arrive_hits=args.hits,
                              depart_misses=args.misses, alert_any=args.any)
    watch_desc = ", ".join(
        [a for a in args.address] + ['~"{}"'.format(n) for n in args.name]) \
        or "any new device"
    print(paint("Watching for: {}", _C.BOLD).format(watch_desc))
    print("Scanning every ~{:.0f}s (inquiry {:.0f}s + pause {:.0f}s).  "
          "Press Ctrl+C to stop.".format(args.scan_duration + args.interval,
                                         args.scan_duration, args.interval))

    try:
        while True:
            devices = safe_scan(bluetooth, args.scan_duration)
            log.info("inquiry done: %d device(s) found", len(devices))

            for event, dev in watcher.process_scan(devices):
                if event == "departed" and args.no_depart:
                    continue
                if event == "arrived":
                    headline = paint("IN RANGE: {}", _C.GREEN + _C.BOLD) \
                        .format(dev.label)
                else:
                    headline = paint("LEFT RANGE: {}", _C.RED + _C.BOLD) \
                        .format(dev.label)
                log.info(headline)

                if not args.no_notify:
                    send_notification(
                        "Bluetooth {}".format("in range" if event == "arrived"
                                              else "left range"),
                        dev.label)
                play_alert_sound(event, enabled=not args.no_sound)

            log.info(watcher.summary())
            time.sleep(max(0.0, args.interval))
    except KeyboardInterrupt:
        print("\nStopped.  Final status of watched devices:")
        for entry in watcher.tracked.values() or []:
            print("   " + str(entry))
        if not watcher.tracked:
            print("   (none of the watched devices was ever seen)")


if __name__ == "__main__":
    main()
