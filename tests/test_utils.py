import unittest
import marshmallow
from dds_web import utils
import pytest
from unittest.mock import patch
from dds_web import db
from dds_web.database import models
from dds_web.errors import AccessDeniedError, VersionMismatchError, VersionNotFoundError
import flask
import flask_login
import datetime
from pyfakefs.fake_filesystem import FakeFilesystem
import os
import flask_mail
from flask.testing import FlaskClient
import requests_mock
import werkzeug

# Variables

url: str = "http://localhost"
pypi_api_url: str = "https://pypi.python.org/pypi/dds-cli/json"

# contains_uppercase


def test_contains_uppercase_false():
    """Test if a lower case string contains an upper case character."""
    with pytest.raises(marshmallow.ValidationError) as err:
        utils.contains_uppercase(indata="nouppercasehere")
    assert "Required: at least one upper case letter." in str(err.value)


def test_contains_uppercase_true():
    """Test if a string contains an upper case letter."""
    utils.contains_uppercase(indata="ThereisanuppercaseInhere")


# contains_lowercase


def test_contains_lowercase_false():
    """Test if a upper case string contains a lower case character."""
    with pytest.raises(marshmallow.ValidationError) as err:
        utils.contains_lowercase(indata="NOLOWERCASEHERE")
    assert "Required: at least one lower case letter." in str(err.value)


def test_contains_lowercase_true():
    """Test if a string contains a lower case character."""
    utils.contains_lowercase(indata="ThereISALOWERCASE")


# contains_digit_or_specialchar


def test_contains_digit_or_specialchar_no_digit_or_char():
    """Test if a string without a digit or char contains a digit and char."""
    with pytest.raises(marshmallow.ValidationError) as err:
        utils.contains_digit_or_specialchar(indata="Thereisnodigitorchar")
    assert "Required: at least one digit OR a special character (#?!@$%^&*-)." in str(err.value)


def test_contains_digit_or_specialchar_no_digit():
    """Test if a string without a digit contains a digit."""
    utils.contains_digit_or_specialchar(indata="Thereisnodigitbutthereisacharhere$")


def test_contains_digit_or_specialchar_no_char():
    """Test if a string without a char contains a char."""
    utils.contains_digit_or_specialchar(indata="Thereisnodigitorchar1")


# contains_disallowed_characters


def test_contains_disallowed_characters_contains_char():
    """Test if a string contains any disallowed characters."""
    with pytest.raises(marshmallow.ValidationError) as err:
        utils.contains_disallowed_characters(indata="Also contains <")
    assert "The character '<' within" in str(err.value)
    assert "is not allowed" in str(err.value)


def test_contains_disallowed_characters_contains_multiple_char():
    """Test if a string contains any disallowed characters - multiple."""
    with pytest.raises(marshmallow.ValidationError) as err:
        utils.contains_disallowed_characters(indata="Also contains < $")
    assert "The characters '$ <' within" in str(err.value) or "The characters '< $' within" in str(
        err.value
    )
    assert "are not allowed" in str(err.value)


def test_contains_disallowed_characters():
    """Test if a string contains any disallowed characters - it doesn't."""
    utils.contains_disallowed_characters(indata="Does not contain any disallowed character")


# contains_unicode_emojis


