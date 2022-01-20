"""User related endpoints e.g. authentication."""

####################################################################################################
# IMPORTS ################################################################################ IMPORTS #
####################################################################################################

# Standard library
import datetime
import pathlib
import secrets
import os
import smtplib

# Installed
import flask
import flask_restful
import flask_mail
import itsdangerous
import marshmallow
from jwcrypto import jwk, jwt
import pandas
import sqlalchemy
import pyotp

# Own modules
from dds_web import auth, mail, db, basic_auth, limiter
from dds_web.database import models
import dds_web.utils
import dds_web.forms
import dds_web.api.errors as ddserr
from dds_web.api.db_connector import DBConnector
from dds_web.api.schemas import project_schemas
from dds_web.api.schemas import user_schemas

# VARIABLES ############################################################################ VARIABLES #

ENCRYPTION_KEY_BIT_LENGTH = 256
ENCRYPTION_KEY_CHAR_LENGTH = int(ENCRYPTION_KEY_BIT_LENGTH / 8)

####################################################################################################
# FUNCTIONS ############################################################################ FUNCTIONS #
####################################################################################################


def encrypted_jwt_token(
    username, sensitive_content, expires_in=datetime.timedelta(hours=48), additional_claims=None
):
    """
    Encrypts a signed JWT token. This is to be used for any encrypted token regardless of the sensitive content.

    :param str username: Username must be obtained through authentication
    :param str or None sensitive_content: This is the content that must be protected by encryption.
        Can be set to None for protecting the signed token.
    :param timedelta expires_in: This is the maximum allowed age of the token. (default 2 days)
    :param Dict or None additional_claims: Any additional token claims can be added. e.g., {"iss": "DDS"}
    """
    token = jwt.JWT(
        header={"alg": "A256KW", "enc": "A256GCM"},
        claims=__signed_jwt_token(
            username=username,
            sensitive_content=sensitive_content,
            expires_in=expires_in,
            additional_claims=additional_claims,
        ),
    )
    key = jwk.JWK.from_password(flask.current_app.config.get("SECRET_KEY"))
    token.make_encrypted_token(key)
    return token.serialize()


def __signed_jwt_token(
    username,
    sensitive_content=None,
    expires_in=datetime.timedelta(hours=48),
    additional_claims=None,
):
    """
    Generic signed JWT token. This is to be used by both signed-only and signed-encrypted tokens.

    :param str username: Username must be obtained through authentication
    :param str or None sensitive_content: This is the content that must be protected by encryption. (default None)
    :param timedelta expires_in: This is the maximum allowed age of the token. (default 2 days)
    :param Dict or None additional_claims: Any additional token claims can be added. e.g., {"iss": "DDS"}
    """
    expiration_time = dds_web.utils.current_time() + expires_in
    data = {"sub": username, "exp": expiration_time.timestamp(), "nonce": secrets.token_hex(32)}
    if additional_claims is not None:
        data.update(additional_claims)
    if sensitive_content is not None:
        data["sen_con"] = sensitive_content

    key = jwk.JWK.from_password(flask.current_app.config.get("SECRET_KEY"))
    token = jwt.JWT(header={"alg": "HS256"}, claims=data, algs=["HS256"])
    token.make_signed_token(key)
    return token.serialize()


def jwt_token(username, expires_in=datetime.timedelta(hours=48), additional_claims=None):
    """
    Generates a signed JWT token. This is to be used for general purpose signed token.

    :param str username: Username must be obtained through authentication
    :param timedelta expires_in: This is the maximum allowed age of the token. (default 2 days)
    :param Dict or None additional_claims: Any additional token claims can be added. e.g., {"iss": "DDS"}
    """
    return __signed_jwt_token(
        username=username, expires_in=expires_in, additional_claims=additional_claims
    )


