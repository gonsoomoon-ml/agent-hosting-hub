"""Lambda entry point of the hosting review. The function's ACTION variable names its step.

The step gets a deadline MARGIN seconds before the Lambda timeout: its waits end by then, so a step that runs
out of time still deletes what it half-made (a policy that is not ACTIVE) and fails with its own message."""
import os

from platform_team.hosting_review.review_steps import STEPS
from platform_team.shared_code.aws_helpers import Clients, Deadline
from platform_team.shared_code.config import Settings

MARGIN = 60   # s: cleanup after the last wait (delete a policy and wait until it is gone) and the error return


def handler(event, context):
    env = dict(os.environ)
    c = Clients.for_settings(Settings(region=env["HUB_REGION"], prefix=env["PREFIX"]))
    deadline = Deadline(context.get_remaining_time_in_millis() / 1000 - MARGIN)
    return STEPS[env["ACTION"]](event, c, env, deadline=deadline)
