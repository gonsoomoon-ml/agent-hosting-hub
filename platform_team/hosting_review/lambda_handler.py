"""Lambda entry point of the hosting review. The function's ACTION variable names its step."""
import os

from platform_team.hosting_review.review_steps import STEPS
from platform_team.shared_code.aws_helpers import Clients
from platform_team.shared_code.config import Settings


def handler(event, context):
    env = dict(os.environ)
    c = Clients.for_settings(Settings(region=env["HUB_REGION"], prefix=env["PREFIX"]))
    return STEPS[env["ACTION"]](event, c, env)
