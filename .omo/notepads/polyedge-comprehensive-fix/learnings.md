
### Scheduler Crash Recovery - Job Persistence

**Pattern:** Scheduled jobs in `backend/core/scheduler.py` are now persisted to a `ScheduledJob` table in `backend/models/database.py` before being registered with APScheduler. On application startup, the scheduler reloads these persisted jobs to ensure continuity after crashes or restarts.

**Key Components:**
- **`ScheduledJob` Model:** A new SQLAlchemy model in `backend/models/database.py` stores `job_name`, `job_state_json` (APScheduler's job state including trigger and kwargs), `last_run`, `next_run`, and `enabled` status.
- **`_persist_and_add_job` Function:** A helper function in `scheduler.py` that first saves the job's metadata to the `ScheduledJob` table and then registers it with APScheduler.
- **`load_scheduler_state` Function:** On scheduler initialization, this function queries the `ScheduledJob` table for all enabled jobs and re-adds them to the APScheduler instance. It uses a `JOB_FUNCTION_REGISTRY` to map function names to actual callable objects.

**Benefits:**
- **Crash Recovery:** Ensures no scheduled jobs are lost due to application restarts or crashes.
- **Stateful Scheduling:** The scheduler can maintain its state across sessions.
- **Centralized Job Management:** Provides a single source of truth for all scheduled tasks.

**Usage:**
- When adding a new job in `scheduler.py`, use `_persist_and_add_job` instead of `scheduler.add_job` directly.
- Ensure all job functions are registered in `JOB_FUNCTION_REGISTRY` for proper reloading.
