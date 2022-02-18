"""User related endpoints e.g. authentication."""

####################################################################################################
# IMPORTS ################################################################################ IMPORTS #
####################################################################################################

# Standard library
import os
import smtplib
import time
import datetime

# Installed
import flask
import flask_restful
import flask_mail
import itsdangerous
import marshmallow
import structlog
import sqlalchemy
import http


# Own modules
from dds_web import auth, mail, db, basic_auth, limiter
from dds_web.database import models
import dds_web.utils
import dds_web.forms
import dds_web.errors as ddserr
from dds_web.api.schemas import project_schemas, user_schemas, token_schemas
from dds_web.api.dds_decorators import logging_bind_request
from dds_web.security.project_user_keys import (
    generate_invite_key_pair,
    share_project_private_key,
)
from dds_web.security.tokens import encrypted_jwt_token, update_token_with_mfa
from dds_web.security.auth import get_user_roles_common


# initiate bound logger
action_logger = structlog.getLogger("actions")

####################################################################################################
# ENDPOINTS ############################################################################ ENDPOINTS #
####################################################################################################
class AddUser(flask_restful.Resource):
    @auth.login_required(role=["Super Admin", "Unit Admin", "Unit Personnel", "Project Owner"])
    @logging_bind_request
    def post(self):
        """Associate existing users or unanswered invites with projects or create invites"""
        args = flask.request.args
        json_info = flask.request.json
        if not json_info:
            raise ddserr.DDSArgumentError(
                message="Missing required information, cannot add or invite."
            )

        project = args.get("project") if args else None
        role = json_info.get("role")
        email = json_info.get("email")

        # A project may or may not be specified
        if project:
            project = project_schemas.ProjectRequiredSchema().load({"project": project})

        if not email:
            raise ddserr.DDSArgumentError(message="Email adress required to add or invite.")

        # Check if email is registered to a user
        existing_user = user_schemas.UserSchema().load({"email": email})
        unanswered_invite = user_schemas.UnansweredInvite().load({"email": email})

        if existing_user or unanswered_invite:
            if project and role:
                whom = existing_user or unanswered_invite
                add_user_result = self.add_to_project(whom=whom, project=project, role=role)
                flask.current_app.logger.debug(f"Add user result?: {add_user_result}")
                return add_user_result, add_user_result["status"]
            else:
                raise ddserr.DDSArgumentError(
                    message="This user was already added to the system. Specify the project you wish to give access to."
                )

        else:
            if not role:
                raise ddserr.DDSArgumentError(message="No user role specified.")

            # Send invite if the user doesn't exist
            if project:
                invite_user_result = self.invite_user(
                    email=email, new_user_role=role, project=project
                )
            else:
                invite_user_result = self.invite_user(email=email, new_user_role=role)

            return invite_user_result, invite_user_result["status"]

    @staticmethod
    @logging_bind_request
    def invite_user(email, new_user_role, project=None):
        """Invite a new user"""

        current_user_role = get_user_roles_common(user=auth.current_user())

        # Verify role or current and new user
        if current_user_role == "Super Admin" and project:
            return {
                "status": ddserr.InviteError.code.value,
                "message": (
                    "Super Admins do not have project data access and can therefore "
                    "not invite users to specific projects."
                ),
            }
        elif current_user_role == "Unit Admin" and new_user_role == "Super Admin":
            raise ddserr.AccessDeniedError()
        elif current_user_role == "Unit Personnel" and new_user_role in [
            "Super Admin",
            "Unit Admin",
        ]:
            raise ddserr.AccessDeniedError()
        elif current_user_role == "Project Owner":
            if new_user_role in ["Super Admin", "Unit Admin", "Unit Personnel"]:
                raise ddserr.AccessDeniedError()
            elif new_user_role in ["Project Owner", "Researcher"] and not project:
                raise ddserr.DDSArgumentError(
                    message="Project ID required to invite users to projects."
                )
        elif current_user_role == "Researcher":
            raise ddserr.AccessDeniedError()

        # Create invite row
        new_invite = models.Invite(email=email, role=new_user_role)

        # Create URL safe token for invitation link
        token = encrypted_jwt_token(
            username="",
            sensitive_content=generate_invite_key_pair(invite=new_invite).hex(),
            expires_in=datetime.timedelta(
                hours=flask.current_app.config["INVITATION_EXPIRES_IN_HOURS"]
            ),
            additional_claims={"inv": new_invite.email},
        )

        # Create link for invitation email
        link = flask.url_for("auth_blueprint.confirm_invite", token=token, _external=True)

        # Quick search gave this as the URL length limit.
        if len(link) >= 2048:
            flask.current_app.logger.error(
                "Invitation link was not possible to create due to length."
            )
            return {
                "message": "Invite failed due to server error",
                "status": http.HTTPStatus.INTERNAL_SERVER_ERROR,
            }

        # Compose and send email
        AddUser.compose_and_send_email_to_user(userobj=new_invite, mail_type="invite", link=link)

        # Append invite to unit if applicable
        if new_invite.role in ["Unit Admin", "Unit Personnel"]:
            if "Unit" in auth.current_user().role:
                # Give new unit user access to all projects of the unit
                auth.current_user().unit.invites.append(new_invite)
                for unit_project in auth.current_user().unit.projects:
                    if unit_project.is_active:
                        share_project_private_key(
                            from_user=auth.current_user(),
                            to_another=new_invite,
                            from_user_token=dds_web.security.auth.obtain_current_encrypted_token(),
                            project=unit_project,
                        )

                if project:  # specified project is disregarded for unituser invites
                    msg = f"{str(new_invite)} was successful."
                else:
                    msg = f"{str(new_invite)} was successful, but specification for {str(project)} dropped. Unit Users have automatic access to projects of their unit."

        else:
            db.session.add(new_invite)
            if project:
                project.invites.append(
                    models.ProjectInvites(
                        project_id=project.id,
                        invite_id=new_invite.id,
                        owner=new_invite.role == "Project Owner",
                    )
                )
                share_project_private_key(
                    from_user=auth.current_user(),
                    to_another=new_invite,
                    project=project,
                    from_user_token=dds_web.security.auth.obtain_current_encrypted_token(),
                )

        db.session.commit()
        msg = f"{str(new_invite)} was successful."

        return {
            "email": new_invite.email,
            "message": msg,
            "status": http.HTTPStatus.OK,
        }

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
    @logging_bind_request
    def add_to_project(whom, project, role):
        """Add existing user to a project"""

        allowed_roles = ["Project Owner", "Researcher"]

        if role not in allowed_roles or whom.role not in allowed_roles:
            return {
                "status": ddserr.AccessDeniedError.code.value,
                "message": (
                    "User Role should be either 'Project Owner' or "
                    "'Researcher' to be added to a project"
                ),
            }

        owner = role == "Project Owner"
        ownership_change = False

        if isinstance(whom, models.ResearchUser):
            link = project.researchusers
        else:
            link = project.invites

        for rusers in link:
            if rusers.researchuser == whom:
                if rusers.owner == owner:
                    return {
                        "status": ddserr.RoleException.code.value,
                        "message": f"{str(whom)} is already associated with the {str(project)} in this capacity. ",
                    }

                ownership_change = True
                rusers.owner = owner
                break

        if not ownership_change:
            if isinstance(whom, models.ResearchUser):
                project.researchusers.append(
                    models.ProjectUsers(
                        project_id=project.id,
                        user_id=whom.username,
                        owner=owner,
                    )
                )
            else:
                project.invites.append(
                    models.ProjectInvites(
                        project_id=project.id,
                        invite_id=whom.id,
                        owner=owner,
                    )
                )

            share_project_private_key(
                from_user=auth.current_user(),
                to_another=whom,
                from_user_token=dds_web.security.auth.obtain_current_encrypted_token(),
                project=project,
            )

        try:
            db.session.commit()
        except (sqlalchemy.exc.SQLAlchemyError, sqlalchemy.exc.IntegrityError) as err:
            flask.current_app.logger.exception(err)
            db.session.rollback()
            raise ddserr.DatabaseError(
                message=f"Server Error: User was not associated with the project"
            )

        # If project is already released and not expired, send mail to user
        if project.current_status == "Available":
            AddUser.compose_and_send_email_to_user(whom, "project_release", project=project)

        flask.current_app.logger.debug(
            f"{str(whom)} was associated with {str(project)} as Owner={owner}."
        )

        return {
            "status": http.HTTPStatus.OK,
            "message": (f"{str(whom)} was associated with " f"{str(project)} as Owner={owner}."),
        }

    @staticmethod
    @logging_bind_request
    def compose_and_send_email_to_user(userobj, mail_type, link=None, project=None):
        """Compose and send email"""
        if hasattr(userobj, "emails"):
            recipients = [x.email for x in userobj.emails]
        else:
            # userobj likely an invite
            recipients = [userobj.email]

        unit_name = None
        unit_email = None
        project_id = None
        deadline = None
        if auth.current_user().role in ["Unit Admin", "Unit Personnel"]:
            unit = auth.current_user().unit
            unit_name = unit.external_display_name
            unit_email = unit.contact_email
            sender_name = auth.current_user().name
            subject_subject = unit_name

        else:
            sender_name = auth.current_user().name
            subject_subject = sender_name

        # Fill in email subject with sentence subject
        if mail_type == "invite":
            subject = f"{subject_subject} invites you to the SciLifeLab Data Delivery System"
        elif mail_type == "project_release":
            subject = f"Project made available by {subject_subject} in the SciLifeLab Data Delivery System"
            project_id = project.public_id
            deadline = project.current_deadline.astimezone(datetime.timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S %Z"
            )
        else:
            raise ddserr.DDSArgumentError(message="Invalid mail type!")

        msg = flask_mail.Message(
            subject,
            recipients=recipients,
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
            f"mail/{mail_type}.txt",
            link=link,
            sender_name=sender_name,
            unit_name=unit_name,
            unit_email=unit_email,
            project_id=project_id,
            deadline=deadline,
        )
        msg.html = flask.render_template(
            f"mail/{mail_type}.html",
            link=link,
            sender_name=sender_name,
            unit_name=unit_name,
            unit_email=unit_email,
            project_id=project_id,
            deadline=deadline,
        )

        AddUser.send_email_with_retry(msg)


