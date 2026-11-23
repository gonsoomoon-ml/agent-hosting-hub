"""Records in the catalog (AWS Agent Registry). A record is a tool or an agent; a search finds approved records only.
The application (or tool description) travels as JSON in the record's custom descriptor."""
import json
import time

from botocore.exceptions import ClientError

from platform_team.shared_code.aws_helpers import all_items, wait_status

SETTLED = ("DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED", "DEPRECATED")


def records(c, registry_id: str) -> dict[str, dict]:
    return {r["name"]: r for r in all_items(c.reg.list_registry_records, registryId=registry_id, maxResults=100)}


def put_record(c, registry_id: str, name: str, record_type: str, description: str, payload: dict) -> str:
    """Create the record, or change the one with this name; a new or changed record is a DRAFT. Returns the record ID.
    The registry treats an update that changes nothing as no update: the record keeps its status (found by running)."""
    data = json.dumps(payload)
    old = records(c, registry_id).get(name)
    if old:
        rid = old["recordId"]
        # an update is a patch: every field it changes sits in an optionalValue wrapper
        c.reg.update_registry_record(
            registryId=registry_id, recordId=rid, recordType=record_type, description={"optionalValue": description},
            descriptors={"optionalValue": {"custom": {"optionalValue": {"data": {"optionalValue": data}}}}})
    else:
        arn = c.reg.create_registry_record(registryId=registry_id, name=name, description=description,
                                           recordType=record_type, recordVersion="1.0.0",
                                           descriptors={"custom": {"data": data}})["recordArn"]
        rid = arn.rsplit("/", 1)[-1]
    # CREATING or UPDATING -> DRAFT; the status changes before the call returns
    wait_status(lambda: c.reg.get_registry_record(registryId=registry_id, recordId=rid), SETTLED, f"record {name}")
    return rid


def submit(c, registry_id: str, record_id: str) -> str:
    """Ask for approval. Returns the new status (PENDING_APPROVAL)."""
    return c.reg.submit_registry_record_for_approval(registryId=registry_id, recordId=record_id)["status"]


def set_status(c, registry_id: str, record_id: str, status: str, reason: str) -> str:
    """Approve, reject or deprecate a record, with the reason shown to its owner. Returns the new status."""
    return c.reg.update_registry_record_status(registryId=registry_id, recordId=record_id,
                                               status=status, statusReason=reason)["status"]


def search_records(c, registry_id: str, query: str) -> list[dict]:
    """The approved records that match the query as the search gives them (name, recordType, description, ...), best
    match first."""
    found = c.disc.search_discoverable_registry_records(searchQuery=query, registryIds=[registry_id], maxResults=20)
    return found["registryRecords"]


def search(c, registry_id: str, query: str) -> list[str]:
    """Names of the approved records that match the query, best match first."""
    return [r["name"] for r in search_records(c, registry_id, query)]


def drop_record(c, registry_id: str, record_id: str, timeout: int = 90) -> None:
    """Delete a record and wait until the registry no longer lists it. A record that is already gone is fine."""
    try:
        c.reg.delete_registry_record(registryId=registry_id, recordId=record_id)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return
        raise
    t0 = time.monotonic()
    while any(r["recordId"] == record_id for r in records(c, registry_id).values()):
        if time.monotonic() - t0 > timeout:
            raise TimeoutError(f"record {record_id} still listed after {timeout}s")
        time.sleep(3)
