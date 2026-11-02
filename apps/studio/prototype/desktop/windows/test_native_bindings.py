"""Load the real Windows Ramulator binding and Chakra schema; Wine != native."""
import ctypes
from pathlib import Path
import sys
import unittest

BUILD = Path(__file__).resolve().parents[2] / ".desktop-build/windows"


@unittest.skipUnless(sys.platform == "win32", "requires Windows binaries")
class WindowsNativeBindingTest(unittest.TestCase):
    def test_ramulator_binding_imports_from_built_directory(self):
        binding = BUILD / "ramulator-binding/ramulator"
        self.assertTrue(binding.is_dir(), f"missing Windows binding build: {binding}")
        ctypes.WinDLL(str(binding / "libramulator.dll"))  # proves the DLL itself loads
        sys.path.insert(0, str(binding.parent))
        from ramulator._ramulator import Simulation
        self.assertTrue(callable(Simulation))

    def test_chakra_protobuf_schema_is_importable(self):
        chakra = BUILD / "chakra"
        sys.path.insert(0, str(chakra))
        from chakra.schema.protobuf import et_def_pb2
        node = et_def_pb2.Node()
        self.assertEqual(node.SerializeToString(), b"")
        self.assertTrue(et_def_pb2.Node.DESCRIPTOR.fields, "schema has no fields")
        round_trip = et_def_pb2.Node()
        round_trip.ParseFromString(node.SerializeToString())
        self.assertEqual(round_trip.SerializeToString(), b"")


if __name__ == "__main__":
    unittest.main()
