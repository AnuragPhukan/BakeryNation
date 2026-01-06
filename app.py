from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, validator
from typing import List, Dict, Literal

app = FastAPI(title="Bakery BOM/Estimation API", version="1.0.0")

JobType = Literal["cupcakes", "cake", "pastry_box"]

class EstimateRequest(BaseModel):
    job_type: JobType
    quantity: int = Field(..., gt=0)

    @validator("quantity")
    def _qpos(cls, v):
        if v <= 0:
            raise ValueError("quantity must be > 0")
        return v

class Material(BaseModel):
    name: str
    unit: Literal["kg", "L", "ml", "each"]
    qty: float

class EstimateResponse(BaseModel):
    job_type: JobType
    quantity: int
    materials: List[Material]
    labor_hours: float


# --- Fixed per-unit BOMs (units chosen to match your SQL costs) ---

# Note:
# - baking_powder and salt are stored as kg (convert from grams to kg per unit)
# - pastry_box is a box of ~6 pastries as a single unit
BOM_PER_UNIT: Dict[JobType, Dict] = {
    "cupcakes": {
        "materials": [
            {"name": "flour",          "unit": "kg",  "qty": 0.08},
            {"name": "sugar",          "unit": "kg",  "qty": 0.06},
            {"name": "butter",         "unit": "kg",  "qty": 0.04},
            {"name": "eggs",           "unit": "each","qty": 0.5},
            {"name": "milk",           "unit": "L",   "qty": 0.05},
            {"name": "vanilla",        "unit": "ml",  "qty": 1.0},
            {"name": "baking_powder",  "unit": "kg",  "qty": 0.001},  # 1 g = 0.001 kg
        ],
        "labor_hours": 0.05,
    },
    "cake": {
        "materials": [
            {"name": "flour",          "unit": "kg",  "qty": 0.50},
            {"name": "sugar",          "unit": "kg",  "qty": 0.40},
            {"name": "butter",         "unit": "kg",  "qty": 0.30},
            {"name": "eggs",           "unit": "each","qty": 4.0},
            {"name": "milk",           "unit": "L",   "qty": 0.20},
            {"name": "cocoa",          "unit": "kg",  "qty": 0.05},
            {"name": "vanilla",        "unit": "ml",  "qty": 5.0},
            {"name": "baking_powder",  "unit": "kg",  "qty": 0.005},  # 5 g = 0.005 kg
        ],
        "labor_hours": 0.80,
    },
    "pastry_box": {
        "materials": [
            {"name": "flour",          "unit": "kg",  "qty": 0.40},
            {"name": "butter",         "unit": "kg",  "qty": 0.35},
            {"name": "sugar",          "unit": "kg",  "qty": 0.10},
            {"name": "eggs",           "unit": "each","qty": 1.0},
            {"name": "milk",           "unit": "L",   "qty": 0.10},
            {"name": "salt",           "unit": "kg",  "qty": 0.002},  # 2 g = 0.002 kg
            {"name": "yeast",          "unit": "kg",  "qty": 0.005},
        ],
        "labor_hours": 0.60,
    },
}

def scale_bom(job_type: JobType, quantity: int) -> EstimateResponse:
    per_unit = BOM_PER_UNIT[job_type]
    scaled_materials = []
    for m in per_unit["materials"]:
        scaled_qty = m["qty"] * quantity
        # Keep more precision internally; round to 3 decimals for readability (optional)
        if m["unit"] in ("kg", "L"):
            scaled_qty = round(scaled_qty, 3)
        elif m["unit"] == "ml":
            scaled_qty = round(scaled_qty, 1)
        else:  # eggs/each can be halves; keep one decimal
            scaled_qty = round(scaled_qty, 1)
        scaled_materials.append(Material(**{**m, "qty": scaled_qty}))
    labor = round(per_unit["labor_hours"] * quantity, 3)
    return EstimateResponse(
        job_type=job_type,
        quantity=quantity,
        materials=scaled_materials,
        labor_hours=labor,
    )

@app.get("/job-types", response_model=List[JobType])
def get_job_types():
    return list(BOM_PER_UNIT.keys())

@app.post("/estimate", response_model=EstimateResponse)
def estimate(req: EstimateRequest):
    if req.job_type not in BOM_PER_UNIT:
        raise HTTPException(status_code=400, detail="Unknown job_type")
    return scale_bom(req.job_type, req.quantity)

@app.get("/healthz")
def healthz():
    return {"status": "ok"}