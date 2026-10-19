"""Data contracts (pandera). Any schema change upstream must fail loudly here."""
import pandera.pandas as pa

# Ranges are physical sanity limits for India, not model thresholds.
weather_schema = pa.DataFrameSchema(
    {
        "district_id": pa.Column(str, nullable=False),
        "time_utc": pa.Column("datetime64[ns]", nullable=False),
        "temperature_2m": pa.Column(float, pa.Check.in_range(-30, 60), nullable=True),
        "relative_humidity_2m": pa.Column(float, pa.Check.in_range(0, 100), nullable=True),
        "apparent_temperature": pa.Column(float, pa.Check.in_range(-40, 70), nullable=True),
        "precipitation": pa.Column(float, pa.Check.ge(0), nullable=True),
        "wind_speed_10m": pa.Column(float, pa.Check.ge(0), nullable=True),
        "source": pa.Column(str),
        "fetched_at_utc": pa.Column(str),
        "sha256": pa.Column(str),
    },
    unique=["district_id", "time_utc"],
    strict=True,
    coerce=True,
)

air_schema = pa.DataFrameSchema(
    {
        "district_id": pa.Column(str, nullable=False),
        "time_utc": pa.Column("datetime64[ns]", nullable=False),
        "pm2_5": pa.Column(float, pa.Check.ge(0), nullable=True),
        "pm10": pa.Column(float, pa.Check.ge(0), nullable=True),
        "nitrogen_dioxide": pa.Column(float, pa.Check.ge(0), nullable=True),
        "ozone": pa.Column(float, pa.Check.ge(0), nullable=True),
        "us_aqi": pa.Column(float, pa.Check.in_range(0, 1000), nullable=True),
        "source": pa.Column(str),
        "fetched_at_utc": pa.Column(str),
        "sha256": pa.Column(str),
    },
    unique=["district_id", "time_utc"],
    strict=True,
    coerce=True,
)

quake_schema = pa.DataFrameSchema(
    {
        "event_id": pa.Column(str),
        "time_utc": pa.Column("datetime64[ns]"),
        "lat": pa.Column(float, pa.Check.in_range(-90, 90)),
        "lon": pa.Column(float, pa.Check.in_range(-180, 180)),
        "depth_km": pa.Column(float, nullable=True),
        "magnitude": pa.Column(float, pa.Check.in_range(-2, 10), nullable=True),
        "place": pa.Column(str, nullable=True),
        "source": pa.Column(str),
        "fetched_at_utc": pa.Column(str),
        "sha256": pa.Column(str),
    },
    unique=["event_id"],
    strict=True,
    coerce=True,
)

climate_daily_schema = pa.DataFrameSchema(
    {
        "district_id": pa.Column(str, nullable=False),
        "date": pa.Column("datetime64[ns]", nullable=False),
        "temperature_2m_max": pa.Column(float, pa.Check.in_range(-30, 60), nullable=True),
        "temperature_2m_min": pa.Column(float, pa.Check.in_range(-40, 50), nullable=True),
        "temperature_2m_mean": pa.Column(float, pa.Check.in_range(-35, 55), nullable=True),
        "apparent_temperature_max": pa.Column(float, pa.Check.in_range(-40, 70), nullable=True),
        "precipitation_sum": pa.Column(float, pa.Check.in_range(0, 1500), nullable=True),
        "wind_speed_10m_max": pa.Column(float, pa.Check.ge(0), nullable=True),
        "source": pa.Column(str),
        "fetched_at_utc": pa.Column(str),
        "sha256": pa.Column(str),
    },
    unique=["district_id", "date"],
    strict=True,
    coerce=True,
)
