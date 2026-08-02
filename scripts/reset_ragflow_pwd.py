"""Reset RAGFlow admin password."""
import hashlib
import base64
import os

password = b'Enclave2024!'
salt = os.urandom(16)
hash_bytes = hashlib.scrypt(password, salt=salt, n=32768, r=8, p=1, maxmem=64*1024*1024)
salt_b64 = base64.b64encode(salt).decode()
hash_hex = hash_bytes.hex()
new_hash = f"scrypt:32768:8:1${salt_b64}${hash_hex}"
print(new_hash)
