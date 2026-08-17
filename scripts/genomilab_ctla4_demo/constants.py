from __future__ import annotations

import hashlib
from typing import Any


JsonObject = dict[str, Any]

QUESTION = (
    "I have Crohn disease and keep getting sinus and chest infections. My doctor "
    "thinks the infections might be from my medication, but I also had very low "
    "platelets as a teenager. Could any of this be connected?"
)
DISEASE_SCOPE = (
    "Crohn disease, recurrent sinus and chest infections, and prior low platelets"
)
CTLA4_REFERENCE_PROTEIN = (
    "MACLGFQRHKAQLNLATRTWPCTLLFFLLFIPVFCKAMHVAQPAVVLASSRGIASFVCEYASPGK"
    "ATEVRVTVLRQADSQVTEVCAATYMMGNELTFLDDSICTGTSSGNQVNLTIQGLRAMDTGLYICK"
    "VELMYPPPYYLGIGNGTQIYVIDPEPCPDSDFLLWILAAVSSGLFFYSFLLTAVSLSKMLKKRSP"
    "LTTGVYVKMPPTEPECEKQFQPYFIPIN"
)
SPECIALISTS = [
    {
        "specialist_id": "specialist-clinical-timeline",
        "role": "Clinical timeline specialist",
        "task": "Align immune findings, infections, and medication dates",
    },
    {
        "specialist_id": "specialist-immune-genetics",
        "role": "Immune-genetics specialist",
        "task": "Build a focused candidate set and interpret chair-returned genome evidence",
    },
    {
        "specialist_id": "specialist-evidence-skeptic",
        "role": "Literature and evidence-skeptic specialist",
        "task": "Review replayed public evidence, alternatives, conflicts, and gaps",
    },
]


def approval(candidate: JsonObject) -> JsonObject:
    return {
        key: value
        for key, value in candidate.items()
        if key
        not in {
            "status",
            "requires_explicit_approval",
            "user_id",
            "investigation_id",
        }
    } | {"approved": True}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
