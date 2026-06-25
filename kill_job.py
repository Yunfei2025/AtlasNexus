#!/usr/bin/env python3
"""
Utility to kill stuck jobs.

Usage:
    python kill_job.py list              # List all running jobs
    python kill_job.py <job_id>          # Kill a specific job
    python kill_job.py <partial_job_id>  # Kill by partial ID (e.g., first 5 chars)
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from web.services.jobs import list_running_jobs, kill_job, get_job_status


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "list":
        running = list_running_jobs()
        if not running:
            print("No jobs running.")
            return

        print(f"\n{'JOB ID':<12} {'STATE':<10} {'TYPE':<15} {'PID':<8}")
        print("-" * 60)
        for job in running:
            cmd_parts = job.get("cmd", [])
            # Extract job type from command (e.g., "eod", "curve-backtest")
            job_type = "unknown"
            for i, part in enumerate(cmd_parts):
                if "main.py" in part and i + 1 < len(cmd_parts):
                    job_type = cmd_parts[i + 1]
                    break

            pid = job.get("pid", "?")
            print(f"{job['job_id']:<12} {job['state']:<10} {job_type:<15} {pid:<8}")

    else:
        # Kill job by ID or partial ID
        job_id = command

        # Try exact match first
        status = get_job_status(job_id)

        # If no exact match, try to find by prefix
        if status is None:
            running = list_running_jobs()
            for job in running:
                if job['job_id'].startswith(job_id):
                    job_id = job['job_id']
                    status = get_job_status(job_id)
                    break

        if status is None:
            print(f"❌ Job '{command}' not found.")
            sys.exit(1)

        result = kill_job(job_id)
        print(f"✓ {result}")


if __name__ == "__main__":
    main()