def test_contains_unicode_emojis_true():
    """Test if a string contains any unicode emojis."""
    # Contains flag
    with pytest.raises(marshmallow.ValidationError) as err:
        utils.contains_unicode_emojis(indata="\U0001F1E0")
    assert "This input is not allowed: \U0001F1E0" in str(err.value)

    # Contains symbol
    with pytest.raises(marshmallow.ValidationError) as err:
        utils.contains_unicode_emojis(indata="\U0001F300\U0001F301")
    assert "This input is not allowed: \U0001F300\U0001F301" in str(err.value)

    # Contains emoticons
    with pytest.raises(marshmallow.ValidationError) as err:
        utils.contains_unicode_emojis(indata="\U0001F600\U0001F601")
    assert "This input is not allowed: \U0001F600\U0001F601" in str(err.value)

    # Contains transport
    with pytest.raises(marshmallow.ValidationError) as err:
        utils.contains_unicode_emojis(indata="\U0001F680\U0001F681")
    assert "This input is not allowed: \U0001F680\U0001F681" in str(err.value)

    # Contains alchemical symbols
    with pytest.raises(marshmallow.ValidationError) as err:
        utils.contains_unicode_emojis(indata="\U0001F700\U0001F701")
    assert "This input is not allowed: \U0001F700\U0001F701" in str(err.value)

    # Contains geometric shapes extended
    with pytest.raises(marshmallow.ValidationError) as err:
        utils.contains_unicode_emojis(indata="\U0001F780\U0001F781")
    assert "This input is not allowed: \U0001F780\U0001F781" in str(err.value)

    # Contains supplemental arrows-c
    with pytest.raises(marshmallow.ValidationError) as err:
        utils.contains_unicode_emojis(indata="\U0001F800\U0001F801")
    assert "This input is not allowed: \U0001F800\U0001F801" in str(err.value)

    # Contains supplemental symbols and pictographs
    with pytest.raises(marshmallow.ValidationError) as err:
        utils.contains_unicode_emojis(indata="\U0001F900\U0001F901")
    assert "This input is not allowed: \U0001F900\U0001F901" in str(err.value)

    # Contains chess symbols
    with pytest.raises(marshmallow.ValidationError) as err:
        utils.contains_unicode_emojis(indata="\U0001FA00\U0001FA01")
    assert "This input is not allowed: \U0001FA00\U0001FA01" in str(err.value)

    # Contains symbols and pictographs
    with pytest.raises(marshmallow.ValidationError) as err:
        utils.contains_unicode_emojis(indata="\U0001FA70\U0001FA71")
    assert "This input is not allowed: \U0001FA70\U0001FA71" in str(err.value)

    # Contains dingbats
    with pytest.raises(marshmallow.ValidationError) as err:
        utils.contains_unicode_emojis(indata="\U00002702\U00002703")
    assert "This input is not allowed: \U00002702\U00002703" in str(err.value)


def test_contains_unicode_emojis_false():
    """Test if a string contains any unicode emojis."""
    utils.contains_unicode_emojis(indata="Doesn't contain any emojis.")


# email_not_taken


def test_email_not_taken_true(client):
    """Check if a non taken email is taken or not."""
    utils.email_not_taken(indata="nonexistentemail@mail.com")


def test_email_not_taken_false(client):
    """Check if a taken email is taken or not."""
    from dds_web import db
    from dds_web.database import models

    user = db.session.query(models.User).first()
    with pytest.raises(marshmallow.ValidationError) as err:
        utils.email_not_taken(indata=user.primary_email)
    assert "The email is already taken by another user." in str(err.value)


# email_taken


def test_email_taken_false(client):
    """Check if a non taken email is taken or not."""
    with pytest.raises(marshmallow.ValidationError) as err:
        utils.email_taken(indata="nonexistentemail@mail.com")
    assert "If the email is connected to a user within the DDS" in str(err.value)


def test_email_taken_false(client):
    """Check if a taken email is taken or not."""
    from dds_web import db
    from dds_web.database import models

    user = db.session.query(models.User).first()
    utils.email_taken(indata=user.primary_email)


# username_not_taken


def test_username_not_taken_taken(client):
    """Check that a username is taken."""
    from dds_web import db
    from dds_web.database import models

    user = db.session.query(models.User).first()
    with pytest.raises(marshmallow.ValidationError) as err:
        utils.username_not_taken(indata=user.username)
    assert "That username is taken. Please choose a different one." in str(err.value)


def test_username_not_taken_nottaken(client):
    """Check that a username is not taken."""
    utils.username_not_taken(indata="nosuchusername")


# valid_user_role


def test_valid_user_role_false():
    """Test if a role is incorrect."""
    valid = utils.valid_user_role(specified_role="Some Role")
    assert not valid


