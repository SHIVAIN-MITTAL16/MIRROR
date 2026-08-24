from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence
from bisect import bisect_right
from math import ceil, isfinite, log
from functools import lru_cache
from hashlib import sha256
from types import MappingProxyType
from collections import Counter
import json
import base64
import hmac
import hashlib
import os
import random
from time import perf_counter
from decimal import Decimal, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


APP = FastAPI()

SKU_COLUMNS = [
	"sku_id", "price_tier", "margin_profile", "list_price", "current_price",
	"discount_pct", "cost_ratio", "unit_cost", "margin_floor", "minimum_price",
	"current_margin",
]
PRODUCT_COLUMNS = ["brand", "ram_gb", "storage_gb"]
MERCHANT_STATE_COLUMNS = [
	"sku_id", "heterogeneity_multiplier", "mu", "nb_k", "incoming_exists",
	"incoming_quantity", "incoming_eta_days", "on_hand", "reserved",
]
BUYER_QUANTITY_LOG_SIGMA = 0.65
BUYER_BUDGET_LOG_LOCATION = log(0.92)
BUYER_BUDGET_LOG_SIGMA = 0.10
BUYER_DEADLINE_VALUES = (2, 3, 5, 7, 10)
BUYER_DEADLINE_PROBABILITIES = (0.10, 0.20, 0.35, 0.25, 0.10)
EXPERIMENT_SEED = 20260821
TARGET_SEED = EXPERIMENT_SEED + 1
PRICE_SEED = EXPERIMENT_SEED + 2
QUANTITY_SEED = EXPERIMENT_SEED + 3
TIMING_SEED = EXPERIMENT_SEED + 4
SUBSTITUTION_SEED = EXPERIMENT_SEED + 5
BUYER_QUANTITY_SEED = EXPERIMENT_SEED + 6
BUYER_BUDGET_SEED = EXPERIMENT_SEED + 7
BUYER_DEADLINE_SEED = EXPERIMENT_SEED + 8
CDF_BASE_SEED = 20260901
CDF_WINDOW_DAYS = (2, 3, 5, 7, 10)
CDF_SAMPLE_SIZE = 10_000
FLEXIBILITY_PROBABILITIES = (0.50, 0.35, 0.15)
PRICE_FLEXIBILITY_CHOICES = (("Low", 0.02), ("Medium", 0.05), ("High", 0.10))
QUANTITY_FLEXIBILITY_CHOICES = (("Low", 0.10), ("Medium", 0.25), ("High", 0.50))
TIMING_FLEXIBILITY_CHOICES = (("Low", 0), ("Medium", 2), ("High", 3))
SUBSTITUTION_TOLERANCE_VALUES = (0, 1)
SUBSTITUTION_TOLERANCE_PROBABILITIES = (0.60, 0.40)
DECISION_MONTE_CARLO_PATHS = 10_000
ACTION_PRIORITY = {"PRICE": 0, "QUANTITY": 1, "TIMING": 2, "SUBSTITUTION": 3, "BASELINE": 4}


def get_data_path() -> Path:
	# The locked demand/inventory dataset is the source of truth for this slice.
	root = Path(__file__).resolve().parents[1]
	return root / "data" / "mirror_sku_demand_inventory_v1.csv"


def load_and_validate(csv_path: Path) -> pd.DataFrame:
	df = pd.read_csv(csv_path)

	expected_rows = 50
	required_columns = set(SKU_COLUMNS + PRODUCT_COLUMNS + MERCHANT_STATE_COLUMNS)

	if len(df) != expected_rows:
		raise RuntimeError(f"CSV must contain exactly {expected_rows} rows (found {len(df)})")

	missing = required_columns - set(df.columns)
	if missing:
		raise RuntimeError(f"Missing required columns: {sorted(missing)}")

	if df["sku_id"].duplicated().any():
		raise RuntimeError("Duplicate sku_id values found in CSV")

	# An ETA is intentionally blank when there is no incoming shipment.
	non_nullable_columns = required_columns - {"incoming_eta_days"}
	if df[list(non_nullable_columns)].isnull().any().any():
		raise RuntimeError("Missing values found in required locked data fields")

	# unit_cost < current_price for every SKU
	if not (df["unit_cost"] < df["current_price"]).all():
		raise RuntimeError("Validation failed: unit_cost must be less than current_price for every SKU")

	# minimum_price <= current_price for every SKU
	if not (df["minimum_price"] <= df["current_price"]).all():
		raise RuntimeError("Validation failed: minimum_price must be <= current_price for every SKU")

	if not (df["mu"] > 0).all():
		raise RuntimeError("Validation failed: mu must be positive for every SKU")

	if not (df["reserved"] <= df["on_hand"]).all():
		raise RuntimeError("Validation failed: reserved must be <= on_hand for every SKU")

	incoming = df["incoming_exists"]
	if not df.loc[incoming, "incoming_eta_days"].between(2, 10).all():
		raise RuntimeError("Validation failed: incoming shipment ETA must be between 2 and 10 days")

	if not (df.loc[~incoming, "incoming_quantity"] == 0).all():
		raise RuntimeError("Validation failed: absent shipments must have zero incoming quantity")

	return df


@lru_cache(maxsize=1)
def load_locked_data() -> Dict:
	"""Load and cache the locked catalog and merchant-state records."""
	csv_path = get_data_path()
	if not csv_path.exists():
		raise RuntimeError(f"SKU CSV not found at {csv_path}")

	df = load_and_validate(csv_path)
	locked_records = jsonable_encoder(
		df.astype(object).where(pd.notna(df), None).to_dict(orient="records")
	)
	skus = [
		{column: record[column] for column in SKU_COLUMNS}
		for record in locked_records
	]
	merchant_states = [
		{column: record[column] for column in MERCHANT_STATE_COLUMNS}
		for record in locked_records
	]
	catalog_skus = [
		{column: record[column] for column in SKU_COLUMNS + PRODUCT_COLUMNS}
		for record in locked_records
	]
	return {
		"skus": skus,
		"merchant_states": merchant_states,
		"merchant_states_by_sku": {
			state["sku_id"]: state for state in merchant_states
		},
		"catalog_skus": catalog_skus,
		"catalog_skus_by_sku": {sku["sku_id"]: sku for sku in catalog_skus},
	}


def simulate_demand_window(
	mu: float,
	nb_k: int,
	days: int,
	rng: np.random.Generator,
) -> Dict:
	"""Simulate independent Distribution #2 daily demand for one window."""
	if mu <= 0:
		raise ValueError("mu must be positive")
	if days < 0:
		raise ValueError("days must be non-negative")
	n = int(nb_k)
	if n <= 0 or n != nb_k:
		raise ValueError("nb_k must be a positive integer")
	p = n / (n + mu)
	daily_demand = [int(draw) for draw in rng.negative_binomial(n=n, p=p, size=days)]
	return {
		"daily_demand": daily_demand,
		"cumulative_demand": sum(daily_demand),
	}


