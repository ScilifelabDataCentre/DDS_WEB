"""Project module."""

####################################################################################################
# IMPORTS ################################################################################ IMPORTS #
####################################################################################################

# Standard Library

# Installed
import flask_restful
import flask
import sqlalchemy
from cryptography.hazmat.primitives.kdf import scrypt
from nacl.bindings import crypto_aead_chacha20poly1305_ietf_decrypt as decrypt
from cryptography.hazmat import backends
import os
import marshmallow
import datetime
import botocore

# Own modules
import dds_web.utils
from dds_web import auth, db
from dds_web.database import models
from dds_web.api.api_s3_connector import ApiS3Connector
from dds_web.api.db_connector import DBConnector
from dds_web.api.errors import (
    DDSArgumentError,
    DatabaseError,
    AccessDeniedError,
    EmptyProjectException,
    DeletionError,
    BucketNotFoundError,
    KeyNotFoundError,
    S3ConnectionError,
)
from dds_web.api.user import AddUser
from dds_web.api.schemas import project_schemas
from dds_web.api.schemas import user_schemas


####################################################################################################
# ENDPOINTS ############################################################################ ENDPOINTS #
####################################################################################################
class ProjectStatus(flask_restful.Resource):
    """Get and update Project status"""

    @auth.login_required
    def get(self):
        """Get current project status and optionally entire status history"""
        project = project_schemas.ProjectRequiredSchema().load(flask.request.args)
        extra_args = flask.request.json
        return_info = {"current_status": project.current_status}

        if extra_args and extra_args.get("history") == True:
            history = []
            for pstatus in project.project_statuses:
                history.append(tuple((pstatus.status, pstatus.date_created)))
            history.sort(key=lambda x: x[1], reverse=True)
            return_info.update({"history": history})

        return flask.jsonify(return_info)

    @auth.login_required(role=["Super Admin", "Unit Admin", "Unit Personnel"])
    def post(self):
        """Update Project Status"""
        # Project row
        project = project_schemas.ProjectRequiredSchema().load(flask.request.args)
        public_id = project.public_id

        # Get status
        extra_args = flask.request.json
        new_status = extra_args.get("new_status")

        # Timestamp for current time
        curr_date = dds_web.utils.current_time()

        # Additional message
        additional_message = None

        if not self.is_transition_possible(project.current_status, new_status):
            raise DDSArgumentError("Invalid status transition")

        try:
            if new_status == "In Progress":
                new_status_row = self.retract(
                    project=project,
                    current_time=curr_date,
                )
            elif new_status == "Available":
                # Optional int arg deadline in days
                new_status_row = self.release(
                    project=project,
                    current_time=curr_date,
                    deadline=extra_args.get("deadline", project.responsible_unit.days_in_available),
                )
            elif new_status == "Expired":
                new_status_row = self.expire(
                    project=project,
                    current_time=curr_date,
                    deadline=extra_args.get("deadline", project.responsible_unit.days_in_expired),
                )
            elif new_status == "Deleted":
                new_status_row, additional_message = self.delete(
                    project=project, current_time=curr_date
                )
            elif new_status == "Archived":
                new_status_row, additional_message = self.archive(
                    project=project,
                    current_time=curr_date,
                    abort=extra_args.get("is_aborted", False),
                )

            project.project_statuses.append(new_status_row)
            db.session.commit()
        except (
            sqlalchemy.exc.SQLAlchemyError,
            TypeError,
            DatabaseError,
            DeletionError,
            BucketNotFoundError,
        ) as err:
            flask.current_app.logger.exception(err)
            db.session.rollback()
            raise DatabaseError(message="Server Error: Status was not updated")

        return flask.jsonify(
            {"message": f"{public_id} updated to status {new_status}" + (additional_message or "")}
        )

    @staticmethod
    def retract(project, current_time):

        new_status_row = models.ProjectStatuses(
            project_id=project.id,
            status="In Progress",
            date_created=current_time,
            deadline=project.current_deadline,
        )
        return new_status_row

    @staticmethod
    def release(project, current_time, deadline):
        new_deadline = dds_web.utils.current_time(to_midnight=True) + datetime.timedelta(
            days=deadline
        )
        if project.current_status == "Expired":
            # Project can only move from Expired 2 times
            if project.times_expired > 2:
                raise DDSArgumentError(
                    "Project availability limit: Project cannot be made Available any more times"
                )
        else:  # current status is in progress
            if project.has_been_available:
                # No change in deadline if made available before
                new_deadline = project.current_deadline
            else:
                project.released = current_time

        new_status_row = models.ProjectStatuses(
            project_id=project.id,
            status="Available",
            date_created=current_time,
            deadline=new_deadline,
        )
        return new_status_row

    @staticmethod
    def expire(project, current_time, deadline):
        new_deadline = dds_web.utils.current_time(to_midnight=True) + datetime.timedelta(
            days=deadline
        )
        new_status_row = models.ProjectStatuses(
            project_id=project.id,
            status="Expired",
            date_created=current_time,
            deadline=new_deadline,
        )
        return new_status_row

    @staticmethod
    def delete(project, current_time):

        # Can only be Deleted if never made Available
        if project.has_been_available:
            raise DDSArgumentError(
                "Project cannot be deleted if it has ever been made available, abort it instead"
            )

        new_status_row = models.ProjectStatuses(
            project_id=project.id,
            status="Deleted",
            date_created=current_time,
        )

        _ = RemoveContents().delete_project_contents(project)
        ProjectStatus().delete_project_info(project=project)
        additoinal_message = f"\nAll files in {project.public_id} deleted"

        return new_status_row, additional_message

    @staticmethod
    def archive(project, current_time, abort=False):
        if project.current_status == "In Progress":
            if not (project.has_been_available and abort):
                raise DDSArgumentError(
                    "Project cannot be archived from this status but can be aborted if it has ever been made available"
                )

        new_status_row = models.ProjectStatuses(
            project_id=project.id, status="Archived", date_created=current_time, is_aborted=abort
        )
        _ = RemoveContents().delete_project_contents(project)
        additoinal_message = f"\nAll files in {project.public_id} deleted"
        if aborted:
            ProjectStatus().delete_project_info(project=project)
            additoinal_message += " and project info cleared"
        return new_status_row, additional_message

    @staticmethod
    def is_transition_possible(current_status, new_status):
        """Check if the transition is valid"""
        if new_status not in [
            "In Progress",
            "Deleted",
            "Available",
            "Expired",
            "Archived",
        ]:
            raise DDSArgumentError("Invalid status")

        status_transitions = {
            "In Progress": ["Available", "Delete", "Archived"],
            "Available": ["In Progress", "Expired", "Archived"],
            "Expired": ["Available", "Archived"],
        }

        possible_transitions = status_transitions.get(current_status)
        if possible_transitions and new_status in possible_transitions:
            return True

        return False

    @classmethod
    def delete_project_info(cls, project):
        """Delete certain metadata from proj on deletion/abort"""
        project.public_id = None
        project.title = None
        project.date_created = None
        project.date_updated = None
        project.description = None
        project.pi = None
        project.public_key = None
        project.private_key = None
        project.privkey_salt = None
        project.privkey_nonce = None
        project.is_sensitive = None
        project.unit_id = None
        project.created_by = None
        # Delete User associations
        for user in project.researchusers:
            db.session.delete(user)