class RetrieveUserInfo(flask_restful.Resource):
    @auth.login_required
    @logging_bind_request
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
    @logging_bind_request
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
                    "message": (
                        "The confirmation link has already "
                        f"been sent to your address {email_str}!"
                    ),
                    "status": http.HTTPStatus.OK,
                }

        except sqlalchemy.exc.SQLAlchemyError as sqlerr:
            db.session.rollback()
            raise ddserr.DatabaseError(
                message=f"Creation of self-deletion request failed due to database error: {sqlerr}",
            )

        # Create link for deletion request email
        link = flask.url_for("auth_blueprint.confirm_self_deletion", token=token, _external=True)
        subject = f"Confirm deletion of your user account {username} in the SciLifeLab Data Delivery System"
        projectnames = "; ".join(proj_ids)

        msg = flask_mail.Message(
            subject,
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
            f"The user account {username} / {email_str} ({current_user.role}) "
            "has requested self-deletion."
        )

        return {
            "message": (
                "Requested account deletion initiated. An e-mail with a "
                f"confirmation link has been sent to your address {email_str}!"
            ),
        }


class UserActivation(flask_restful.Resource):
    """Endpoint to reactivate/deactivate users in the system

    Unit admins can reactivate/deactivate unitusers. Super admins can reactivate/deactivate any user."""

    @auth.login_required(role=["Super Admin", "Unit Admin"])
    @logging_bind_request
    def post(self):
        # Verify that user specified
        extra_args = flask.request.json
        if not extra_args:
            raise DDSArgumentError(message="Required information missing.")

        if "email" not in extra_args:
            raise DDSArgumentError(message="User email missing.")

        user = user_schemas.UserSchema().load({"email": extra_args.pop("email")})
        if not user:
            raise ddserr.NoSuchUserError()

        # Verify that the action is specified -- reactivate or deactivate
        action = flask.request.json.get("action")
        if action is None or action == "":
            raise ddserr.DDSArgumentError(
                message="Please provide an action 'deactivate' or 'reactivate' for this request."
            )

        user_email_str = user.primary_email
        current_user = auth.current_user()

        if current_user.role == "Unit Admin":
            if user.role not in ["Unit Admin", "Unit Personnel"] or current_user.unit != user.unit:
                raise ddserr.AccessDeniedError(
                    message=(
                        f"You are not allowed to {action} this user. As a unit admin, "
                        f"you're only allowed to {action} users in your unit."
                    )
                )

        if current_user == user:
            raise ddserr.AccessDeniedError(message=f"You cannot {action} your own account!")

        if (action == "reactivate" and user.is_active) or (
            action == "deactivate" and not user.is_active
        ):
            raise ddserr.DDSArgumentError(message="User is already in desired state!")

        # TODO: Check if user has lost access to any projects and if so, grant access again.
        if action == "reactivate":
            user.active = True

            # TODO: Super admins (current_user) don't have access to projects currently, how handle this?
            list_of_projects = None
            if user.role in ["Project Owner", "Researcher"]:
                list_of_projects = [x.project for x in user.project_associations]
            elif user.role in ["Unit Personnel", "Unit Admin"]:
                list_of_projects = user.unit.projects

            from dds_web.api.project import ProjectAccess  # Needs to be here because of circ.import

            ProjectAccess.give_project_access(
                project_list=list_of_projects, current_user=current_user, user=user
            )

        else:
            user.active = False

        try:
            db.session.commit()
        except sqlalchemy.exc.SQLAlchemyError as err:
            db.session.rollback()
            raise ddserr.DatabaseError(message=str(err))
        msg = (
            f"The user account {user.username} ({user_email_str}, {user.role}) "
            f" has been {action}d successfully been by {current_user.name} ({current_user.role})."
        )
        flask.current_app.logger.info(msg)

        with structlog.threadlocal.bound_threadlocal(
            who={"user": user.username, "role": user.role},
            by_whom={"user": current_user.username, "role": current_user.role},
        ):
            action_logger.info(self.__class__)

        return {
            "message": (
                f"You successfully {action}d the account {user.username} "
                f"({user_email_str}, {user.role})!"
            )
        }


