from django.contrib import admin

from .models import Conversation, Message, InferenceLog


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "created_at")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "role", "content", "created_at")
    list_filter = ("role",)


@admin.register(InferenceLog)
class InferenceLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "provider",
        "model",
        "status",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "conversation",
        "created_at",
    )
    list_filter = ("status", "provider", "model")
    readonly_fields = (
        "id",
        "created_at",
        "input_preview",
        "output_preview",
        "error_message",
    )
    fields = (
        "id",
        "conversation",
        "session_id",
        "provider",
        "model",
        "status",
        "latency_ms",
        "input_tokens",
        "output_tokens",
        "input_preview",
        "output_preview",
        "error_message",
        "created_at",
    )
