"""Config for DDS setup."""

####################################################################################################
# IMPORTS ################################################################################ IMPORTS #
####################################################################################################

# Standard library
import os
import datetime

####################################################################################################
# CLASSES ################################################################################ CLASSES #
####################################################################################################


class Config(object):
    """Base config"""

    SITE_NAME = "Data Delivery System"
    SECRET_KEY = "REPLACE_THE_STRING_IN_PRODUCTION"

    # DB related config
    SQLALCHEMY_DATABASE_URI = "mysql+pymysql://TEST_USER:TEST_PASSWORD@db/DeliverySystem"
    SQLALCHEMY_ECHO = False
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Data related config
    MAX_CONTENT_LENGTH = 0x1000000
    MAX_DOWNLOAD_LIMIT = 1000000000

    # Expected paths - these are the bind paths *inside* the container
    USE_LOCAL_DB = True
    LOGS_DIR = "/dds_web/logs"
    SAFESPRING_URL = os.environ.get("DDS_SAFESPRING_URL", "https://example.endpoint.net")
    DDS_SAFESPRING_PROJECT = os.environ.get("DDS_SAFESPRING_PROJECT", "project-name.example.se")
    DDS_SAFESPRING_ACCESS = os.environ.get("DDS_SAFESPRING_ACCESS", "SAFESPRINGACCESSKEY")
    DDS_SAFESPRING_SECRET = os.environ.get("DDS_SAFESPRING_SECRET", "SAFESPRINGSECRETKEY")

    # Use short-lived session cookies:
    PERMANENT_SESSION_LIFETIME = datetime.timedelta(hours=1)

    # Devel settings
    TEMPLATES_AUTO_RELOAD = True

    # OIDC
    OIDC_CLIENT_ID = ""
    OIDC_CLIENT_SECRET = ""
    OIDC_ACCESS_TOKEN_URL = ""

    MAIL_SERVER = "smtp.mailtrap.io"
    MAIL_PORT = 2525
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "mailtrap_username")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "mailtrap_password")
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False
    MAIL_DEFAULT_SENDER = "dds@noreply.se"

    TOKEN_ENDPOINT_ACCESS_LIMIT = "10/hour"
    RATELIMIT_STORAGE_URI = os.environ.get(
        "RATELIMIT_STORAGE_URI", "memory://"
    )  # Use in devel only! Use Redis or memcached in prod

    INVITATION_EXPIRES_IN_HOURS = 7 * 24

    # 512MiB; at least 4GiB (0x400000) recommended in production
    ARGON_MEMORY_COST = os.environ.get("ARGON_MEMORY_COST", 0x80000)