####################################################################################################
# ENDPOINTS ############################################################################ ENDPOINTS #
####################################################################################################
class AddUser(flask_restful.Resource):
    @auth.login_required
    def post(self):
        """Create an invite and send email."""

        args = flask.request.json

        project = args.pop("project", None)

        # Check if email is registered to a user
        existing_user = user_schemas.UserSchema().load(args)

        if not existing_user:
            # Send invite if the user doesn't exist
            invite_user_result = self.invite_user(args)
            return flask.make_response(
                flask.jsonify(invite_user_result), invite_user_result["status"]
            )
        else:
            # If there is an existing user, add them to project.
            if project:
                add_user_result = self.add_user_to_project(existing_user, project, args.get("role"))
                flask.current_app.logger.debug(f"Add user result?: {add_user_result}")
                return flask.make_response(
                    flask.jsonify(add_user_result), add_user_result["status"]
                )
            else:
                return flask.make_response(
                    flask.jsonify(
                        {
                            "message": "User exists! Specify a project if you want to add this user to a project."
                        }
                    ),
                    ddserr.error_codes["DDSArgumentError"]["status"],
                )

    @staticmethod
    def invite_user(args):
        """Invite a new user"""

        try:
            # Use schema to validate and check args, and create invite row
            new_invite = user_schemas.InviteUserSchema().load(args)

        except ddserr.InviteError as invite_err:
            return {
                "message": invite_err.description,
                "status": ddserr.error_codes["InviteError"]["status"].value,
            }

        except sqlalchemy.exc.SQLAlchemyError as sqlerr:
            raise ddserr.DatabaseError(message=str(sqlerr))
        except marshmallow.ValidationError as valerr:
            raise ddserr.InviteError(message=valerr.messages)

        # Create URL safe token for invitation link
        s = itsdangerous.URLSafeTimedSerializer(flask.current_app.config["SECRET_KEY"])
        token = s.dumps(new_invite.email, salt="email-confirm")

        # Create link for invitation email
        link = flask.url_for("auth_blueprint.confirm_invite", token=token, _external=True)

        # Compose and send email
        unit_name = None
        if auth.current_user().role in ["Unit Admin", "Unit Personnel"]:
            unit = auth.current_user().unit
            unit_name = unit.external_display_name
            unit_email = unit.contact_email
            sender_name = auth.current_user().name
            subject = f"{unit_name} invites you to the SciLifeLab Data Delivery System"
        else:
            sender_name = auth.current_user().name
            subject = f"{sender_name} invites you to the SciLifeLab Data Delivery System"

        msg = flask_mail.Message(
            subject,
            sender=flask.current_app.config["MAIL_SENDER_ADDRESS"],
            recipients=[new_invite.email],
        )

        # Need to attach the image to be able to use it
        msg.attach(
            "scilifelab_logo.png",
            "image/png",
            open(
                os.path.join(flask.current_app.static_folder, "img/scilifelab_logo.png"), "rb"
            ).read(),
            "inline",
            headers=[
                ["Content-ID", "<Logo>"],
            ],
        )

        msg.body = flask.render_template(
            "mail/invite.txt",
            link=link,
            sender_name=sender_name,
            unit_name=unit_name,
            unit_email=unit_email,
        )
        msg.html = flask.render_template(
            "mail/invite.html",
            link=link,
            sender_name=sender_name,
            unit_name=unit_name,
            unit_email=unit_email,
        )

        AddUser.send_email_with_retry(msg)

        # Append invite to unit if applicable
        if new_invite.role in ["Unit Admin", "Unit Personnel"]:
            auth.current_user().unit.invites.append(new_invite)
        else:
            db.session.add(new_invite)

        db.session.commit()

        # TODO: Format response with marshal with?
        return {"email": new_invite.email, "message": "Invite successful!", "status": 200}

    @staticmethod
    def send_email_with_retry(msg, times_retried=0):
        """Send email with retry on exception"""

        try:
            mail.send(msg)
        except smtplib.SMTPException as err:
            # Wait a little bit
            time.sleep(10)
            # Retry twice
            if times_retried < 2:
                retry = times_retried + 1
                AddUser.send_email_with_retry(msg, retry)

    @staticmethod
    def add_user_to_project(existing_user, project, role):
        """Add existing user to a project"""

        allowed_roles = ["Project Owner", "Researcher"]

        if role not in allowed_roles or existing_user.role not in allowed_roles:
            return {
                "status": 403,
                "message": "User Role should be either 'Project Owner' or 'Researcher' to be added to a project",
            }

        owner = False
        if role == "Project Owner":
            owner = True

        project = project_schemas.ProjectRequiredSchema().load({"project": project})
        ownership_change = False
        for rusers in project.researchusers:
            if rusers.researchuser is existing_user:
                if rusers.owner == owner:
                    return {
                        "status": 403,
                        "message": "User is already associated with the project in this capacity",
                    }

                ownership_change = True
                rusers.owner = owner
                break

        if not ownership_change:
            project.researchusers.append(
                models.ProjectUsers(
                    project_id=project.id,
                    user_id=existing_user.username,
                    owner=owner,
                )
            )

        try:
            db.session.commit()
        except (sqlalchemy.exc.SQLAlchemyError, sqlalchemy.exc.IntegrityError) as err:
            flask.current_app.logger.exception(err)
            db.session.rollback()
            message = "User was not associated with the project"
            raise ddserr.DatabaseError(message=f"Server Error: {message}")

        flask.current_app.logger.debug(
            f"User {existing_user.username} associated with project {project.public_id} as Owner={owner}."
        )

        return {
            "status": 200,
            "message": f"User {existing_user.username} associated with project {project.public_id} as Owner={owner}.",
        }


