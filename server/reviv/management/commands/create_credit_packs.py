"""Django management command to seed initial credit pack definitions.

This command is intended for development/initial deployment and is idempotent:
it uses ``get_or_create`` so running it multiple times will not duplicate rows.
"""

from django.core.management.base import BaseCommand

from reviv.models import CreditPack


class Command(BaseCommand):
    """Create (or ensure existence of) default `CreditPack` rows."""

    help = "Create initial credit packs"

    def handle(self, *args, **options):
        """Create default credit packs if they do not already exist."""
        packs = [
            {"sku": "pack_5", "credits": 5, "price_cents": 999, "active": True},
            {"sku": "pack_10", "credits": 10, "price_cents": 1499, "active": True},
        ]

        for pack_data in packs:
            pack, created = CreditPack.objects.get_or_create(
                sku=pack_data["sku"],
                defaults={
                    "credits": pack_data["credits"],
                    "price_cents": pack_data["price_cents"],
                    "active": pack_data["active"],
                },
            )

            if created:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Created credit pack: {pack.sku} - {pack.credits} credits"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f"Credit pack already exists: {pack.sku}")
                )

        self.stdout.write(self.style.SUCCESS("Credit packs initialization complete"))
