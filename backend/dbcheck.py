from app.db.session import get_session_factory
from sqlalchemy import text

s = get_session_factory()()
total = s.execute(text("select count(*) from check_definitions")).scalar()
court = [r[0] for r in s.execute(
    text("select id from check_definitions where provider = 'ecourts' order by id"))]
print("db checks:", total)
print("court checks:", court)