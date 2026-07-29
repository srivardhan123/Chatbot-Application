from django.urls import path

from . import views

urlpatterns = [
    path(
        "conversations/",
        views.ConversationListCreateView.as_view(),
        name="conversation-list-create",
    ),
    path(
        "conversations/<uuid:conversation_id>/messages/",
        views.ConversationMessagesView.as_view(),
        name="conversation-messages",
    ),
    path("logs/", views.LogIngestListView.as_view(), name="log-ingest-list"),
]
