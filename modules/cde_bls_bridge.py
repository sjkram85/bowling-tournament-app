"""Import/export bridge for BITS / Bowler TRAC roster files and AutoScoring ASCII streams."""

import csv
import io

from modules.db_state import get_connection

# Header aliases (lower-cased, stripped of spaces/underscores) -> roster field.
_FIELD_ALIASES = {
    "usbcid": "usbc_id",
    "usbc": "usbc_id",
    "memberid": "usbc_id",
    "id": "usbc_id",
    "name": "name",
    "bowler": "name",
    "bowlername": "name",
    "firstname": "first_name",
    "first": "first_name",
    "lastname": "last_name",
    "last": "last_name",
    "average": "entering_avg",
    "avg": "entering_avg",
    "enteringavg": "entering_avg",
    "enteringaverage": "entering_avg",
    "handicap": "handicap",
    "hdcp": "handicap",
    "email": "email",
    "emailaddress": "email",
}
# Layout assumed for header-less files.
_POSITIONAL_FIELDS = ["usbc_id", "last_name", "first_name", "entering_avg", "handicap", "email"]

BITS_COLUMNS = ["USBC ID", "Last Name", "First Name", "Average", "Handicap", "Lane", "Game 1", "Game 2", "Game 3"]
_NAME_WIDTH = 24
_ID_WIDTH = 12


def _normalize_header(value: str) -> str:
    return value.strip().lower().replace(" ", "").replace("_", "")


def _to_int(value: str | None) -> int | None:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def parse_bls_bits_file(file_content: str | bytes) -> list[dict]:
    """Parse a comma-delimited BITS / Bowler TRAC file into bowler roster records.

    Uses the header row when one is present, otherwise assumes the column order
    USBC ID, Last, First, Average, Handicap, Email. Rows without a name are skipped.
    """
    if isinstance(file_content, bytes):
        file_content = file_content.decode("utf-8-sig", errors="replace")
    rows = [row for row in csv.reader(io.StringIO(file_content.lstrip("\ufeff"))) if any(c.strip() for c in row)]
    if not rows:
        return []

    mapped_header = [_FIELD_ALIASES.get(_normalize_header(cell)) for cell in rows[0]]
    if any(mapped_header):
        fields, data_rows = mapped_header, rows[1:]
    else:
        fields, data_rows = _POSITIONAL_FIELDS, rows

    records = []
    for row in data_rows:
        raw = {field: cell.strip() for field, cell in zip(fields, row) if field}
        name = raw.get("name") or " ".join(
            part for part in (raw.get("first_name"), raw.get("last_name")) if part
        )
        if not name:
            continue
        records.append(
            {
                "name": name,
                "usbc_id": raw.get("usbc_id") or None,
                "email": raw.get("email") or None,
                "entering_avg": _to_int(raw.get("entering_avg")),
                "handicap": _to_int(raw.get("handicap")),
            }
        )
    return records


def _split_name(name: str) -> tuple[str, str]:
    parts = name.strip().rsplit(" ", 1)
    return (parts[0], "") if len(parts) == 1 else (parts[1], parts[0])


def generate_bls_export(tournament_id: int) -> str:
    """Return the AutoScoring ASCII ``.dat`` stream of game-by-game scores for a tournament."""
    return build_bls_streams(tournament_id)["autoscoring_dat"]


def build_bls_streams(tournament_id: int) -> dict[str, str]:
    """Build every export stream for a tournament.

    Returns {"bits_csv", "autoscoring_dat", "autoscoring_txt"}: a BITS flat CSV,
    a fixed-width AutoScoring ASCII stream, and a tab-delimited .txt equivalent.
    """
    connection = get_connection()
    try:
        game_count = connection.execute(
            "SELECT game_count FROM tournaments WHERE id = ?", (tournament_id,)
        ).fetchone()
        if game_count is None:
            raise ValueError(f"Tournament {tournament_id} not found")
        game_count = game_count["game_count"]
        bowlers = connection.execute(
            "SELECT id, name, usbc_id, entering_avg, handicap, lane_assignment "
            "FROM bowlers WHERE tournament_id = ? ORDER BY lane_assignment, name",
            (tournament_id,),
        ).fetchall()
        scores: dict[int, dict[int, int]] = {}
        for row in connection.execute(
            "SELECT bowler_id, game_number, scratch_score FROM bowler_scores WHERE tournament_id = ?",
            (tournament_id,),
        ):
            scores.setdefault(row["bowler_id"], {})[row["game_number"]] = row["scratch_score"]
    finally:
        connection.close()

    game_headers = [f"Game {n}" for n in range(1, game_count + 1)]
    columns = BITS_COLUMNS[:5] + ["Lane"] + game_headers

    bits_out = io.StringIO()
    bits_writer = csv.writer(bits_out, lineterminator="\r\n")
    bits_writer.writerow(columns)
    txt_out = io.StringIO()
    txt_writer = csv.writer(txt_out, delimiter="\t", lineterminator="\r\n")
    txt_writer.writerow(columns)
    dat_lines = []

    for bowler in bowlers:
        last, first = _split_name(bowler["name"])
        game_scores = [scores.get(bowler["id"], {}).get(n) for n in range(1, game_count + 1)]
        values = [
            bowler["usbc_id"] or "",
            last,
            first,
            bowler["entering_avg"] if bowler["entering_avg"] is not None else "",
            bowler["handicap"] if bowler["handicap"] is not None else "",
            bowler["lane_assignment"] if bowler["lane_assignment"] is not None else "",
            *["" if s is None else s for s in game_scores],
        ]
        bits_writer.writerow(values)
        txt_writer.writerow(values)
        dat_lines.append(
            f"{bowler['lane_assignment'] or 0:>3}"
            f"{bowler['name'][:_NAME_WIDTH]:<{_NAME_WIDTH}}"
            f"{(bowler['usbc_id'] or '')[:_ID_WIDTH]:<{_ID_WIDTH}}"
            f"{bowler['entering_avg'] or 0:>3}"
            f"{bowler['handicap'] or 0:>3}"
            + "".join(f"{s or 0:>3}" for s in game_scores)
        )

    return {
        "bits_csv": bits_out.getvalue(),
        "autoscoring_dat": "\r\n".join(dat_lines) + ("\r\n" if dat_lines else ""),
        "autoscoring_txt": txt_out.getvalue(),
    }
