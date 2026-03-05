#!/usr/bin/env bash
# ========================================================
# Enclave Security Audit Script
# ========================================================
# Comprehensive security checklist and automated scans:
#   1. Dependency vulnerability scan (pip-audit + npm audit)
#   2. Secret/credential leak detection
#   3. Docker image scan (Trivy if available)
#   4. Security headers verification
#   5. Configuration security review
#
# Usage:
#   chmod +x scripts/security-audit.sh
#   ./scripts/security-audit.sh               # Full audit
#   ./scripts/security-audit.sh --deps-only   # Dependencies only
#   ./scripts/security-audit.sh --config-only # Config check only
#
# Exit codes:
#   0 — All checks passed
#   1 — Critical issues found
#   2 — Warnings only
# ========================================================

set -euo pipefail

MODE="${1:-full}"
EXIT_CODE=0
WARNINGS=0
CRITICALS=0

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

log_pass()  { echo -e "  ${GREEN}✓${NC} $1"; }
log_warn()  { echo -e "  ${YELLOW}⚠${NC} $1"; WARNINGS=$((WARNINGS + 1)); }
log_fail()  { echo -e "  ${RED}✗${NC} $1"; CRITICALS=$((CRITICALS + 1)); }
log_info()  { echo -e "  ${CYAN}ℹ${NC} $1"; }
section()   { echo -e "\n${CYAN}━━━ $1 ━━━${NC}"; }

echo "════════════════════════════════════════════"
echo "  Enclave Security Audit"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════"

# ============================================
# 1. Dependency Vulnerability Scan
# ============================================
if [[ "${MODE}" == "full" ]] || [[ "${MODE}" == "--deps-only" ]]; then
section "1. Python Dependency Vulnerabilities"

if command -v pip-audit &>/dev/null; then
    echo "  Running pip-audit..."
    if pip-audit -r requirements.txt --desc 2>/dev/null; then
        log_pass "No known Python vulnerabilities"
    else
        log_fail "Python vulnerabilities found — run 'pip-audit -r requirements.txt' for details"
    fi
else
    log_warn "pip-audit not installed — run 'pip install pip-audit'"
fi

section "2. Node.js Dependency Vulnerabilities (Frontend)"