class DeleteUser(flask_restful.Resource):
    """Endpoint to remove users from the system

    Unit admins can delete unitusers. Super admins can delete any user."""

    @auth.login_required(role=["Super Admin", "Unit Admin"])
    @logging_bind_request
    def delete(self):

        user = user_schemas.UserSchema().load(flask.request.json)
        if not user:
            raise ddserr.UserDeletionError(
                message=(
                    "This e-mail address is not associated with a user in the DDS, "
                    "make sure it is not misspelled."
                )
            )

        user_email_str = user.primary_email
        current_user = auth.current_user()

        if current_user.role == "Unit Admin":
            if user.role not in ["Unit Admin", "Unit Personnel"] or current_user.unit != user.unit:
                raise ddserr.UserDeletionError(
                    message=(
                        "You are not allowed to delete this user. As a unit admin, "
                        "you're only allowed to delete users in your unit."
                    )
                )

        if current_user == user:
            raise ddserr.UserDeletionError(
                message="To delete your own account, use the '--self' flag instead!"
            )

        self.delete_user(user)

        msg = (
            f"The user account {user.username} ({user_email_str}, {user.role}) has been "
            f"terminated successfully been by {current_user.name} ({current_user.role})."
        )
        flask.current_app.logger.info(msg)

        with structlog.threadlocal.bound_threadlocal(
            who={"user": user.username, "role": user.role},
            by_whom={"user": current_user.username, "role": current_user.role},
        ):
            action_logger.info(self.__class__)

        return {
            "message": (
                f"You successfully deleted the account {user.username} "
                f"({user_email_str}, {user.role})!"
            )
        }

    @staticmethod
    def delete_user(user):
        try:
            parent_user = models.User.query.get(user.username)
            db.session.delete(parent_user)
            db.session.commit()
        except sqlalchemy.exc.SQLAlchemyError as err:
            db.session.rollback()
            raise ddserr.DatabaseError(message=str(err))


