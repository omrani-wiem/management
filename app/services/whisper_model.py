"""Un SEUL moteur Whisper (faster-whisper), chargé à la demande.

Rien n'est chargé à l'import : l'API ne charge le modèle que si le mode live est utilisé,
et le worker Celery ne le charge qu'au premier audio traité.
"""
import logging
import threading
from functools import lru_cache

from app.config import settings

logger = logging.getLogger(__name__)

# faster-whisper n'est pas pensé pour des appels concurrents sur le même modèle
whisper_lock = threading.Lock()


@lru_cache(maxsize=1)
def get_model():
    from faster_whisper import WhisperModel  # import tardif

    logger.info(
        "Chargement du modèle Whisper '%s' (%s, %s)",
        settings.whisper_model, settings.whisper_device, settings.whisper_compute_type,
    )
    return WhisperModel(
        settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )
