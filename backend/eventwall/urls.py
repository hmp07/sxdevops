from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import EventRecordViewSet, EventSourceViewSet, ExternalEventIngestView

router = DefaultRouter()
router.register('events', EventRecordViewSet, basename='event-record')
router.register('event-sources', EventSourceViewSet, basename='event-source')

urlpatterns = [
    path('event-sources/<slug:type>/ingest/', ExternalEventIngestView.as_view(), name='event-source-ingest'),
    path('', include(router.urls)),
]
