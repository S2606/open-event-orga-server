# Ignore ExtDeprecationWarnings for Flask 0.11 - see http://stackoverflow.com/a/38080580
import warnings
from flask.exthook import ExtDeprecationWarning

warnings.simplefilter('ignore', ExtDeprecationWarning)
# Keep it before flask extensions are imported

from pytz import utc

from celery import Celery
from celery.signals import after_task_publish
import logging
import os.path
from os import environ
from envparse import env
import sys
from flask import Flask, json, make_response
from app.settings import get_settings, get_setts
from flask_migrate import Migrate, MigrateCommand
from flask_script import Manager
from flask_login import current_user
from flask_jwt import JWT
from datetime import timedelta
from flask_cors import CORS
from raven.contrib.flask import Sentry
from flask_rest_jsonapi.errors import jsonapi_errors
from flask_rest_jsonapi.exceptions import JsonApiException

import sqlalchemy as sa

import stripe
from app.settings import get_settings
from app.models import db
from app.api.helpers.jwt import jwt_authenticate, jwt_identity
from app.api.helpers.cache import cache
from werkzeug.contrib.profiler import ProfilerMiddleware
from app.views import BlueprintsManager
from app.api.helpers.auth import AuthManager
from app.models.event import Event, EventsUsers
from app.models.role_invite import RoleInvite



BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)

env.read_envfile()


class ReverseProxied(object):
    """
    ReverseProxied flask wsgi app wrapper from http://stackoverflow.com/a/37842465/1562480 by aldel
    """

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        scheme = environ.get('HTTP_X_FORWARDED_PROTO')
        if scheme:
            environ['wsgi.url_scheme'] = scheme
        if os.getenv('FORCE_SSL', 'no') == 'yes':
            environ['wsgi.url_scheme'] = 'https'
        return self.app(environ, start_response)


app.wsgi_app = ReverseProxied(app.wsgi_app)


def create_app():
    BlueprintsManager.register(app)
    Migrate(app, db)

    app.config.from_object(env('APP_CONFIG', default='config.ProductionConfig'))
    db.init_app(app)
    _manager = Manager(app)
    _manager.add_command('db', MigrateCommand)

    if app.config['CACHING']:
        cache.init_app(app, config={'CACHE_TYPE': 'simple'})
    else:
        cache.init_app(app, config={'CACHE_TYPE': 'null'})

    stripe.api_key = 'SomeStripeKey'
    app.secret_key = 'super secret key'
    app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False
    app.config['FILE_SYSTEM_STORAGE_FILE_VIEW'] = 'static'

    app.logger.addHandler(logging.StreamHandler(sys.stdout))
    app.logger.setLevel(logging.ERROR)

    # set up jwt
    app.config['JWT_AUTH_USERNAME_KEY'] = 'email'
    app.config['JWT_EXPIRATION_DELTA'] = timedelta(seconds=24 * 60 * 60)
    app.config['JWT_AUTH_URL_RULE'] = '/auth/session'
    _jwt = JWT(app, jwt_authenticate, jwt_identity)

    # setup celery
    app.config['CELERY_BROKER_URL'] = environ.get('REDIS_URL', 'redis://localhost:6379/0')
    app.config['CELERY_RESULT_BACKEND'] = app.config['CELERY_BROKER_URL']

    CORS(app, resources={r"/*": {"origins": "*"}})
    AuthManager.init_login(app)

    if app.config['TESTING'] and app.config['PROFILE']:
        # Profiling
        app.wsgi_app = ProfilerMiddleware(app.wsgi_app, restrictions=[30])

    # nextgen api
    with app.app_context():
        from app.api.bootstrap import api_v1
        from app.api.uploads import upload_routes
        app.register_blueprint(api_v1)
        app.register_blueprint(upload_routes)

    sa.orm.configure_mappers()

    if app.config['SERVE_STATIC']:
        app.add_url_rule('/static/<path:filename>',
                         endpoint='static',
                         view_func=app.send_static_file)

    # sentry
    if app.config['SENTRY_DSN']:
        sentry = Sentry(dsn=app.config['SENTRY_DSN'])
        sentry.init_app(app)

    return app, _manager, db, _jwt


current_app, manager, database, jwt = create_app()


# http://stackoverflow.com/questions/26724623/
@app.before_request
def track_user():
    if current_user.is_authenticated:
        current_user.update_lat()


def make_celery(app):
    celery = Celery(app.import_name, broker=app.config['CELERY_BROKER_URL'])
    celery.conf.update(app.config)
    task_base = celery.Task

    class ContextTask(task_base):
        abstract = True

        def __call__(self, *args, **kwargs):
            if current_app.config['TESTING']:
                with app.test_request_context():
                    return task_base.__call__(self, *args, **kwargs)
            with app.app_context():
                return task_base.__call__(self, *args, **kwargs)

    celery.Task = ContextTask
    return celery


celery = make_celery(current_app)


# http://stackoverflow.com/questions/9824172/find-out-whether-celery-task-exists
@after_task_publish.connect
def update_sent_state(sender=None, body=None, **kwargs):
    # the task may not exist if sent using `send_task` which
    # sends tasks by name, so fall back to the default result backend
    # if that is the case.
    task = celery.tasks.get(sender)
    backend = task.backend if task else celery.backend
    backend.store_result(body['id'], None, 'WAITING')


# register celery tasks. removing them will cause the tasks to not function. so don't remove them
# it is important to register them after celery is defined to resolve circular imports

#import api.helpers.tasks
# import helpers.tasks


# scheduler = BackgroundScheduler(timezone=utc)
# scheduler.add_job(send_mail_to_expired_orders, 'interval', hours=5)
# scheduler.add_job(empty_trash, 'cron', hour=5, minute=30)
# scheduler.add_job(send_after_event_mail, 'cron', hour=5, minute=30)
# scheduler.add_job(send_event_fee_notification, 'cron', day=1)
# scheduler.add_job(send_event_fee_notification_followup, 'cron', day=15)
# scheduler.start()


@app.errorhandler(500)
def internal_server_error(error):
    if current_app.config['PROPOGATE_ERROR'] is True:
        exc = JsonApiException({'pointer': ''}, str(error))
    else:
        exc = JsonApiException({'pointer': ''}, 'Unknown error')
    return make_response(json.dumps(jsonapi_errors([exc.to_dict()])), exc.status,
                         {'Content-Type': 'application/vnd.api+json'})


if __name__ == '__main__':
    current_app.run()
