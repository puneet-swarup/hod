.PHONY: dev dev-lan test backup migrate revision clean

# Local-only dev server. Binds to loopback so nothing on the LAN can reach it.
dev:
	uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Dev server reachable from other devices on your LAN (e.g. testing on your phone).
# Only use on a trusted network.
dev-lan:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	pytest -v

migrate:
	alembic upgrade head

revision:
	alembic revision --autogenerate -m "$(m)"

backup:
	mkdir -p backups
	sqlite3 data/bakery.db ".backup 'backups/bakery_$$(date +%Y%m%d_%H%M%S).db'"
	@echo "Backup complete."

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
