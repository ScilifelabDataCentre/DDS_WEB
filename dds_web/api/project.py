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


# Own modules
import dds_web.utils
from dds_web import auth, db
from dds_web.database import models
from dds_web.api.api_s3_connector import ApiS3Connector
from dds_web.api.db_connector import DBConnector
from dds_web.api.errors import (
    MissingProjectIDError,
    DatabaseError,
    NoSuchProjectError,
    AccessDeniedError,
    EmptyProjectException,
    DeletionError,
    BucketNotFoundError,
    DDSArgumentError,
    KeyNotFoundError,
)
from dds_web.crypt import key_gen
from dds_web.api import marshmallows

####################################################################################################
# ENDPOINTS ############################################################################ ENDPOINTS #
####################################################################################################


class GetPublic(flask_restful.Resource):
    """Gets the public key beloning to the current project."""

    @auth.login_required
    def get(self):
        """Get public key from database."""

        project = marshmallows.ProjectRequiredSchema().load(flask.request.args)

        flask.current_app.logger.debug("Getting the public key.")

        if not project.public_key:
            raise KeyNotFoundError(project=project.public_id)

        return flask.jsonify({"public": project.public_key})


class GetPrivate(flask_restful.Resource):
    """Gets the private key belonging to the current project."""

    @auth.login_required
    def get(self):
        """Get private key from database"""

        project = marshmallows.ProjectRequiredSchema().load(flask.request.args)

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
            return flask.make_response(str(err), 500)

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
        total_gbhours_db = 0.0
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
                "Status": p.status,
                "Last updated": p.date_updated if p.date_updated else p.date_created,
                "Size": dds_web.utils.add_unit_prefix(p.size, unit="B"),
            }

            # Get proj size and update total size
            proj_size = sum([f.size_stored for f in p.files])
            total_size += proj_size
            project_info["Size"] = dds_web.utils.add_unit_prefix(proj_size, unit="B")

            if usage:
                proj_gbhours, proj_cost = DBConnector().project_usage(p)
                total_gbhours_db += proj_gbhours
                total_cost_db += proj_cost

                project_info.update(
                    {
                        "GBHours": str(proj_gbhours),
                        "Cost": f"{dds_web.utils.add_unit_prefix(proj_cost, unit=' SEK')}",
                    }
                )

            all_projects.append(project_info)

        return_info = {
            "project_info": all_projects,
            "total_usage": {
                "gbhours": f"{dds_web.utils.add_unit_prefix(total_gbhours_db)}"
                if total_gbhours_db > 1.0
                else str(0),
                "cost": f"{dds_web.utils.add_unit_prefix(total_cost_db, unit=' SEK')}"
                if total_cost_db > 1.0
                else f"0 kr",
            },
            "total_size": dds_web.utils.add_unit_prefix(total_size, unit="B"),
        }

        return flask.jsonify(return_info)


class RemoveContents(flask_restful.Resource):
    """Removes all project contents."""

    @auth.login_required(role=["Super Admin", "Unit Admin", "Unit Personnel"])
    def delete(self):
        """Removes all project contents."""

        project = marshmallows.ProjectRequiredSchema().load(flask.request.args)

        # Delete files
        removed = False
        with DBConnector(project=project) as dbconn:
            try:
                removed = dbconn.delete_all()
            except (DatabaseError, EmptyProjectException):
                raise

            # Return error if contents not deleted from db
            if not removed:
                raise DeletionError(
                    message="No project contents deleted.",
                    username=current_user.username,
                    project=project.public_id,
                )

            # Delete from bucket
            try:
                with ApiS3Connector(project=project) as s3conn:
                    removed = s3conn.remove_all()

                    # Return error if contents not deleted from s3 bucket
                    if not removed:
                        db.session.rollback()
                        raise DeletionError(
                            message="Deleting project contents failed.",
                            username=current_user.username,
                            project=project.public_id,
                        )

                    # Commit changes to db
                    db.session.commit()
            except sqlalchemy.exc.SQLAlchemyError as err:
                raise DatabaseError(message=str(err))
            except (DeletionError, BucketNotFoundError):
                raise

        return flask.jsonify({"removed": removed})