class RetrieveUserInfo(flask_restful.Resource):
    @auth.login_required
    def get(self):
        """Return own info when queried"""
        curr_user = auth.current_user()
        info = {}
        info["email_primary"] = curr_user.primary_email
        info["emails_all"] = [x.email for x in curr_user.emails]
        info["role"] = curr_user.role
        info["username"] = curr_user.username
        info["name"] = curr_user.name
        if "Unit" in curr_user.role and curr_user.is_admin:
            info["is_admin"] = curr_user.is_admin

        return {"info": info}


class DeleteUserSelf(flask_restful.Resource):
    """Endpoint to initiate user self removal from the system
    Every user can self-delete the own account with an e-mail confirmation.
    """

    @auth.login_required
    def delete(self):
        current_user = auth.current_user()

        email_str = current_user.primary_email

        username = current_user.username

        proj_ids = [proj.public_id for proj in current_user.projects]

        # Create URL safe token for invitation link
        s = itsdangerous.URLSafeTimedSerializer(flask.current_app.config["SECRET_KEY"])
        token = s.dumps(email_str, salt="email-delete")

        # Create deletion request in database unless it already exists
        try:
            if not dds_web.utils.delrequest_exists(email_str):
                new_delrequest = models.DeletionRequest(
                    **{
                        "requester": current_user,
                        "email": email_str,
                        "issued": dds_web.utils.current_time(),
                    }
                )
                db.session.add(new_delrequest)
                db.session.commit()
            else:
                return {
                    "message": f"The confirmation link has already been sent to your address {email_str}!",
                    "status": 200,
                }

        except sqlalchemy.exc.SQLAlchemyError as sqlerr:
            db.session.rollback()
            raise ddserr.DatabaseError(
                message=f"Creation of self-deletion request failed due to database error: {sqlerr}",
                pass_message=False,
            )

        # Create link for deletion request email
        link = flask.url_for("auth_blueprint.confirm_self_deletion", token=token, _external=True)
        subject = f"Confirm deletion of your user account {username} in the SciLifeLab Data Delivery System"
        projectnames = "; ".join(proj_ids)

        msg = flask_mail.Message(
            subject,
            sender=flask.current_app.config["MAIL_SENDER_ADDRESS"],
            recipients=[email_str],
        )

        # Need to attach the image to be able to use it
        msg.attach(
            "scilifelab_logo.png",
            "image/png",
            open(
                os.path.join(flask.current_app.static_folder, "img/scilifelab_logo.png"), "rb"
            ).read(),
            "inline",
            headers=[
                ["Content-ID", "<Logo>"],
            ],
        )

        msg.body = flask.render_template(
            "mail/deletion_request.txt",
            link=link,
            sender_name=current_user.name,
            projects=projectnames,
        )
        msg.html = flask.render_template(
            "mail/deletion_request.html",
            link=link,
            sender_name=current_user.name,
            projects=projectnames,
        )

        mail.send(msg)

        flask.current_app.logger.info(
            f"The user account {username} / {email_str} ({current_user.role}) has requested self-deletion."
        )

        return flask.make_response(
            flask.jsonify(
                {
                    "message": f"Requested account deletion initiated. An e-mail with a confirmation link has been sent to your address {email_str}!",
                }
            )
        )


