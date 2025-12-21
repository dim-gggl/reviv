from decimal import Decimal

import stripe
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from reviv.models import CreditPack, CreditTransaction
from reviv.utils import format_error
from reviv.serializers import (
    CreditPackSerializer,
    CreditTransactionSerializer,
    PurchaseRequestSerializer,
)

stripe.api_key = settings.STRIPE_SECRET_KEY
User = get_user_model()


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_credit_packs(request):
    """
    List available credit packs.
    """
    packs = CreditPack.objects.filter(active=True).order_by("credits")
    serializer = CreditPackSerializer(packs, many=True)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_transactions(request):
    """
    List user's credit transactions.
    """
    transactions = CreditTransaction.objects.filter(user=request.user)[:50]
    serializer = CreditTransactionSerializer(transactions, many=True)
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_checkout_session(request):
    """
    Create Stripe checkout session for credit pack purchase.
    """
    serializer = PurchaseRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            format_error(
                code="validation_error",
                message="Invalid purchase request",
                details=serializer.errors,
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    sku = serializer.validated_data["sku"]

    try:
        pack = CreditPack.objects.get(sku=sku, active=True)
    except CreditPack.DoesNotExist:
        return Response(
            format_error(code="invalid_pack", message="Invalid credit pack"),
            status=status.HTTP_400_BAD_REQUEST,
        )

    frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "euro",
                        "product_data": {
                            "name": f"reviv.pics - {pack.credits} Credits",
                            "description": f"Pack of {pack.credits} image restoration credits",
                        },
                        "unit_amount": pack.price_cents,
                    },
                    "quantity": 1,
                }
            ],
            mode="payment",
            success_url=(
                f"{frontend_url}/payment/success?session_id={{CHECKOUT_SESSION_ID}}"
            ),
            cancel_url=f"{frontend_url}/payment/cancelled",
            metadata={
                "user_id": str(request.user.id),
                "sku": sku,
                "credits": str(pack.credits),
            },
            customer_email=request.user.email or None,
        )
    except stripe.error.StripeError as exc:
        return Response(
            format_error(code="stripe_error", message=str(exc)),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return Response({"checkout_url": session.url})


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponse(status=400)

    if event.get("type") == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = session.get("metadata") or {}
        user_id = metadata.get("user_id")
        credits_raw = metadata.get("credits")
        stripe_payment_id = session.get("payment_intent")

        if not user_id or not credits_raw:
            return HttpResponse(status=200)

        if stripe_payment_id and CreditTransaction.objects.filter(
            stripe_payment_id=stripe_payment_id
        ).exists():
            return HttpResponse(status=200)

        credits = int(credits_raw)
        with transaction.atomic():
            user = User.objects.select_for_update().get(id=user_id)
            user.credit_balance = user.credit_balance + Decimal(str(credits))
            user.save(update_fields=["credit_balance"])

            CreditTransaction.objects.create(
                user=user,
                amount=credits,
                transaction_type="purchase",
                stripe_payment_id=stripe_payment_id,
            )

    return HttpResponse(status=200)
