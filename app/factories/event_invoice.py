import factory
from app.models.event_invoice import db, EventInvoice
from app.factories.event import EventFactoryBasic
from app.factories.user import UserFactory
from app.factories.discount_code import DiscountCodeFactory
import app.factories.common as common


class EventInvoiceFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = EventInvoice
        sqlalchemy_session = db.session

    event = factory.RelatedFactory(EventFactoryBasic)
    user = factory.RelatedFactory(UserFactory)
    discount_codes = factory.RelatedFactory(DiscountCodeFactory)
    amount = common.float_
    address = common.string_
    city = common.string_
    state = common.string_
    country = "US"
    zipcode = "10001"
    transaction_id = common.string_
    paid_via = "stripe"
    payment_mode = common.string_
    brand = common.string_
    exp_month = "10"
    exp_year = "2100"
    last4 = "1234"
    stripe_token = common.string_
    paypal_token = common.string_
