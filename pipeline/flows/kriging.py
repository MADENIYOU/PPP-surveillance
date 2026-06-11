#!/usr/bin/env python3
"""Flow Prefect — Interpolation spatiale par kriging (GPR scikit-learn).

Référence : pipeline/PIPELINE_SPEC.md §7.

Planification : toutes les heures.
Génère une grille GeoJSON 200×200 de PM2.5 interpolé sur Dakar,
stockée dans PostgreSQL `kriging_grid`. Nettoie les grilles > 72h.

Modèle : GaussianProcessRegressor avec noyau RBF (sklearn). Le GPR
est réentraîné légèrement sur le snapshot PM2.5 de l'heure courante
(quelques dizaines de points = rapide), puis prédit sur la grille fixe
[14.60-14.82°N, -17.58-(-17.30)°E] à résolution 200×200 (~50m).

Si aucun capteur actif n'a de données cleansed dans la dernière heure,
le flow se termine proprement sans écriture (log WARNING).
"""
from __future__ import annotations

import json
import os
import structlog
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE_ROOT))

try:
    from prefect import flow, task
    from prefect.logging import get_run_logger
    HAS_PREFECT = True
except ImportError:
    HAS_PREFECT = False
    def flow(*a, **kw):
        def _d(fn): return fn
        return _d
    def task(*a, **kw):
        def _d(fn): return fn
        return _d
    def get_run_logger():
        return structlog.get_logger("kriging")

from db.influxdb_client import get_influxdb_client, query_cleansed_zone_mean  # noqa: E402
from db.postgres_client import PostgresPool  # noqa: E402

LOGGER = structlog.get_logger("kriging")

# Grille Dakar (§7.1)
LAT_MIN, LAT_MAX = 14.60, 14.82
LON_MIN, LON_MAX = -17.58, -17.30
GRID_SIZE = 200
MAX_GRID_AGE_H = 72


