from rest_framework import serializers

from .models import Conversation, Message, InferenceLog


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = ["id", "title", "created_at"]
        read_only_fields = ["id", "created_at"]


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "conversation", "role", "content", "created_at"]
        read_only_fields = ["id", "conversation", "role", "created_at"]


class MessageCreateSerializer(serializers.Serializer):
    content = serializers.CharField(allow_blank=False)


class InferenceLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = InferenceLog
        fields = [
            "id",
            "conversation",
            "session_id",
            "provider",
            "model",
            "latency_ms",
            "input_tokens",
            "output_tokens",
            "status",
            "error_message",
            "input_preview",
            "output_preview",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
        extra_kwargs = {"conversation": {"required": False, "allow_null": True}}
