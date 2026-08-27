"""Composition root for core and future tenant-approved media providers."""

from app.services.video_understanding import (
    AudioSignalOutlierProvider,
    EvidenceRuleTimelineProvider,
    FfmpegSceneProvider,
    MultimodalProviderRegistry,
)


def build_multimodal_provider_registry() -> MultimodalProviderRegistry:
    return MultimodalProviderRegistry(
        [
            FfmpegSceneProvider(),
            EvidenceRuleTimelineProvider(),
            AudioSignalOutlierProvider(),
        ]
    )