def test_valid_user_role_false():
    """Test if a role is incorrect."""
    valid = utils.valid_user_role(specified_role="Super Admin")
    assert valid

    valid = utils.valid_user_role(specified_role="Unit Admin")
    assert valid

    valid = utils.valid_user_role(specified_role="Unit Personnel")
    assert valid

    valid = utils.valid_user_role(specified_role="Project Owner")
    assert valid

    valid = utils.valid_user_role(specified_role="Researcher")
    assert valid


# username_contains_valid_characters

# class TestForm(flask_wtf.FlaskForm):
#     """User registration form."""
#     username = wtforms.StringField(
#         "Username",
#         validators=[
#             utils.username_contains_valid_characters(),
#         ],
#     )

# def test_username_contains_valid_characters(client):
#     """"""
#     form = TestForm()
#     form.username.data = "hehej?"
#     with pytest.raises(wtforms.validators.ValidationError) as err:
#         form.validate()

# verify_enough_unit_admins


def test_verify_enough_unit_admins_less_than_2(client):
    """Verify that an exception is thrown when a unit has less than 2 unit admins."""
    # Get unit
    unit = db.session.query(models.Unit).first()
    assert unit

    # Get number of admins
    num_admins = db.session.query(models.UnitUser).filter_by(is_admin=True, unit_id=unit.id).count()
    assert num_admins == 1

    # Run function
    with pytest.raises(AccessDeniedError) as err:
        utils.verify_enough_unit_admins(unit_id=unit.id)
    assert "Your unit does not have enough Unit Admins" in str(err.value)


def test_verify_enough_unit_admins_less_than_3(client):
    """Verify that an error message is returned when a unit has less than 3 unit admins."""
    # Unit ID
    unit_id = 1

    # Get unit
    unit = db.session.query(models.Unit).filter_by(id=unit_id).one_or_none()
    assert unit

    # Get number of admins
    num_admins = db.session.query(models.UnitUser).filter_by(is_admin=True, unit_id=unit_id).count()
    assert num_admins == 1

    # Create another unit admin
    from tests import test_project_creation

    test_project_creation.create_unit_admins(num_admins=1, unit_id=unit_id)

    # Get number of admins
    num_admins = db.session.query(models.UnitUser).filter_by(is_admin=True, unit_id=unit_id).count()
    assert num_admins == 2

    # Run function
    response = utils.verify_enough_unit_admins(unit_id=unit_id)
    assert "Your unit only has 2 Unit Admins. This poses a high risk of data loss" in response


def test_verify_enough_unit_admins_ok(client):
    """Verify that no exception is thrown and no error is returned if there are at least 3 unit admins."""
    # Unit ID
    unit_id = 1

    # Get unit
    unit = db.session.query(models.Unit).filter_by(id=unit_id).one_or_none()
    assert unit

    # Get number of admins
    num_admins = db.session.query(models.UnitUser).filter_by(is_admin=True, unit_id=unit_id).count()
    assert num_admins == 1

    # Create another unit admin
    from tests import test_project_creation

    test_project_creation.create_unit_admins(num_admins=2, unit_id=unit_id)

    # Get number of admins
    num_admins = db.session.query(models.UnitUser).filter_by(is_admin=True, unit_id=unit_id).count()
    assert num_admins == 3

    # Run function
    response = utils.verify_enough_unit_admins(unit_id=unit_id)
    assert not response


# valid_chars_in_username


def test_valid_chars_in_username_only_valid():
    """Verify return true if contains only valid characters."""
    response: bool = utils.valid_chars_in_username(indata="valid")
    assert response


def test_valid_chars_in_username_some_invalid():
    """Verify return false if contains only some invalid characters."""
    response: bool = utils.valid_chars_in_username(indata="invalid$")
    assert not response


# email_in_db


def test_email_in_db_true(client):
    """Verify return True if email is in database."""
    # Get email known to be in database
    email_row: models.Email = db.session.query(models.Email).first()
    assert email_row

    # Check that found in database
    response: bool = utils.email_in_db(email=email_row.email)
    assert response


