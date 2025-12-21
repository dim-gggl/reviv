import cloudinary.uploader
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from reviv.models import CreditPack, CreditTransaction, Passkey, RestorationJob, User
from reviv.tasks.cleanup import extract_public_id


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin for custom User model."""

    list_display = [
        "email",
        "oauth_provider",
        "credit_balance",
        "free_preview_used",
        "social_share_unlock_used",
        "created_at",
    ]
    list_filter = [
        "oauth_provider",
        "free_preview_used",
        "social_share_unlock_used",
        "created_at",
    ]
    search_fields = ["email", "first_name", "last_name", "oauth_id"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal Info", {"fields": ("first_name", "last_name")}),
        ("OAuth", {"fields": ("oauth_provider", "oauth_id")}),
        (
            "Credits & Features",
            {"fields": ("credit_balance", "free_preview_used", "social_share_unlock_used")},
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important Dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )

    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),
    )

    ordering = ["-created_at"]


@admin.register(Passkey)
class PasskeyAdmin(admin.ModelAdmin):
    """Admin for Passkey model."""

    list_display = ["name", "user", "created_at", "last_used_at"]
    list_filter = ["created_at", "last_used_at"]
    search_fields = ["name", "user__email", "credential_id"]
    readonly_fields = ["credential_id", "public_key", "sign_count", "created_at", "last_used_at"]

    fieldsets = (
        (None, {"fields": ("user", "name")}),
        ("Credential Data", {"fields": ("credential_id", "public_key", "sign_count")}),
        ("Timestamps", {"fields": ("created_at", "last_used_at")}),
    )


@admin.register(RestorationJob)
class RestorationJobAdmin(admin.ModelAdmin):
    """Admin for RestorationJob model."""

    list_display = ["id", "user", "status", "unlock_method", "created_at", "expires_at"]
    list_filter = ["status", "unlock_method", "created_at"]
    search_fields = ["user__email", "kie_task_id"]
    readonly_fields = ["created_at", "is_unlocked"]
    date_hierarchy = "created_at"

    fieldsets = (
        (None, {"fields": ("user", "status")}),
        (
            "Images",
            {"fields": ("original_image_url", "restored_preview_url", "restored_full_url")},
        ),
        ("kie.ai", {"fields": ("kie_task_id",)}),
        ("Unlock", {"fields": ("unlock_method", "unlocked_at", "is_unlocked")}),
        ("Timestamps", {"fields": ("created_at", "expires_at")}),
    )

    actions = ["mark_as_failed", "delete_with_cleanup"]

    def mark_as_failed(self, request, queryset):
        """Mark selected jobs as failed."""
        count = queryset.update(status="failed")
        self.message_user(request, f"{count} jobs marked as failed")

    mark_as_failed.short_description = "Mark selected jobs as failed"

    def delete_with_cleanup(self, request, queryset):
        """Delete jobs and cleanup Cloudinary images."""
        count = 0
        for job in queryset:
            if job.original_image_url:
                public_id = extract_public_id(job.original_image_url)
                if public_id:
                    cloudinary.uploader.destroy(public_id)

            if job.restored_preview_url:
                public_id = extract_public_id(job.restored_preview_url)
                if public_id:
                    cloudinary.uploader.destroy(public_id)

            if job.restored_full_url:
                public_id = extract_public_id(job.restored_full_url)
                if public_id:
                    cloudinary.uploader.destroy(public_id, type="private")

            job.delete()
            count += 1

        self.message_user(request, f"{count} jobs deleted with Cloudinary cleanup")

    delete_with_cleanup.short_description = "Delete with Cloudinary cleanup"


@admin.register(CreditPack)
class CreditPackAdmin(admin.ModelAdmin):
    """Admin for CreditPack model."""

    list_display = ["sku", "credits", "price_cents", "price_dollars", "active"]
    list_filter = ["active"]
    search_fields = ["sku"]

    def price_dollars(self, obj):
        """Display price in dollars."""
        return f"${obj.price_cents / 100:.2f}"

    price_dollars.short_description = "Price (EUR)"


@admin.register(CreditTransaction)
class CreditTransactionAdmin(admin.ModelAdmin):
    """Admin for CreditTransaction model."""

    list_display = [
        "id",
        "user",
        "amount",
        "transaction_type",
        "stripe_payment_id",
        "created_at",
    ]
    list_filter = ["transaction_type", "created_at"]
    search_fields = ["user__email", "stripe_payment_id"]
    readonly_fields = [
        "user",
        "amount",
        "transaction_type",
        "stripe_payment_id",
        "restoration_job",
        "created_at",
    ]
    date_hierarchy = "created_at"

    fieldsets = (
        (None, {"fields": ("user", "amount", "transaction_type")}),
        ("Payment", {"fields": ("stripe_payment_id", "restoration_job")}),
        ("Timestamp", {"fields": ("created_at",)}),
    )
