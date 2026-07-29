from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Conversation, Message, InferenceLog
from .serializers import (
    ConversationSerializer,
    MessageSerializer,
    MessageCreateSerializer,
    InferenceLogSerializer,
)
from .sdk.logged_client import LoggedGeminiClient

HISTORY_LIMIT = 20


class ConversationListCreateView(generics.ListCreateAPIView):
    queryset = Conversation.objects.all()
    serializer_class = ConversationSerializer


class ConversationMessagesView(APIView):
    def get(self, request, conversation_id):
        conversation = get_object_or_404(Conversation, id=conversation_id)
        messages = conversation.messages.all()
        return Response(MessageSerializer(messages, many=True).data)

    def post(self, request, conversation_id):
        conversation = get_object_or_404(Conversation, id=conversation_id)
        input_serializer = MessageCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        user_message = Message.objects.create(
            conversation=conversation,
            role="user",
            content=input_serializer.validated_data["content"],
        )

        recent = list(conversation.messages.order_by("-created_at")[:HISTORY_LIMIT])
        recent.reverse()
        history = [{"role": m.role, "content": m.content} for m in recent]

        try:
            client = LoggedGeminiClient()
            reply_text = client.send(
                session_id=str(conversation.id),
                conversation_id=conversation.id,
                messages=history,
            )
        except Exception as exc:
            return Response(
                {
                    "user_message": MessageSerializer(user_message).data,
                    "error": str(exc),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        assistant_message = Message.objects.create(
            conversation=conversation,
            role="assistant",
            content=reply_text,
        )

        return Response(
            {
                "user_message": MessageSerializer(user_message).data,
                "assistant_message": MessageSerializer(assistant_message).data,
            },
            status=status.HTTP_201_CREATED,
        )


class LogIngestListView(generics.ListCreateAPIView):
    """Ingestion endpoint: the SDK wrapper POSTs captured inference metadata here."""

    queryset = InferenceLog.objects.all()
    serializer_class = InferenceLogSerializer
