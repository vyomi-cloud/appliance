"""Starts one cloud's lab environment (simulator + emulators + test model) in its own process and keeps it alive.
Prints one JSON line {endpoint, env} when ready. Used by the Labs deployer so a chapter's resources persist for the next chapter."""
import importlib
import json
import sys
import time


def main():
    cloud = sys.argv[1]
    endpoint, env = importlib.import_module(f"vyomilabs.labenv_{cloud}").start(sys.argv[2] if len(sys.argv) > 2 else None)
    print("VYOMI_ENV " + json.dumps(dict(endpoint=endpoint, env={k: v for k, v in env.items()})), flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
