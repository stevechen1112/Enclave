#!/usr/bin/env python3
"""
Generate production secrets for UniHR SaaS deployment.

Usage:
    python scripts/generate_secrets.py
    python scripts/generate_secrets.py --output .env.production
"""
import secrets
import sys


def generate_secrets() -> dict[str, str]:
    """Generate all required production secrets."""
    return {
        "SECRET_KEY": secrets.token_urlsafe(48),
        "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
        "REDIS_PASSWORD": secrets.token_urlsafe(24),
        "ADMIN_REDIS_PASSWORD": secrets.token_urlsafe(24),
        "GRAFANA_PASSWORD": secrets.token_urlsafe(16),
    }


def main():
    generated = generate_secrets()

    # If --output specified, patch the file in-place
    if len(sys.argv) >= 3 and sys.argv[1] == "--output":
        target = sys.argv[2]
        try:
            with open(target, "r", encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            print(f"File not found: {target}")
            print("Copy .env.production.example to .env.production first:")
            print(f"  cp .env.production.example {target}")
            sys.exit(1)

        replacements = 0
        for key, value in generated.items():
            # Replace empty values: KEY=<spaces/comment>
            import re
            pattern = rf"^({key}=)\s*(#.*)?$"
            new_content = re.sub(pattern, rf"\1{value}", content, flags=re.MULTILINE)
            if new_content != content:
                replacements += 1
                content = new_content

        # Also fix CELERY URLs with the actual Redis password
        redis_pw = generated["REDIS_PASSWORD"]
        content = content.replace(
            "redis://:YOUR_REDIS_PASSWORD@redis:6379/0",
            f"redis://:{redis_pw}@redis:6379/0",
        )

        with open(target, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"✅ Patched {replacements} secrets into {target}")
        print(f"   (CELERY URLs also updated with Redis password)")
        print(f"\n⚠️  Remember to also set:")
        print(f"   - FIRST_SUPERUSER_EMAIL")
        print(f"   - FIRST_SUPERUSER_PASSWORD")
        print(f"   - OPENAI_API_KEY")
        print(f"   - VOYAGE_API_KEY")
        print(f"   - LLAMAPARSE_API_KEY")
        print(f"   - BACKEND_CORS_ORIGINS")
        return

    # Default: just print the secrets
    print("=" * 60)
    print("  UniHR SaaS — Generated Production Secrets")
    print("=" * 60)
    for key, value in generated.items():
        print(f"{key}={value}")
    print("=" * 60)
    print()
    print("To auto-patch .env.production:")
    print("  1. cp .env.production.example .env.production")
    print("  2. python scripts/generate_secrets.py --output .env.production")


if __name__ == "__main__":
    main()