@lru_cache(maxsize=1)
def build_demand_cdf_cache() -> MappingProxyType:
	"""Build immutable empirical cumulative-demand CDFs for all locked SKUs."""
	merchant_states = load_locked_data()["merchant_states"]
	cache = {}
	for sku_index, state in enumerate(merchant_states):
		for window_index, window_days in enumerate(CDF_WINDOW_DAYS):
			seed = CDF_BASE_SEED + sku_index * 100 + window_index
			rng = np.random.default_rng(seed)
			samples = sorted(
				simulate_demand_window(
					state["mu"], state["nb_k"], window_days, rng
				)["cumulative_demand"]
				for _ in range(CDF_SAMPLE_SIZE)
			)
			cache[(state["sku_id"], window_days)] = tuple(samples)
	return MappingProxyType(cache)


def get_demand_cdf(sku_id: str, window_days: int) -> tuple[int, ...]:
	"""Return the fixed empirical cumulative-demand samples for a SKU/window."""
	try:
		return build_demand_cdf_cache()[(sku_id, window_days)]
	except KeyError as error:
		raise ValueError("Unknown SKU or unsupported delivery window") from error


def demand_percentile(sku_id: str, window_days: int, cumulative_demand: int) -> float:
	"""Return the empirical fraction of cached samples less than or equal to demand."""
	samples = get_demand_cdf(sku_id, window_days)
	return bisect_right(samples, cumulative_demand) / len(samples)


def sla_miss_probability(demand_percentile: float) -> float:
	"""Apply the locked SLA-miss formula after clamping a finite percentile to [0, 1]."""
	if not isfinite(demand_percentile):
		raise ValueError("demand_percentile must be finite")
	percentile = min(1.0, max(0.0, demand_percentile))
	return min(0.14, 0.05 + 0.30 * max(0.0, percentile - 0.70))


def get_return_probability(sla_missed: bool) -> float:
	"""Return the locked probability conditional on the actual SLA outcome."""
	return 0.15 if sla_missed else 0.06


def calculate_return_loss(
	returned_units: int,
	candidate_price: float,
	unit_cost: float,
) -> float:
	"""Calculate the locked 30% unrecovered candidate contribution loss."""
	return returned_units * (candidate_price - unit_cost) * 0.30


def simulate_returns(
	fulfilled_units: int,
	sla_missed: bool,
	candidate_price: float,
	unit_cost: float,
	rng: np.random.Generator,
) -> Dict:
	"""Sample returned units after SLA resolution and calculate candidate-price loss."""
	if fulfilled_units < 0:
		raise ValueError("fulfilled_units must be non-negative")
	returned_units = int(rng.binomial(fulfilled_units, get_return_probability(sla_missed)))
	return {
		"returned_units": returned_units,
		"return_loss": calculate_return_loss(returned_units, candidate_price, unit_cost),
	}


def evaluate_candidate_monte_carlo(
	sku_id: str,
	delivery_window_days: int,
	requested_quantity: int,
	candidate_price: float,
	paths: int,
	seed: int,
	include_path_results: bool = True,
) -> Dict:
	"""Evaluate one fixed candidate across independent demand and return paths.

	``include_path_results=False`` preserves every stochastic draw and aggregate,
	but avoids allocating path dictionaries when only aggregate metrics and P05
	are needed by the decision engine.
	"""
	if delivery_window_days < 0:
		raise ValueError("delivery_window_days must be non-negative")
	if requested_quantity < 0:
		raise ValueError("requested_quantity must be non-negative")
	if paths <= 0:
		raise ValueError("paths must be positive")

	locked_data = load_locked_data()
	try:
		state = locked_data["merchant_states_by_sku"][sku_id]
		sku = locked_data["catalog_skus_by_sku"][sku_id]
	except KeyError as error:
		raise ValueError("Unknown SKU") from error

	demand_rng = np.random.default_rng(seed + 1)
	return_rng = np.random.default_rng(seed + 2)
	incoming_available = (
		state["incoming_quantity"]
		if state["incoming_exists"] and state["incoming_eta_days"] <= delivery_window_days
		else 0
	)
	contribution_per_unit = candidate_price - sku["unit_cost"]
	path_results = [] if include_path_results else None
	net_contributions = []
	sla_miss_count = 0
	return_path_count = 0
	fulfilled_total = 0
	returned_total = 0
	gross_total = 0.0
	return_loss_total = 0.0
	net_total = 0.0

	for path_id in range(1, paths + 1):
		demand = simulate_demand_window(
			state["mu"], state["nb_k"], delivery_window_days, demand_rng
		)
		simulated_available = (
			state["on_hand"]
			- state["reserved"]
			+ incoming_available
			- demand["cumulative_demand"]
		)
		fulfilled_units = min(requested_quantity, max(0, simulated_available))
		sla_missed = fulfilled_units < requested_quantity
		returns = simulate_returns(
			fulfilled_units,
			sla_missed,
			candidate_price,
			sku["unit_cost"],
			return_rng,
		)
		gross_contribution = fulfilled_units * contribution_per_unit
		net_contribution = gross_contribution - returns["return_loss"]
		sla_miss_count += sla_missed
		return_path_count += returns["returned_units"] > 0
		fulfilled_total += fulfilled_units
		returned_total += returns["returned_units"]
		gross_total += gross_contribution
		return_loss_total += returns["return_loss"]
		net_total += net_contribution
		net_contributions.append(net_contribution)
		if include_path_results:
			path_results.append({
				"path_id": path_id,
				"daily_demand": demand["daily_demand"],
				"cumulative_demand": demand["cumulative_demand"],
				"simulated_available": simulated_available,
				"fulfilled_units": fulfilled_units,
				"sla_missed": sla_missed,
				"returned_units": returns["returned_units"],
				"return_loss": returns["return_loss"],
				"gross_contribution": gross_contribution,
				"net_contribution": net_contribution,
			})

	return {
		"sku_id": sku_id,
		"delivery_window_days": delivery_window_days,
		"requested_quantity": requested_quantity,
		"candidate_price": candidate_price,
		"paths": paths,
		"sla_success_probability": (paths - sla_miss_count) / paths,
		"sla_miss_probability": sla_miss_count / paths,
		"return_probability": return_path_count / paths,
		"expected_fulfilled_units": fulfilled_total / paths,
		"expected_returned_units": returned_total / paths,
		"expected_gross_contribution": gross_total / paths,
		"expected_return_loss": return_loss_total / paths,
		"expected_net_contribution": net_total / paths,
		"path_results": path_results,
		"net_contributions": net_contributions,
	}


def buyer_total_ceiling(request: Dict) -> float:
	return request["budget"] * (1 + request["price_tolerance_pct"])


