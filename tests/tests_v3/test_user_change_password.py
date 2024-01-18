import http

import flask

import tests.tests_v3 as tests
from dds_web.database import models
from tests.test_login_web import successful_web_login


def test_get_user_change_password_without_login(client):
    response = client.get(
        tests.DDSEndpoint.CHANGE_PASSWORD,
        content_type="application/json",
        follow_redirects=True,
        headers=tests.DEFAULT_HEADER,
    )

    # Because it redirects to login
    assert response.status_code == http.HTTPStatus.OK
    assert response.request.path == tests.DDSEndpoint.LOGIN


def test_unsuccessful_user_change_password_with_login_nonlatin1(client):
    """Non latin 1 chars should not be accepted."""
    # Get user
    user_auth = tests.UserAuth(tests.USER_CREDENTIALS["researcher"])

    # Verify current password
    user = models.User.query.get(user_auth.username)
    assert user.verify_password("password")

    # Get and verify variables
    public_key_initial = user.public_key
    nonce_initial = user.nonce
    private_key_initial = user.private_key
    kd_salt_initial = user.kd_salt

    assert public_key_initial
    assert nonce_initial
    assert private_key_initial
    assert kd_salt_initial

    # Login
    form_token = successful_web_login(client, user_auth)

    # Define change password data
    form_data = {
        "csrf_token": form_token,
        "current_password": "password",
        "new_password": "123$%^qweRTY€",
        "confirm_new_password": "123$%^qweRTY€",
        "submit": "Change Password",
    }

    # Attempt to change password -- should fail
    response = client.post(
        tests.DDSEndpoint.CHANGE_PASSWORD,
        json=form_data,
        follow_redirects=True,
        headers=tests.DEFAULT_HEADER,
    )
    assert response.status_code == http.HTTPStatus.OK
    assert response.request.path == tests.DDSEndpoint.CHANGE_PASSWORD

    # Password should not have changed, neither should other info
    assert user.verify_password("password")
    assert not user.verify_password("123$%^qweRTY€")

    public_key_after_password_change = user.public_key
    nonce_after_password_change = user.nonce
    private_key_after_password_change = user.private_key
    kd_salt_after_password_change = user.kd_salt

    assert public_key_after_password_change
    assert nonce_after_password_change
    assert private_key_after_password_change
    assert kd_salt_after_password_change

    assert public_key_after_password_change == public_key_initial
    assert nonce_after_password_change == nonce_initial
    assert private_key_after_password_change == private_key_initial
    assert kd_salt_after_password_change == kd_salt_initial


def test_successful_user_change_password_with_login(client):
    user_auth = tests.UserAuth(tests.USER_CREDENTIALS["researcher"])

    user = models.User.query.get(user_auth.username)
    assert user.verify_password("password")

    public_key_initial = user.public_key
    nonce_initial = user.nonce
    private_key_initial = user.private_key
    kd_salt_initial = user.kd_salt

    assert public_key_initial
    assert nonce_initial
    assert private_key_initial
    assert kd_salt_initial

    form_token = successful_web_login(client, user_auth)

    form_data = {
        "csrf_token": form_token,
        "current_password": "password",
        "new_password": "123$%^qweRTY",
        "confirm_new_password": "123$%^qweRTY",
        "submit": "Change Password",
    }

    response = client.post(
        tests.DDSEndpoint.CHANGE_PASSWORD,
        json=form_data,
        follow_redirects=True,
        headers=tests.DEFAULT_HEADER,
    )
    assert response.status_code == http.HTTPStatus.OK
    assert response.request.path == tests.DDSEndpoint.LOGIN

    assert not user.verify_password("password")
    assert user.verify_password("123$%^qweRTY")

    public_key_after_password_change = user.public_key
    nonce_after_password_change = user.nonce
    private_key_after_password_change = user.private_key
    kd_salt_after_password_change = user.kd_salt

    assert public_key_after_password_change
    assert nonce_after_password_change
    assert private_key_after_password_change
    assert kd_salt_after_password_change

    assert public_key_after_password_change == public_key_initial
    assert nonce_after_password_change != nonce_initial
    assert private_key_after_password_change != private_key_initial
    assert kd_salt_after_password_change != kd_salt_initial
