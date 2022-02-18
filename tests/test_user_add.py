import flask_mail
import http
import json
import sqlalchemy
from dds_web import db
from dds_web.database import models
import tests
import pytest
import unittest
import marshmallow

existing_project = "public_project_id"
first_new_email = {"email": "first_test_email@mailtrap.io"}
first_new_user = {**first_new_email, "role": "Researcher"}
first_new_owner = {**first_new_email, "role": "Project Owner"}
first_new_user_existing_project = {**first_new_user, "project": "public_project_id"}
first_new_user_extra_args = {**first_new_user, "extra": "test"}
first_new_user_invalid_role = {**first_new_email, "role": "Invalid Role"}
first_new_user_invalid_email = {"email": "first_invalid_email", "role": first_new_user["role"]}
existing_invite = {"email": "existing_invite_email@mailtrap.io", "role": "Researcher"}
new_unit_admin = {"email": "new_unit_admin@mailtrap.io", "role": "Super Admin"}
new_unit_user = {"email": "new_unit_user@mailtrap.io", "role": "Unit Personnel"}
existing_research_user = {"email": "researchuser2@mailtrap.io", "role": "Researcher"}
existing_research_user_owner = {"email": "researchuser2@mailtrap.io", "role": "Project Owner"}
existing_research_user_to_existing_project = {
    **existing_research_user,
    "project": "public_project_id",
}
existing_research_user_to_nonexistent_proj = {
    **existing_research_user,
    "project": "not_a_project_id",
}
change_owner_existing_user = {
    "email": "researchuser@mailtrap.io",
    "role": "Project Owner",
    "project": "public_project_id",
}
submit_with_same_ownership = {
    **existing_research_user_owner,
    "project": "second_public_project_id",
}


def test_add_user_with_researcher(client):
    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["researchuser"]).token(client),
        data=json.dumps(first_new_user),
        content_type="application/json",
    )
    assert response.status_code == http.HTTPStatus.FORBIDDEN
    invited_user = models.Invite.query.filter_by(email=first_new_user["email"]).one_or_none()
    assert invited_user is None


def test_add_user_with_unituser_no_role(client):
    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["unitadmin"]).token(client),
        data=json.dumps(first_new_email),
        content_type="application/json",
    )
    assert response.status_code == http.HTTPStatus.BAD_REQUEST
    invited_user = models.Invite.query.filter_by(email=first_new_email["email"]).one_or_none()
    assert invited_user is None


def test_add_user_with_unitadmin_with_extraargs(client):
    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["unitadmin"]).token(client),
        data=json.dumps(first_new_user_extra_args),
        content_type="application/json",
    )
    assert response.status_code == http.HTTPStatus.OK
    invited_user = models.Invite.query.filter_by(
        email=first_new_user_extra_args["email"]
    ).one_or_none()
    assert invited_user


def test_add_user_with_unitadmin_and_invalid_role(client):
    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["unitadmin"]).token(client),
        data=json.dumps(first_new_user_invalid_role),
        content_type="application/json",
    )
    assert response.status_code == http.HTTPStatus.BAD_REQUEST
    invited_user = models.Invite.query.filter_by(
        email=first_new_user_invalid_role["email"]
    ).one_or_none()
    assert invited_user is None


def test_add_user_with_unitadmin_and_invalid_email(client):
    with unittest.mock.patch.object(flask_mail.Mail, "send") as mock_mail_send:
        with pytest.raises(marshmallow.ValidationError):
            response = client.post(
                tests.DDSEndpoint.USER_ADD,
                headers=tests.UserAuth(tests.USER_CREDENTIALS["unitadmin"]).token(client),
                data=json.dumps(first_new_user_invalid_email),
                content_type="application/json",
            )
        # An email is always sent when receiving the partial token
        mock_mail_send.assert_called_once()

    invited_user = models.Invite.query.filter_by(
        email=first_new_user_invalid_email["email"]
    ).one_or_none()
    assert invited_user is None


def test_add_user_with_unitadmin(client):
    with unittest.mock.patch.object(flask_mail.Mail, "send") as mock_mail_send:
        response = client.post(
            tests.DDSEndpoint.USER_ADD,
            headers=tests.UserAuth(tests.USER_CREDENTIALS["unitadmin"]).token(client),
            data=json.dumps(first_new_user),
            content_type="application/json",
        )
        # One mail sent for partial token and one for the invite
        assert mock_mail_send.call_count == 2

    assert response.status_code == http.HTTPStatus.OK

    invited_user = models.Invite.query.filter_by(email=first_new_user["email"]).one_or_none()
    assert invited_user
    assert invited_user.email == first_new_user["email"]
    assert invited_user.role == first_new_user["role"]

    assert invited_user.nonce is not None
    assert invited_user.public_key is not None
    assert invited_user.private_key is not None
    assert invited_user.project_invite_keys == []


