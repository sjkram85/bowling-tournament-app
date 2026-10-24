"""USBC Playing Rules lookup: split the rulebook into sections and find the best matches for a question.

The section index (assets/usbc_rulebook_index.json) is built once from the PDF with
scripts/build_rulebook_index.py and committed, so the app needs no PDF tools at runtime.
Search is a small built-in BM25 keyword ranking (no extra packages).
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

INDEX_PATH = Path(__file__).resolve().parent.parent / "assets" / "usbc_rulebook_index.json"
MAX_CHUNK_CHARS = 1500

# "Rule 8 – Dead Ball", "Rule 303a - Tournament Manager", "Rule 51a. Single Game Awards"
HEADING = re.compile(r"^Rule (\d{1,3}[a-z]?)\s*(?:[–\-]|\.)\s+(\S.*)$")
# "Youth Membership Eligibility - Rule 400"
HEADING_REV = re.compile(r"^([A-Z][A-Za-z /,'&\-]{3,60}?)\s+[–\-]\s+Rule (\d{1,3}[a-z]?)$")
PAGE_NOISE = re.compile(r"^(\d{1,3}\s*)?(USBC)?(\s*\d{1,3})?$|^USBC Playing Rules|^\f")
TOC_DOTS = re.compile(r"\.\s?\.\s?\.")

STOPWORDS = set(
    "a an and are as at be by can do does for from has have he her his how i if in is it its may me my "
    "of on or our she should so that the their them then there they this to was we were what when where "
    "which who will with would you your bowler player rule rules usbc".split()
)


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    out = []
    for w in words:
        if w in STOPWORDS or len(w) < 2:
            continue
        # light stemming: fouls->foul, lanes->lane
        if len(w) > 4 and w.endswith("es") and not w.endswith("ses"):
            w = w[:-1]
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


def parse_rulebook_text(text: str) -> list[dict]:
    """Split rulebook plain text into sections: {rule, title, text}. Skips the table of contents."""
    sections: list[dict] = []
    current = None
    for raw in text.splitlines():
        line = raw.replace("\t", " ").strip()
        if not line or PAGE_NOISE.match(line) or TOC_DOTS.search(line):
            continue
        m = HEADING.match(line)
        rev = None if m else HEADING_REV.match(line)
        if rev and rev.group(1).lower().startswith("commonly asked"):
            rev = None  # Q&A block inside the current rule, not a new section
        if m or rev:
            rule, title = (m.group(1), m.group(2)) if m else (rev.group(2), rev.group(1))
            current = {"rule": rule, "title": title.strip(" .*"), "lines": []}
            sections.append(current)
            continue
        if current is not None:
            current["lines"].append(line)

    # Merge repeated headings for the same rule (page breaks), then chunk long sections.
    merged: dict[tuple, dict] = {}
    order = []
    for s in sections:
        key = (s["rule"], s["title"].lower())
        if key not in merged:
            merged[key] = {"rule": s["rule"], "title": s["title"], "lines": []}
            order.append(key)
        merged[key]["lines"].extend(s["lines"])

    out = []
    for key in order:
        s = merged[key]
        body = re.sub(r"\s+", " ", " ".join(s["lines"])).strip()
        if len(body) < 40:  # table-of-contents stubs or empty headings
            continue
        chunks, buf = [], ""
        for sentence in re.split(r"(?<=[.?!])\s+", body):
            if buf and len(buf) + len(sentence) > MAX_CHUNK_CHARS:
                chunks.append(buf)
                buf = ""
            buf = (buf + " " + sentence).strip()
        if buf:
            chunks.append(buf)
        for i, chunk in enumerate(chunks):
            out.append({"rule": s["rule"], "title": s["title"], "part": i + 1, "text": chunk})
    return out


@lru_cache(maxsize=1)
def load_sections() -> tuple:
    if not INDEX_PATH.is_file():
        return tuple()
    return tuple(json.loads(INDEX_PATH.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def _bm25_index():
    secs = load_sections()
    docs = [_tokens(f"{s['title']} {s['title']} {s['text']}") for s in secs]
    df = Counter(t for d in docs for t in set(d))
    avg = sum(len(d) for d in docs) / max(len(docs), 1)
    return secs, [Counter(d) for d in docs], [len(d) for d in docs], df, avg


def search(question: str, k: int = 3, min_score: float = 3.0, min_coverage: float = 0.5) -> list[dict]:
    """Return up to k best-matching sections, each with a 'score'. Empty list if nothing matches well."""
    secs, tfs, lens, df, avg = _bm25_index()
    if not secs:
        return []
    n = len(secs)
    q = _tokens(question)
    # Explicit "rule 8" mention boosts that rule.
    asked = set(re.findall(r"rule\s*(\d{1,3}[a-z]?)", question.lower()))
    k1, b = 1.5, 0.75
    scored = []
    for i, tf in enumerate(tfs):
        s = 0.0
        hit = set()
        for t in q:
            if t not in tf:
                continue
            hit.add(t)
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * lens[i] / avg))
        if secs[i]["rule"] in asked:
            s += 10
        coverage = len(hit) / max(len(set(q)), 1)
        if s >= min_score and (coverage >= min_coverage or secs[i]["rule"] in asked):
            scored.append((s, i))
    scored.sort(reverse=True)
    results, seen = [], set()
    for s, i in scored:
        key = (secs[i]["rule"], secs[i]["part"])
        if key in seen:
            continue
        seen.add(key)
        results.append({**secs[i], "score": round(s, 2)})
        if len(results) == k:
            break
    return results


def format_for_prompt(sections: list[dict]) -> str:
    return "\n\n".join(f"[Rule {s['rule']} – {s['title']}]\n{s['text']}" for s in sections)
