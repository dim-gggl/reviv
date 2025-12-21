from django.core.management import call_command
from django.test import TestCase

from reviv.models import CreditPack


class CreateCreditPacksCommandTest(TestCase):
    def test_create_credit_packs_is_idempotent(self):
        call_command("create_credit_packs")

        self.assertEqual(CreditPack.objects.count(), 2)
        self.assertTrue(CreditPack.objects.filter(sku="pack_5").exists())
        self.assertTrue(CreditPack.objects.filter(sku="pack_10").exists())

        call_command("create_credit_packs")
        self.assertEqual(CreditPack.objects.count(), 2)
