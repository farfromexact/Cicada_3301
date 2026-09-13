"""Keep program errors and timeouts separate from completed scientific negatives."""
import subprocess
import time

def execute(command, *, cwd, timeout, stdin=None):
    start = time.monotonic()
    try:
        p = subprocess.run(command, cwd=cwd, input=stdin, capture_output=True,
                           text=True, encoding="utf8", timeout=timeout)
        return dict(command=command, status="completed" if p.returncode == 0 else "error",
                    exit_code=p.returncode, stdout=p.stdout, stderr=p.stderr,
                    elapsed_seconds=time.monotonic()-start, timeout_seconds=timeout)
    except subprocess.TimeoutExpired as exc:
        def decode(value):
            return value.decode("utf8", errors="replace") if isinstance(value, bytes) else (value or "")
        return dict(command=command, status="timeout", exit_code=None,
                    stdout=decode(exc.stdout), stderr=decode(exc.stderr),
                    elapsed_seconds=time.monotonic()-start, timeout_seconds=timeout)
