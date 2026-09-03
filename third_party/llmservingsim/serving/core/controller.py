import re
from .logger import get_logger

class Controller():
    def __init__(self, total_num, network_backend='analytical'):
        self.end_dict = {}
        self.total_num = total_num
        self.network_backend = network_backend
        self.logger = get_logger(self.__class__)

        for i in range(total_num):
            self.end_dict[i] = -1


    def read_wait(self, p):
        out = [""]
        while True:
            line = p.stdout.readline()
            if not line:  # EOF
                break
            out.append(line)
            p.stdout.flush()
            if "Waiting" in out[-1] or out[-1] == "Checking Non-Exited Systems ...\n":
                break
        return out

    def check_end(self, p):
        # Neither BookSim nor the patched analytical frontend output the
        # "All Request Has Been Exited" / "ERROR" termination strings.
        # The terminate/kill cleanup below handles shutdown. Just return.
        return []

    def write_flush(self, p, input):
        # For debugging
        # print(input)
        # Binary may have exited (e.g. after "exit"/all requests done) —
        # catch BrokenPipeError and stop trying to write.
        try:
            p.stdin.write(input+'\n')
            p.stdin.flush()
        except (BrokenPipeError, OSError):
            import sys as _sys
            print(f"[controller] subprocess closed stdin, ignoring: {input!r}", file=_sys.stderr, flush=True)
        return

    def parse_all_booksim(self, output):
        """Return list of {sys, cycle} for ALL non-sys0 lines in BookSim output.
        sys=0 is handled by parse_output separately.
        Does NOT modify any state - id computation deferred to caller."""
        pattern = r"\[workload\] sys\[(\d+)\] finished, (\d+) cycles, exposed communication (\d+) cycles."
        results = []
        seen = set()
        for m in re.finditer(pattern, output):
            sys_id = int(m.group(1))
            cycle = int(m.group(2))
            if sys_id == 0 or sys_id in seen:
                continue
            seen.add(sys_id)
            results.append({'sys': sys_id, 'cycle': cycle})
        return results

    def parse_output(self, output):
        # Analytical backend: "sys[N] iteration M finished, X cycles, exposed communication Y cycles."
        pattern = r"sys\[(\d+)\] iteration (\d+) finished, (\d+) cycles, exposed communication (\d+) cycles."
        match = re.search(pattern, output)
        if match:
            sys = int(match.group(1))
            id = int(match.group(2))
            cycle = int(match.group(3))
            com_cycle = int(match.group(4))

            if self.end_dict[sys] != id:
                self.logger.info(
                    "NPU[%d] iteration %d finished, %d cycles, exposed communication %d cycles.",
                    sys,
                    id,
                    cycle,
                    com_cycle,
                )
                self.end_dict[sys] = id
            return {'sys': sys, 'id': id, 'cycle': cycle}
        # BookSim backend: "[workload] sys[N] finished, X cycles, exposed communication Y cycles."
        # BookSim outputs one line per NPU; pick sys 0 (start_npu) to match single-instance scheduling
        # Match both formats:
        #   [workload] sys[N] finished, X cycles, exposed communication Y cycles.
        #   [workload] [info] sys[N] finished, X cycles, exposed communication Y cycles.
        pattern_booksim = r"\[workload\](?:\s+\[info\])?\s+sys\[(\d+)\] finished, (\d+) cycles, exposed communication (\d+) cycles."
        matches = list(re.finditer(pattern_booksim, output))
        if matches:
            # Process ALL sys lines (needed for TP>1: add_done requires all NPUs to complete)
            result = None
            for m in matches:
                sys = int(m.group(1))
                cycle = int(m.group(2))
                com_cycle = int(m.group(3))
                id = self.end_dict.get(sys, -1) + 1
                if self.end_dict[sys] != id:
                    self.logger.info(
                        "NPU[%d] BookSim finished, %d cycles, exposed communication %d cycles.",
                        sys,
                        cycle,
                        com_cycle,
                    )
                    self.end_dict[sys] = id
                # Return sys 0 result for scheduling
                # Don't increment counter here - caller handles it
                if sys == 0:
                    result = {'sys': sys, 'id': 0, 'cycle': cycle}
            if result:
                return result
        # Fallback: any sys if 0 not found
        match_booksim = re.search(pattern_booksim, output)
        if match_booksim:
            sys = int(match_booksim.group(1))
            cycle = int(match_booksim.group(2))
            id = self.end_dict.get(sys, -1) + 1
            self.end_dict[sys] = id
            return {'sys': sys, 'id': id, 'cycle': cycle}
        return