"""
Convenience one-command launcher for the demo.

Starts Script B (broker adapter) and Script C (mock broker) as background
processes, waits for them to bind/connect, then runs Script A (strategy) in
the foreground so you see its report directly. Ctrl+C cleans everything up.

For a true "3 separate services" feel (closer to how you'd run this in
production, and easier to inspect each process's own log), run each script
in its own terminal instead - see README.md.
"""

import subprocess
import sys
import time

PY = sys.executable


def main():
    b = subprocess.Popen([PY, "script_b_broker_adapter.py"])
    time.sleep(0.5)
    c = subprocess.Popen([PY, "script_c_mock_broker.py"])
    time.sleep(0.5)

    try:
        subprocess.run([PY, "script_a_strategy.py"], check=False)
    finally:
        time.sleep(0.3)
        for p in (c, b):
            p.terminate()
        for p in (c, b):
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