@task(name="get-zone-snapshots", retries=1)
def get_zone_snapshots(pool: PostgresPool, influx_client) -> list[dict]:
    """Snapshot PM2.5 moyen de la dernière heure par zone active."""
    log = get_run_logger() if HAS_PREFECT else LOGGER
    snapshots = []
    with pool.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT s.zone_id,
                   split_part(z.path::text, '.', -1) AS zone_slug,
                   ST_Y(ST_Centroid(z.geom)) AS lat,
                   ST_X(ST_Centroid(z.geom)) AS lon
            FROM sensors s
            JOIN zones z ON z.id = s.zone_id
            WHERE s.status = 'active'
        """)
        zones = list(cur.fetchall())

    for zone in zones:
        slug = zone["zone_slug"]
        means = query_cleansed_zone_mean(influx_client, slug, hours=1)
        pm25 = means.get("pm25")
        if pm25 is not None:
            snapshots.append({
                "zone_slug": slug,
                "lat": float(zone["lat"]),
                "lon": float(zone["lon"]),
                "pm25_mean": float(pm25),
            })

    log.info("kriging_snapshots n=%d", len(snapshots))
    return snapshots


@task(name="fit-kriging-model", retries=1)
def fit_and_predict(snapshots: list[dict]) -> Optional[dict]:
    """Entraîne GPR sur les snapshots et prédit sur la grille 200×200 (§7.1)."""
    if len(snapshots) < 2:
        (get_run_logger() if HAS_PREFECT else LOGGER).warning(
            "kriging_insufficient_points n=%d min=2", len(snapshots))
        return None

    import numpy as np
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, WhiteKernel

    positions = np.array([[s["lat"], s["lon"]] for s in snapshots])
    pm25_vals = np.array([s["pm25_mean"] for s in snapshots])

    kernel = RBF(length_scale=0.05) + WhiteKernel(noise_level=1.0)
    gpr = GaussianProcessRegressor(kernel=kernel, n_restarts_optimizer=3, normalize_y=True)
    gpr.fit(positions, pm25_vals)

    # Leave-one-out RMSE pour la métadonnée qualité
    if len(snapshots) >= 3:
        loo_errors = []
        for i in range(len(snapshots)):
            mask = [j for j in range(len(snapshots)) if j != i]
            gpr_loo = GaussianProcessRegressor(kernel=kernel, normalize_y=True)
            gpr_loo.fit(positions[mask], pm25_vals[mask])
            pred_loo = gpr_loo.predict(positions[i:i+1])[0]
            loo_errors.append((pred_loo - pm25_vals[i]) ** 2)
        rmse_loo = float(np.sqrt(np.mean(loo_errors)))
    else:
        rmse_loo = None

    # Grille de prédiction
    lats = np.linspace(LAT_MIN, LAT_MAX, GRID_SIZE)
    lons = np.linspace(LON_MIN, LON_MAX, GRID_SIZE)
    lat_grid, lon_grid = np.meshgrid(lats, lons)
    grid_points = np.column_stack([lat_grid.ravel(), lon_grid.ravel()])
    pm25_pred, pm25_std = gpr.predict(grid_points, return_std=True)
    pm25_pred = np.maximum(0.0, pm25_pred.reshape(GRID_SIZE, GRID_SIZE))
    pm25_std  = pm25_std.reshape(GRID_SIZE, GRID_SIZE)

    return {
        "lat_range": [LAT_MIN, LAT_MAX],
        "lon_range": [LON_MIN, LON_MAX],
        "grid_size": GRID_SIZE,
        "pm25_grid": pm25_pred.tolist(),
        "pm25_std_grid": pm25_std.tolist(),
        "rmse_loo": rmse_loo,
    }


@task(name="build-kriging-geojson")
def build_geojson(grid_result: dict, snapshots: list[dict]) -> str:
    """Sérialise la grille + points de mesure en GeoJSON FeatureCollection."""
    features = []
    # Points de mesure originaux
    for s in snapshots:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
            "properties": {"pm25": s["pm25_mean"], "type": "measurement", "zone": s["zone_slug"]},
        })
    # Métadonnées grille (on ne sérialise pas la grille complète dans le GeoJSON
    # pour garder le payload raisonnable — la grille est dans les champs JSONB de la table)
    geojson = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "lat_range": grid_result["lat_range"],
            "lon_range": grid_result["lon_range"],
            "grid_size": grid_result["grid_size"],
            "rmse_loo": grid_result.get("rmse_loo"),
        },
    }
    return json.dumps(geojson, ensure_ascii=False)


@task(name="write-kriging-grid")
def write_kriging_grid(pool: PostgresPool, geojson_str: str, grid_result: dict,
                        computed_at: datetime) -> None:
    # Utilise kriging_results (migration 02) — table dédiée à la grille GeoJSON agrégée.
    # kriging_grid (schéma 01) stocke des points individuels pour usage vectoriel fin.
    with pool.cursor() as cur:
        cur.execute("""
            INSERT INTO kriging_results (computed_at, geojson, rmse_loo, grid_resolution)
            VALUES (%s, %s::jsonb, %s, %s)
        """, (computed_at, geojson_str, grid_result.get("rmse_loo"), GRID_SIZE))


@task(name="delete-old-kriging-grids")
def delete_old_kriging_grids(pool: PostgresPool, max_age_hours: int = MAX_GRID_AGE_H) -> int:
    with pool.cursor() as cur:
        cur.execute(
            "DELETE FROM kriging_results WHERE computed_at < now() - (%s * interval '1 hour') RETURNING id",
            (max_age_hours,),
        )
        n = len(cur.fetchall())
    if n:
        (get_run_logger() if HAS_PREFECT else LOGGER).info("kriging_old_grids_deleted n=%d", n)
    return n


@flow(name="kriging_interpolation", retries=1, retry_delay_seconds=300)
def run_kriging():
    pool = PostgresPool()
    influx = get_influxdb_client()
    ts = datetime.now(timezone.utc)

    snapshots = get_zone_snapshots(pool, influx)
    if not snapshots:
        (get_run_logger() if HAS_PREFECT else LOGGER).warning("kriging_no_snapshots — flow abandonné")
        return {"status": "no_data"}

    grid_result = fit_and_predict(snapshots)
    if grid_result is None:
        return {"status": "insufficient_points"}

    geojson_str = build_geojson(grid_result, snapshots)
    write_kriging_grid(pool, geojson_str, grid_result, ts)
    n_deleted = delete_old_kriging_grids(pool)

    return {
        "status": "ok",
        "n_zones": len(snapshots),
        "rmse_loo": grid_result.get("rmse_loo"),
        "grids_deleted": n_deleted,
        "computed_at": _iso(ts),
    }


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
    result = run_kriging()
    print("kriging result:", result)
