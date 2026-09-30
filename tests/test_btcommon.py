"""Unit tests for bluetooth.btcommon.

These run without Bluetooth hardware and without the compiled extension
module: if importing the ``bluetooth`` package fails (it pulls in the
platform backend), btcommon.py is loaded directly from disk instead.
"""

import importlib.util
import os
import unittest

try:
    from bluetooth import btcommon
except ImportError:
    _path = os.path.join(os.path.dirname(__file__), os.pardir,
                         "bluetooth", "btcommon.py")
    _spec = importlib.util.spec_from_file_location("btcommon", _path)
    btcommon = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(btcommon)


class IsValidAddressTest(unittest.TestCase):
    def test_valid_addresses(self):
        self.assertTrue(btcommon.is_valid_address("01:23:45:67:89:AB"))
        self.assertTrue(btcommon.is_valid_address("aa:bb:cc:dd:ee:ff"))
        self.assertTrue(btcommon.is_valid_address("00:00:00:00:00:00"))

    def test_invalid_addresses(self):
        for addr in ["",
                     "01:23:45:67:89",          # too short
                     "01:23:45:67:89:AB:CD",    # too long
                     "01-23-45-67-89-AB",       # wrong separator
                     "01:23:45:67:89:AG",       # non-hex digit
                     "01:23:45:67:89:A",        # truncated byte
                     "01:23:45:67:89:ABC",      # oversized byte
                     "IN:VA:LI:DA:DD:RE",
                     "0x12:34:56:78:9a:bc",     # int() quirks must not pass
                     "1_2:34:56:78:9a:bc",
                     None,
                     0x0123456789AB]:
            self.assertFalse(btcommon.is_valid_address(addr), addr)


class IsValidUuidTest(unittest.TestCase):
    def test_valid_uuids(self):
        self.assertTrue(btcommon.is_valid_uuid("1101"))
        self.assertTrue(btcommon.is_valid_uuid("11011213"))
        self.assertTrue(btcommon.is_valid_uuid(
            "00001101-0000-1000-8000-00805F9B34FB"))
        self.assertTrue(btcommon.is_valid_uuid(
            "00001101-0000-1000-8000-00805f9b34fb"))  # case insensitive

    def test_invalid_uuids(self):
        for uuid in ["",
                     "110",                  # wrong length
                     "1101121",              # wrong length
                     "1101121314",           # wrong length
                     "110g",                 # non-hex
                     "0x11",                 # int() quirks must not pass
                     "1_23",
                     "00001101-0000-1000-8000-00805F9B34F",   # short group
                     "00001101-0000-1000-8000-00805F9B34FB0", # long group
                     "000011010000-1000-8000-00805F9B34FB",   # bad grouping
                     None,
                     b"1101"]:
            self.assertFalse(btcommon.is_valid_uuid(uuid), uuid)


class ToFullUuidTest(unittest.TestCase):
    def test_short_uuid(self):
        self.assertEqual(btcommon.to_full_uuid("1101"),
                         "00001101-0000-1000-8000-00805F9B34FB")

    def test_word_uuid(self):
        self.assertEqual(btcommon.to_full_uuid("11011213"),
                         "11011213-0000-1000-8000-00805F9B34FB")

    def test_full_uuid_unchanged(self):
        full = "00001101-0000-1000-8000-00805F9B34FB"
        self.assertEqual(btcommon.to_full_uuid(full), full)

    def test_invalid_uuid_raises(self):
        with self.assertRaises(ValueError):
            btcommon.to_full_uuid("not-a-uuid")


class SdpElementRoundtripTest(unittest.TestCase):
    def roundtrip(self, type_, value):
        data = btcommon.sdp_make_data_element(type_, value)
        rtype, rval, consumed = btcommon.sdp_parse_data_element(data)
        self.assertEqual(consumed, len(data))
        return rtype, rval

    def test_nil(self):
        self.assertEqual(self.roundtrip("Nil", None), ("Nil", None))

    def test_unsigned_ints(self):
        for type_ in ["UInt8", "UInt16", "UInt32", "UInt64"]:
            with self.subTest(type=type_):
                self.assertEqual(self.roundtrip(type_, 42), (type_, 42))

    def test_signed_ints(self):
        for type_ in ["SInt8", "SInt16", "SInt32", "SInt64"]:
            with self.subTest(type=type_):
                self.assertEqual(self.roundtrip(type_, -42), (type_, -42))

    def test_uint128(self):
        value = 0x00112233445566778899AABBCCDDEEFF
        self.assertEqual(self.roundtrip("UInt128", value), ("UInt128", value))

    def test_uuid_16bit(self):
        self.assertEqual(self.roundtrip("UUID", "1101"), ("UUID", "1101"))

    def test_uuid_32bit(self):
        self.assertEqual(self.roundtrip("UUID", "11011213"), ("UUID", "11011213"))

    def test_uuid_128bit(self):
        full = "00001101-0000-1000-8000-00805F9B34FB"
        self.assertEqual(self.roundtrip("UUID", full), ("UUID", full))

    def test_string(self):
        self.assertEqual(self.roundtrip("String", "PyBluez"), ("String", "PyBluez"))

    def test_string_utf8(self):
        self.assertEqual(self.roundtrip("String", "caf\u00e9"),
                         ("String", "caf\u00e9"))

    def test_bool(self):
        self.assertEqual(self.roundtrip("Bool", True), ("Bool", True))
        self.assertEqual(self.roundtrip("Bool", False), ("Bool", False))

    def test_url(self):
        self.assertEqual(self.roundtrip("URL", "https://pybluez.github.io/"),
                         ("URL", "https://pybluez.github.io/"))

    def test_elem_seq(self):
        seq = [("UUID", "1101"), ("UInt8", 5), ("Bool", True)]
        rtype, rval = self.roundtrip("ElemSeq", seq)
        self.assertEqual(rtype, "ElemSeq")
        self.assertEqual(rval, [("UUID", "1101"), ("UInt8", 5), ("Bool", True)])

    def test_alt_elem_seq(self):
        seq = [("UInt16", 0x0100), ("UInt16", 0x0101)]
        rtype, rval = self.roundtrip("AltElemSeq", seq)
        self.assertEqual(rtype, "AltElemSeq")
        self.assertEqual(rval, [("UInt16", 0x0100), ("UInt16", 0x0101)])

    def test_invalid_type_raises(self):
        with self.assertRaises(ValueError):
            btcommon.sdp_make_data_element("Bogus", 1)

    def test_sdp_parse_raw_record(self):
        record = [
            ("UInt16", 0x0001), ("UInt16", 0x0100),
            ("UInt16", 0x0100), ("ElemSeq", [("UUID", "1101")]),
            ("UInt16", 0x0101), ("String", "svc"),
        ]
        data = btcommon.sdp_make_data_element("ElemSeq", record)
        parsed = btcommon.sdp_parse_raw_record(data)
        self.assertEqual(parsed[0x0001], 0x0100)
        self.assertEqual(parsed[0x0100], [("UUID", "1101")])
        self.assertEqual(parsed[0x0101], "svc")


if __name__ == "__main__":
    unittest.main()
