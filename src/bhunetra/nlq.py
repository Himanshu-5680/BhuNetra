"""Natural-language question -> safe, parameterised DuckDB query. Rule-based (no LLM key needed).

Guardrails: in-memory DuckDB with ONE registered table, a fixed SQL template, user text never reaches the
SQL string (only bound parameters), horizon restricted to {1,2,3}. The generated query is shown to the user.
"""
from __future__ import annotations

import re
import unicodedata

import duckdb
import pandas as pd


class Unparsed(ValueError):
    """The question could not be understood. Shown to the user, never guessed around."""


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return re.sub(r"[^a-z0-9 ]+", " ", "".join(c for c in s if not unicodedata.combining(c)).lower()).strip()


LEVELS = [("very high", 0.60), ("high", 0.40), ("moderate", 0.10), ("medium", 0.10), ("any", 0.10)]


def parse(question: str, states: list[str], bands: dict) -> dict:
    q = " " + _norm(question) + " "
    if len(q.strip()) < 3:
        raise Unparsed("Please type a question, e.g. 'Which districts in Uttar Pradesh have high heat risk tomorrow?'")
    if "heat" not in q and "garmi" not in q:
        raise Unparsed("I can only answer about HEAT risk for now (rain, air quality and fire are not built yet).")
    horizon = 2 if "day after tomorrow" in q else 3 if re.search(r"\b(3|three) days?\b|\bin 3\b", q) else 1
    min_p, level = bands["high_from"], "high"
    for word, val in LEVELS:
        if f" {word} " in q:
            level, min_p = word, val if word != "high" else bands["high_from"]
            break
    by_norm = {_norm(s): s for s in states}
    hits = [orig for n, orig in sorted(by_norm.items(), key=lambda kv: -len(kv[0])) if f" {n} " in q]
    state = hits[0] if hits else None
    if state is None and re.search(r"\bin [a-z ]+\b", q) and not any(w in q for w in ("india", "all states", "every state", "anywhere")):
        raise Unparsed("I did not recognise the state. Use a state name from the sample (see the table) or say 'in India'.")
    return {"horizon": horizon, "min_p": float(min_p), "level": level, "state": state}


def run(df: pd.DataFrame, date: pd.Timestamp, spec: dict) -> tuple[str, list, pd.DataFrame]:
    if spec["horizon"] not in (1, 2, 3):                      # allow-list: only these column names can appear in SQL
        raise Unparsed("Horizon must be 1, 2 or 3 days.")
    col = f"p{int(spec['horizon'])}"
    view = df[["name", "state", "date", col]].rename(columns={"name": "district", col: "p"})
    where, params = ["date = ?", "p >= ?"], [pd.Timestamp(date).to_pydatetime(), spec["min_p"]]
    if spec["state"]:
        where.append("state = ?"); params.append(spec["state"])
    sql = f"SELECT district, state, ROUND(p * 100, 1) AS heat_risk_pct FROM risk_view WHERE {' AND '.join(where)} ORDER BY p DESC LIMIT 50"
    con = duckdb.connect(":memory:")
    con.register("risk_view", view)
    try:
        return sql, params, con.execute(sql, params).df()
    finally:
        con.close()