def test_email_in_db_false(client):
    """Verify return False if email is not in database."""
    # Define email
    email_address: str = "notindb@mail.com"

    # Check that email is not in database
    email_row: models.Email = (
        db.session.query(models.Email).filter_by(email="notindb@mail.com").first()
    )
    assert not email_row

    # Check that found in database
    response: bool = utils.email_in_db(email=email_address)
    assert not response


# username_in_db


def test_username_in_db_true(client):
    """Verify return True if username is in database."""
    # Get username known to be in database
    user_in_db: models.User = db.session.query(models.User).first()
    assert user_in_db

    # Check that found in database
    response: bool = utils.username_in_db(username=user_in_db.username)
    assert response


def test_username_in_db_false(client):
    """Verify return False if username is not in database."""
    # Define username
    username: str = "notindb"

    # Check that username is not in database
    user_in_db: models.User = db.session.query(models.User).filter_by(username=username).first()
    assert not user_in_db

    # Check that found in database
    response: bool = utils.username_in_db(username=username)
    assert not response


# get_username_or_request_ip


def test_get_username_or_request_ip_auth_current_user(client):
    """Verify that the correct user object is returned."""
    # Create new user
    username: str = "new_user_for_test"
    new_user: models.ResearchUser = models.ResearchUser(username=username, password="goodpassword")
    db.session.add(new_user)
    db.session.commit()

    # Authenticate user
    # auth.current_user() calls the following
    # ref: https://github.com/miguelgrinberg/Flask-HTTPAuth/blob/b42168ed174cde0a9404dbf0b05b5b5c5d6eb46d/src/flask_httpauth.py#L185-L187
    # def current_user(self):
    #     if hasattr(g, 'flask_httpauth_user'):
    #         return g.flask_httpauth_user
    flask.g.flask_httpauth_user = new_user

    # Call function
    response: str = utils.get_username_or_request_ip()
    assert response and response == new_user.username == username


def test_get_username_or_request_ip_flask_login_current_user(client):
    """Verify that the correct user object is returned."""
    # Get user
    user_object: models.User = db.session.query(models.User).first()
    assert user_object.is_authenticated

    # Login user
    flask_login.login_user(user_object)

    # Call function
    response: str = utils.get_username_or_request_ip()
    assert response and response == user_object.username


def test_get_username_or_request_ip_anonymous(client):
    """Verify that anonymous user is returned."""
    # Call function
    response: str = utils.get_username_or_request_ip()
    assert "(anonymous)" in response


def test_get_username_or_request_ip_remote_addr(client):
    """Verify that remote addr is returned"""
    flask.request.remote_addr = "http://localhost"
    assert flask.request.remote_addr == "http://localhost"
    # Call function
    response: str = utils.get_username_or_request_ip()
    assert "http://localhost" in response


# Access route test not implemented
# def test_get_username_or_request_ip_access_route(client):
#    pass


def test_delrequest_exists_true(client):
    """Verify deletion request row exists."""
    # Create deletion request
    user: models.User = db.session.query(models.User).first()
    deletion_request: models.DeletionRequest = models.DeletionRequest(
        email=user.primary_email, issued=utils.current_time()
    )
    user.deletion_request.append(deletion_request)
    db.session.commit()

    # Call function
    response: bool = utils.delrequest_exists(email=deletion_request.email)
    assert response


def test_delrequest_exists_false(client):
    """Check that deletion request does not exist."""
    # Define email
    email = "nosuchrequest@mail.com"

    # Create deletion request
    deletion_request: models.DeletionRequest = (
        db.session.query(models.DeletionRequest).filter_by(email=email).first()
    )
    assert not deletion_request

    # Run function
    response: bool = utils.delrequest_exists(email=email)
    assert not response


# send_reset_email


def test_send_reset_email(client):
    """Send reset email."""
    # Get email row
    email_row: models.Email = db.session.query(models.Email).first()

    # Run function
    with patch("dds_web.utils.mail.send"):
        response = utils.send_reset_email(email_row=email_row, token="")
    assert response is None


# send_project_access_reset_email


def test_send_project_access_reset_email(client):
    """Send project access reset email."""
    # Get email row
    email_row: models.Email = db.session.query(models.Email).first()

    # Call function
    with patch("dds_web.utils.mail.send"):
        response = utils.send_project_access_reset_email(
            email_row=email_row, email=email_row.email, token=None
        )
    assert response is None