class GetPublic(flask_restful.Resource):
    """Gets the public key beloning to the current project."""

    @auth.login_required
    def get(self):
        """Get public key from database."""

        project = project_schemas.ProjectRequiredSchema().load(flask.request.args)

        # TODO: Change logging
        flask.current_app.logger.debug("Getting the public key.")

        public_key = None
        if project.is_sensitive:
            if not project.public_key:
                raise KeyNotFoundError(project=project.public_id)

            public_key = project.public_key

        return flask.jsonify({"sensitive": project.is_sensitive, "public": public_key})


class GetPrivate(flask_restful.Resource):
    """Gets the private key belonging to the current project."""

    @auth.login_required
    def get(self):
        """Get private key from database"""

        project = project_schemas.ProjectRequiredSchema().load(flask.request.args)

        # TODO (ina): Change handling of private key -- not secure
        flask.current_app.logger.debug("Getting the private key.")

        app_secret = flask.current_app.config.get("SECRET_KEY")
        passphrase = app_secret.encode("utf-8")

        enc_key = bytes.fromhex(project.private_key)
        nonce = bytes.fromhex(project.privkey_nonce)
        salt = bytes.fromhex(project.privkey_salt)

        kdf = scrypt.Scrypt(
            salt=salt,
            length=32,
            n=2 ** 14,
            r=8,
            p=1,
            backend=backends.default_backend(),
        )

        key_enc_key = kdf.derive(passphrase)
        try:
            decrypted_key = decrypt(ciphertext=enc_key, aad=None, nonce=nonce, key=key_enc_key)
        except Exception as err:
            flask.current_app.logger.exception(err)
            raise KeyNotFoundError

        return flask.jsonify({"private": decrypted_key.hex().upper()})


