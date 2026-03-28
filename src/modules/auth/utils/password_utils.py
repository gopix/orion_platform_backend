
import hashlib
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")



def hash_password(password: str):
    # Step 1: Normalize length using SHA256
    password = hashlib.sha256(password.encode()).hexdigest()

    # Step 2: Hash with bcrypt
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Apply SAME transformation as hashing
    plain_password = hashlib.sha256(plain_password.encode()).hexdigest()

    return pwd_context.verify(plain_password, hashed_password)
