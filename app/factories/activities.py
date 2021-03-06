import factory
from app.models.activity import db, Activity
import app.factories.common as common


class ActivityFactory(factory.alchemy.SQLAlchemyModelFactory):

    class Meta:
        model = Activity
        sqlalchemy_session = db.session

    actor = common.string_
    action = common.url_
