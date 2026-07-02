from datetime import date, timedelta

from dotenv import load_dotenv

from src.helpers import get_garmin_client, get_notion_client

# ============================================================
# CONFIG — edit these freely
# ============================================================
LOOKBACK_DAYS = 7          # how many past days to sync each run (1 = today only)
SKIP_EMPTY_ROWS = True     # don't create a row if every metric is missing
# ============================================================


def _safe(fn, *args, default=None):
    """Run a Garmin call; return default if the endpoint errors or is empty."""
    try:
        return fn(*args)
    except Exception as e:
        print(f"  ! {getattr(fn, '__name__', 'call')} failed: {e}")
        return default


def get_physiology_for_date(garmin, d: str) -> dict:
    """Collect one day's physiology metrics. Keys map to Notion properties.
    NOTE: method names match cyberjunky/python-garminconnect. If a call fails,
    verify the exact name in your installed version and tweak here."""
    metrics = {}

    # VO2 max
    mm = _safe(garmin.get_max_metrics, d)
    if mm and isinstance(mm, list) and mm:
        gen = mm[0].get("generic", {}) or {}
        metrics["vo2max"] = gen.get("vo2MaxPreciseValue") or gen.get("vo2MaxValue")

    # Resting HR
    hr = _safe(garmin.get_heart_rates, d)
    if hr:
        metrics["resting_hr"] = hr.get("restingHeartRate")

    # HRV (last night avg)
    hrv = _safe(garmin.get_hrv_data, d)
    if hrv:
        summary = hrv.get("hrvSummary", {}) or {}
        metrics["hrv"] = summary.get("lastNightAvg")

    # Training readiness
    tr = _safe(garmin.get_training_readiness, d)
    if tr and isinstance(tr, list) and tr:
        metrics["readiness"] = tr[0].get("score")

    # Body battery peak
    bb = _safe(garmin.get_body_battery, d, d)
    if bb and isinstance(bb, list) and bb:
        levels = [x[1] for x in bb[0].get("bodyBatteryValuesArray", []) if x and x[1] is not None]
        if levels:
            metrics["body_battery_peak"] = max(levels)

    # Sleep score
    sleep = _safe(garmin.get_sleep_data, d)
    if sleep:
        scores = (sleep.get("dailySleepDTO", {}) or {}).get("sleepScores", {}) or {}
        metrics["sleep_score"] = (scores.get("overall", {}) or {}).get("value")

    return metrics


def row_exists(client, database_id, iso_date):
    q = client.databases.query(
        database_id=database_id,
        filter={"property": "Long Date", "date": {"equals": iso_date}},
    )
    results = q.get("results", [])
    return results[0] if results else None


def build_properties(iso_date: str, m: dict) -> dict:
    y, mo, da = iso_date.split("-")
    props = {
        "Date": {"title": [{"text": {"content": f"{da}.{mo}.{y}"}}]},
        "Long Date": {"date": {"start": iso_date}},
    }
    number_map = {
        "vo2max": "VO2 Max",
        "resting_hr": "Resting HR",
        "hrv": "HRV (ms)",
        "readiness": "Training Readiness",
        "body_battery_peak": "Body Battery Peak",
        "sleep_score": "Sleep Score",
    }
    for key, prop_name in number_map.items():
        val = m.get(key)
        if val is not None:
            props[prop_name] = {"number": round(float(val), 1)}
    return props


def main():
    load_dotenv()
    garmin_client, _ = get_garmin_client()
    notion_client, notion_dbs = get_notion_client()
    database_id = notion_dbs.physiology

    today = date.today()
    for i in range(LOOKBACK_DAYS):
        d = (today - timedelta(days=i)).isoformat()
        print(f"Physiology: {d}")
        metrics = get_physiology_for_date(garmin_client, d)

        if SKIP_EMPTY_ROWS and not any(v is not None for v in metrics.values()):
            print("  (no data, skipped)")
            continue

        props = build_properties(d, metrics)
        existing = row_exists(notion_client, database_id, d)
        if existing:
            notion_client.pages.update(page_id=existing["id"], properties=props)
            print("  updated")
        else:
            notion_client.pages.create(
                parent={"database_id": database_id}, properties=props, icon={"emoji": "🫀"}
            )
            print("  created")


if __name__ == "__main__":
    main()
