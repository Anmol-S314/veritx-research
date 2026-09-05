import re
from .logger import get_logger

# ASTRA-Sim's per-iteration report, the one line of its stdout the frontend
# has to parse. Compiled once: parse_output runs on every handshake, and at
# 8 NPUs a 10-request run makes 337,786 of them.
_ITERATION_RE = re.compile(
    r"sys\[(\d+)\] iteration (\d+) finished, (\d+) cycles, "
    r"exposed communication (\d+) cycles."
)


class Controller():
    def __init__(self, total_num):
        self.end_dict = {}
        self.total_num = total_num
        self.logger = get_logger(self.__class__)
        for i in range(total_num):
            self.end_dict[i] = -1


    def read_wait(self, p):
        """Read ASTRA-Sim's stdout up to the "Waiting" prompt.

        Every line before the prompt is the iteration report; ASTRA-Sim used
        to interleave a per-tick "Checking ..." line per NPU, which made this
        loop 3.07M reads on a 10-request 8-NPU run against 675k now. See the
        ASTRA_SIM_TRACE_POLLING note in the analytical backend's main.cc.
        """
        out = [""]
        while "Waiting" not in out[-1] and out[-1] != "Checking Non-Exited Systems ...\n":
            line = p.stdout.readline()
            if not line:
                # VeritX: EOF — backend exited (crash/arg error). Break so the
                # caller fails loudly instead of spinning forever on a dead pipe.
                break
            # For debugging
            # print(line, end='')
            out.append(line)
        return out

    def check_end(self, p):
        out = ["",""]
        while out[-2] != "All Request Has Been Exited\n" and out[-2] != "ERROR: Some Requests Remain\n":
            line = p.stdout.readline()
            if not line:
                # VeritX: EOF — backend already gone; don't spin.
                break
            out.append(line)
            p.stdout.flush()
        print(out[-4] if len(out) >= 4 else "", end='')
        print(out[-2], end='')
        return out

    def write_flush(self, p, input):
        # For debugging
        # print(input)
        p.stdin.write(input+'\n')
        p.stdin.flush()
        return

    def parse_all_booksim(self, output):
        """VeritX forward-port: return list of {sys, cycle} for ALL non-sys0
        lines in BookSim output. sys=0 is handled by parse_output separately.
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
        match = _ITERATION_RE.search(output)
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
        # VeritX forward-port, BookSim backend:
        # "[workload] sys[N] finished, X cycles, exposed communication Y cycles."
        # BookSim outputs one line per NPU; pick sys 0 (start_npu) to match
        # single-instance scheduling. Matches both formats (with/without [info]).
        # NOTE: the caller must pass the JOINED read_wait output, not a single
        # line — BookSim's per-NPU lines arrive in one read.
        pattern_booksim = r"\[workload\](?:\s+\[info\])?\s+sys\[(\d+)\] finished, (\d+) cycles, exposed communication (\d+) cycles."
        matches = list(re.finditer(pattern_booksim, output))
        if matches:
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