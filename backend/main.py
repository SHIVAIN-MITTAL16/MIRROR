from pathlib import Path
from typing import List, Dict
from math import ceil, log
import random

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.encoders import jsonable_encoder


APP = FastAPI()

SKU_COLUMNS = [
	"sku_id", "price_tier", "margin_profile", "list_price", "current_price",
	"discount_pct", "cost_ratio", "unit_cost", "margin_floor", "minimum_price",
	"current_margin",
]
MERCHANT_STATE_COLUMNS = [
	"sku_id", "heterogeneity_multiplier", "mu", "nb_k", "incoming_exists",
	"incoming_quantity", "incoming_eta_days", "on_hand", "reserved",
]
BUYER_QUANTITY_LOG_SIGMA = 0.65
BUYER_BUDGET_LOG_LOCATION = log(0.92)
BUYER_BUDGET_LOG_SIGMA = 0.10
BUYER_DEADLINE_VALUES = (2, 3, 5, 7, 10)
BUYER_DEADLINE_PROBABILITIES = (0.10, 0.20, 0.35, 0.25, 0.10)


def get_data_path() -> Path:
	# The locked demand/inventory dataset is the source of truth for this slice.
	root = Path(__file__).resolve().parents[1]
	return root / "data" / "mirror_sku_demand_inventory_v1.csv"


def load_and_validate(csv_path: Path) -> pd.DataFrame:
	df = pd.read_csv(csv_path)

	expected_rows = 50
	required_columns = set(SKU_COLUMNS + MERCHANT_STATE_COLUMNS)

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


def generate_buyer_request_quantity(mu: float, rng=random) -> Dict:
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
	rng=random,
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


@APP.on_event("startup")
def startup_load_data() -> None:
	csv_path = get_data_path()
	if not csv_path.exists():
		raise RuntimeError(f"SKU CSV not found at {csv_path}")

	df = load_and_validate(csv_path)

	locked_records = jsonable_encoder(
		df.astype(object).where(pd.notna(df), None).to_dict(orient="records")
	)
	APP.state.skus: List[Dict] = [
		{column: record[column] for column in SKU_COLUMNS}
		for record in locked_records
	]
	APP.state.merchant_states: List[Dict] = [
		{column: record[column] for column in MERCHANT_STATE_COLUMNS}
		for record in locked_records
	]
	APP.state.merchant_states_by_sku = {
		state["sku_id"]: state for state in APP.state.merchant_states
	}
	APP.state.skus_by_sku = {sku["sku_id"]: sku for sku in APP.state.skus}
	APP.state.buyer_deadline_rng = random.Random()


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

	incoming_available = (
		state["incoming_quantity"]
		if state["incoming_exists"] and state["incoming_eta_days"] <= days
		else 0
	)
	expected_demand_for_feasibility = ceil(state["mu"] * days)
	available = (
		state["on_hand"]
		- state["reserved"]
		+ incoming_available
		- expected_demand_for_feasibility
	)
	return {
		"sku_id": sku_id,
		"days": days,
		"on_hand": state["on_hand"],
		"reserved": state["reserved"],
		"incoming_available": incoming_available,
		"expected_demand_for_feasibility": expected_demand_for_feasibility,
		"available": available,
	}


@APP.get("/buyer-request/{sku_id}")
def get_buyer_request_quantity(sku_id: str):
	state = APP.state.merchant_states_by_sku.get(sku_id)
	if state is None:
		raise HTTPException(status_code=404, detail="SKU not found")

	quantity = generate_buyer_request_quantity(state["mu"])
	sku = APP.state.skus_by_sku[sku_id]
	budget = generate_buyer_budget(quantity["requested_quantity"], sku["current_price"])
	deadline_days = generate_buyer_deadline(APP.state.buyer_deadline_rng)
	return {
		"sku_id": sku_id,
		"mu": state["mu"],
		**quantity,
		"current_price": sku["current_price"],
		**budget,
		"deadline_days": deadline_days,
	}


app = APP