class DeleteUser(flask_restful.Resource):
    """Endpoint to remove users from the system

    Unit admins can delete unitusers. Super admins can delete any user."""

    @auth.login_required(role=["Super Admin", "Unit Admin"])
    def delete(self):

        user = user_schemas.UserSchema().load(flask.request.json)
        if user is None:
            raise ddserr.UserDeletionError(
                message=f"This e-mail address is not associated with a user in the DDS, make sure it is not misspelled."
            )

        user_email_str = user.primary_email
        current_user = auth.current_user()

        if current_user.role == "Unit Admin":
            if user.role not in ["Unit Admin", "Unit Personnel"] or current_user.unit != user.unit:
                raise ddserr.UserDeletionError(
                    message=f"You are not allowed to delete this user. As a unit admin, you're only allowed to delete users in your unit."
                )

        if current_user == user:
            raise ddserr.UserDeletionError(
                message=f"To delete your own account, use the '--self' flag instead!"
            )

        DBConnector().delete_user(user)

        msg = f"The user account {user.username} ({user_email_str}, {user.role})  has been terminated successfully been by {current_user.name} ({current_user.role})."
        flask.current_app.logger.info(msg)

        return flask.make_response(
            flask.jsonify(
                {
                    "message": f"You successfully deleted the account {user.username} ({user_email_str}, {user.role})!"
                }
            )
        )


class RemoveUserAssociation(flask_restful.Resource):
    @auth.login_required
    def post(self):
        """Remove a user from a project"""

        args = flask.request.json

        project_id = args.pop("project")
        user_email = args.pop("email")

        # Check if email is registered to a user
        existing_user = user_schemas.UserSchema().load({"email": user_email})
        project = project_schemas.ProjectRequiredSchema().load({"project": project_id})

        if existing_user:
            user_in_project = False
            for user_association in project.researchusers:
                if user_association.user_id == existing_user.username:
                    user_in_project = True
                    db.session.delete(user_association)
            if user_in_project:
                try:
                    db.session.commit()
                    message = (
                        f"User with email {user_email} no longer associated with {project_id}."
                    )
                except (sqlalchemy.exc.SQLAlchemyError, sqlalchemy.exc.IntegrityError) as err:
                    flask.current_app.logger.exception(err)
                    db.session.rollback()
                    message = "Removing user association with the project has not succeeded"
                    raise ddserr.DatabaseError(message=f"Server Error: {message}")
            else:
                message = "User already not associated with this project"
            status = 200
            flask.current_app.logger.debug(
                f"User {existing_user.username} no longer associated with project {project.public_id}."
            )
        else:
            message = f"{user_email} already not associated with this project"
            status = ddserr.error_codes["NoSuchUserError"]["status"].value

        return {"message": message}, status


class Token(flask_restful.Resource):
    """Generates token for the user."""

    decorators = [
        limiter.limit(
            dds_web.utils.rate_limit_from_config,
            methods=["GET"],
            error_message=ddserr.error_codes["TooManyRequestsError"]["message"],
        )
    ]

    @basic_auth.login_required
    def get(self):
        return flask.jsonify({"token": jwt_token(username=auth.current_user().username)})


