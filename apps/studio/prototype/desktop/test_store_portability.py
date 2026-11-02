"""Storage portability regression; run with unittest on each native OS."""
import multiprocessing
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tracks/t3-topology/dse"))
from veritx_dse.product.store import ProductStore


def increment(root):
    store = ProductStore(root)
    for _ in range(20):
        with store._locked():
            path = store.root / "counter.json"
            value = store._read(path, "counter")["value"]
            with store._locked():
                store._atomic_write(path, {"value": value + 1})


class StorePortabilityTest(unittest.TestCase):
    def test_atomic_reentrant_cross_process_storage(self):
        with tempfile.TemporaryDirectory(prefix="srota space-λ-") as root:
            store = ProductStore(root)
            path = Path(root) / "counter.json"
            store._atomic_write(path, {"value": 0})
            context = multiprocessing.get_context("spawn")
            processes = [context.Process(target=increment, args=(root,)) for _ in range(3)]
            for process in processes:
                process.start()
            try:
                for process in processes:
                    process.join(30)
                    self.assertEqual(process.exitcode, 0)
            finally:
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                        process.join()
            restarted = ProductStore(root)
            self.assertEqual(restarted._read(path, "counter"), {"value": 60})
            self.assertEqual(list(Path(root).glob(".tmp-*")), [])


if __name__ == "__main__":
    unittest.main()
