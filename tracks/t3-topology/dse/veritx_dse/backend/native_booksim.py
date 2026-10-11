"""One persistent actual BookSim process, with bounded protocol I/O."""
import os
import selectors
import subprocess
import time
from types import SimpleNamespace

from veritx_dse.core.errors import EvidenceInvalid


class NativeBookSimProcess:
    MAX_LINE_BYTES = 64 * 1024
    MAX_MCAST_LINKS = 64
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
        if len(line) > self.MAX_LINE_BYTES:
            raise EvidenceInvalid('native BookSim protocol line exceeded bound')
        try:
            line = line.decode('ascii')
        except UnicodeDecodeError:
            raise EvidenceInvalid('native BookSim protocol line is not ASCII') from None
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

    def inject_multicast(self, operation_id, src, replication_point,
                         traffic_class, destinations):
        if (not isinstance(operation_id, str) or not operation_id
                or len(operation_id.encode('utf-8')) > 128):
            raise EvidenceInvalid('native multicast needs a bounded authored operation id')
        if type(src) is not int or type(replication_point) is not int or src != replication_point:
            raise EvidenceInvalid('native profile requires the authored source-router replication point')
        if type(traffic_class) is not int or not isinstance(destinations, (tuple, list)):
            raise EvidenceInvalid('native multicast binding has invalid class/destinations')
        if len(destinations) < 2 or len(set(destinations)) != len(destinations):
            raise EvidenceInvalid('native multicast destinations must be unique with fanout >= 2')
        if any(type(dst) is not int or dst < 0 or dst == src for dst in destinations):
            raise EvidenceInvalid('native multicast destination is invalid or names its source')
        token = operation_id.encode('utf-8').hex()
        command = 'inject_mcast {} {} {} {} {} {}'.format(
            token, src, replication_point, traffic_class, len(destinations),
            ' '.join(str(dst) for dst in destinations))
        self._send(command)
        response = self._read('')
        if response == ['MADMIT']:
            return None
        if len(response) != 3 or response[0] != 'MPID' or response[2] != token:
            raise EvidenceInvalid('invalid native multicast admission response')
        return int(response[1])

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
            if fields[0] == 'RET' and len(fields) == 7:
                rows.append(SimpleNamespace(**dict(zip(
                    ('pid', 'src', 'dst', 'cl', 'itime', 'atime'),
                    map(int, fields[1:])))))
                continue
            if fields[0] == 'MRET' and len(fields) >= 12:
                operation = fields[1]
                (pid, src, dst, cl, itime, atime, branch, route_steps,
                 physical_link_flits, trace_len) = map(int, fields[2:12])
                if trace_len < 1 or trace_len > self.MAX_MCAST_LINKS:
                    raise EvidenceInvalid('native multicast route trace exceeds bound')
                if physical_link_flits < 0 or physical_link_flits > self.MAX_MCAST_LINKS:
                    raise EvidenceInvalid('native multicast physical-link count exceeds bound')
                if len(fields) > 12 + 2 * self.MAX_MCAST_LINKS:
                    raise EvidenceInvalid('native multicast retirement fields exceed bound')
                if len(fields) != 12 + 2 * trace_len:
                    raise EvidenceInvalid('native multicast route trace length mismatch')
                route_trace = tuple((int(fields[i]), int(fields[i + 1]))
                                    for i in range(12, len(fields), 2))
                try:
                    operation_id = bytes.fromhex(operation).decode('utf-8')
                except (ValueError, UnicodeDecodeError):
                    raise EvidenceInvalid('native multicast operation id is invalid') from None
                rows.append(SimpleNamespace(
                    multicast=True, operation_id=operation_id,
                    pid=pid, src=src, dst=dst, cl=cl, itime=itime, atime=atime,
                    branch_id=branch, route_steps=route_steps,
                    physical_link_flits=physical_link_flits,
                    route_trace=route_trace))
                continue
            raise EvidenceInvalid('invalid native retirement')

    def counts(self):
        self._send('counts')
        counts = dict(zip(('packets', 'flits_constructed', 'flits_retired', 'tails',
                           'flits_live', 'flits_source_queued'),
                          map(int, self._read('COUNTS '))))
        counts.update(dict(zip(('mcast_branch_flits_constructed',
                                'mcast_branch_flits_retired',
                                'mcast_branch_physical_link_flits'),
                               map(int, self._read('MCOUNTS ')))))
        return counts

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
