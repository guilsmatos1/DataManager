from sqlalchemy import BigInteger, Column, DateTime, String, create_engine
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Deal(Base):
    __tablename__ = "deals"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, primary_key=True)
    name = Column(String)


engine = create_engine("sqlite:///:memory:")

for table in Base.metadata.tables.values():
    for column in table.columns:
        if (
            column.primary_key
            and column.autoincrement
            and len(table.primary_key.columns) > 1
        ):
            column.autoincrement = False

Base.metadata.create_all(engine)
print("Success!")
