import os
import pathlib
print("CWD:", os.getcwd())
env_files = list(pathlib.Path(".").glob(".env*"))
print("Found:", env_files)
if env_files:
    with open(env_files[0]) as f:
        for line in f:
            if 'CELERY' in line or 'REDIS' in line:
                print(line.rstrip())
