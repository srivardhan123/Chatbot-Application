import uuid

from django.db import models


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255, default="New Conversation")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.id})"


class Message(models.Model):
    ROLE_CHOICES = [
        ("user", "user"),
        ("assistant", "assistant"),
    ]

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"[{self.role}] {self.content[:40]}"


class InferenceLog(models.Model):
    STATUS_CHOICES = [
        ("success", "success"),
        ("error", "error"),
    ]

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        related_name="inference_logs",
        null=True,
        blank=True,
    )
    session_id = models.CharField(max_length=64)
    provider = models.CharField(max_length=64)
    model = models.CharField(max_length=128)
    latency_ms = models.FloatField()
    input_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    error_message = models.TextField(null=True, blank=True)
    input_preview = models.TextField(blank=True)
    output_preview = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.provider}/{self.model} - {self.status} ({self.latency_ms}ms)"
