"""Shared metadata for tournament host centers and default handicap rules."""

HOST_CENTERS = {
    "FHL": {
        "name": "Forest Hill Lanes",
        "address": "1 Maurice Drive, Forest Hill, MD 21050",
        "phone": "(410) 838-4477",
        "capacity_lanes": 40,
        "capacity_pairs": 20,
    },
    "HL": {
        "name": "Harford Lanes",
        "address": "20 Custis Street, Aberdeen, MD 21001",
        "phone": "(410) 272-3555",
        "capacity_lanes": 20,
        "capacity_pairs": 10,
    },
    "APG": {
        "name": "APG Bowling Center",
        "address": "Aberdeen Boulevard, APG North BLDG 2342, APG, MD 21005",
        "phone": "(410) 278-4041",
        "capacity_lanes": 12,
        "capacity_pairs": 6,
    },
    "CHUSBC": {
        "name": "Cecil Harford USBC",
        "capacity_lanes": 40,
    },
}

CENTERS = {
    "FHL": {
        "name": "Forest Hill Lanes",
        "lanes": 40,
        "pairs": 20,
        "logo_file": "forest hill lanes.png",
        "address": "1 Maurice Drive, Forest Hill, MD 21050",
    },
    "HL": {
        "name": "Harford Lanes",
        "lanes": 20,
        "pairs": 10,
        "logo_file": "Harford.png",
        "address": "20 Custis Street, Aberdeen, MD 21001",
    },
    "APG": {
        "name": "APG Bowling Center",
        "lanes": 12,
        "pairs": 6,
        "logo_file": "APG.png",
        "address": "Aberdeen Blvd Bldg 2342, APG, MD 21005",
    },
    "CHUSBC": {
        "name": "Cecil Harford USBC",
        "logo_file": "CHUSBC.jpg",
    },
}

DEFAULT_HANDICAP_BASE = 220
DEFAULT_HANDICAP_PERCENT = 0.90
DEFAULT_MYSTERY_DOUBLES_FEE = 5.0

DEFAULT_HANDICAP_RULES = {
    "percentage": int(DEFAULT_HANDICAP_PERCENT * 100),
    "base": DEFAULT_HANDICAP_BASE,
}