class UpdateProjectSize(flask_restful.Resource):
    @auth.login_required(role=["Super Admin", "Unit Admin", "Unit Personnel"])
    def put(self):
        """Update the project size and updated time stamp."""

        project = marshmallows.ProjectRequiredSchema().load(flask.request.args)

        updated, error = (False, "")
        current_try, max_tries = (1, 5)
        while current_try < max_tries:
            try:
                tot_file_size = (
                    models.File.query.with_entities(
                        sqlalchemy.func.sum(models.File.size_original).label("sizeSum")
                    )
                    .filter(models.File.project_id == project.id)
                    .first()
                )

                project.size = tot_file_size.sizeSum
                project.date_updated = dds_web.utils.current_time()

                db.session.commit()
            except sqlalchemy.exc.SQLAlchemyError as err:
                flask.current_app.logger.exception(err)
                db.session.rollback()
                current_try += 1
            else:
                flask.current_app.logger.debug("Updated project size!")
                updated = True
                break

        return flask.jsonify({"updated": updated, "error": error, "tries": current_try})


class CreateProject(flask_restful.Resource):
    @auth.login_required(role=["Super Admin", "Unit Admin", "Unit Personnel"])
    def post(self):
        """Create a new project"""

        if flask.request.is_json:
            try:
                p_info = flask.request.json
            except:
                raise DDSArgumentError(message="Error: Malformed data provided")
        else:
            raise DDSArgumentError(message="Error: Malformed data provided")

        if "title" not in p_info or "description" not in p_info:
            raise DDSArgumentError(
                message="Error: Title/description missing when creating a project"
            )
        cur_user = auth.current_user()
        # Add check for user permissions

        created_time = dds_web.utils.current_time()

        try:
            # lock Unit row
            unit_row = (
                db.session.query(models.Unit)
                .filter_by(id=cur_user.unit_id)
                .with_for_update()
                .one_or_none()
            )

            if not unit_row:
                raise AccessDeniedError(message=f"Error: Your user is not associated to a unit.")

            unit_row.counter = unit_row.counter + 1 if unit_row.counter else 1
            public_id = "{}{:03d}".format(unit_row.internal_ref, unit_row.counter)

            project_info = {
                "created_by": auth.current_user().username,
                "public_id": public_id,
                "title": p_info["title"],
                "date_created": created_time,
                "date_updated": created_time,
                "status": "Ongoing",  # ?
                "description": p_info["description"],
                "pi": p_info.get("pi", ""),  # Not a foreign key, only a name
                "size": 0,
                "bucket": self.__create_bucket_name(public_id, created_time),
            }
            pkg = key_gen.ProjectKeys(project_info["public_id"])
            project_info.update(pkg.key_dict())

            if "sensitive" in p_info:
                project_info["is_sensitive"] = p_info["sensitive"]

            new_project = models.Project(**project_info)
            unit_row.projects.append(new_project)
            # cur_user.unit = unit_row
            cur_user.created_projects.append(new_project)

            db.session.commit()

        except (sqlalchemy.exc.SQLAlchemyError, TypeError) as err:
            flask.current_app.logger.exception(err)
            db.session.rollback()
            raise DatabaseError(message="Server Error: Project was not created")

        else:
            flask.current_app.logger.debug(
                f"Project {public_id} created by user {cur_user.username}."
            )
            return flask.jsonify(
                {
                    "status": 200,
                    "message": "Added new project '{}'".format(new_project.title),
                    "project_id": new_project.public_id,
                }
            )

    def __create_bucket_name(self, public_id, created_time):
        """Create a bucket name for the given project"""
        return "{pid}-{tstamp}-{rstring}".format(
            pid=public_id.lower(),
            tstamp=dds_web.utils.timestamp(dts=created_time, ts_format="%y%m%d%H%M%S%f"),
            rstring=os.urandom(4).hex(),
        )


class ProjectUsers(flask_restful.Resource):
    """Get all users in a specific project."""

    @auth.login_required
    def get(self):

        project = marshmallows.ProjectRequiredSchema().load(flask.request.args)

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