def test_add_unit_user_with_unitadmin(client):
    with unittest.mock.patch.object(flask_mail.Mail, "send") as mock_mail_send:
        response = client.post(
            tests.DDSEndpoint.USER_ADD,
            headers=tests.UserAuth(tests.USER_CREDENTIALS["unitadmin"]).token(client),
            data=json.dumps(new_unit_user),
            content_type="application/json",
        )
        # One mail sent for partial token and one for the invite
        assert mock_mail_send.call_count == 2

    assert response.status_code == http.HTTPStatus.OK

    invited_user = models.Invite.query.filter_by(email=new_unit_user["email"]).one_or_none()
    assert invited_user
    assert invited_user.email == new_unit_user["email"]
    assert invited_user.role == new_unit_user["role"]

    assert invited_user.nonce is not None
    assert invited_user.public_key is not None
    assert invited_user.private_key is not None

    project_invite_keys = invited_user.project_invite_keys
    number_of_asserted_projects = 0
    for project_invite_key in project_invite_keys:
        if (
            project_invite_key.project.public_id == "public_project_id"
            or project_invite_key.project.public_id == "unused_project_id"
            or project_invite_key.project.public_id == "restricted_project_id"
            or project_invite_key.project.public_id == "second_public_project_id"
            or project_invite_key.project.public_id == "file_testing_project"
        ):
            number_of_asserted_projects += 1
    assert len(project_invite_keys) == number_of_asserted_projects
    assert len(project_invite_keys) == len(invited_user.unit.projects)
    assert len(project_invite_keys) == 5


def test_add_user_with_superadmin(client):
    with unittest.mock.patch.object(flask_mail.Mail, "send") as mock_mail_send:
        response = client.post(
            tests.DDSEndpoint.USER_ADD,
            headers=tests.UserAuth(tests.USER_CREDENTIALS["superadmin"]).token(client),
            data=json.dumps(first_new_user),
            content_type="application/json",
        )
        # One mail sent for partial token and one for the invite
        assert mock_mail_send.call_count == 2

    assert response.status_code == http.HTTPStatus.OK

    invited_user = models.Invite.query.filter_by(email=first_new_user["email"]).one_or_none()
    assert invited_user
    assert invited_user.email == first_new_user["email"]
    assert invited_user.role == first_new_user["role"]


def test_add_user_existing_email(client):
    invited_user = models.Invite.query.filter_by(
        email=existing_invite["email"], role=existing_invite["role"]
    ).one_or_none()
    assert invited_user
    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["unitadmin"]).token(client),
        data=json.dumps(existing_invite),
        content_type="application/json",
    )
    assert response.status_code == http.HTTPStatus.BAD_REQUEST


def test_add_unitadmin_user_with_unitpersonnel_permission_denied(client):
    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["unituser"]).token(client),
        data=json.dumps(new_unit_admin),
        content_type="application/json",
    )
    assert response.status_code == http.HTTPStatus.FORBIDDEN

    invited_user = models.Invite.query.filter_by(email=new_unit_admin["email"]).one_or_none()
    assert invited_user is None


def test_add_existing_user_without_project(client):
    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["unituser"]).token(client),
        data=json.dumps(existing_research_user),
        content_type="application/json",
    )
    assert response.status_code == http.HTTPStatus.BAD_REQUEST


def test_research_user_cannot_add_existing_user_to_existing_project(client):
    user_copy = existing_research_user_to_existing_project.copy()
    project_id = user_copy.pop("project")

    project = models.Project.query.filter_by(public_id=project_id).one_or_none()
    user = models.Email.query.filter_by(
        email=existing_research_user_to_existing_project["email"]
    ).one_or_none()
    project_user_before_addition = models.ProjectUsers.query.filter(
        sqlalchemy.and_(
            models.ProjectUsers.user_id == user.user_id,
            models.ProjectUsers.project_id == project.id,
        )
    ).one_or_none()
    assert project_user_before_addition is None

    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["researchuser"]).token(client),
        query_string={"project": project_id},
        data=json.dumps(user_copy),
        content_type="application/json",
    )
    assert response.status_code == http.HTTPStatus.FORBIDDEN

    project_user_after_addition = models.ProjectUsers.query.filter(
        sqlalchemy.and_(
            models.ProjectUsers.user_id == user.user_id,
            models.ProjectUsers.project_id == project.id,
        )
    ).one_or_none()
    assert project_user_after_addition is None


