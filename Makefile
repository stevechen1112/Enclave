# ═══════════════════════════════════════════
# Enclave — Makefile
# ═══════════════════════════════════════════
.PHONY: dev staging prod down logs migrate test

# ─── Development ───────────────────────────
dev:
	cp .env.development .env 2>/dev/null || true
	docker-compose up -d --build
	@echo "✅ Development environment running"
	@echo "   Backend:  http://localhost:8000"
	@echo "   Frontend: http://localhost:3001"
	@echo "   API docs: http://localhost:8000/docs"

# ─── Staging ───────────────────────────────
staging:
	cp .env.staging .env 2>/dev/null || true
	docker-compose -f docker-compose.yml -f docker-compose.staging.yml up -d --build
	@echo "✅ Staging environment running"

# ─── Production ────────────────────────────
prod:
	cp .env.production .env 2>/dev/null || true
	docker-compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
	@echo "✅ Production environment running"

# ─── Tear down ─────────────────────────────
down:
	docker-compose down
	@echo "⏹️  All services stopped"

down-v:
	docker-compose down -v
	@echo "⏹️  All services stopped and volumes removed"

# ─── Logs ──────────────────────────────────
logs:
	docker-compose logs -f --tail=100

logs-web:
	docker-compose logs -f --tail=100 web

logs-worker:
	docker-compose logs -f --tail=100 worker

# ─── Database ─────────────────────────────
migrate:
	docker-compose exec web alembic upgrade head

migrate-create:
	@read -p "Migration name: " name; \
	docker-compose exec web alembic revision --autogenerate -m "$$name"

migrate-history:
	docker-compose exec web alembic history

# ─── Build ─────────────────────────────────
build:
	docker-compose build

build-web:
	docker-compose build web

build-frontend:
	docker-compose build frontend

# ─── Shell ─────────────────────────────────
shell:
	docker-compose exec web bash

db-shell:
	docker-compose exec db psql -U postgres -d enclave

redis-cli:
	docker-compose exec redis redis-cli

# ─── Status ────────────────────────────────
status:
	docker-compose ps

health:
	@echo "Backend:"
	@curl -s http://localhost:8000/api/v1/admin/system/health 2>/dev/null | python3 -m json.tool || echo "  ⚠️  Not accessible"
	@echo ""
	@echo "Frontend:"
	@curl -so /dev/null -w "  HTTP %{http_code}\n" http://localhost:3001 2>/dev/null || echo "  ⚠️  Not accessible"
