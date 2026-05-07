import asyncio
import os
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

app = FastAPI(title="Solar Swarm API", version="1.0.0")
@app.get("/")
def read_root():
    return {
        "message": "Solar Swarm API is Active",
        "endpoints": ["/docs", "/scout", "/finance", "/health"]
    }

GOOGLE_SOLAR_API_KEY = os.getenv("GOOGLE_SOLAR_API_KEY", "YOUR_GOOGLE_SOLAR_API_KEY")
NREL_API_KEY = os.getenv("NREL_API_KEY", "DEMO_KEY")


class SolarScoutRequest(BaseModel):
    lat: float
    lon: float
    system_size_kw: Optional[float] = 5.0


class SolarScoutResponse(BaseModel):
    location: dict
    google_solar: dict
    nrel_solar: dict
    estimate: dict


class FinancialRequest(BaseModel):
    project_cost_usd: float
    annual_energy_savings_usd: float
    system_lifespan_years: Optional[int] = 25


class FinancialResponse(BaseModel):
    project_cost_usd: float
    annual_energy_savings_usd: float
    system_lifespan_years: int
    simple_roi_percent: float
    payback_period_years: float
    total_savings_usd: float


class GoogleSolarAgent:
    BASE_URL = "https://www.googleapis.com/solar/v1"

    async def fetch_estimate(self, lat: float, lon: float, system_size_kw: float) -> dict:
        url = f"{self.BASE_URL}/estimate"
        params = {
            "lat": lat,
            "lon": lon,
            "system_size_kw": system_size_kw,
            "api_key": GOOGLE_SOLAR_API_KEY,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, params=params)
            if response.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail={
                        "source": "google_solar",
                        "status_code": response.status_code,
                        "body": response.text,
                    },
                )
            return response.json()


class NRELAgent:
    BASE_URL = "https://developer.nrel.gov/api/solar/solar_resource/v1.json"

    async def fetch_resource(self, lat: float, lon: float) -> dict:
        params = {
            "api_key": NREL_API_KEY,
            "lat": lat,
            "lon": lon,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(self.BASE_URL, params=params)
            if response.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail={
                        "source": "nrel",
                        "status_code": response.status_code,
                        "body": response.text,
                    },
                )
            return response.json()


class ScoutAgent:
    def __init__(self) -> None:
        self.google_agent = GoogleSolarAgent()
        self.nrel_agent = NRELAgent()

    async def scout(self, lat: float, lon: float, system_size_kw: float) -> SolarScoutResponse:
        google_task = self.google_agent.fetch_estimate(lat, lon, system_size_kw)
        nrel_task = self.nrel_agent.fetch_resource(lat, lon)

        google_result, nrel_result = await asyncio.gather(google_task, nrel_task)

        estimate = {
            "annual_production_kwh": google_result.get("annual_production_kwh"),
            "annual_savings_usd": google_result.get("annual_savings_usd"),
            "nrel_annual_irradiance": nrel_result.get("outputs", {}).get("avg_annual_irradiance"),
        }

        return SolarScoutResponse(
            location={"lat": lat, "lon": lon, "system_size_kw": system_size_kw},
            google_solar=google_result,
            nrel_solar=nrel_result,
            estimate=estimate,
        )


class FinancialAgent:
    @staticmethod
    def calculate_roi(project_cost_usd: float, annual_energy_savings_usd: float, system_lifespan_years: int = 25) -> FinancialResponse:
        if project_cost_usd <= 0 or annual_energy_savings_usd <= 0:
            raise HTTPException(status_code=422, detail="Project cost and annual savings must both be positive values.")

        total_savings = annual_energy_savings_usd * system_lifespan_years
        simple_roi = ((total_savings - project_cost_usd) / project_cost_usd) * 100
        payback_years = project_cost_usd / annual_energy_savings_usd

        return FinancialResponse(
            project_cost_usd=project_cost_usd,
            annual_energy_savings_usd=annual_energy_savings_usd,
            system_lifespan_years=system_lifespan_years,
            simple_roi_percent=round(simple_roi, 2),
            payback_period_years=round(payback_years, 2),
            total_savings_usd=round(total_savings, 2),
        )


scout_agent = ScoutAgent()
financial_agent = FinancialAgent()


@app.get("/scout", response_model=SolarScoutResponse)
async def scout(
    lat: float = Query(..., description="Latitude of the site"),
    lon: float = Query(..., description="Longitude of the site"),
    system_size_kw: float = Query(5.0, description="Solar system capacity in kW"),
):
    return await scout_agent.scout(lat, lon, system_size_kw)


@app.get("/finance", response_model=FinancialResponse)
async def finance(
    project_cost_usd: float = Query(..., description="Total project cost in USD"),
    annual_energy_savings_usd: float = Query(..., description="Estimated annual energy savings in USD"),
    system_lifespan_years: int = Query(25, description="Expected system lifespan in years"),
):
    return financial_agent.calculate_roi(project_cost_usd, annual_energy_savings_usd, system_lifespan_years)


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}