class UserProjects(flask_restful.Resource):
    """Gets all projects registered to a specific user."""

    @auth.login_required
    def get(self):
        """Get info regarding all projects which user is involved in."""
        current_user = auth.current_user()

        # TODO: Return different things depending on if unit or not
        all_projects = list()

        # Total number of GB hours and cost saved in the db for the specific unit
        total_bhours_db = 0.0
        total_cost_db = 0.0
        total_size = 0

        usage = flask.request.args.get("usage") == "True" and current_user.role in [
            "Super Admin",
            "Unit Admin",
            "Unit Personnel",
        ]

        # Get info for all projects
        for p in current_user.projects:
            project_info = {
                "Project ID": p.public_id,
                "Title": p.title,
                "PI": p.pi,
                "Status": p.current_status,
                "Last updated": p.date_updated if p.date_updated else p.date_created,
                "Size": p.size,
            }

            # Get proj size and update total size
            proj_size = p.size
            total_size += proj_size
            project_info["Size"] = proj_size

            if usage:
                proj_bhours, proj_cost = DBConnector().project_usage(p)
                total_bhours_db += proj_bhours
                total_cost_db += proj_cost
                # return ByteHours
                project_info.update({"Usage": proj_bhours, "Cost": proj_cost})

            all_projects.append(project_info)

        return_info = {
            "project_info": all_projects,
            "total_usage": {
                # return ByteHours
                "usage": total_bhours_db,
                "cost": total_cost_db,
            },
            "total_size": total_size,
        }

        return flask.jsonify(return_info)


class RemoveContents(flask_restful.Resource):
    """Removes all project contents."""

    @auth.login_required(role=["Super Admin", "Unit Admin", "Unit Personnel"])
    def delete(self):
        """Removes all project contents."""

        project = project_schemas.ProjectRequiredSchema().load(flask.request.args)

        # Delete files
        if not project.files:
            raise EmptyProjectException("The are no project contents to delete.")
        try:
            removed = self.delete_project_contents(project)
            if removed:
                db.session.commit()
            else:
                db.session.rollback()
        except sqlalchemy.exc.SQLAlchemyError as err:
            raise DatabaseError(message=str(err))
        except DatabaseError as err:
            raise DeletionError(
                message=f"No project contents deleted: {err}",
                project=project.public_id,
            )
        except (DeletionError, BucketNotFoundError):
            raise

        return flask.jsonify({"removed": True})

    @staticmethod
    def delete_project_contents(project):
        """Remove project contents"""
        DBConnector(project=project).delete_all()

        removed = False
        # Delete from bucket
        with ApiS3Connector(project=project) as s3conn:
            removed = s3conn.remove_all()

        return removed


class CreateProject(flask_restful.Resource):
    @auth.login_required(role=["Super Admin", "Unit Admin", "Unit Personnel"])
    def post(self):
        """Create a new project"""
        # Get project info from request
        project_info = flask.request.json

        # Create new project with user specified info
        new_project = project_schemas.CreateProjectSchema().load(project_info)
        if not new_project:
            raise DDSArgumentError("Failed to create project.")

        # TODO: Change -- the bucket should be created before the row is added to the database
        # This is a quick fix so that things do not break
        try:
            with ApiS3Connector(project=new_project) as s3:
                s3.resource.create_bucket(Bucket=new_project.bucket)
        except botocore.exceptions.ClientError as err:
            # For now just keeping the project row
            raise S3ConnectionError(str(err))

        # TODO: Change logging
        flask.current_app.logger.debug(
            f"Project {new_project.public_id} created by user {auth.current_user().username}."
        )

        user_addition_statuses = []
        if "users_to_add" in project_info:
            for user in project_info["users_to_add"]:
                existing_user = user_schemas.UserSchema().load(user)
                if not existing_user:
                    # Send invite if the user doesn't exist
                    invite_user_result = AddUser.invite_user(
                        {
                            "email": user.get("email"),
                            "role": user.get("role"),
                        }
                    )
                    if invite_user_result["status"] == 200:
                        invite_msg = f"Invitation sent to {user['email']}. The user should have a valid account to be added to a project"
                    else:
                        invite_msg = invite_user_result["message"]
                    user_addition_statuses.append(invite_msg)
                else:
                    # If it is an existing user, add them to project.
                    addition_status = ""
                    try:
                        add_user_result = AddUser.add_user_to_project(
                            existing_user=existing_user,
                            project=new_project.public_id,
                            role=user.get("role"),
                        )
                    except DatabaseError as err:
                        addition_status = f"Error for {user['email']}: {err.description}"
                    else:
                        addition_status = add_user_result["message"]
                    user_addition_statuses.append(addition_status)

        return flask.jsonify(
            {
                "status": 200,
                "message": "Added new project '{}'".format(new_project.title),
                "project_id": new_project.public_id,
                "user_addition_statuses": user_addition_statuses,
            }
        )


class ProjectUsers(flask_restful.Resource):
    """Get all users in a specific project."""

    @auth.login_required
    def get(self):

        project = project_schemas.ProjectRequiredSchema().load(flask.request.args)

        # Get info on research users
        research_users = list()

        for user in project.researchusers:
            user_info = {
                "User Name": user.user_id,
                "Primary email": "",
            }
            for user_email in user.researchuser.emails:
                if user_email.primary:
                    user_info["Primary email"] = user_email.email
            research_users.append(user_info)

        return flask.jsonify({"research_users": research_users})
