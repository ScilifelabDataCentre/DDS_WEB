"Utility functions and classes useful within the DDS."

####################################################################################################
# IMPORTS ################################################################################ IMPORTS #
####################################################################################################

# Standard library
import datetime
from email import message
import os
import re
import typing
import urllib.parse

# Installed
from contextlib import contextmanager
import flask
from dds_web.errors import AccessDeniedError, VersionMismatchError, VersionNotFoundError
import flask_mail
import flask_login
import requests
import requests_cache
import simplejson


# # imports related to scheduling
import atexit
import werkzeug
from apscheduler.schedulers import background
import marshmallow
import wtforms


# Own modules
from dds_web.database import models
from dds_web import auth, db, mail

####################################################################################################
# VALIDATORS ########################################################################## VALIDATORS #
####################################################################################################

# General ################################################################################ General #


def contains_uppercase(indata):
    """Verify that string contains at least one upper case letter."""
    if not re.search("[A-Z]", indata):
        raise marshmallow.ValidationError("Required: at least one upper case letter.")


def contains_lowercase(indata):
    """Verify that string contains at least one lower case letter."""
    if not re.search("[a-z]", indata):
        raise marshmallow.ValidationError("Required: at least one lower case letter.")


def contains_digit_or_specialchar(indata):
    """Verify that string contains at least one special character OR digit."""
    if not any(re.search(x, indata) for x in ["[0-9]", "[#?!@$%^&*-]"]):
        raise marshmallow.ValidationError(
            "Required: at least one digit OR a special character (#?!@$%^&*-)."
        )


def contains_disallowed_characters(indata):
    """Indatas like <f0><9f><98><80> cause issues in Project names etc."""
    disallowed = re.findall(r"[^(\w\s)]+", indata)
    if disallowed:
        disallowed = set(disallowed)  # unique values
        chars = "characters"
        raise marshmallow.ValidationError(
            f"The {chars if len(disallowed) > 1 else chars[:-1]} '{' '.join(disallowed)}' within '[italic]{indata}[/italic]' {'are' if len(disallowed) > 1 else 'is'} not allowed."
        )


def contains_unicode_emojis(indata):
    """Find unicode emojis in string - cause SQLAlchemyErrors."""
    # Ref: https://gist.github.com/Alex-Just/e86110836f3f93fe7932290526529cd1#gistcomment-3208085
    # Ref: https://en.wikipedia.org/wiki/Unicode_block
    EMOJI_PATTERN = re.compile(
        "(["
        "\U0001F1E0-\U0001F1FF"  # flags (iOS)
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F700-\U0001F77F"  # alchemical symbols
        "\U0001F780-\U0001F7FF"  # Geometric Shapes Extended
        "\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
        "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
        "\U0001FA00-\U0001FA6F"  # Chess Symbols
        "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
        "\U00002702-\U000027B0"  # Dingbats
        "])"
    )
    emojis = re.findall(EMOJI_PATTERN, indata)
    if emojis:
        raise marshmallow.ValidationError(f"This input is not allowed: {''.join(emojis)}")


def email_not_taken(indata):
    """Validator - verify that email is not taken.

    If used by marshmallow Schema, this validator should never raise an error since the email
    field should not be changable and if it is the form validator should catch it.
    """
    if email_in_db(email=indata):
        raise marshmallow.validate.ValidationError("The email is already taken by another user.")


def email_taken(indata):
    """Validator - verify that email is taken."""
    if not email_in_db(email=indata):
        raise marshmallow.validate.ValidationError(
            "If the email is connected to a user within the DDS, you should receive an email with the password reset instructions."
        )


def username_not_taken(indata):
    """Validate that username is not taken.

    If used by marshmallow Schema, this validator should never raise an error since
    the form validator should catch it.
    """
    if username_in_db(username=indata):
        raise marshmallow.validate.ValidationError(
            "That username is taken. Please choose a different one."
        )


def valid_user_role(specified_role):
    """Returns whether or not a role is valid in the DDS."""
    return specified_role in [
        "Super Admin",
        "Unit Admin",
        "Unit Personnel",
        "Project Owner",
        "Researcher",
    ]


# wtforms ################################################################################ wtforms #


def username_contains_valid_characters():
    def _username_contains_valid_characters(form, field):
        """Validate that the username contains valid characters."""
        if not valid_chars_in_username(indata=field.data):
            raise wtforms.validators.ValidationError(
                "The username contains invalid characters. "
                "Usernames can only contain letters, digits and underscores (_)."
            )

    return _username_contains_valid_characters


def password_contains_valid_characters():
    def _password_contains_valid_characters(form, field):
        """Validate that the password contains valid characters and raise ValidationError."""
        errors = []
        validators = [
            contains_uppercase,
            contains_lowercase,
            contains_digit_or_specialchar,
        ]
        for val in validators:
            try:
                val(indata=field.data)
            except marshmallow.ValidationError as valerr:
                errors.append(str(valerr).strip("."))

        if errors:
            raise wtforms.validators.ValidationError(", ".join(errors))

    return _password_contains_valid_characters


