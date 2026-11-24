from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet


logger = logging.getLogger(__name__)


class PasswordCipher:
    """Шифрование и расшифровка паролей учеников через Fernet."""

    def __init__(self, encryption_key: str, fallback_secret: str) -> None:
        raw_key = encryption_key.strip()
        if raw_key:
            key_bytes = raw_key.encode("utf-8")
        else:
            logger.warning(
                "ENCRYPTION_KEY не задан — используется производный ключ из BOT_TOKEN. "
                "Для продакшена рекомендуется задать отдельный ENCRYPTION_KEY."
            )
            digest = hashlib.sha256(fallback_secret.encode("utf-8")).digest()
            key_bytes = base64.urlsafe_b64encode(digest)

        self._fernet = Fernet(key_bytes)

    def encrypt(self, plain_text: str) -> str:
        """Шифрует строку в токен Fernet."""
        return self._fernet.encrypt(plain_text.encode("utf-8")).decode("utf-8")

    def decrypt(self, token: str) -> str:
        """Расшифровывает токен Fernet обратно в строку."""
        return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
