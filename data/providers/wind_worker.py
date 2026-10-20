"""Long-lived Wind worker process (see data/providers/retrieve.py).

WindPy lives only in this process: a native fault here kills the worker, not
the web server. It connects once (w.start() takes ~15s) and then serves
requests from stdin until stdin closes.

Protocol (pickle frames): worker -> ("READY",) | ("ERR", text) after start,
then per request (id, func_name, args) -> (id, "OK", value) | (id, "ERR", text).
"""
import os
import pickle
import sys


def main() -> None:
    # WindPy prints a banner to stdout; keep the real stdout for the protocol
    # only and point fd 1 / sys.stdout at stderr.
    out = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    inp = sys.stdin.buffer

    def send(obj) -> None:
        pickle.dump(obj, out, protocol=pickle.HIGHEST_PROTOCOL)
        out.flush()

    try:
        from WindPy import w
        res = w.start(waitTime=60)
        if getattr(res, "ErrorCode", 0) != 0 and not w.isconnected():
            send(("ERR", "w.start failed: %r" % (getattr(res, "Data", res),)))
            return
        send(("READY",))
    except Exception as ex:
        send(("ERR", repr(ex)))
        return

    while True:
        try:
            req_id, func_name, args = pickle.load(inp)
        except (EOFError, pickle.UnpicklingError):
            return  # parent closed the pipe / died
        try:
            if not w.isconnected():
                w.start(waitTime=60)
            value = getattr(w, func_name)(*args, usedf=True)[1]
            send((req_id, "OK", value))
        except Exception as ex:
            send((req_id, "ERR", repr(ex)))


if __name__ == "__main__":
    main()
