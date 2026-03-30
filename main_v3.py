"""
Optribute v3 — Production VRPTW Solver
========================================
Key improvements over v2:
1. OR-Tools with proper local search operators (all inter-route moves enabled)
2. Multi-depot support (Katman 0: depot assignment)
3. First solution: PARALLEL_CHEAPEST_INSERTION (geographically coherent)
4. Open/closed route handling via zero-cost depot return arcs
5. 4 optimization goals: distance, makespan, balance, min_vehicles
6. OSRM with fallback to haversine
7. Proper time window handling
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
import math, time, logging, requests

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("optribute_v3")

app = FastAPI(title="Optribute API v3", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

OSRM_BASE = "http://router.project-osrm.org"

# ─────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────

class Job(BaseModel):
    id: int
    lat: float
    lon: float
    demand: int = 0
    time_start: int = 0       # minutes from midnight
    time_end: int = 1440      # minutes from midnight

class Depot(BaseModel):
    id: int
    lat: float
    lon: float

class OptRequest(BaseModel):
    depots: List[Depot]                         # 1+ depots
    jobs: List[Job]
    vehicle_count: int
    vehicle_capacity: int = 999999
    use_capacity: bool = False
    open_route: bool = False
    service_time: int = 10                      # minutes per stop
    route_start_time: int = 480                 # minutes from midnight
    optimization_goal: str = "distance"         # distance | makespan | balance | min_vehicles
    max_ratio: float = 3.0                      # soft balance limit
    time_limit: int = 30                        # solver seconds

# ─────────────────────────────────────────
# Distance Matrix
# ─────────────────────────────────────────

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = math.sin(dLat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dLon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def haversine_matrix(locations):
    """Build distance (meters) and duration (minutes) matrices using haversine."""
    n = len(locations)
    dist = [[0]*n for _ in range(n)]
    dur = [[0]*n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            km = haversine_km(locations[i]["lat"], locations[i]["lon"],
                              locations[j]["lat"], locations[j]["lon"])
            # Assume 30 km/h average urban speed, * 1.3 road winding factor
            dist[i][j] = int(km * 1300)  # meters, with 1.3x factor
            dur[i][j] = int((km * 1.3) / 30 * 60)  # minutes
    return dist, dur

def osrm_matrix(locations):
    """Build distance/duration matrices from OSRM. Falls back to haversine on failure."""
    coords = ";".join(f"{l['lon']},{l['lat']}" for l in locations)
    url = f"{OSRM_BASE}/table/v1/driving/{coords}?annotations=distance,duration"
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            raise Exception(f"OSRM HTTP {resp.status_code}")
        data = resp.json()
        if data.get("code") != "Ok":
            raise Exception(f"OSRM error: {data.get('code')}")
        dist = [[int(v) if v else 10_000_000 for v in row] for row in data["distances"]]
        dur = [[int(v/60) if v else 9999 for v in row] for row in data["durations"]]
        return dist, dur
    except Exception as e:
        log.warning(f"OSRM failed ({e}), falling back to haversine")
        return haversine_matrix(locations)

def get_matrices(locations):
    """Try OSRM first, fall back to haversine."""
    if len(locations) > 200:
        log.info(f"Large problem ({len(locations)} nodes), using haversine to avoid OSRM timeout")
        return haversine_matrix(locations)
    return osrm_matrix(locations)

# ─────────────────────────────────────────
# Multi-Depot: Assign customers to depots
# ─────────────────────────────────────────

def assign_to_depots(depots, jobs, dist_matrix):
    """Assign each job to nearest depot using real distance matrix."""
    groups = {d["id"]: [] for d in depots}
    for j_idx, job in enumerate(jobs):
        best_depot = depots[0]["id"]
        best_dist = float("inf")
        for d in depots:
            d_idx = d["_matrix_idx"]
            j_real_idx = job["_matrix_idx"]
            d_val = dist_matrix[d_idx][j_real_idx]
            if d_val < best_dist:
                best_dist = d_val
                best_depot = d["id"]
        groups[best_depot].append(job)
    return groups

# ─────────────────────────────────────────
# OR-Tools Solver (single depot)
# ─────────────────────────────────────────

def solve_single_depot(depot, customers, dist_matrix_full, dur_matrix_full, req: OptRequest):
    """
    Solve VRPTW for one depot + its assigned customers.
    Returns list of routes, each route = list of {lat, lon, id, arrival_time, ...}
    """
    if not customers:
        return []

    # Build sub-matrices: index 0 = depot, 1..n = customers
    indices = [depot["_matrix_idx"]] + [c["_matrix_idx"] for c in customers]
    n = len(indices)
    dist_sub = [[dist_matrix_full[indices[i]][indices[j]] for j in range(n)] for i in range(n)]
    dur_sub = [[dur_matrix_full[indices[i]][indices[j]] for j in range(n)] for i in range(n)]

    # Determine vehicle count for this depot
    if len(req.depots) == 1:
        v_count = req.vehicle_count
    else:
        # Proportional split based on customer count
        total_customers = len(req.jobs)
        proportion = len(customers) / total_customers if total_customers > 0 else 1
        v_count = max(1, round(req.vehicle_count * proportion))

    eff_cap = req.vehicle_capacity if req.use_capacity else 999999

    # ── Create OR-Tools model ──
    manager = pywrapcp.RoutingIndexManager(n, v_count, 0)
    routing = pywrapcp.RoutingModel(manager)

    # Distance callback
    def dist_cb(from_idx, to_idx):
        f = manager.IndexToNode(from_idx)
        t = manager.IndexToNode(to_idx)
        if req.open_route and t == 0:
            return 0  # free return to depot for open routes
        return dist_sub[f][t]

    # Time callback (travel + service)
    def time_cb(from_idx, to_idx):
        f = manager.IndexToNode(from_idx)
        t = manager.IndexToNode(to_idx)
        if f == t:
            return 0
        if req.open_route and t == 0:
            return 0
        travel = dur_sub[f][t]
        service = req.service_time if f != 0 else 0
        return travel + service

    # Demand callback
    def demand_cb(from_idx):
        node = manager.IndexToNode(from_idx)
        if node == 0:
            return 0
        return customers[node - 1].get("demand", 0)

    dist_cb_idx = routing.RegisterTransitCallback(dist_cb)
    time_cb_idx = routing.RegisterTransitCallback(time_cb)
    demand_cb_idx = routing.RegisterUnaryTransitCallback(demand_cb)

    # ── Set arc cost based on optimization goal ──
    if req.optimization_goal == "makespan":
        routing.SetArcCostEvaluatorOfAllVehicles(time_cb_idx)
    else:
        routing.SetArcCostEvaluatorOfAllVehicles(dist_cb_idx)

    # ── Capacity dimension ──
    routing.AddDimensionWithVehicleCapacity(
        demand_cb_idx, 0,
        [eff_cap] * v_count,
        True, "Capacity"
    )

    # ── Distance dimension (for tracking) ──
    routing.AddDimension(dist_cb_idx, 0, 999_999_999, True, "Distance")

    # ── Time dimension ──
    max_time = 1440 * 2  # 48 hours in minutes (allow overnight)
    routing.AddDimension(time_cb_idx, max_time, max_time, False, "Time")
    time_dim = routing.GetDimensionOrDie("Time")

    # Vehicle start time
    for vid in range(v_count):
        start_var = time_dim.CumulVar(routing.Start(vid))
        start_var.SetRange(req.route_start_time, req.route_start_time)

    # Time windows for customers
    for i, cust in enumerate(customers):
        idx = manager.NodeToIndex(i + 1)
        tw_start = cust.get("time_start", 0)
        tw_end = cust.get("time_end", 1440)

        # Fix inverted windows
        if tw_start > tw_end:
            tw_start, tw_end = tw_end, tw_start

        # If window ends before route start, extend it
        if tw_end <= req.route_start_time:
            window_dur = max(tw_end - tw_start, 60)
            tw_start = req.route_start_time
            tw_end = tw_start + window_dur

        effective_start = max(tw_start, req.route_start_time)
        time_dim.CumulVar(idx).SetRange(effective_start, effective_start)  # will use soft bound below
        time_dim.SetCumulVarSoftUpperBound(idx, tw_end, 50000)

    # ── Optimization goal specifics ──
    num_stops = len(customers)
    avg_stops = max(1, num_stops // v_count)

    # Stop count dimension (for balance / force vehicles)
    def stop_cb(from_idx):
        node = manager.IndexToNode(from_idx)
        return 1 if node != 0 else 0
    stop_cb_idx = routing.RegisterUnaryTransitCallback(stop_cb)
    routing.AddDimension(stop_cb_idx, 0, num_stops + 1, True, "StopCount")
    stop_dim = routing.GetDimensionOrDie("StopCount")

    # Sample average distance for penalty calibration
    sample = [dist_sub[0][j] for j in range(1, min(n, 15))]
    avg_dist = int(sum(sample) / len(sample)) if sample else 5000

    if req.optimization_goal == "min_vehicles":
        # High fixed cost per vehicle → minimize active vehicles
        routing.SetFixedCostOfAllVehicles(max(int(avg_dist * avg_stops * 1.5), 50000))

    elif req.optimization_goal == "balance":
        # Penalize imbalance in stop counts
        stop_dim.SetGlobalSpanCostCoefficient(avg_dist)

    elif req.optimization_goal == "makespan":
        # Penalize longest route time
        time_dim.SetGlobalSpanCostCoefficient(300)

    else:  # "distance" — default
        pass

    # Soft force vehicles (unless min_vehicles mode)
    if req.optimization_goal != "min_vehicles":
        max_forceable = min(v_count, num_stops)
        for vid in range(max_forceable):
            stop_dim.SetCumulVarSoftLowerBound(
                routing.End(vid), 1, avg_dist * 2
            )

    # Max ratio constraint (soft upper bound on stops per vehicle)
    max_per = int(avg_stops * req.max_ratio)
    for vid in range(v_count):
        stop_dim.SetCumulVarSoftUpperBound(
            routing.End(vid), max_per, avg_dist
        )

    # ── Search parameters ──
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = req.time_limit

    # ★ Enable all local search operators for best quality
    params.local_search_operators.use_relocate = pywrapcp.BOOL_TRUE
    params.local_search_operators.use_relocate_pair = pywrapcp.BOOL_TRUE
    params.local_search_operators.use_relocate_neighbors = pywrapcp.BOOL_TRUE
    params.local_search_operators.use_exchange = pywrapcp.BOOL_TRUE
    params.local_search_operators.use_cross = pywrapcp.BOOL_TRUE
    params.local_search_operators.use_cross_exchange = pywrapcp.BOOL_TRUE
    params.local_search_operators.use_two_opt = pywrapcp.BOOL_TRUE
    params.local_search_operators.use_or_opt = pywrapcp.BOOL_TRUE
    params.local_search_operators.use_lin_kernighan = pywrapcp.BOOL_TRUE
    params.local_search_operators.use_tsp_opt = pywrapcp.BOOL_TRUE
    params.local_search_operators.use_make_active = pywrapcp.BOOL_TRUE
    params.local_search_operators.use_make_inactive = pywrapcp.BOOL_TRUE
    params.local_search_operators.use_make_chain_inactive = pywrapcp.BOOL_TRUE
    params.local_search_operators.use_swap_active = pywrapcp.BOOL_TRUE
    params.local_search_operators.use_extended_swap_active = pywrapcp.BOOL_TRUE
    params.local_search_operators.use_path_lns = pywrapcp.BOOL_TRUE
    params.local_search_operators.use_full_path_lns = pywrapcp.BOOL_TRUE

    # ── Solve ──
    t0 = time.time()
    solution = routing.SolveWithParameters(params)
    elapsed = round(time.time() - t0, 1)

    if not solution:
        log.warning(f"No solution found for depot {depot['id']} ({len(customers)} customers, {v_count} vehicles)")
        return []

    log.info(f"Depot {depot['id']}: solution found in {elapsed}s, cost={solution.ObjectiveValue()}")

    # ── Extract routes ──
    routes = []
    for vid in range(v_count):
        idx = routing.Start(vid)
        stops = []
        total_load = 0
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            arrival = solution.Min(time_dim.CumulVar(idx))
            arr_h = (arrival // 60) % 24
            arr_m = arrival % 60

            if node == 0:
                loc = depot
            else:
                loc = customers[node - 1]

            total_load += loc.get("demand", 0)
            stops.append({
                "node": node,
                "id": loc["id"],
                "lat": loc["lat"],
                "lon": loc["lon"],
                "demand": loc.get("demand", 0),
                "arrival_time": f"{arr_h:02d}:{arr_m:02d}",
                "arrival_minutes": arrival,
            })
            idx = solution.Value(routing.NextVar(idx))

        # Add depot return for closed routes
        if not req.open_route and len(stops) > 1:
            end_arrival = solution.Min(time_dim.CumulVar(idx))
            arr_h = (end_arrival // 60) % 24
            arr_m = end_arrival % 60
            stops.append({
                "node": 0,
                "id": depot["id"],
                "lat": depot["lat"],
                "lon": depot["lon"],
                "demand": 0,
                "arrival_time": f"{arr_h:02d}:{arr_m:02d}",
                "arrival_minutes": end_arrival,
            })

        if len(stops) <= 1:
            continue  # empty route

        # Calculate real distance via OSRM route (for display) or sum matrix
        total_km = 0
        for si in range(len(stops) - 1):
            from_mi = stops[si]["node"]
            to_mi = stops[si + 1]["node"]
            if req.open_route and to_mi == 0:
                continue
            total_km += dist_sub[from_mi][to_mi]
        total_km = round(total_km / 1000, 2)

        customer_stops = [s for s in stops if s["id"] != depot["id"]]

        routes.append({
            "vehicle_id": vid + 1,
            "depot_id": depot["id"],
            "path": [
                {
                    "order": i + 1,
                    "lat": s["lat"],
                    "lon": s["lon"],
                    "original_id": s["id"],
                    "demand": s["demand"],
                    "arrival_time": s["arrival_time"],
                    "arrival_minutes": s["arrival_minutes"],
                }
                for i, s in enumerate(stops)
            ],
            "total_km": total_km,
            "total_load": total_load,
            "stop_count": len(customer_stops),
        })

    return routes

# ─────────────────────────────────────────
# Main Optimization Endpoint
# ─────────────────────────────────────────

@app.post("/optimize")
def optimize(req: OptRequest):
    if not req.depots:
        raise HTTPException(400, "En az 1 depo gerekli")
    if not req.jobs:
        raise HTTPException(400, "En az 1 teslimat noktası gerekli")

    # Build unified location list: depots first, then jobs
    locations = []
    for d in req.depots:
        loc = {"id": d.id, "lat": d.lat, "lon": d.lon, "_matrix_idx": len(locations)}
        locations.append(loc)

    depot_dicts = [locations[i] for i in range(len(req.depots))]

    job_dicts = []
    for j in req.jobs:
        loc = {
            "id": j.id, "lat": j.lat, "lon": j.lon,
            "demand": j.demand,
            "time_start": j.time_start, "time_end": j.time_end,
            "_matrix_idx": len(locations),
        }
        locations.append(loc)
        job_dicts.append(loc)

    # Distance matrices
    t0 = time.time()
    try:
        dist_matrix, dur_matrix = get_matrices(locations)
    except Exception as e:
        raise HTTPException(500, f"Distance matrix error: {e}")
    matrix_time = round(time.time() - t0, 1)
    log.info(f"Matrix computed in {matrix_time}s for {len(locations)} locations")

    # Multi-depot: assign customers to depots
    if len(depot_dicts) == 1:
        groups = {depot_dicts[0]["id"]: job_dicts}
    else:
        groups = assign_to_depots(depot_dicts, job_dicts, dist_matrix)

    # Solve per depot
    all_routes = []
    total_solve_time = 0
    for depot in depot_dicts:
        customers = groups.get(depot["id"], [])
        if not customers:
            continue
        t1 = time.time()
        routes = solve_single_depot(depot, customers, dist_matrix, dur_matrix, req)
        total_solve_time += time.time() - t1
        all_routes.extend(routes)

    if not all_routes:
        raise HTTPException(400, "Rota bulunamadı — araç sayısını veya kapasiteyi artır")

    # Renumber vehicles globally
    for i, r in enumerate(all_routes):
        r["vehicle_id"] = i + 1

    total_km = round(sum(r["total_km"] for r in all_routes), 1)
    total_load = sum(r["total_load"] for r in all_routes)

    solver_info = {
        "version": "3.0.0",
        "solver": "OR-Tools v3",
        "matrix_time": matrix_time,
        "solve_time": round(total_solve_time, 1),
        "total_time": round(time.time() - t0, 1),
        "depots": len(depot_dicts),
        "customers": len(job_dicts),
        "active_vehicles": len(all_routes),
        "optimization_goal": req.optimization_goal,
    }

    return {
        "status": "success",
        "routes": all_routes,
        "solver_info": solver_info,
        "summary": {
            "total_km": total_km,
            "total_load": total_load,
            "active_vehicles": len(all_routes),
        },
    }

# ─────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": "3.0.0",
        "features": [
            "multi_depot",
            "open_closed_routes",
            "capacity_constraints",
            "time_windows",
            "4_optimization_goals",
            "all_local_search_operators",
        ],
    }
