# Sport Analyzer — F1 Live
# Windows users without make: run the commands inside each target directly.

PY ?= python

.PHONY: setup phase0 fixture kaggle report dev-backend dev-frontend test gen-types

setup:
	$(PY) -m pip install -r requirements.txt
	cd frontend && npm install

# ---- Phase 0: data spike ----
fixture:
	$(PY) scripts/record_fixture.py

kaggle:
	$(PY) scripts/download_kaggle.py

report:
	$(PY) scripts/data_report.py

phase0: report

# ---- Phase 1: replay pipeline + leaderboard ----
dev-backend:
	$(PY) -m uvicorn backend.app:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

test:
	$(PY) -m pytest backend/tests -q

# regenerate frontend/src/lib/ws/types.ts after editing backend/api/schema.py
gen-types:
	$(PY) -m backend.api.gen_types
