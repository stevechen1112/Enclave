"""Application composition root for ingestion capabilities."""

from app.ingestion.core_adapters import (
    CoreDocumentIngestionAdapter,
    CoreVideoIngestionAdapter,
    LongInterviewAudioIngestionAdapter,
)
from app.platform.ingestion import IngestionAdapterRegistry


def build_ingestion_adapter_registry() -> IngestionAdapterRegistry:
    return IngestionAdapterRegistry(
        [
            CoreDocumentIngestionAdapter(),
            LongInterviewAudioIngestionAdapter(),
            CoreVideoIngestionAdapter(),
        ]
    )