def username_not_taken_wtforms():
    def _username_not_taken(form, field):
        """Validate that the username is not taken already."""
        try:
            username_not_taken(indata=field.data)
        except marshmallow.validate.ValidationError as valerr:
            raise wtforms.validators.ValidationError(valerr)

    return _username_not_taken


def email_not_taken_wtforms():
    def _email_not_taken(form, field):
        """Validate that the email is not taken already."""
        try:
            email_not_taken(indata=field.data)
        except marshmallow.validate.ValidationError as valerr:
            raise wtforms.validators.ValidationError(valerr)

    return _email_not_taken


def email_taken_wtforms():
    def _email_taken(form, field):
        """Validate that the email exists."""
        try:
            email_taken(indata=field.data)
        except marshmallow.validate.ValidationError as valerr:
            raise wtforms.validators.ValidationError(valerr)

    return _email_taken


####################################################################################################
# FUNCTIONS ############################################################################ FUNCTIONS #
####################################################################################################


def verify_enough_unit_admins(unit_id: str, force_create: bool = False):
    """Verify that the unit has enough Unit Admins."""
    num_admins = models.UnitUser.query.filter_by(is_admin=True, unit_id=unit_id).count()
    if num_admins < 2:
        raise AccessDeniedError(
            message=(
                "Your unit does not have enough Unit Admins. "
                "At least two Unit Admins are required for a project to be created."
            )
        )

    if num_admins < 3 and not force_create:
        return (
            f"Your unit only has {num_admins} Unit Admins. This poses a high risk of data loss. "
            "We HIGHLY recommend that you do not create this project until there are more Unit "
            "Admins connected to your unit."
        )


def valid_chars_in_username(indata):
    """Check if the username contains only valid characters."""
    return bool(re.search(r"^[a-zA-Z0-9_\.-]+$", indata))


def email_in_db(email):
    """Check if the email is in the Email table."""
    if models.Email.query.filter_by(email=email).first():
        return True

    return False


def username_in_db(username):
    """Check if username is in the User table."""
    if models.User.query.filter_by(username=username).first():
        return True

    return False


def get_username_or_request_ip():
    """Util function for action logger: Try to identify the requester"""

    if auth.current_user():
        current_user = auth.current_user().username
    elif flask_login.current_user.is_authenticated:
        current_user = flask_login.current_user.username
    else:
        username = (
            flask.request.authorization.get("username") if flask.request.authorization else "---"
        )
        if flask.request.remote_addr:
            current_user = f"{username} ({flask.request.remote_addr})"  # log IP instead of username
        elif flask.request.access_route:
            current_user = (
                f"{username} ({flask.request.access_route[0]})"  # log IP instead of username
            )
        else:
            current_user = f"{username} (anonymous)"

    return current_user


def delrequest_exists(email):
    """Check if there is already a deletion request for that email."""
    if models.DeletionRequest.query.filter_by(email=email).first():
        return True
    return False


def send_reset_email(email_row, token):
    """Generate password reset email."""
    msg = flask_mail.Message(
        "WARNING! Password Reset Request for SciLifeLab Data Delivery System",
        recipients=[email_row.email],
    )

    # Need to attach the image to be able to use it
    msg.attach(
        "scilifelab_logo.png",
        "image/png",
        open(os.path.join(flask.current_app.static_folder, "img/scilifelab_logo.png"), "rb").read(),
        "inline",
        headers=[
            ["Content-ID", "<Logo>"],
        ],
    )

    link = flask.url_for("auth_blueprint.reset_password", token=token, _external=True)
    msg.body = flask.render_template("mail/password_reset.txt", link=link)
    msg.html = flask.render_template("mail/password_reset.html", link=link)

    mail.send(msg)


def send_project_access_reset_email(email_row, email, token):
    """Generate password reset email."""
    msg = flask_mail.Message(
        "WARNING! A Unit Admin has lost access",
        recipients=[email_row.email],
    )

    # Need to attach the image to be able to use it
    msg.attach(
        "scilifelab_logo.png",
        "image/png",
        open(os.path.join(flask.current_app.static_folder, "img/scilifelab_logo.png"), "rb").read(),
        "inline",
        headers=[
            ["Content-ID", "<Logo>"],
        ],
    )

    msg.body = flask.render_template("mail/project_access_reset.txt", email=email)
    msg.html = flask.render_template("mail/project_access_reset.html", email=email)

    mail.send(msg)