def build_price_grid(lower_bound: float, upper_bound: float) -> List[float]:
	if upper_bound < lower_bound:
		return []
	if upper_bound == lower_bound:
		return [lower_bound]
	return [lower_bound + (upper_bound - lower_bound) * index / 4 for index in range(5)]


def build_baseline_reference(request: Dict) -> Dict:
	"""Build the status-quo reference; it is explicitly ceiling-exempt."""
	sku = load_locked_data()["catalog_skus_by_sku"][request["target_sku_id"]]
	return {
		"sku_id": request["target_sku_id"], "quantity": request["requested_quantity"],
		"delivery_window_days": request["deadline_days"], "candidate_price": sku["current_price"],
		"action_type": "BASELINE",
	}


def build_decision_candidates(request: Dict) -> List[Dict]:
	"""Build ceiling-constrained single-lever MIRROR alternatives only."""
	data = load_locked_data()
	catalog, states = data["catalog_skus_by_sku"], data["merchant_states_by_sku"]
	target_id, quantity, deadline = request["target_sku_id"], request["requested_quantity"], request["deadline_days"]
	ceiling, target = buyer_total_ceiling(request), catalog[target_id]
	candidates = []
	def add(sku_id, candidate_quantity, window, price, action):
		sku = catalog[sku_id]
		if (candidate_quantity > 0 and candidate_quantity <= available_for_window(states[sku_id], window)["available"]
			and price >= sku["minimum_price"] and price * candidate_quantity <= ceiling):
			candidates.append({"sku_id": sku_id, "quantity": candidate_quantity,
				"delivery_window_days": window, "candidate_price": price, "action_type": action})
	for price in build_price_grid(target["minimum_price"], min(target["current_price"], ceiling / quantity)):
		add(target_id, quantity, deadline, price, "PRICE")
	q_alt = max(1, ceil(quantity * (1 - request["quantity_tolerance_pct"])))
	add(target_id, q_alt, deadline, target["current_price"], "QUANTITY")
	add(target_id, quantity, deadline + request["timing_tolerance_days"], target["current_price"], "TIMING")
	for sku_id in request["eligible_substitute_skus"]:
		sku, substitute_quantity = catalog[sku_id], min(quantity, max(0, available_for_window(states[sku_id], deadline)["available"]))
		if substitute_quantity:
			for price in build_price_grid(sku["minimum_price"], min(sku["current_price"], ceiling / substitute_quantity)):
				add(sku_id, substitute_quantity, deadline, price, "SUBSTITUTION")
	return candidates


def candidate_scenario_seed(experiment_seed: int, request: Dict, candidate: Dict) -> int:
	"""Stable SKU/window scenario identity provides common random numbers where applicable."""
	text = f"{experiment_seed}|{request['experiment_seed']}|{request['request_id']}|{candidate['sku_id']}|{candidate['delivery_window_days']}"
	return int.from_bytes(sha256(text.encode()).digest()[:8], "big")


def empirical_p05(net_contributions: Sequence[float]) -> float:
	"""Return the locked nearest-rank empirical P05 from path net values."""
	values = sorted(net_contributions)
	return values[ceil(len(values) * .05) - 1]


def candidate_passes_risk_gate(candidate_p05: float, reference_p05: float) -> bool:
	return candidate_p05 >= reference_p05 - .10 * abs(reference_p05)


def score_candidate(expected_net: float, candidate_p05: float, reference_p05: float) -> float:
	return expected_net - max(0, reference_p05 - candidate_p05)


def select_best_candidate(candidates: List[Dict]) -> Dict:
	return min(candidates, key=lambda c: (-c["score"], ACTION_PRIORITY[c["action_type"]]))


def decision_from_scores(best_score: float, reference_score: float, baseline_feasible: bool) -> str:
	if best_score > reference_score + .05 * abs(reference_score):
		return "NEGOTIATE"
	return "ACCEPT" if baseline_feasible else "REJECT"


def evaluate_decision_candidate(candidate: Dict, request: Dict, experiment_seed: int) -> Dict:
	scenario_seed = candidate_scenario_seed(experiment_seed, request, candidate)
	evaluation = evaluate_candidate_monte_carlo(
		candidate["sku_id"], candidate["delivery_window_days"], candidate["quantity"], candidate["candidate_price"],
		DECISION_MONTE_CARLO_PATHS, scenario_seed, include_path_results=False,
	)
	return {
		**candidate,
		**{key: value for key, value in evaluation.items()
		   if key not in {"path_results", "net_contributions"}},
		"scenario_seed": scenario_seed,
		"p05_net_contribution": empirical_p05(evaluation["net_contributions"]),
	}


def evaluate_request_decision(request: Dict, experiment_seed: int) -> Dict:
	"""Evaluate a frozen request without changing it after observing outcomes."""
	if request["classification"] == "HARD_REJECT":
		return {"decision": "REJECT", "reference_type": "NO_DEAL", "reference_score": 0, "reference_p05": 0,
			"risk_threshold": 0, "candidates": [], "risk_gate_rejections": 0}
	if request["baseline_feasible"]:
		reference = evaluate_decision_candidate(build_baseline_reference(request), request, experiment_seed)
		reference_type = "BASELINE"
	else:
		reference, reference_type = {"expected_net_contribution": 0, "p05_net_contribution": 0, "score": 0}, "NO_DEAL"
	reference_p05 = reference["p05_net_contribution"]
	reference_score = reference["expected_net_contribution"] if reference_type == "BASELINE" else 0
	evaluated = [evaluate_decision_candidate(c, request, experiment_seed) for c in build_decision_candidates(request)]
	for candidate in evaluated:
		candidate["passes_risk_gate"] = candidate_passes_risk_gate(candidate["p05_net_contribution"], reference_p05)
		if candidate["passes_risk_gate"]:
			candidate["score"] = score_candidate(candidate["expected_net_contribution"], candidate["p05_net_contribution"], reference_p05)
	survivors = [candidate for candidate in evaluated if candidate["passes_risk_gate"]]
	best = select_best_candidate(survivors) if survivors else None
	best_score = best["score"] if best else 0
	return {"decision": decision_from_scores(best_score, reference_score, request["baseline_feasible"]),
		"reference_type": reference_type, "reference_score": reference_score, "reference_p05": reference_p05,
		"risk_threshold": reference_p05 - .10 * abs(reference_p05), "best_candidate": best,
		"reference": reference, "candidates": evaluated, "risk_gate_rejections": len(evaluated) - len(survivors)}


def get_buyer_request_data_path() -> Path:
	return Path(__file__).resolve().parents[1] / "data" / "mirror_buyer_requests_5seeds_v1.csv"


