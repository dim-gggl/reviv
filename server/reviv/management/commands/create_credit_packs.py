from django.core.management.base import BaseCommand

from reviv.models import CreditPack


class Command(BaseCommand):
    help = "Create initial credit packs"

    def handle(self, *args, **options):
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