# is_safe_url - not tested
# def test_is_safe_url(client):
#     """Check if url is safe to redirect to."""

# current_time


def test_current_time():
    """Test getting the current time."""
    # Get current time
    current_time_manual = datetime.datetime.utcnow()

    # Call function
    current_time_from_function: datetime.datetime = utils.current_time()

    # Check that they are relatively close to each other
    assert current_time_manual < current_time_from_function
    assert current_time_from_function - datetime.timedelta(seconds=15) < current_time_manual
    assert isinstance(current_time_from_function, datetime.datetime)

    # tzinfo is None if in utc
    assert current_time_from_function.tzinfo is None


def test_current_time_to_midnight():
    """Test getting the current date, time: midnight."""
    # Get current time
    current_time_manual = datetime.datetime.utcnow()

    # Call function
    current_time_from_function: datetime.datetime = utils.current_time(to_midnight=True)

    # Check that correct time and date
    assert current_time_from_function.hour == 23
    assert current_time_from_function.minute == 59
    assert current_time_from_function.second == 59
    assert current_time_from_function.day == current_time_manual.day

    # tzinfo is None if in utc
    assert current_time_from_function.tzinfo is None


# timestamp


def add_zero_to_start(input: int, correct_length: int = 2):
    """Add a zero to each part of a timestamp."""
    return_string: str = str(input)
    field_length: int = len(str(input))
    if field_length < correct_length:
        return_string = str(0) + return_string

    return return_string


def test_timestamp():
    """Verify that timestamp is returned."""
    # Call function to create timestamp
    new_timestamp: str = utils.timestamp()
    assert isinstance(new_timestamp, str)


def test_timestamp_input_timestamp():
    """Check that function returns string representation of timestamp passed in."""
    # Get current time
    now: datetime.datetime = datetime.datetime.utcnow()

    # Call function
    datetime_string: str = utils.timestamp(dts=now)
    assert isinstance(datetime_string, str)
    assert (
        datetime_string
        == f"{add_zero_to_start(input=now.year, correct_length=4)}-{add_zero_to_start(input=now.month)}-{add_zero_to_start(input=now.day)} {add_zero_to_start(input=now.hour)}:{add_zero_to_start(input=now.minute)}:{add_zero_to_start(input=now.second)}.{add_zero_to_start(input=now.microsecond, correct_length=6)}"
    )


def test_timestamp_new_tsformat():
    """Verify that new format is applied."""
    # Get current time
    now: datetime.datetime = datetime.datetime.utcnow()

    # Call function
    datetime_string: str = utils.timestamp(dts=now, ts_format="%Y-%m")
    assert isinstance(datetime_string, str)
    assert (
        datetime_string
        == f"{add_zero_to_start(input=now.year, correct_length=4)}-{add_zero_to_start(input=now.month)}"
    )


def test_timestamp_datetime_string():
    """Check that year is returned when datetime string is entered."""
    # Get current time
    now: datetime.datetime = datetime.datetime.utcnow()

    # Call function
    datetime_string: str = utils.timestamp(dts=now)
    assert isinstance(datetime_string, str)

    # Call function again - real test
    new_datetime_string: str = utils.timestamp(datetime_string=datetime_string)
    assert (
        new_datetime_string
        == f"{add_zero_to_start(input=now.year, correct_length=4)}-{add_zero_to_start(input=now.month)}-{add_zero_to_start(input=now.day)}"
    )


# rate_limit_from_config


def test_rate_limit_from_config(client):
    """Test the limiter."""
    limit: str = utils.rate_limit_from_config()
    assert limit == "10/hour"


# working_directory


def test_working_directory(fs: FakeFilesystem):
    """Check that working directory has changed."""
    initial_path = os.getcwd()
    test_dir = "thisisatest"
    with utils.working_directory(path=test_dir):
        assert os.getcwd() == f"/{test_dir}"
    assert os.getcwd() == initial_path


# page_query