def is_safe_url(target):
    """Check if the url is safe for redirects."""
    ref_url = urllib.parse.urlparse(flask.request.host_url)
    test_url = urllib.parse.urlparse(urllib.parse.urljoin(flask.request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


def current_time(to_midnight=False):
    """Return the current time for UTC"""

    curr_time = datetime.datetime.utcnow()
    if to_midnight:
        curr_time = curr_time.replace(hour=23, minute=59, second=59)

    return curr_time


def timestamp(dts=None, datetime_string=None, ts_format="%Y-%m-%d %H:%M:%S.%f"):
    """Gets the current time. Formats timestamp.

    Returns:
        str:    Timestamp in format 'YY-MM-DD_HH-MM-SS'

    """
    if datetime_string is not None:
        datetime_stamp = datetime.datetime.strptime(datetime_string, ts_format)
        return str(datetime_stamp.date())

    now = current_time() if dts is None else dts
    t_s = str(now.strftime(ts_format))
    return t_s


def rate_limit_from_config():
    return flask.current_app.config.get("TOKEN_ENDPOINT_ACCESS_LIMIT", "10/hour")


@contextmanager
def working_directory(path):
    """Contexter for changing working directory"""
    current_path = os.getcwd()
    try:
        if not os.path.exists(path):
            os.mkdir(path)
        os.chdir(path)
        yield
    finally:
        os.chdir(current_path)


def page_query(q):
    offset = 0
    while True:
        r = False
        for elem in q.limit(1000).offset(offset):
            r = True
            yield elem
        offset += 1000
        if not r:
            break


def create_one_time_password_email(user, hotp_value):
    """Create HOTP email."""
    msg = flask_mail.Message(
        "DDS One-Time Authentication Code",
        recipients=[user.primary_email],
    )

    msg.attach(
        "scilifelab_logo.png",
        "image/png",
        open(os.path.join(flask.current_app.static_folder, "img/scilifelab_logo.png"), "rb").read(),
        "inline",
        headers=[
            ["Content-ID", "<Logo>"],
        ],
    )
    msg.body = flask.render_template(
        "mail/authenticate.txt", one_time_value=hotp_value.decode("utf-8")
    )
    msg.html = flask.render_template(
        "mail/authenticate.html", one_time_value=hotp_value.decode("utf-8")
    )

    return msg


def bucket_is_valid(bucket_name):
    """Verify that the bucket name is valid."""
    valid = False
    message = ""
    if not (3 <= len(bucket_name) <= 63):
        message = f"The bucket name has the incorrect length {len(bucket_name)}"
    elif re.findall(r"[^a-zA-Z0-9.-]", bucket_name):
        message = "The bucket name contains invalid characters."
    elif not bucket_name[0].isalnum():
        message = "The bucket name must begin with a letter or number."
    elif bucket_name.count(".") > 2:
        message = "The bucket name cannot contain more than two dots."
    elif bucket_name.startswith("xn--"):
        message = "The bucket name cannot begin with the 'xn--' prefix."
    elif bucket_name.endswith("-s3alias"):
        message = "The bucket name cannot end with the '-s3alias' suffix."
    else:
        valid = True
    return valid, message


def validate_major_cli_version() -> None:
    """Validate that major CLI version matches latest version on PyPi."""
    from dds_web.version import __version__ as version_number

    # Define header name
    header_name: str = "X-CLI-Version"

    # Get CLI version from request headers
    request_version: str = flask.request.headers.get(header_name)
    if not request_version:
        raise VersionMismatchError(message="No CLI version found in request header.")

    # Major version
    major_version_request: str = request_version[0]

    # Get latest version from PyPi and save to cache
    # app.config.get
    if "cached_version" not in locals():
        cached_version = {}
        try:
            response: flask.Response = requests.get(
                "https://pypi.python.org/pypi/dds-cli/json",
                headers={
                    "User-Agent": f"dds-web {version_number} (https://github.com/ScilifelabDataCentre/dds_web)"
                },
            )
            response_json: typing.Dict = response.json()
        except (requests.exceptions.RequestException, simplejson.JSONDecodeError) as err:
            flask.current_app.logger.exception(err)
            raise VersionNotFoundError(
                message="Failed checking latest DDS PyPi version. Cannot proceed with request."
            )

        # Check that enough info is returned from PyPi
        if "info" not in response_json or (
            "info" in response_json and "version" not in response_json["info"]
        ):
            raise VersionNotFoundError(message="No version information received from PyPi.")

        cached_version: str = response_json["info"]["version"]

    latest_version: str = cached_version
    major_version_latest: typing.List = latest_version[0]

    if major_version_request != major_version_latest:
        raise VersionMismatchError(
            message=f"You have an outdated version of the DDS CLI installed. Please upgrade to version {latest_version} and try again."
        )


#


def get_latest_motd():
    """Return latest MOTD."""
    motd_object = models.MOTD.query.order_by(models.MOTD.date_created.desc()).first()
    return motd_object.message if motd_object else ""
