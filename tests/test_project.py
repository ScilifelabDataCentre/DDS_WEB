from base64 import b64encode
import json
from dds_web import db
from dds_web.database import models
import datetime

proj_data = {"pi": "piName", "title": "Test proj", "description": "A longer project description"}


def test_create_project_without_credentials(client):
    credentials = b64encode(b"username:password").decode("utf-8")
    response = client.post(
        "/api/v1/proj/create",
        headers={"Authorization": f"Basic {credentials}"},
        data=json.dumps(proj_data),
        content_type="application/json",
    )
    assert response.status == "403 FORBIDDEN"
    created_proj = (
        db.session.query(models.Project)
        .filter_by(
            created_by="username",
            title=proj_data["title"],
            pi=proj_data["pi"],
            description=proj_data["description"],
        )
        .one_or_none()
    )
    assert created_proj is None


def test_create_project_with_credentials(client):
    credentials = b64encode(b"admin:password").decode("utf-8")
    time_before_run = datetime.datetime.now()
    response = client.post(
        "/api/v1/proj/create",
        headers={"Authorization": f"Basic {credentials}"},
        data=json.dumps(proj_data),
        content_type="application/json",
    )
    assert response.status == "200 OK"
    created_proj = (
        db.session.query(models.Project)
        .filter_by(
            created_by="admin",
            title=proj_data["title"],
            pi=proj_data["pi"],
            description=proj_data["description"],
        )
        .one_or_none()
    )
    assert created_proj and created_proj.date_created > time_before_run


def test_create_project_without_title_description(client):
    credentials = b64encode(b"admin:password").decode("utf-8")
    response = client.post(
        "/api/v1/proj/create",
        headers={"Authorization": f"Basic {credentials}"},
        data=json.dumps({"pi": "piName"}),
        content_type="application/json",
    )
    assert response.status == "400 BAD REQUEST"
    created_proj = (
        db.session.query(models.Project)
        .filter_by(
            created_by="admin",
            pi=proj_data["pi"],
        )
        .one_or_none()
    )
    assert created_proj is None


def test_create_project_with_malformed_json(client):
    credentials = b64encode(b"admin:password").decode("utf-8")
    response = client.post(
        "/api/v1/proj/create",
        headers={"Authorization": f"Basic {credentials}"},
        data="",
        content_type="application/json",
    )
    assert response.status == "400 BAD REQUEST"
    created_proj = (
        db.session.query(models.Project)
        .filter_by(
            created_by="admin",
            title="",
            pi="",
            description="",
        )
        .one_or_none()
    )
    assert created_proj is None


def test_create_project_by_user_with_no_unit(client):
    credentials = b64encode(b"admin2:password").decode("utf-8")
    response = client.post(
        "/api/v1/proj/create",
        headers={"Authorization": f"Basic {credentials}"},
        data=json.dumps(proj_data),
        content_type="application/json",
    )
    assert response.status == "403 FORBIDDEN"
    created_proj = (
        db.session.query(models.Project)
        .filter_by(
            created_by="admin2",
            title=proj_data["title"],
            pi=proj_data["pi"],
            description=proj_data["description"],
        )
        .one_or_none()
    )
    assert created_proj is None