def test_page_query(client):
    """Test if paging works."""
    previous_projects = db.session.query(models.Project).count()

    # Create 1020 projects
    projects = [
        models.Project(
            public_id=f"project__{x}",
            title=f"{x} Project",
            description="This is a test project. You will be able to upload to but NOT download "
            "from this project. Create a new project to test the entire system. ",
            pi="support@example.com",
            bucket=f"testbucket_{x}",
        )
        for x in range(1020)
    ]
    assert len(projects) == 1020
    db.session.add_all(projects)
    db.session.commit()

    # Keep track of iterations
    iteration = 0

    # Run function
    for x in utils.page_query(db.session.query(models.Project)):
        iteration += 1

    assert iteration == (len(projects) + previous_projects)


# create_one_time_password_email


def test_create_one_time_password_email(client):
    """Test creating one time password email."""
    # User
    current_user: models.User = db.session.query(models.User).first()

    # Call function
    message: str = utils.create_one_time_password_email(user=current_user, hotp_value=b"012345")
    assert isinstance(message, flask_mail.Message)


# bucket_is_valid


def test_bucket_is_valid_too_short():
    """Test that a bucket name with length shorter than 3."""
    # Call function
    valid, message = utils.bucket_is_valid(bucket_name="bb")
    assert not valid
    assert "The bucket name has the incorrect length 2" in message


def test_bucket_is_valid_too_long():
    """Test that a bucket name with length longer than 63 is not valid."""
    # Call function
    valid, message = utils.bucket_is_valid(bucket_name="b" * 64)
    assert not valid
    assert "The bucket name has the incorrect length 64" in message


def test_bucket_is_valid_invalid_chars():
    """Test that a bucket name with underscore is not valid."""
    # Call function
    valid, message = utils.bucket_is_valid(bucket_name="bb_")
    assert not valid
    assert "The bucket name contains invalid characters." in message


def test_bucket_is_valid_begin_with_dot_or_dash():
    """Test that a bucket name beginning with a dot or a dash is not valid."""
    # Call function
    valid, message = utils.bucket_is_valid(bucket_name=".bb")
    assert not valid
    assert "The bucket name must begin with a letter or number." in message

    # Call function again
    valid, message = utils.bucket_is_valid(bucket_name="-bb")
    assert not valid
    assert "The bucket name must begin with a letter or number." in message


def test_bucket_is_valid_too_many_dots():
    """Test that a bucket name with more than 2 dots is not valid."""
    # Call function
    valid, message = utils.bucket_is_valid(bucket_name="bb...")
    assert not valid
    assert "The bucket name cannot contain more than two dots." in message


def test_bucket_is_valid_invalid_prefix():
    """Test that a bucket name with prefix xn-- is not valid."""
    # Call function
    valid, message = utils.bucket_is_valid(bucket_name="xn--something")
    assert not valid
    assert "The bucket name cannot begin with the 'xn--' prefix." in message


def test_bucket_is_valid_invalid_suffix():
    """Test that a bucket name with suffix -s3alias is not valid."""
    # Call function
    valid, message = utils.bucket_is_valid(bucket_name="something-s3alias")
    assert not valid
    assert "The bucket name cannot end with the '-s3alias' suffix." in message


def test_bucket_is_valid_ok():
    """Test that a bucket name with suffix -s3alias is not valid."""
    # Call function
    valid, message = utils.bucket_is_valid(bucket_name="something-.")
    assert valid
    assert message == ""


# validate_major_cli_version


def test_validate_major_cli_version_without_custom_header(client: FlaskClient):
    """No CLI version in header should give error."""
    with pytest.raises(VersionMismatchError) as err:
        with client.session_transaction() as session:
            utils.validate_major_cli_version()
    assert "No CLI version found in request header." in str(err.value)


