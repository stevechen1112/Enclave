from passlib.context import CryptContext
ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
h = "$2b$12$lYyu9WkqDXTKkTaV63qTtetylYfhok4lbdD0DGk1gBY2vocR8Iaoa"
print("verify:", ctx.verify("admin123", h))