# projectowner adds researchuser2 to projects[0]
def test_project_owner_can_add_existing_user_to_existing_project(client):
    user_copy = existing_research_user_to_existing_project.copy()
    project_id = user_copy.pop("project")

    project = models.Project.query.filter_by(public_id=project_id).one_or_none()
    user = models.Email.query.filter_by(
        email=existing_research_user_to_existing_project["email"]
    ).one_or_none()
    project_user_before_addition = models.ProjectUsers.query.filter(
        sqlalchemy.and_(
            models.ProjectUsers.user_id == user.user_id,
            models.ProjectUsers.project_id == project.id,
        )
    ).one_or_none()
    assert project_user_before_addition is None

    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["projectowner"]).token(client),
        query_string={"project": project_id},
        data=json.dumps(user_copy),
        content_type="application/json",
    )
    assert response.status_code == http.HTTPStatus.OK

    project_user_after_addition = models.ProjectUsers.query.filter(
        sqlalchemy.and_(
            models.ProjectUsers.user_id == user.user_id,
            models.ProjectUsers.project_id == project.id,
        )
    ).one_or_none()
    assert project_user_after_addition is not None


def test_add_existing_user_to_existing_project(client):
    user_copy = existing_research_user_to_existing_project.copy()
    project_id = user_copy.pop("project")

    project = models.Project.query.filter_by(public_id=project_id).one_or_none()
    user = models.Email.query.filter_by(
        email=existing_research_user_to_existing_project["email"]
    ).one_or_none()
    project_user_before_addition = models.ProjectUsers.query.filter(
        sqlalchemy.and_(
            models.ProjectUsers.user_id == user.user_id,
            models.ProjectUsers.project_id == project.id,
        )
    ).one_or_none()
    assert project_user_before_addition is None

    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["unituser"]).token(client),
        query_string={"project": project_id},
        data=json.dumps(user_copy),
        content_type="application/json",
    )
    assert response.status_code == http.HTTPStatus.OK

    project_user_after_addition = models.ProjectUsers.query.filter(
        sqlalchemy.and_(
            models.ProjectUsers.user_id == user.user_id,
            models.ProjectUsers.project_id == project.id,
        )
    ).one_or_none()
    assert project_user_after_addition


def test_add_existing_user_to_existing_project_after_release(client):
    user_copy = existing_research_user_to_existing_project.copy()
    project_id = user_copy.pop("project")

    project = models.Project.query.filter_by(public_id=project_id).one_or_none()
    user = models.Email.query.filter_by(
        email=existing_research_user_to_existing_project["email"]
    ).one_or_none()
    project_user_before_addition = models.ProjectUsers.query.filter(
        sqlalchemy.and_(
            models.ProjectUsers.user_id == user.user_id,
            models.ProjectUsers.project_id == project.id,
        )
    ).one_or_none()
    assert project_user_before_addition is None

    # release project
    response = client.post(
        tests.DDSEndpoint.PROJECT_STATUS,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["unituser"]).token(client),
        query_string={"project": project_id},
        data=json.dumps({"new_status": "Available"}),
        content_type="application/json",
    )
    assert response.status_code == http.HTTPStatus.OK
    assert project.current_status == "Available"

    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["unituser"]).token(client),
        query_string={"project": project_id},
        data=json.dumps(user_copy),
        content_type="application/json",
    )
    assert response.status_code == http.HTTPStatus.OK

    project_user_after_addition = models.ProjectUsers.query.filter(
        sqlalchemy.and_(
            models.ProjectUsers.user_id == user.user_id,
            models.ProjectUsers.project_id == project.id,
        )
    ).one_or_none()
    assert project_user_after_addition


def test_add_existing_user_to_nonexistent_proj(client):
    user_copy = existing_research_user_to_nonexistent_proj.copy()
    project = user_copy.pop("project")
    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["unituser"]).token(client),
        query_string={"project": project},
        data=json.dumps(user_copy),
        content_type="application/json",
    )
    assert response.status_code == http.HTTPStatus.BAD_REQUEST


def test_existing_user_change_ownership(client):
    project = models.Project.query.filter_by(
        public_id=change_owner_existing_user["project"]
    ).one_or_none()
    user = models.Email.query.filter_by(email=change_owner_existing_user["email"]).one_or_none()
    project_user = models.ProjectUsers.query.filter(
        sqlalchemy.and_(
            models.ProjectUsers.user_id == user.user_id,
            models.ProjectUsers.project_id == project.id,
        )
    ).one_or_none()

    assert not project_user.owner

    user_new_owner_status = change_owner_existing_user.copy()
    project = user_new_owner_status.pop("project")
    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["unituser"]).token(client),
        query_string={"project": project},
        data=json.dumps(user_new_owner_status),
        content_type="application/json",
    )

    assert response.status_code == http.HTTPStatus.OK

    db.session.refresh(project_user)

    assert project_user.owner


def test_existing_user_change_ownership_same_permissions(client):
    user_same_ownership = submit_with_same_ownership.copy()
    project = user_same_ownership.pop("project")
    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["unituser"]).token(client),
        query_string={"project": project},
        data=json.dumps(user_same_ownership),
        content_type="application/json",
    )
    assert response.status_code == http.HTTPStatus.FORBIDDEN


