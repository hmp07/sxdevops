"""凭据透明加密工具（Fernet）。

密钥来源：SXDEVOPS_CREDENTIAL_KEY 环境变量优先；未设置时由 SECRET_KEY 派生。
密文带 `enc:` 前缀，兼容历史明文值（无前缀直接按明文返回）。
"""
import base64
import hashlib
import os

from cryptography.fernet import Fernet

PREFIX = 'enc:'


def _fernet():
    raw = os.environ.get('SXDEVOPS_CREDENTIAL_KEY', '')
    if raw:
        secret = raw
    else:
        from django.conf import settings

        secret = settings.SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_secret(value):
    """明文 → 密文（幂等：已是密文或空值原样返回）。"""
    if not value:
        return value
    if value.startswith(PREFIX):
        return value
    return PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value):
    """密文/明文 → 明文。解密失败时原样返回（避免历史脏数据影响功能）。"""
    if not value:
        return value
    if not value.startswith(PREFIX):
        return value
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode()).decode()
    except Exception:
        return value


def is_encrypted(value):
    return bool(value) and value.startswith(PREFIX)
