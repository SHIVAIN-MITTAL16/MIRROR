from pathlib import Path
from typing import List, Dict
from bisect import bisect_right
from math import ceil, isfinite, log
from functools import lru_cache
from types import MappingProxyType
import random

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.encoders import jsonable_encoder


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
) -> Dict:
	"""Evaluate one fixed candidate across independent demand and return paths."""
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
	path_results = []

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
		"sla_success_probability": sum(
			not result["sla_missed"] for result in path_results
		) / paths,
		"sla_miss_probability": sum(
			result["sla_missed"] for result in path_results
		) / paths,
		"return_probability": sum(
			result["returned_units"] > 0 for result in path_results
		) / paths,
		"expected_fulfilled_units": sum(
			result["fulfilled_units"] for result in path_results
		) / paths,
		"expected_returned_units": sum(
			result["returned_units"] for result in path_results
		) / paths,
		"expected_gross_contribution": sum(
			result["gross_contribution"] for result in path_results
		) / paths,
		"expected_return_loss": sum(
			result["return_loss"] for result in path_results
		) / paths,
		"expected_net_contribution": sum(
			result["net_contribution"] for result in path_results
		) / paths,
		"path_results": path_results,
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


app = APP
