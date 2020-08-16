#!/usr/bin/env python3
import os
import sys
import json
import datetime
from sun_grid_engine_map import _dummy_queue as dummy

# dummy qdel

assert len(sys.argv) == 2
JB_job_number = sys.argv[1]

with open(dummy.QUEUE_STATE_PATH, "rt") as f:
    old_state = json.loads(f.read())

found = False
state = {
    "pending": [],
    "running": [],
    "evil_jobs": old_state["evil_jobs"],
}
for job in old_state["running"]:
    if job["JB_job_number"] == JB_job_number:
        found = True
    else:
        state["running"].append(job)

for job in old_state["pending"]:
    if job["JB_job_number"] == JB_job_number:
        found = True
    else:
        state["pending"].append(job)

with open(dummy.QUEUE_STATE_PATH, "wt") as f:
    f.write(json.dumps(state, indent=4))

if found == True:
    sys.exit(0)
else:
    print("Can not find ", JB_job_number)
    sys.exit(1)
