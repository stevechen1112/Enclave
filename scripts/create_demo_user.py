"""Retired unsafe remote-user script.

Customer users must be provisioned through the authenticated organization UI.
For the public six-door Demo, run ``python scripts/demo_tenant.py seed``.
"""


def main() -> None:
    raise SystemExit(
        "This remote provisioning script is retired. Use the organization UI or "
        "`python scripts/demo_tenant.py seed` for synthetic Demo identities."
    )


if __name__ == "__main__":
    main()