class EncryptedToken(flask_restful.Resource):
    """Generates encrypted token for the user."""

    decorators = [
        limiter.limit(
            dds_web.utils.rate_limit_from_config,
            methods=["GET"],
            error_message=ddserr.error_codes["TooManyRequestsError"]["message"],
        )
    ]

    @basic_auth.login_required
    def get(self):
        return flask.jsonify(
            {
                "token": encrypted_jwt_token(
                    username=auth.current_user().username, sensitive_content=None
                )
            }
        )


class ShowUsage(flask_restful.Resource):
    """Calculate and display the amount of GB hours and the total cost."""

    @auth.login_required(role=["Super Admin", "Unit Admin", "Unit Personnel"])
    def get(self):
        current_user = auth.current_user()

        # Check that user is unit account
        if current_user.role != "unit":
            raise ddserr.AccessDeniedError(
                "Access denied - only unit accounts can get invoicing information."
            )

        # Get unit info from table (incl safespring proj name)
        try:
            unit_info = models.Unit.query.filter(
                models.Unit.id == sqlalchemy.func.binary(current_user.unit_id)
            ).first()
        except sqlalchemy.exc.SQLAlchemyError as err:
            flask.current_app.logger.exception(err)
            raise ddserr.DatabaseError(f"Failed getting unit information.")

        # Total number of GB hours and cost saved in the db for the specific unit
        total_gbhours_db = 0.0
        total_cost_db = 0.0

        # Project (bucket) specific info
        usage = {}
        for p in unit_info.projects:

            # Define fields in usage dict
            usage[p.public_id] = {"gbhours": 0.0, "cost": 0.0}

            for f in p.files:
                for v in f.versions:
                    # Calculate hours of the current file
                    time_uploaded = v.time_uploaded
                    time_deleted = (
                        v.time_deleted if v.time_deleted else dds_web.utils.current_time()
                    )
                    file_hours = (time_deleted - time_uploaded).seconds / (60 * 60)

                    # Calculate GBHours, if statement to avoid zerodivision exception
                    gb_hours = ((v.size_stored / 1e9) / file_hours) if file_hours else 0.0

                    # Save file version gbhours to project info and increase total unit sum
                    usage[p.public_id]["gbhours"] += gb_hours
                    total_gbhours_db += gb_hours

                    # Calculate approximate cost per gbhour: kr per gb per month / (days * hours)
                    cost_gbhour = 0.09 / (30 * 24)
                    cost = gb_hours * cost_gbhour

                    # Save file cost to project info and increase total unit cost
                    usage[p.public_id]["cost"] += cost
                    total_cost_db += cost

            usage[p.public_id].update(
                {
                    "gbhours": round(usage[p.public_id]["gbhours"], 2),
                    "cost": round(usage[p.public_id]["cost"], 2),
                }
            )

        return flask.jsonify(
            {
                "total_usage": {
                    "gbhours": round(total_gbhours_db, 2),
                    "cost": round(total_cost_db, 2),
                },
                "project_usage": usage,
            }
        )


class InvoiceUnit(flask_restful.Resource):
    """Calculate the actual cost from the Safespring invoicing specification."""

    @auth.login_required(role=["Super Admin", "Unit Admin", "Unit Personnel"])
    def get(self):
        current_user = auth.current_user()

        # Check that user is unit account
        if current_user.role != "unit":
            raise ddserr.AccessDeniedError(
                "Access denied - only unit accounts can get invoicing information."
            )

        # Get unit info from table (incl safespring proj name)
        try:
            unit_info = models.Unit.query.filter(
                models.Unit.id == sqlalchemy.func.binary(current_user.unit_id)
            ).first()
        except sqlalchemy.exc.SQLAlchemyError as err:
            flask.current_app.logger.exception(err)
            raise ddserr.DatabaseError(f"Failed getting unit information.")

        # Get info from safespring invoice
        # TODO (ina): Move to another class or function - will be calling the safespring api
        csv_path = pathlib.Path("").parent / pathlib.Path("development/safespring_invoicespec.csv")
        csv_contents = pandas.read_csv(csv_path, sep=";", header=1)
        safespring_project_row = csv_contents.loc[csv_contents["project"] == unit_info.safespring]

        flask.current_app.logger.debug(safespring_project_row)

        return flask.jsonify({"test": "ok"})


