"""fake_sim — behavioral stand-in for a simulator binary (redesign PR 4).

Level-2 fixtures (§26): real processes at the real OS boundary, each
behavior a failure mode §27 says the control plane must survive. argv:

    sleep <s>                    sleep <s>, exit 0 (well-behaved)
    ignore-term <s>              ignore SIGTERM, print IGNORE-READY, sleep
    spawn-sleeper <pidfile> <s>  fork a sleeping grandchild, write its pid
    flood <n>                    print n long lines between FLOOD markers
    print-env <var>              print $var or MISSING
    echo-exit <code>             print stdout+stderr lines, exit <code>
    kill-self <sig>              raise signal <sig> on itself
"""
import os
import signal
import sys
import time


def main() -> None:
    mode, args = sys.argv[1], sys.argv[2:]

    if mode == "sleep":
        time.sleep(float(args[0]))

    elif mode == "ignore-term":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        print("IGNORE-READY", flush=True)
        time.sleep(float(args[0]))

    elif mode == "spawn-sleeper":
        pidfile, secs = args[0], float(args[1])
        pid = os.fork()
        if pid == 0:
            time.sleep(secs)
            os._exit(0)
        with open(pidfile, "w") as f:
            f.write(str(pid))
        print("SPAWNED", flush=True)
        time.sleep(secs)

    elif mode == "flood":
        n = int(args[0])
        print("FLOOD-HEAD", flush=True)
        for _ in range(n):
            print("x" * 200)
        print("FLOOD-END", flush=True)

    elif mode == "print-env":
        print(os.environ.get(args[0], "MISSING"), flush=True)

    elif mode == "echo-exit":
        print("stdout-line", flush=True)
        print("stderr-line", file=sys.stderr, flush=True)
        sys.exit(int(args[0]))

    elif mode == "kill-self":
        os.kill(os.getpid(), int(args[0]))
        time.sleep(30)  # unreachable if the signal lands

    else:
        raise SystemExit(f"fake_sim: unknown mode {mode!r}")


if __name__ == "__main__":
    main()
