"""Regression tests for the Linux (BlueZ) backend.

These need the compiled ``bluetooth._bluetooth`` extension; they are skipped
when it is not available (e.g. on non-Linux platforms or without BlueZ
development headers).  No Bluetooth hardware is required: the extension is
mocked out.
"""

import sys
import unittest
from unittest import mock

if not sys.platform.startswith("linux"):
    raise unittest.SkipTest("BlueZ backend is only available on Linux")

try:
    from bluetooth import bluez
    import bluetooth
except ImportError:
    raise unittest.SkipTest("bluetooth._bluetooth extension is not built")


class VersionTest(unittest.TestCase):
    def test_version_is_string(self):
        self.assertIsInstance(bluetooth.__version__, str)


class DiscoverDevicesTest(unittest.TestCase):
    def _discover(self, **kwargs):
        sock = mock.Mock()
        with mock.patch.object(bluez, "_gethcisock", return_value=sock), \
             mock.patch.object(bluez._bt, "hci_inquiry",
                               return_value=[]) as inquiry:
            bluez.discover_devices(device_id=0, **kwargs)
        return inquiry.call_args.kwargs, sock

    def test_flush_cache_is_forwarded(self):
        for flush in (True, False):
            with self.subTest(flush_cache=flush):
                kwargs, _ = self._discover(flush_cache=flush)
                self.assertEqual(kwargs["flush_cache"], flush)

    def test_flush_cache_defaults_to_true(self):
        kwargs, _ = self._discover()
        self.assertTrue(kwargs["flush_cache"])

    def test_socket_closed_on_return(self):
        _, sock = self._discover()
        sock.close.assert_called_once()


class AdvertiseServiceTest(unittest.TestCase):
    def setUp(self):
        self.sock = mock.Mock(_sock=mock.sentinel.raw)

    def test_no_shared_mutable_defaults(self):
        with mock.patch.object(bluez._bt, "sdp_advertise_service") as advertise:
            bluez.advertise_service(self.sock, "svc-a")
            bluez.advertise_service(self.sock, "svc-b",
                                    service_classes=["1101"])
        calls = advertise.call_args_list
        # sdp_advertise_service(sock, name, service_id, service_classes,
        #                       profiles, provider, description, protocols)
        self.assertEqual(calls[0].args[3], [])
        self.assertEqual(calls[0].args[4], [])
        self.assertEqual(calls[0].args[7], [])
        self.assertEqual(calls[1].args[3], ["1101"])
        self.assertIsNot(calls[0].args[3], calls[1].args[3])

    def test_invalid_service_id_rejected(self):
        with self.assertRaises(ValueError):
            bluez.advertise_service(self.sock, "svc", service_id="not-a-uuid")

    def test_invalid_service_class_rejected(self):
        with self.assertRaises(ValueError):
            bluez.advertise_service(self.sock, "svc",
                                    service_classes=["not-a-uuid"])

    def test_invalid_profile_rejected(self):
        with self.assertRaises(ValueError):
            bluez.advertise_service(self.sock, "svc",
                                    profiles=[("1101", -1)])


if __name__ == "__main__":
    unittest.main()
