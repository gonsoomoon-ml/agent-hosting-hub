from botocore.exceptions import ClientError
from platform_team.shared_code.aws_helpers import mask, already_exists, wait_status
import pytest

def test_mask_hides_the_account():
    assert mask("arn:aws:iam::111122223333:role/x", "111122223333") == "arn:aws:iam::<ACCOUNT>:role/x"

def test_already_exists_reads_code_and_message():
    err = lambda code, msg: ClientError({"Error": {"Code": code, "Message": msg}}, "Op")
    assert already_exists(err("ConflictException", "x")) and already_exists(err("ValidationException", "name already exists"))
    assert not already_exists(err("AccessDeniedException", "no"))

def test_wait_status_raises_on_failed_state():
    with pytest.raises(RuntimeError, match="CREATE_FAILED"):
        wait_status(lambda: {"status": "CREATE_FAILED", "statusReasons": ["why"]}, ("READY",), "thing", timeout=1, step=0)
