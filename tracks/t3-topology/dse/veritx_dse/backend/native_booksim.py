"""One persistent actual BookSim process, with bounded protocol I/O."""
import os
import selectors
import subprocess
import time
from types import SimpleNamespace

from veritx_dse.core.errors import EvidenceInvalid


class NativeBookSimProcess:
    def __init__(self, executable, config_path, flit_limit, directory):
        self.log = open(directory / 'booksim.log', 'wb')
        self.p = subprocess.Popen([executable, str(config_path), str(flit_limit)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=self.log, cwd=directory, bufsize=0)
        self.buffer = b''
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.p.stdout, selectors.EVENT_READ)
        try:
            self.num_nodes = int(self._read('NODES ')[0])
        except BaseException:
            self.close(force=True)
            raise

    def _read(self, prefix):
        deadline = time.monotonic() + 30
        while b'\n' not in self.buffer:
            if not self.selector.select(max(0, deadline - time.monotonic())):
                raise EvidenceInvalid('native BookSim protocol timed out')
            chunk = os.read(self.p.stdout.fileno(), 4096)
            if not chunk:
                self.log.flush()
                with open(self.log.name, 'rb') as diagnostic:
                    diagnostic.seek(0, os.SEEK_END)
                    diagnostic.seek(max(0, diagnostic.tell() - 4096))
                    detail = diagnostic.read().decode('utf-8', errors='replace')
                raise EvidenceInvalid('native BookSim exited: ' + detail)
            self.buffer += chunk
            if len(self.buffer) > 1024 * 1024:
                raise EvidenceInvalid('native BookSim protocol exceeded bound')
        line, self.buffer = self.buffer.split(b'\n', 1)
        line = line.decode('ascii')
        if not line.startswith(prefix):
            raise EvidenceInvalid('unexpected native BookSim response: ' + line)
        return line[len(prefix):].split()

    def _send(self, command):
        try:
            self.p.stdin.write((command + '\n').encode('ascii'))
        except (BrokenPipeError, OSError) as exc:
            raise EvidenceInvalid('native BookSim command failed') from exc

    def inject(self, src, dst, size):
        self._send(f'inject {src} {dst} {size} 0')
        return int(self._read('PID ')[0])

    def step(self):
        self._send('step')
        return int(self._read('CYCLE ')[0])

    def drain(self, node):
        self._send(f'drain {node}')
        rows = []
        while True:
            fields = self._read('')
            if fields == ['END']:
                return rows
            if len(fields) != 7 or fields[0] != 'RET':
                raise EvidenceInvalid('invalid native retirement')
            rows.append(SimpleNamespace(**dict(zip(('pid', 'src', 'dst', 'cl', 'itime', 'atime'),
                                                   map(int, fields[1:])))))

    def counts(self):
        self._send('counts')
        return dict(zip(('packets', 'flits_constructed', 'flits_retired', 'tails',
                         'flits_live', 'flits_source_queued'), map(int, self._read('COUNTS '))))

    def close(self, force=False):
        try:
            if self.p.poll() is None:
                if not force:
                    self._send('quit')
                    self._read('BYE')
                    self.p.wait(timeout=5)
                else:
                    self.p.kill()
        finally:
            if self.p.poll() is None:
                self.p.kill()
            self.p.wait()
            self.selector.close()
            self.p.stdin.close()
            self.p.stdout.close()
            self.log.close()
