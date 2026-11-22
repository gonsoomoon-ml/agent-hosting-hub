"""Synthetic records. No real company, product or person appears here."""

INSPECTIONS = {
    "Q-1001": {"case_id": "Q-1001", "part_id": "P-100", "result": "PASS", "inspector_id": "EMP-204817"},
    "Q-1002": {"case_id": "Q-1002", "part_id": "P-200", "result": "PENDING", "inspector_id": "EMP-318425"},
}

PARTS = {
    "P-100": {"part_id": "P-100", "spec": "M4 x 12 mm, steel"},
    "P-200": {"part_id": "P-200", "spec": "M6 x 20 mm, aluminum"},
}

TEST_RESULTS = {
    "P-100": {"part_id": "P-100", "result": "PASS", "inspector_id": "EMP-204817"},
    "P-200": {"part_id": "P-200", "result": "PENDING", "inspector_id": "EMP-318425"},
}