def test_validate_major_cli_version_no_version_info(client: FlaskClient):
    """Version info from pypi required."""
    # Mock requests
    with requests_mock.Mocker() as mock:
        # Create mocks for no info
        _: requests_mock.adapter._Matcher = mock.get(url, status_code=200, json={})
        pypi_response: requests_mock.adapter._Matcher = mock.get(
            pypi_api_url, status_code=200, json={"test": "test"}
        )

        # Perform request to have header - this will call pypi once
        client.get(url, headers={"X-CLI-Version": "0.0.0"})
        assert pypi_response.call_count == 0

        # Verify failure
        with pytest.raises(VersionNotFoundError) as err:
            utils.validate_major_cli_version()
        assert "No version information received from PyPi." in str(err.value)
        assert pypi_response.call_count == 1

        # Create mock for no version in info
        pypi_response_2: requests_mock.adapter._Matcher = mock.get(
            pypi_api_url, status_code=200, json={"info": {"test": "test"}}
        )

        # Verify failure
        with pytest.raises(VersionNotFoundError) as err:
            utils.validate_major_cli_version()
        assert "No version information received from PyPi." in str(err.value)
        assert pypi_response_2.call_count == 1


def test_validate_major_cli_version_mismatch_major(client: FlaskClient):
    """Major version mismatch should result in blocking."""
    # Mock requests
    with requests_mock.mocker.Mocker() as mock:
        # Create mocks for request with version
        _: requests_mock.adapter._Matcher = mock.get(url, status_code=200, json={})
        pypi_response: requests_mock.adapter._Matcher = mock.get(
            pypi_api_url, status_code=200, json={"info": {"version": "1.0.0"}}
        )

        # Perform request to have header - major mismatch from latest
        client.get(url, headers={"X-CLI-Version": "0.0.0"})
        assert pypi_response.call_count == 0

        # Verify failure - major version mismatch
        with pytest.raises(VersionMismatchError) as err:
            utils.validate_major_cli_version()
        assert (
            "You have an outdated version of the DDS CLI installed. Please upgrade to version 1.0.0 and try again."
            in str(err.value)
        )
        assert pypi_response.call_count == 1


def test_validate_major_cli_version_mismatch_minor(client: FlaskClient):
    """Minor version mismatch should pass."""
    # Mock requests
    with requests_mock.mocker.Mocker() as mock:
        # Create mocks with version
        _: requests_mock.adapter._Matcher = mock.get(url, status_code=200, json={})
        pypi_response: requests_mock.adapter._Matcher = mock.get(
            pypi_api_url, status_code=200, json={"info": {"version": "1.0.0"}}
        )

        # Perform request to have header - minor mismatch from latest
        client.get(url, headers={"X-CLI-Version": "1.1.0"})
        assert pypi_response.call_count == 0

        # Verify ok - should pass
        utils.validate_major_cli_version()
        assert pypi_response.call_count == 1

        # Perform request to have header - minor mismatch from latest
        client.get(url, headers={"X-CLI-Version": "1.0.1"})
        assert pypi_response.call_count == 1

        # Verify ok - should pass
        utils.validate_major_cli_version()
        assert pypi_response.call_count == 2


def test_validate_major_cli_version_jsonerror(client: FlaskClient):
    """Json decode error should fail."""
    # Mock requests
    with requests_mock.mocker.Mocker() as mock:
        # Create mocks with version
        base_response: requests_mock.adapter._Matcher = mock.get(url, status_code=200, json={})
        pypi_response: requests_mock.adapter._Matcher = mock.get(
            pypi_api_url, status_code=200, json=None
        )

        # Perform request
        client.get(url, headers={"X-CLI-Version": "0.0.0"})
        assert pypi_response.call_count == 0

        # Try function
        with pytest.raises(VersionNotFoundError) as err:
            utils.validate_major_cli_version()
        assert pypi_response.call_count == 1
        assert "Failed checking latest DDS PyPi version." in str(err.value)


# get_latest_motd


def test_get_latest_motd_no_motd(client: FlaskClient):
    motd = utils.get_latest_motd()
    assert not motd


def test_get_latest_motd(client: FlaskClient):
    new_message: str = "test message"
    new_motd = models.MOTD(message=new_message, date_created=utils.current_time())
    db.session.add(new_motd)
    db.session.commit()

    motd = utils.get_latest_motd()
    assert motd == new_message