class PublicKey(flask_restful.Resource):
    """Handle the user public key."""

    @auth.login_required(role=["Unit Admin", "Unit Personnel"])
    def post(self):
        """Add new public key to the user."""
        # Check that all args are ok
        if not flask.request.json:
            raise ddserr.DDSArgumentError("Missing public key.")

        public_key = flask.request.json.get("public")
        if not public_key:
            raise ddserr.DDSArgumentError("Missing public key.")

        # They should use reset if it's already setup but want to add a new public key
        if auth.current_user().public_key:
            raise ddserr.AccessDeniedError("There's already a public key pair setup.")

        # Set new public key
        auth.current_user().public_key = public_key
        try:
            db.session.commit()
        except Exception as err:
            flask.current_app.logger.error(err)
            raise ddserr.DatabaseError(err)

        return {"message": "Public key updated."}

    @auth.login_required(role=["Unit Admin", "Unit Personnel"])
    def put(self):
        """Update user public key."""
        # Verify correct args
        if not flask.request.json:
            raise ddserr.DDSArgumentError("Can't replace public key without a new one.")

        public_key = flask.request.json.get("public")
        if not public_key:
            raise ddserr.DDSArgumentError("Missing public key in args.")

        # Set new public key
        auth.current_user().public_key = public_key
        # 1. Query: filter rows corresponding to user and every project for unit
        # 2. Remove all of the rows or set to null?
        # 3. Send request to unit admin or someone else to add them to the project again

        try:
            db.session.commit()
        except Exception as err:
            flask.current_app.logger.error(err)
            raise ddserr.DatabaseError(err)

        return {
            "message": (
                "Public key updated, no project access at this time. "
                "Request has been send to unit administrator."
            )
        }


class ProjectAccess(flask_restful.Resource):
    """Manage unit user project access."""

    @auth.login_required(role=["Unit Admin", "Unit Personnel"])
    def get(self):
        """Get keys required for renewed access to unit projects.

        Get public key for user getting renewed access
        and project private keys belonging to current user.
        """
        # Check that args ok
        if not flask.request.json:
            raise ddserr.DDSArgumentError("Can't get user public key without user email.")

        email = flask.request.json.get("email")
        if not email:
            raise ddserr.DDSArgumentError("Missing email. Can't get public key for user.")

        user = user_schemas.UserSchema().load({"email": email})
        if not user:
            # I know we're not having this particular exception, this is an example
            raise ddserr.NoSuchUserError("Didn't find a user with the email specified.")

        public_key = user.public_key

        # Get all projectkey rows for current user
        # return the project private keys together with the public key above

        return {"public": public_key, "project_private": []}

    @auth.login_required(role=["Unit Admin", "Unit Personnel"])
    def post(self, email):
        """Add encrypted project private keys to user getting renewed access to unit projects."""
        # Check args ok
        if not flask.request.json:
            raise ddserr.DDSArgumentError("No keys found in request data.")

        keys = flask.request.json.get("keys")
        if not keys:
            raise ddserr.DDSArgumentError(
                "Key argument empty. Cannot update users access to projects."
            )

        email = flask.request.json.get("email")
        if not email:
            raise ddserr.DDSArgumentError("Email for user required to update project access.")

        public_key = flask.request.json.get("public")
        if not public_key:
            raise ddserr.DDSArgumentError(
                "Public key required to verify users possession of corresponding key."
            )

        user = user_schemas.UserSchema().load({"email": email})
        if not user:
            raise ddserr.NoSuchUserError("Could not find a user with the specified email.")

        if user.public_key != public_key:
            raise ddserr.AccessDeniedError(
                "This public key does not belong to this user. Will not replace the project private keys."
            )

        # 1. Add rows to ProjectKeys table / update the users specific rows
        # 2. commit
        # 3. Return message of success