class RemoveUserAssociation(flask_restful.Resource):
    @auth.login_required
    @logging_bind_request
    def post(self):
        """Remove a user from a project"""

        project_id = flask.request.args.get("project")

        args = flask.request.json
        user_email = args.pop("email")

        # Check if email is registered to a user
        existing_user = user_schemas.UserSchema().load({"email": user_email})
        project = project_schemas.ProjectRequiredSchema().load({"project": project_id})

        if not existing_user:
            raise ddserr.NoSuchUserError(
                f"The user with email '{user_email}' does not have access to the specified project."
                " Cannot remove non-existent project access."
            )

        user_in_project = False
        for user_association in project.researchusers:
            if user_association.user_id == existing_user.username:
                user_in_project = True
                db.session.delete(user_association)
                project_user_key = models.ProjectUserKeys.query.filter_by(
                    project_id=project.id, user_id=existing_user.username
                ).first()
                if project_user_key:
                    db.session.delete(project_user_key)

        if not user_in_project:
            raise ddserr.NoSuchUserError(
                f"The user with email '{user_email}' does not have access to the specified project."
                " Cannot remove non-existent project access."
            )

        try:
            db.session.commit()
        except (sqlalchemy.exc.SQLAlchemyError, sqlalchemy.exc.IntegrityError) as err:
            flask.current_app.logger.exception(err)
            db.session.rollback()
            raise ddserr.DatabaseError(
                message=(
                    "Server Error: Removing user association with the project has not succeeded"
                )
            )

        flask.current_app.logger.debug(
            f"User {existing_user.username} no longer associated with project {project.public_id}."
        )

        return {"message": f"User with email {user_email} no longer associated with {project_id}."}