@lru_cache(maxsize=1)
def load_buyer_request_population_data() -> tuple[MappingProxyType, ...]:
	"""Load the frozen 500-request population once for decision evaluation."""
	csv_path = get_buyer_request_data_path()
	if not csv_path.exists():
		raise RuntimeError(f"Buyer request CSV not found at {csv_path}")
	requests = []
	for record in pd.read_csv(csv_path).to_dict(orient="records"):
		record["eligible_substitute_skus"] = tuple(json.loads(record["eligible_substitute_skus"]))
		record["baseline_feasible"] = bool(record["baseline_feasible"])
		requests.append(MappingProxyType(record))
	if len(requests) != 500:
		raise RuntimeError(f"Buyer request CSV must contain exactly 500 rows (found {len(requests)})")
	return tuple(requests)


def selected_transaction_metrics(result: Dict) -> Optional[Dict]:
	"""Return the transaction selected by the frozen final decision rule."""
	if result["decision"] == "NEGOTIATE":
		return result["best_candidate"]
	if result["decision"] == "ACCEPT":
		return result["reference"]
	return None


def evaluate_decision_seed(
	experiment_seed: int,
	request_order: Optional[Sequence[int]] = None,
	progress_callback: Optional[Callable[[int, int, int], None]] = None,
	progress_every: int = 25,
) -> Dict:
	"""Incrementally evaluate one frozen 100-request experiment seed.

	Only compact per-candidate aggregates are retained; 10,000 path objects are
	never accumulated across requests. ``request_order`` is test-only support for
	verifying order independence and has no effect on scenario seeds.
	"""
	requests = [
		dict(request) for request in load_buyer_request_population_data()
		if request["experiment_seed"] == experiment_seed
	]
	if len(requests) != 100:
		raise ValueError(f"Expected 100 requests for seed {experiment_seed}, found {len(requests)}")
	if request_order is not None:
		by_id = {request["request_id"]: request for request in requests}
		if set(request_order) != set(by_id) or len(request_order) != len(by_id):
			raise ValueError("request_order must contain each request_id exactly once")
		requests = [by_id[request_id] for request_id in request_order]

	started = perf_counter()
	class_counts = Counter()
	decision_counts = Counter()
	selected_totals = Counter()
	candidate_count = 0
	baseline_evaluation_count = 0
	risk_gate_rejections = 0
	constraint_conflict_count = 0
	constraint_conflict_negotiated = 0
	improvement_total = 0.0
	results_by_request_id = {}

	for completed, request in enumerate(requests, start=1):
		result = evaluate_request_decision(request, experiment_seed)
		results_by_request_id[request["request_id"]] = result
		class_counts[request["classification"]] += 1
		decision_counts[result["decision"]] += 1
		candidate_count += len(result["candidates"])
		baseline_evaluation_count += result["reference_type"] == "BASELINE"
		risk_gate_rejections += result["risk_gate_rejections"]
		if request["classification"] == "CONSTRAINT_CONFLICT":
			constraint_conflict_count += 1
			constraint_conflict_negotiated += result["decision"] == "NEGOTIATE"
		selected = selected_transaction_metrics(result)
		if selected is not None:
			for metric in (
				"expected_net_contribution", "p05_net_contribution",
				"expected_gross_contribution", "expected_return_loss",
				"sla_success_probability", "sla_miss_probability",
				"return_probability", "expected_returned_units",
			):
				selected_totals[metric] += selected[metric]
			improvement_total += selected["expected_net_contribution"] - result["reference"]["expected_net_contribution"]
		if progress_callback and (completed % progress_every == 0 or completed == len(requests)):
			progress_callback(experiment_seed, completed, len(requests))

	total_requests = len(requests)
	selected_count = sum(decision_counts[decision] for decision in ("ACCEPT", "NEGOTIATE"))
	return {
		"experiment_seed": experiment_seed,
		"requests": total_requests,
		"runtime_seconds": perf_counter() - started,
		"class_counts": dict(class_counts),
		"decision_counts": dict(decision_counts),
		"candidate_count": candidate_count,
		"baseline_evaluation_count": baseline_evaluation_count,
		"candidate_evaluation_count": candidate_count + baseline_evaluation_count,
		"risk_gate_rejections": risk_gate_rejections,
		"selected_transaction_count": selected_count,
		"average_selected_expected_net_contribution": (
			selected_totals["expected_net_contribution"] / selected_count if selected_count else 0
		),
		"average_selected_p05_net_contribution": (
			selected_totals["p05_net_contribution"] / selected_count if selected_count else 0
		),
		"average_selected_expected_gross_contribution": (
			selected_totals["expected_gross_contribution"] / selected_count if selected_count else 0
		),
		"average_selected_expected_return_loss": (
			selected_totals["expected_return_loss"] / selected_count if selected_count else 0
		),
		"average_selected_sla_success_probability": (
			selected_totals["sla_success_probability"] / selected_count if selected_count else 0
		),
		"average_selected_sla_miss_probability": (
			selected_totals["sla_miss_probability"] / selected_count if selected_count else 0
		),
		"average_selected_return_probability": (
			selected_totals["return_probability"] / selected_count if selected_count else 0
		),
		"average_selected_expected_returned_units": (
			selected_totals["expected_returned_units"] / selected_count if selected_count else 0
		),
		"constraint_conflict_rescue_rate": (
			constraint_conflict_negotiated / constraint_conflict_count if constraint_conflict_count else 0
		),
		"average_selected_vs_reference_expected_net_improvement": improvement_total / total_requests,
		"hard_reject_rate": class_counts["HARD_REJECT"] / total_requests,
		"results_by_request_id": results_by_request_id,
	}


def evaluate_all_decision_seeds(
	seeds: Sequence[int] = (20260821, 20260822, 20260823, 20260824, 20260825),
	progress_callback: Optional[Callable[[int, int, int], None]] = None,
	progress_every: int = 25,
) -> Dict[int, Dict]:
	"""Evaluate every requested frozen experiment seed independently."""
	return {
		seed: evaluate_decision_seed(seed, progress_callback=progress_callback, progress_every=progress_every)
		for seed in seeds
	}


def generate_buyer_request_quantity(mu: float, rng: random.Random) -> Dict:
	"""Generate Distribution #6 quantity from the locked SKU demand mean."""
	q_raw = rng.lognormvariate(log(3 * mu), BUYER_QUANTITY_LOG_SIGMA)
	quantity_cap = max(20, ceil(8 * mu))
	requested_quantity = min(max(round(q_raw), 1), quantity_cap)
	return {
		"q_raw": q_raw,
		"requested_quantity": requested_quantity,
		"quantity_cap": quantity_cap,
	}


def generate_buyer_budget(
	requested_quantity: int,
	current_price: float,
	rng: random.Random,
) -> Dict:
	"""Generate Distribution #7 buyer willingness-to-pay budget."""
	budget_factor = rng.lognormvariate(
		BUYER_BUDGET_LOG_LOCATION,
		BUYER_BUDGET_LOG_SIGMA,
	)
	budget = requested_quantity * current_price * budget_factor
	return {
		"budget_factor": budget_factor,
		"budget": budget,
	}


