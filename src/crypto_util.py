"""密钥加密/解密工具 - Fernet (AES-128-CBC + HMAC)"""

import base64
import hashlib
import os

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


def _derive_key(machine_id: str, salt: bytes) -> bytes:
    """从机器ID派生加密密钥，确保密钥不落盘"""
    if HAS_CRYPTO:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=600000,
        )
        return base64.urlsafe_b64encode(kdf.derive(machine_id.encode()))
    # 降级：使用SHA256哈希（较弱但仍然不可直接读）
    return base64.urlsafe_b64encode(
        hashlib.pbkdf2_hmac("sha256", machine_id.encode(), salt, 600000)
    )


def get_machine_id() -> str:
    """获取机器唯一标识用于派生密钥"""
    import platform
    node = platform.node()
    # 在Linux上读取machine-id
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        if os.path.exists(p):
            try:
                with open(p) as f:
                    node += f.read().strip()
            except OSError:
                pass
    # Windows注册表中的机器GUID
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Microsoft\Cryptography") as key:
                node += winreg.QueryValueEx(key, "MachineGuid")[0]
        except Exception:
            pass
    return node


def encrypt_data(plaintext: str, machine_id: str = None) -> str:
    """加密字符串，返回 base64 密文"""
    if not plaintext:
        return ""
    if machine_id is None:
        machine_id = get_machine_id()
    salt = os.urandom(16)
    key = _derive_key(machine_id, salt)
    if HAS_CRYPTO:
        f = Fernet(key)
        token = f.encrypt(plaintext.encode())
    else:
        # 降级：简单的XOR + base64编码（防意外泄露，不防专业破解）
        token = bytes([b ^ key[i % len(key)] for i, b in enumerate(plaintext.encode())])
    return base64.b64encode(salt + token).decode()


def decrypt_data(ciphertext_b64: str, machine_id: str = None) -> str:
    """解密 base64 密文，返回明文字符串"""
    if not ciphertext_b64:
        return ""
    if machine_id is None:
        machine_id = get_machine_id()
    try:
        raw = base64.b64decode(ciphertext_b64)
    except Exception:
        return ""
    salt, token = raw[:16], raw[16:]
    key = _derive_key(machine_id, salt)
    if HAS_CRYPTO:
        try:
            f = Fernet(key)
            return f.decrypt(token).decode()
        except Exception:
            return ""
    try:
        plain = bytes([b ^ key[i % len(key)] for i, b in enumerate(token)])
        return plain.decode()
    except Exception:
        return ""