class EncryptedToken(flask_restful.Resource):
    """Generates encrypted token for the user."""

    decorators = [
        limiter.limit(
            dds_web.utils.rate_limit_from_config,
            methods=["GET"],
            error_message=ddserr.TooManyRequestsError.description,
        )
    ]

    @basic_auth.login_required
    @logging_bind_request
    def get(self):
        return {
            "message": "Please take this token to /user/second_factor to authenticate with MFA!",
            "token": encrypted_jwt_token(
                username=auth.current_user().username,
                sensitive_content=flask.request.authorization.get("password"),
            ),
        }


class SecondFactor(flask_restful.Resource):
    """Take in and verify an authentication one-time code entered by an authenticated user with basic credentials"""

    @auth.login_required
    def get(self):

        args = flask.request.json or {}

        token_schemas.TokenSchema().load(args)

        token_claims = dds_web.security.auth.obtain_current_encrypted_token_claims()

        return {"token": update_token_with_mfa(token_claims)}


class ShowUsage(flask_restful.Resource):
    """Calculate and display the amount of GB hours and the total cost."""

    @auth.login_required(role=["Super Admin", "Unit Admin", "Unit Personnel"])
    @logging_bind_request
    def get(self):
        current_user = auth.current_user()

        # Check that user is unit account
        if current_user.role not in ["Unit Admin", "Unit Personnel"]:
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
            raise ddserr.DatabaseError("Failed getting unit information.")

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

        return {
            "total_usage": {
                "gbhours": round(total_gbhours_db, 2),
                "cost": round(total_cost_db, 2),
            },
            "project_usage": usage,
        }