def generate_buyer_deadline(rng: random.Random) -> int:
	"""Generate Distribution #8 buyer fulfillment deadline in days."""
	return rng.choices(
		BUYER_DEADLINE_VALUES,
		weights=BUYER_DEADLINE_PROBABILITIES,
		k=1,
	)[0]


def generate_buyer_flexibility(
	price_rng: random.Random,
	quantity_rng: random.Random,
	timing_rng: random.Random,
	substitution_rng: random.Random,
) -> Dict:
	"""Generate the four independent locked Distribution #9A dimensions."""
	price_flexibility, price_tolerance_pct = price_rng.choices(
		PRICE_FLEXIBILITY_CHOICES,
		weights=FLEXIBILITY_PROBABILITIES,
		k=1,
	)[0]
	quantity_flexibility, quantity_tolerance_pct = quantity_rng.choices(
		QUANTITY_FLEXIBILITY_CHOICES,
		weights=FLEXIBILITY_PROBABILITIES,
		k=1,
	)[0]
	timing_flexibility, timing_tolerance_days = timing_rng.choices(
		TIMING_FLEXIBILITY_CHOICES,
		weights=FLEXIBILITY_PROBABILITIES,
		k=1,
	)[0]
	substitution_tolerance = substitution_rng.choices(
		SUBSTITUTION_TOLERANCE_VALUES,
		weights=SUBSTITUTION_TOLERANCE_PROBABILITIES,
		k=1,
	)[0]
	return {
		"price_flexibility": price_flexibility,
		"price_tolerance_pct": price_tolerance_pct,
		"quantity_flexibility": quantity_flexibility,
		"quantity_tolerance_pct": quantity_tolerance_pct,
		"timing_flexibility": timing_flexibility,
		"timing_tolerance_days": timing_tolerance_days,
		"substitution_tolerance": substitution_tolerance,
	}


def select_target_sku(catalog_skus: List[Dict], rng: random.Random) -> Dict:
	"""Uniformly select one locked SKU without consulting economic fields."""
	return rng.choice(catalog_skus)


def eligible_substitute_skus(
	catalog_skus: List[Dict],
	target_sku_id: str,
	brand_preference: str,
	min_ram_gb: int,
	min_storage_gb: int,
	substitution_tolerance: int,
) -> List[str]:
	"""Match substitutes using only the locked brand and technical requirements."""
	if substitution_tolerance == 0:
		return []
	return [
		sku["sku_id"]
		for sku in catalog_skus
		if sku["sku_id"] != target_sku_id
		and sku["brand"] == brand_preference
		and sku["ram_gb"] >= min_ram_gb
		and sku["storage_gb"] >= min_storage_gb
	]


def available_for_window(state: Dict, days: int) -> Dict:
	"""Deterministic availability details shared by endpoint and classifier."""
	incoming = (
		state["incoming_quantity"]
		if state["incoming_exists"] and state["incoming_eta_days"] <= days
		else 0
	)
	expected_demand = ceil(state["mu"] * days)
	return {
		"incoming_available": incoming,
		"expected_demand_for_feasibility": expected_demand,
		"available": state["on_hand"] - state["reserved"] + incoming - expected_demand,
	}


def classify_buyer_request(
	target_sku: Dict,
	target_state: Dict,
	requested_quantity: int,
	deadline_days: int,
	flexibility: Dict,
	substitutes: List[str],
	states_by_sku: Dict[str, Dict],
) -> Dict:
	"""Pure Distribution #9 classifier; it never calls an optimizer."""
	available_at_deadline = available_for_window(target_state, deadline_days)["available"]
	baseline_feasible = requested_quantity <= available_at_deadline

	price_opportunity = (
		baseline_feasible
		and flexibility["price_tolerance_pct"] > 0
		and target_sku["current_margin"] >= 0.16
	)
	quantity_alternative = max(
		1,
		ceil(requested_quantity * (1 - flexibility["quantity_tolerance_pct"])),
	)
	quantity_conflict = (
		not baseline_feasible
		and flexibility["quantity_tolerance_pct"] > 0
		and quantity_alternative <= available_at_deadline
	)
	timing_deadline = deadline_days + flexibility["timing_tolerance_days"]
	timing_conflict = (
		not baseline_feasible
		and flexibility["timing_tolerance_days"] > 0
		and requested_quantity <= available_for_window(target_state, timing_deadline)["available"]
	)
	substitution_opportunity = (
		baseline_feasible
		and flexibility["substitution_tolerance"] == 1
		and len(substitutes) > 0
	)
	substitution_conflict = (
		not baseline_feasible
		and flexibility["substitution_tolerance"] == 1
		and any(
			requested_quantity <= available_for_window(states_by_sku[sku_id], deadline_days)["available"]
			for sku_id in substitutes
		)
	)

	if baseline_feasible:
		classification = (
			"OPPORTUNITY"
			if price_opportunity or substitution_opportunity
			else "BASELINE_ACCEPT"
		)
	else:
		classification = (
			"CONSTRAINT_CONFLICT"
			if quantity_conflict or timing_conflict or substitution_conflict
			else "HARD_REJECT"
		)
	return {
		"baseline_feasible": baseline_feasible,
		"classification": classification,
	}


def build_buyer_request(sku_id: str) -> Dict:
	"""Combine locked Distributions #6-#9 for one selected target SKU."""
	target_sku = APP.state.catalog_skus_by_sku[sku_id]
	target_state = APP.state.merchant_states_by_sku[sku_id]
	quantity = generate_buyer_request_quantity(
		target_state["mu"],
		APP.state.buyer_quantity_rng,
	)
	budget = generate_buyer_budget(
		quantity["requested_quantity"],
		target_sku["current_price"],
		APP.state.buyer_budget_rng,
	)
	deadline_days = generate_buyer_deadline(APP.state.buyer_deadline_rng)
	flexibility = generate_buyer_flexibility(
		APP.state.buyer_price_rng,
		APP.state.buyer_quantity_flexibility_rng,
		APP.state.buyer_timing_rng,
		APP.state.buyer_substitution_rng,
	)
	brand_preference = target_sku["brand"]
	min_ram_gb = target_sku["ram_gb"]
	min_storage_gb = target_sku["storage_gb"]
	substitutes = eligible_substitute_skus(
		APP.state.catalog_skus,
		sku_id,
		brand_preference,
		min_ram_gb,
		min_storage_gb,
		flexibility["substitution_tolerance"],
	)
	classification = classify_buyer_request(
		target_sku,
		target_state,
		quantity["requested_quantity"],
		deadline_days,
		flexibility,
		substitutes,
		APP.state.merchant_states_by_sku,
	)
	return {
		"sku_id": sku_id,
		"target_sku_id": sku_id,
		"mu": target_state["mu"],
		**quantity,
		"current_price": target_sku["current_price"],
		**budget,
		"deadline_days": deadline_days,
		"brand_preference": brand_preference,
		"min_ram_gb": min_ram_gb,
		"min_storage_gb": min_storage_gb,
		"eligible_substitute_skus": substitutes,
		**flexibility,
		**classification,
	}


