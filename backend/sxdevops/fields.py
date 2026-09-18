"""自定义模型字段：凭据透明加密字段。"""
from django.db import models

from .credential_cipher import decrypt_secret, encrypt_secret


class EncryptedCharField(models.CharField):
    """透明加密字符字段：写库前加密、读库后解密；兼容明文历史值。

    注意：密文非确定性（Fernet 随机 IV），请勿用该字段做精确查询/去重。
    """

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value:
            return encrypt_secret(value)
        return value

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        return decrypt_secret(str(value))

    def to_python(self, value):
        if value is None:
            return value
        if not isinstance(value, str):
            value = str(value)
        return decrypt_secret(value)