def test_add_existing_user_with_unsuitable_role(client):
    user_with_unsuitable_role = existing_research_user_to_existing_project.copy()
    user_with_unsuitable_role["role"] = "Unit Admin"
    project = user_with_unsuitable_role.pop("project")
    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["unituser"]).token(client),
        query_string={"project": project},
        data=json.dumps(user_with_unsuitable_role),
        content_type="application/json",
    )
    assert response.status_code == http.HTTPStatus.FORBIDDEN


### Tests for Invite-Project associations ###


def test_new_invite_with_project_by_unituser(client):
    "Test that a new invite including a project can be created"

    project = existing_project
    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["unituser"]).token(client),
        query_string={"project": project},
        data=json.dumps(first_new_user),
        content_type="application/json",
    )
    assert response.status_code == http.HTTPStatus.OK

    invited_user = models.Invite.query.filter_by(email=first_new_user["email"]).one_or_none()
    assert invited_user
    assert invited_user.email == first_new_user["email"]
    assert invited_user.role == first_new_user["role"]

    assert invited_user.nonce is not None
    assert invited_user.public_key is not None
    assert invited_user.private_key is not None

    project_associations = invited_user.project_associations
    assert len(project_associations) == 1
    assert project_associations[0].project.public_id == project

    project_invite_keys = invited_user.project_invite_keys
    assert len(project_invite_keys) == 1
    assert project_invite_keys[0].project.public_id == project


def test_add_project_to_existing_invite_by_unituser(client):
    "Test that a project can be associated with an existing invite"

    # Create invite upfront

    project = existing_project
    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["unituser"]).token(client),
        data=json.dumps(first_new_user),
        content_type="application/json",
    )
    assert response.status_code == http.HTTPStatus.OK

    invited_user = models.Invite.query.filter_by(email=first_new_user["email"]).one_or_none()

    # Check that the invite has no projects yet

    assert invited_user
    assert len(invited_user.project_associations) == 0
    assert len(invited_user.project_invite_keys) == 0

    # Add project to existing invite

    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["unituser"]).token(client),
        query_string={"project": project},
        data=json.dumps(first_new_user),
        content_type="application/json",
    )

    assert response.status_code == http.HTTPStatus.OK

    # Check that the invite has now a project association

    project_associations = invited_user.project_associations
    assert len(project_associations) == 1
    assert project_associations[0].project.public_id == project

    project_invite_keys = invited_user.project_invite_keys
    assert len(project_invite_keys) == 1
    assert project_invite_keys[0].project.public_id == project


def test_update_project_to_existing_invite_by_unituser(client):
    "Test that project ownership can be updated for an existing invite"

    # Create Invite upfront

    project = existing_project
    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["unituser"]).token(client),
        query_string={"project": project},
        data=json.dumps(first_new_user),
        content_type="application/json",
    )
    assert response.status_code == http.HTTPStatus.OK

    project_obj = models.Project.query.filter_by(public_id=existing_project).one_or_none()
    invite_obj = models.Invite.query.filter_by(email=first_new_user["email"]).one_or_none()

    project_invite = models.ProjectInvites.query.filter(
        sqlalchemy.and_(
            models.ProjectInvites.invite_id == invite_obj.id,
            models.ProjectUsers.project_id == project_obj.id,
        )
    ).one_or_none()

    assert project_invite
    assert not project_invite.owner

    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["unituser"]).token(client),
        query_string={"project": project},
        data=json.dumps(first_new_owner),
        content_type="application/json",
    )

    assert response.status_code == http.HTTPStatus.OK

    db.session.refresh(project_invite)

    assert project_invite.owner


def test_invite_to_project_by_project_owner(client):
    "Test that a project owner can invite to its project"

    project = existing_project
    response = client.post(
        tests.DDSEndpoint.USER_ADD,
        headers=tests.UserAuth(tests.USER_CREDENTIALS["projectowner"]).token(client),
        query_string={"project": project},
        data=json.dumps(first_new_user),
        content_type="application/json",
    )
    assert response.status_code == http.HTTPStatus.OK

    invited_user = models.Invite.query.filter_by(email=first_new_user["email"]).one_or_none()
    assert invited_user
    assert invited_user.email == first_new_user["email"]
    assert invited_user.role == first_new_user["role"]

    assert invited_user.nonce is not None
    assert invited_user.public_key is not None
    assert invited_user.private_key is not None

    project_associations = invited_user.project_associations
    assert len(project_associations) == 1
    assert project_associations[0].project.public_id == project

    project_invite_keys = invited_user.project_invite_keys
    assert len(project_invite_keys) == 1
    assert project_invite_keys[0].project.public_id == project