def create_buyer_rng_streams(experiment_seed: int = EXPERIMENT_SEED) -> Dict[str, random.Random]:
	"""Create independent, reproducible streams for buyer request generation."""
	return {
		"buyer_target_rng": random.Random(experiment_seed + TARGET_SEED - EXPERIMENT_SEED),
		"buyer_price_rng": random.Random(experiment_seed + PRICE_SEED - EXPERIMENT_SEED),
		"buyer_quantity_flexibility_rng": random.Random(
			experiment_seed + QUANTITY_SEED - EXPERIMENT_SEED
		),
		"buyer_timing_rng": random.Random(experiment_seed + TIMING_SEED - EXPERIMENT_SEED),
		"buyer_substitution_rng": random.Random(
			experiment_seed + SUBSTITUTION_SEED - EXPERIMENT_SEED
		),
		"buyer_quantity_rng": random.Random(experiment_seed + BUYER_QUANTITY_SEED - EXPERIMENT_SEED),
		"buyer_budget_rng": random.Random(experiment_seed + BUYER_BUDGET_SEED - EXPERIMENT_SEED),
		"buyer_deadline_rng": random.Random(experiment_seed + BUYER_DEADLINE_SEED - EXPERIMENT_SEED),
	}


def assemble_population_request(
	experiment_seed: int,
	request_id: int,
	streams: Dict[str, random.Random],
	states_by_sku: Dict[str, Dict],
	catalog_skus: List[Dict],
) -> Dict:
	"""Assemble one immutable request from the locked Distributions #1-#9."""
	target_sku = select_target_sku(catalog_skus, streams["buyer_target_rng"])
	target_sku_id = target_sku["sku_id"]
	target_state = states_by_sku[target_sku_id]
	brand_preference = target_sku["brand"]
	min_ram_gb = target_sku["ram_gb"]
	min_storage_gb = target_sku["storage_gb"]

	deadline_days = generate_buyer_deadline(streams["buyer_deadline_rng"])
	quantity = generate_buyer_request_quantity(target_state["mu"], streams["buyer_quantity_rng"])
	budget = generate_buyer_budget(
		quantity["requested_quantity"],
		target_sku["current_price"],
		streams["buyer_budget_rng"],
	)
	flexibility = generate_buyer_flexibility(
		streams["buyer_price_rng"],
		streams["buyer_quantity_flexibility_rng"],
		streams["buyer_timing_rng"],
		streams["buyer_substitution_rng"],
	)
	substitutes = eligible_substitute_skus(
		catalog_skus,
		target_sku_id,
		brand_preference,
		min_ram_gb,
		min_storage_gb,
		flexibility["substitution_tolerance"],
	)
	availability = available_for_window(target_state, deadline_days)
	classification = classify_buyer_request(
		target_sku,
		target_state,
		quantity["requested_quantity"],
		deadline_days,
		flexibility,
		substitutes,
		states_by_sku,
	)
	return {
		"experiment_seed": experiment_seed,
		"request_id": request_id,
		"target_sku_id": target_sku_id,
		"brand_preference": brand_preference,
		"min_ram_gb": min_ram_gb,
		"min_storage_gb": min_storage_gb,
		"eligible_substitute_skus": substitutes,
		"substitution_tolerance": flexibility["substitution_tolerance"],
		"requested_quantity": quantity["requested_quantity"],
		"q_raw": quantity["q_raw"],
		"quantity_cap": quantity["quantity_cap"],
		"current_price": target_sku["current_price"],
		"budget_factor": budget["budget_factor"],
		"budget": budget["budget"],
		"deadline_days": deadline_days,
		"price_flexibility": flexibility["price_flexibility"],
		"price_tolerance_pct": flexibility["price_tolerance_pct"],
		"quantity_flexibility": flexibility["quantity_flexibility"],
		"quantity_tolerance_pct": flexibility["quantity_tolerance_pct"],
		"timing_flexibility": flexibility["timing_flexibility"],
		"timing_tolerance_days": flexibility["timing_tolerance_days"],
		"on_hand": target_state["on_hand"],
		"reserved": target_state["reserved"],
		"incoming_quantity": target_state["incoming_quantity"],
		"incoming_eta_days": target_state["incoming_eta_days"],
		**availability,
		**classification,
	}


def generate_request_population(seed: int, n: int = 100) -> List[Dict]:
	"""Return a reproducible in-memory population of complete buyer requests."""
	if n < 0:
		raise ValueError("n must be non-negative")
	streams = create_buyer_rng_streams(seed)
	locked_data = load_locked_data()
	return [
		assemble_population_request(
			seed,
			request_id,
			streams,
			locked_data["merchant_states_by_sku"],
			locked_data["catalog_skus"],
		)
		for request_id in range(1, n + 1)
	]


def get_experiments_path() -> Path:
	return Path(__file__).resolve().parents[1] / "experiments"


def load_json_file(filename: str) -> Dict:
	path = get_experiments_path() / filename
	if not path.exists():
		raise RuntimeError(f"Persisted experiment artifact not found: {filename}")
	return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_dashboard_artifacts() -> Dict:
	"""Load the audited experiment artifacts without regenerating simulation data."""
	seeds = (20260821, 20260822, 20260823, 20260824, 20260825)
	seed_results = {seed: load_json_file(f"seed_{seed}.json") for seed in seeds}
	requests = {}
	for seed, result in seed_results.items():
		for request_id, record in result["results_by_request_id"].items():
			requests[(seed, int(request_id))] = record
	return {
		"summary": load_json_file("five_seed_summary.json"),
		"analysis": load_json_file("experiment_analysis_v1.json"),
		"seed_results": seed_results,
		"requests": requests,
	}


@lru_cache(maxsize=1)
def load_buyer_request_records() -> Dict:
	"""Index the locked persisted buyer requests for explorer display only."""
	path = Path(__file__).resolve().parents[1] / "data" / "mirror_buyer_requests_5seeds_v1.csv"
	indexed = {}
	df = pd.read_csv(path)
	# A blank incoming ETA means no incoming shipment. Convert that missing CSV
	# cell to JSON null before it can become pandas' non-JSON NaN sentinel.
	for row in df.astype(object).where(pd.notna(df), None).to_dict(orient="records"):
		row["eligible_substitute_skus"] = json.loads(row["eligible_substitute_skus"])
		indexed[(int(row["experiment_seed"]), int(row["request_id"]))] = row
	return indexed


def payment_configuration() -> Dict:
	key_id = os.getenv("RAZORPAY_KEY_ID")
	key_secret = os.getenv("RAZORPAY_KEY_SECRET")
	return {"configured": bool(key_id and key_secret), "key_id": key_id, "key_secret": key_secret}


PAYMENT_ORDERS: Dict[str, Dict] = {}