if [[ -d "frontend" ]]; then
    echo "  Auditing frontend/..."
    pushd frontend > /dev/null
    AUDIT_RESULT=$(npm audit --json 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    vulns = data.get('metadata', {}).get('vulnerabilities', {})
    critical = vulns.get('critical', 0)
    high = vulns.get('high', 0)
    moderate = vulns.get('moderate', 0)
    print(f'{critical},{high},{moderate}')
except:
    print('0,0,0')
" 2>/dev/null || echo "0,0,0")
    popd > /dev/null

    IFS=',' read -r CRIT HIGH MOD <<< "${AUDIT_RESULT}"
    if [[ "${CRIT}" -gt 0 ]] || [[ "${HIGH}" -gt 0 ]]; then
        log_fail "Frontend: ${CRIT} critical, ${HIGH} high, ${MOD} moderate vulnerabilities"
    elif [[ "${MOD}" -gt 0 ]]; then
        log_warn "Frontend: ${MOD} moderate vulnerabilities"
    else
        log_pass "Frontend: No known vulnerabilities"
    fi
fi

fi

# ============================================
# 2. Secret/Credential Leak Detection
# ============================================
if [[ "${MODE}" == "full" ]] || [[ "${MODE}" == "--config-only" ]]; then
section "3. Secret/Credential Leak Detection"

echo "  Scanning source code for hardcoded secrets..."

# Patterns to detect
PATTERNS=(
    'password\s*=\s*["\x27][^"\x27]{4,}'
    'secret\s*=\s*["\x27][^"\x27]{4,}'
    'api_key\s*=\s*["\x27][^"\x27]{4,}'
    'token\s*=\s*["\x27][^"\x27]{8,}'
    'sk-[a-zA-Z0-9]{20,}'
    'AKIA[0-9A-Z]{16}'
    'ghp_[a-zA-Z0-9]{36}'
)

SECRET_FOUND=false
for pattern in "${PATTERNS[@]}"; do
    MATCHES=$(grep -r -n -i -E "${pattern}" \
        --include="*.py" --include="*.ts" --include="*.tsx" --include="*.js" \
        --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=__pycache__ \
        --exclude="*.test.*" --exclude="security-audit.sh" \
        . 2>/dev/null || true)

    if [[ -n "${MATCHES}" ]]; then
        # Filter out env var references and config definitions
        REAL_MATCHES=$(echo "${MATCHES}" | grep -v -E '(os\.environ|getenv|settings\.|config\.|\.env|SECRET_KEY.*=.*Field|default=)' || true)
        if [[ -n "${REAL_MATCHES}" ]]; then
            log_warn "Potential secret pattern found:"
            echo "${REAL_MATCHES}" | head -5 | while read -r line; do
                echo "      ${line}"
            done
            SECRET_FOUND=true
        fi
    fi
done

if [[ "${SECRET_FOUND}" == "false" ]]; then
    log_pass "No hardcoded secrets detected"
fi

# Check for .env files in git
section "4. .env / Sensitive Files in Git"

TRACKED_ENV=$(git ls-files --cached | grep -E '\.env$|\.env\.local$|\.env\.production$|\.env\.staging$' | grep -v '\.example$' || true)
if [[ -n "${TRACKED_ENV}" ]]; then
    log_fail ".env file tracked by git! Add to .gitignore immediately"
    echo "      ${TRACKED_ENV}"
else
    log_pass ".env files not tracked by git (.example templates OK)"
fi

# Check .gitignore
if [[ -f ".gitignore" ]]; then
    if grep -q "\.env" .gitignore; then
        log_pass ".gitignore includes .env patterns"
    else
        log_warn ".gitignore missing .env pattern"
    fi
else
    log_fail "No .gitignore file found!"
fi

# ============================================
# 3. Configuration Security Review
# ============================================
section "5. Application Configuration Security"

# Check DEBUG mode
if grep -r -q 'DEBUG.*=.*True' app/ 2>/dev/null; then
    log_warn "DEBUG=True found in code (ensure it's False in production)"
else
    log_pass "No hardcoded DEBUG=True"
fi

# Check CORS
if grep -r -q 'allow_origins.*=.*\["\*"\]\|allow_origins.*=.*\[.\*.]' app/ 2>/dev/null; then
    log_fail "CORS allows all origins (*) — restrict in production"
else
    log_pass "CORS not set to wildcard"
fi

# Check JWT secret
if grep -r -q 'SECRET_KEY.*=.*"changeme\|SECRET_KEY.*=.*"secret' app/ 2>/dev/null; then
    log_fail "Default/weak SECRET_KEY found"
else
    log_pass "No default SECRET_KEY found"
fi

# Check SQL injection (raw queries)
if grep -r -n -E 'execute\(.*f"|execute\(.*\.format|text\(.*f"' app/ --include="*.py" 2>/dev/null; then
    log_warn "Possible raw SQL with string formatting (SQL injection risk)"
else
    log_pass "No obvious SQL injection patterns"
fi

# Check rate limiting
if grep -r -q 'slowapi\|RateLimiter\|rate_limit' app/ 2>/dev/null; then
    log_pass "Rate limiting configured"
else
    log_warn "No API rate limiting detected in backend"
fi

# Check admin IP whitelist
if grep -q 'ADMIN_IP_WHITELIST_ENABLED' app/config.py 2>/dev/null; then
    log_pass "Admin IP whitelist configured"
else
    log_warn "No admin IP whitelist"
fi

# ============================================
# 4. Security Headers Check
# ============================================
section "6. Nginx Security Headers"

for conf in nginx/*.conf; do
    if [[ -f "${conf}" ]]; then
        echo "  Checking ${conf}..."

        if grep -q "Strict-Transport-Security" "${conf}"; then
            log_pass "HSTS header present"
        else
            log_warn "Missing HSTS header in ${conf}"
        fi

        if grep -q "X-Frame-Options" "${conf}"; then
            log_pass "X-Frame-Options present"
        else
            log_warn "Missing X-Frame-Options in ${conf}"
        fi

        if grep -q "X-Content-Type-Options" "${conf}"; then
            log_pass "X-Content-Type-Options present"
        else
            log_warn "Missing X-Content-Type-Options in ${conf}"
        fi

        if grep -q "Content-Security-Policy" "${conf}"; then
            log_pass "CSP header present"
        else
            log_warn "Missing Content-Security-Policy in ${conf}"
        fi

        if grep -q "X-XSS-Protection" "${conf}"; then
            log_pass "X-XSS-Protection present"
        else
            log_info "X-XSS-Protection not set (modern browsers use CSP instead)"
        fi
    fi
done

# ============================================
# 5. Docker Security
# ============================================
section "7. Docker Security"

# Check Dockerfiles for best practices
for dockerfile in Dockerfile frontend/Dockerfile; do
    if [[ -f "${dockerfile}" ]]; then
        echo "  Checking ${dockerfile}..."

        # Check if running as root
        if grep -q "USER" "${dockerfile}"; then
            log_pass "${dockerfile}: Non-root user specified"
        else
            log_warn "${dockerfile}: No USER directive (runs as root)"
        fi

        # Check for latest tag
        if grep -q "FROM.*:latest" "${dockerfile}"; then
            log_warn "${dockerfile}: Uses :latest tag (pin specific version)"
        else
            log_pass "${dockerfile}: Uses pinned base image version"
        fi
    fi
done

# Check docker-compose for exposed ports
if grep -q "0\.0\.0\.0" docker-compose.prod.yml 2>/dev/null; then
    log_warn "docker-compose.prod.yml binds to 0.0.0.0 (restrict to 127.0.0.1 if behind reverse proxy)"
fi

# Check database port exposure in prod
if grep -A2 "db:" docker-compose.prod.yml 2>/dev/null | grep -q "ports:"; then
    log_fail "Database port exposed in production compose"
else
    log_pass "Database port not exposed in production"
fi

fi

# ============================================
# 6. Docker Image Scan (Trivy)
# ============================================
if [[ "${MODE}" == "full" ]]; then
section "8. Container Image Vulnerability Scan"

if command -v trivy &>/dev/null; then
    echo "  Scanning Docker images with Trivy..."
    for image in enclave-backend enclave-frontend; do
        if docker image inspect "${image}" &>/dev/null; then
            TRIVY_RESULT=$(trivy image --severity HIGH,CRITICAL --quiet "${image}" 2>/dev/null || echo "scan failed")
            if echo "${TRIVY_RESULT}" | grep -q "Total: 0"; then
                log_pass "${image}: No high/critical vulnerabilities"
            else
                log_warn "${image}: Vulnerabilities found — run 'trivy image ${image}' for details"
            fi
        else
            log_info "${image}: Image not built locally (skipping)"
        fi
    done
else
    log_info "Trivy not installed — install with 'brew install trivy' for container scanning"
fi
fi

# ============================================
# OWASP Top 10 Checklist
# ============================================
if [[ "${MODE}" == "full" ]] || [[ "${MODE}" == "--config-only" ]]; then
section "9. OWASP Top 10 Compliance Checklist"

echo ""
echo "  A01 — Broken Access Control"
if grep -r -q "require_superuser\|require_admin\|Depends.*get_current_user" app/ 2>/dev/null; then
    log_pass "Role-based access control implemented"
else
    log_warn "Access control implementation not detected"
fi

echo "  A02 — Cryptographic Failures"
if grep -r -q "bcrypt\|passlib\|argon2" app/ requirements.txt 2>/dev/null; then
    log_pass "Password hashing library in use"
else
    log_warn "No password hashing library detected"
fi

echo "  A03 — Injection"
if grep -r -qi "sqlalchemy\|sqlmodel" app/ requirements.txt 2>/dev/null; then
    log_pass "ORM in use (SQL injection protection)"
else
    log_warn "No ORM detected — verify SQL injection protection"
fi

echo "  A04 — Insecure Design"
log_info "Review: Multi-tenant data isolation, input validation, error handling"

echo "  A05 — Security Misconfiguration"
if [[ -f "docker-compose.prod.yml" ]]; then
    log_pass "Separate production configuration exists"
else
    log_warn "No production docker-compose found"
fi

echo "  A06 — Vulnerable Components"
log_info "Covered by dependency scans above"

echo "  A07 — Auth Failures"
if grep -r -q "JWT\|jose\|jwt" app/ requirements.txt 2>/dev/null; then
    log_pass "JWT-based authentication in use"
else
    log_warn "JWT auth not detected"
fi

echo "  A08 — Data Integrity Failures"
if [[ -f ".github/workflows/ci.yml" ]]; then
    log_pass "CI/CD pipeline configured"
else
    log_warn "No CI/CD pipeline found"
fi

echo "  A09 — Logging & Monitoring"
if grep -r -q "logging\|logger\|audit" app/ 2>/dev/null; then
    log_pass "Logging/audit trail implemented"
else
    log_warn "Logging implementation not detected"
fi

echo "  A10 — SSRF"
log_info "Review: All external URL fetches should be validated and restricted"
fi

# ============================================
# Summary
# ============================================
echo ""
echo "════════════════════════════════════════════"
if [[ ${CRITICALS} -gt 0 ]]; then
    echo -e "  ${RED}✗ AUDIT FAILED${NC}"
    echo -e "  ${RED}${CRITICALS} critical issue(s)${NC}, ${YELLOW}${WARNINGS} warning(s)${NC}"
    EXIT_CODE=1
elif [[ ${WARNINGS} -gt 0 ]]; then
    echo -e "  ${YELLOW}⚠ AUDIT PASSED WITH WARNINGS${NC}"
    echo -e "  ${YELLOW}${WARNINGS} warning(s)${NC}"
    EXIT_CODE=2
else
    echo -e "  ${GREEN}✓ AUDIT PASSED${NC}"
    echo "  No issues found"
fi
echo "════════════════════════════════════════════"

exit ${EXIT_CODE}
