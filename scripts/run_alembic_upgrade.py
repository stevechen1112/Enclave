from alembic.config import Config
from alembic import command

cfg = Config("/code/alembic.ini")
command.upgrade(cfg, "head")
print("alembic upgrade head complete")