def selected_candidate_for_request(seed: int, request_id: int) -> Dict:
	try:
		record = load_dashboard_artifacts()["requests"][(seed, request_id)]
	except KeyError as error:
		raise HTTPException(status_code=404, detail="Persisted MIRROR request not found") from error
	if record["decision"] != "NEGOTIATE" or not record.get("best_candidate"):
		raise HTTPException(status_code=409, detail="Only a selected MIRROR negotiation candidate is payable")
	best = record["best_candidate"]
	if not best.get("passes_risk_gate"):
		raise HTTPException(status_code=409, detail="Selected candidate must pass the persisted risk gate")
	matching = [
		candidate for candidate in record["candidates"]
		if candidate["sku_id"] == best["sku_id"]
		and candidate["action_type"] == best["action_type"]
		and candidate["quantity"] == best["quantity"]
		and candidate["delivery_window_days"] == best["delivery_window_days"]
		and candidate["candidate_price"] == best["candidate_price"]
	]
	if len(matching) != 1:
		raise HTTPException(status_code=409, detail="Persisted selected candidate cannot be validated")
	return best


def candidate_amount_paise(candidate: Dict) -> int:
	amount = Decimal(str(candidate["candidate_price"])) * Decimal(str(candidate["quantity"]))
	return int((amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def razorpay_create_order(amount: int, receipt: str, configuration: Dict) -> Dict:
	"""Call Razorpay Orders API with server-only Basic authentication."""
	payload = json.dumps({"amount": amount, "currency": "INR", "receipt": receipt}).encode("utf-8")
	credentials = f"{configuration['key_id']}:{configuration['key_secret']}".encode("utf-8")
	request = Request(
		"https://api.razorpay.com/v1/orders",
		data=payload,
		headers={
			"Content-Type": "application/json",
			"Authorization": "Basic " + base64.b64encode(credentials).decode("ascii"),
		},
		method="POST",
	)
	try:
		with urlopen(request, timeout=15) as response:
			return json.loads(response.read().decode("utf-8"))
	except (HTTPError, URLError, TimeoutError) as error:
		raise HTTPException(status_code=502, detail="Razorpay order creation failed") from error


def deterministic_explanation(record: Dict) -> List[str]:
	"""Explain a persisted decision strictly from its stored fields."""
	if record["decision"] == "REJECT":
		return [
			"No candidate satisfied the persisted decision rule.",
			"MIRROR did not create a payment transaction.",
		]
	if record["decision"] == "ACCEPT":
		return [
			"The baseline transaction remained the selected safe option.",
			"No risk-gate-passing candidate exceeded the strict improvement threshold.",
		]
	candidate = record["best_candidate"]
	lines = []
	if not record["baseline_feasible"]:
		lines.append("The original request was not baseline-feasible.")
	else:
		lines.append("A MIRROR alternative exceeded the baseline improvement threshold.")
	lines.extend([
		f"MIRROR selected a {candidate['action_type'].lower()} alternative.",
		"The selected candidate passed the persisted P05 downside gate.",
		"It was the highest-scoring surviving option.",
	])
	return lines


@APP.on_event("startup")
def startup_load_data() -> None:
	locked_data = load_locked_data()
	APP.state.skus = locked_data["skus"]
	APP.state.merchant_states = locked_data["merchant_states"]
	APP.state.merchant_states_by_sku = locked_data["merchant_states_by_sku"]
	APP.state.catalog_skus = locked_data["catalog_skus"]
	APP.state.catalog_skus_by_sku = locked_data["catalog_skus_by_sku"]
	for name, rng in create_buyer_rng_streams().items():
		setattr(APP.state, name, rng)


@APP.get("/health")
def health():
	return {"status": "ok", "service": "mirror"}


@APP.get("/skus")
def list_skus():
	return APP.state.skus


@APP.get("/skus/{sku_id}")
def get_sku(sku_id: str):
	for sku in APP.state.skus:
		if sku.get("sku_id") == sku_id:
			return sku
	raise HTTPException(status_code=404, detail="SKU not found")


@APP.get("/merchant-state")
def list_merchant_states():
	return APP.state.merchant_states


@APP.get("/merchant-state/{sku_id}")
def get_merchant_state(sku_id: str):
	state = APP.state.merchant_states_by_sku.get(sku_id)
	if state is None:
		raise HTTPException(status_code=404, detail="SKU not found")
	return state


@APP.get("/availability/{sku_id}")
def get_availability(sku_id: str, days: int = Query(5, ge=0)):
	state = APP.state.merchant_states_by_sku.get(sku_id)
	if state is None:
		raise HTTPException(status_code=404, detail="SKU not found")

	availability = available_for_window(state, days)
	return {
		"sku_id": sku_id,
		"days": days,
		"on_hand": state["on_hand"],
		"reserved": state["reserved"],
		**availability,
	}


@APP.get("/buyer-request/{sku_id}")
def get_buyer_request_quantity(sku_id: str):
	if sku_id not in APP.state.merchant_states_by_sku:
		raise HTTPException(status_code=404, detail="SKU not found")
	return build_buyer_request(sku_id)


@APP.get("/buyer-request")
def get_buyer_request():
	target_sku = select_target_sku(APP.state.catalog_skus, APP.state.buyer_target_rng)
	return build_buyer_request(target_sku["sku_id"])


@APP.get("/dashboard/summary")
def dashboard_summary():
	analysis = load_dashboard_artifacts()["analysis"]["global_experiment_summary"]
	return {
		"data_label": "MIRROR EXPERIMENT DATA",
		"requests": analysis["total_requests"],
		"accept": analysis["accept"],
		"negotiate": analysis["negotiate"],
		"reject": analysis["reject"],
		"candidates": analysis["total_candidates_evaluated"],
		"risk_gate_rejections": analysis["risk_gate_rejections"],
		"rescue_count": analysis["constraint_conflict_rescue_count"],
		"selected_expected_contribution": analysis["total_selected_expected_net_contribution"],
		"selected_p05": analysis["total_selected_p05_net_contribution"],
		"average_contribution": analysis["average_selected_expected_net_contribution_per_request"],
		"negotiation_rate": analysis["negotiate_pct"],
		"rescue_rate": analysis["constraint_conflict_rescue_rate"],
		"risk_rejection_rate": analysis["risk_gate_rejection_rate"],
		"razorpay_test_mode": "CONFIGURED" if payment_configuration()["configured"] else "DISABLED-NO-CREDENTIALS",
	}


@APP.get("/dashboard/levers")
def dashboard_levers():
	return load_dashboard_artifacts()["analysis"]["negotiation_levers"]


@APP.get("/dashboard/seeds")
def dashboard_seeds():
	return load_dashboard_artifacts()["analysis"]["five_seed_stability"]


@APP.get("/dashboard/cases")
def dashboard_cases():
	return load_dashboard_artifacts()["analysis"]["case_studies"]


@APP.get("/dashboard/analysis")
def dashboard_analysis():
	return load_dashboard_artifacts()["analysis"]


@APP.get("/dashboard/product-metrics")
def dashboard_product_metrics():
	"""Read-only presentation metrics derived from persisted experiment records."""
	artifacts = load_dashboard_artifacts()
	seed_metrics = []
	price_candidates = price_pass = 0
	for seed, result in artifacts["seed_results"].items():
		baseline = selected = 0.0
		for record in result["results_by_request_id"].values():
			reference = record.get("reference")
			if record["reference_type"] == "BASELINE":
				baseline += reference["expected_net_contribution"]
			chosen = record.get("best_candidate") if record["decision"] == "NEGOTIATE" else reference if record["decision"] == "ACCEPT" else None
			if chosen:
				selected += chosen["expected_net_contribution"]
			for candidate in record["candidates"]:
				if candidate["action_type"] == "PRICE":
					price_candidates += 1
					price_pass += candidate["passes_risk_gate"]
		seed_metrics.append((selected - baseline) / baseline)
	return {
		"mean_seed_uplift": sum(seed_metrics) / len(seed_metrics),
		"pooled_uplift": (sum(record["total_selected_expected_net_contribution"] for record in artifacts["summary"]["per_seed"].values()) - sum(
			item["total_baseline_expected_net_contribution"] for item in [artifacts["analysis"]["decision_engine_value"]]
		)) / artifacts["analysis"]["decision_engine_value"]["total_baseline_expected_net_contribution"],
		"positive_seed_count": sum(value > 0 for value in seed_metrics),
		"at_least_five_pct_seed_count": sum(value >= .05 for value in seed_metrics),
		"baseline_reference_count": artifacts["analysis"]["decision_engine_value"]["baseline_reference_request_count"],
		"baseline_reference_improvement": artifacts["analysis"]["decision_engine_value"]["aggregate_absolute_improvement"],
		"baseline_reference_improvement_pct": artifacts["analysis"]["decision_engine_value"]["aggregate_percentage_improvement"],
		"negotiable_candidate_count": sum(len(record["candidates"]) for record in artifacts["requests"].values()),
		"baseline_reference_count_for_risk": sum(1 for record in artifacts["requests"].values() if record.get("reference", {}).get("paths") == 10000),
		"price_candidates": price_candidates, "price_passed_risk_gate": price_pass,
	}


@APP.get("/dashboard/requests")
def dashboard_requests():
	"""Compact persisted request index for the virtualized frontend explorer."""
	rows = []
	for (seed, request_id), record in load_dashboard_artifacts()["requests"].items():
		selected = record.get("best_candidate") if record["decision"] == "NEGOTIATE" else record.get("reference")
		rows.append({
			"seed": seed, "request_id": request_id, "classification": record["classification"],
			"decision": record["decision"],
			"lever": selected.get("action_type") if record["decision"] == "NEGOTIATE" else None,
			"expected_net_contribution": selected.get("expected_net_contribution", 0) if selected else 0,
		})
	return sorted(rows, key=lambda row: (row["seed"], row["request_id"]))


@APP.get("/dashboard/request/{seed}/{request_id}")
def dashboard_request(seed: int, request_id: int):
	artifacts = load_dashboard_artifacts()
	try:
		decision = artifacts["requests"][(seed, request_id)]
		buyer_request = load_buyer_request_records()[(seed, request_id)]
	except KeyError as error:
		raise HTTPException(status_code=404, detail="Persisted MIRROR request not found") from error
	return {
		"data_label": "MIRROR EXPERIMENT DATA",
		"buyer_request": buyer_request,
		"decision": decision,
		"explanation": deterministic_explanation(decision),
		"payment": {
			"payable": decision["decision"] == "NEGOTIATE",
			"razorpay_test_mode": "CONFIGURED" if payment_configuration()["configured"] else "DISABLED-NO-CREDENTIALS",
		},
	}


@APP.post("/payments/create-order")
def create_payment_order(payload: Dict):
	configuration = payment_configuration()
	if not configuration["configured"]:
		raise HTTPException(status_code=503, detail="Razorpay Test Mode Not Configured")
	try:
		seed, request_id = int(payload["seed"]), int(payload["request_id"])
	except (KeyError, TypeError, ValueError) as error:
		raise HTTPException(status_code=422, detail="seed and request_id are required") from error
	candidate = selected_candidate_for_request(seed, request_id)
	amount = candidate_amount_paise(candidate)
	receipt = f"mirror-{seed}-{request_id}"
	order = razorpay_create_order(amount, receipt, configuration)
	if not order.get("id") or order.get("amount") != amount or order.get("currency") != "INR":
		raise HTTPException(status_code=502, detail="Razorpay returned an invalid order response")
	if order["id"] in PAYMENT_ORDERS:
		raise HTTPException(status_code=409, detail="Duplicate Razorpay order received")
	PAYMENT_ORDERS[order["id"]] = {
		"seed": seed, "request_id": request_id, "amount": amount,
		"candidate": candidate, "verified": False, "payment_id": None,
	}
	return {"order_id": order["id"], "amount": amount, "currency": "INR", "key_id": configuration["key_id"]}


@APP.post("/payments/verify")
def verify_payment(payload: Dict):
	configuration = payment_configuration()
	if not configuration["configured"]:
		raise HTTPException(status_code=503, detail="Razorpay Test Mode Not Configured")
	try:
		order_id = payload["razorpay_order_id"]
		payment_id = payload["razorpay_payment_id"]
		signature = payload["razorpay_signature"]
	except KeyError as error:
		raise HTTPException(status_code=422, detail="Razorpay payment verification fields are required") from error
	order = PAYMENT_ORDERS.get(order_id)
	if order is None:
		raise HTTPException(status_code=404, detail="Unknown local Razorpay order")
	if order["verified"] or order["payment_id"] is not None:
		raise HTTPException(status_code=409, detail="Payment fulfillment was already processed")
	body = f"{order_id}|{payment_id}".encode("utf-8")
	expected = hmac.new(configuration["key_secret"].encode("utf-8"), body, hashlib.sha256).hexdigest()
	if not hmac.compare_digest(expected, signature):
		raise HTTPException(status_code=400, detail="Invalid Razorpay payment signature")
	order["verified"] = True
	order["payment_id"] = payment_id
	return {"verified": True, "order_id": order_id, "payment_id": payment_id}


STATIC_PATH = Path(__file__).resolve().parents[1] / "frontened"
if STATIC_PATH.exists():
	APP.mount("/ui", StaticFiles(directory=STATIC_PATH), name="merchant-ui")


@APP.get("/", include_in_schema=False)
def merchant_dashboard():
	index = STATIC_PATH / "index.html"
	if not index.exists():
		raise HTTPException(status_code=404, detail="Merchant dashboard is not installed")
	return FileResponse(index)


app = APP
