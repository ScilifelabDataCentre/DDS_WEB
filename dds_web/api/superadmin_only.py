"""User related endpoints e.g. authentication."""

####################################################################################################
# IMPORTS ################################################################################ IMPORTS #
####################################################################################################

# Standard library
import functools
import os
from time import process_time_ns
import typing

# Installed
import flask_restful
import flask
import structlog
import flask_mail

# Own modules
from dds_web import auth, db, mail
from dds_web.api import dds_decorators
from dds_web.database import models
from dds_web.api.dds_decorators import json_required, logging_bind_request, handle_db_error
from dds_web import utils
import dds_web.errors as ddserr
from dds_web.api.user import AddUser


# initiate bound logger
action_logger = structlog.getLogger("actions")

####################################################################################################
# ENDPOINTS ############################################################################ ENDPOINTS #
####################################################################################################


class AllUnits(flask_restful.Resource):
    """Get unit info."""

    @auth.login_required(role=["Super Admin"])
    @logging_bind_request
    @handle_db_error
    def get(self):
        """Return info about unit to super admin."""
        all_units = models.Unit.query.all()

        unit_info = [
            {
                "Name": u.name,
                "Public ID": u.public_id,
                "External Display Name": u.external_display_name,
                "Contact Email": u.contact_email,
                "Safespring Endpoint": u.safespring_endpoint,
                "Days In Available": u.days_in_available,
                "Days In Expired": u.days_in_expired,
                "Size": u.size,
            }
            for u in all_units
        ]

        return {
            "units": unit_info,
            "keys": [
                "Name",
                "Public ID",
                "External Display Name",
                "Days In Available",
                "Days In Expired",
                "Safespring Endpoint",
                "Contact Email",
                "Size",
            ],
        }


class MOTD(flask_restful.Resource):
    """Add a new MOTD message."""

    @auth.login_required(role=["Super Admin"])
    @logging_bind_request
    @json_required
    @handle_db_error
    def post(self):
        """Add a MOTD."""

        curr_date = utils.current_time()
        json_input = flask.request.json
        motd = json_input.get("message")
        if not motd:
            raise ddserr.DDSArgumentError(message="No MOTD specified.")

        flask.current_app.logger.debug(motd)
        new_motd = models.MOTD(message=motd)
        db.session.add(new_motd)
        db.session.commit()

        return {"message": "The MOTD was successfully added to the database."}

    @handle_db_error
    def get(self):
        """Return list of all active MOTDs to super admin."""
        active_motds = models.MOTD.query.filter_by(active=True).all()
        if not active_motds:
            return {"message": "There are no active MOTDs."}

        motd_info = [
            {
                "MOTD ID": m.id,
                "Message": m.message,
                "Created": m.date_created.strftime("%Y-%m-%d %H:%M"),
            }
            for m in active_motds
        ]

        return {"motds": motd_info, "keys": ["MOTD ID", "Message", "Created"]}

    @auth.login_required(role=["Super Admin"])
    @logging_bind_request
    @json_required
    @handle_db_error
    def put(self):
        """Deactivate MOTDs."""
        # Get motd id
        json_input = flask.request.json
        motd_id = json_input.get("motd_id")
        if not motd_id:
            raise ddserr.DDSArgumentError(message="No MOTD for deactivation specified.")

        # Get motd row from db
        motd_to_deactivate = models.MOTD.query.filter_by(id=motd_id).first()
        if not motd_to_deactivate:
            raise ddserr.DDSArgumentError(
                message=f"MOTD with id {motd_id} does not exist in the database"
            )

        # Check if motd is active
        if not motd_to_deactivate.active:
            raise ddserr.DDSArgumentError(message=f"MOTD with id {motd_id} is not active.")

        motd_to_deactivate.active = False
        db.session.commit()

        return {"message": "The MOTD was successfully deactivated in the database."}


class SendMOTD(flask_restful.Resource):
    """Send a MOTD to all users in database."""

    @auth.login_required(role=["Super Admin"])
    @logging_bind_request
    @json_required
    @handle_db_error
    def post(self):
        """Send MOTD as email to users."""
        # Get MOTD ID
        motd_id: int = flask.request.json.get("motd_id")
        if not motd_id or not isinstance(motd_id, int):  # The id starts at 1 - ok to not accept 0
            raise ddserr.DDSArgumentError(
                message="Please specify the ID of the MOTD you want to send."
            )

        # Get MOTD object
        motd_obj: models.MOTD = models.MOTD.query.get(motd_id)
        if not motd_obj or not motd_obj.active:
            raise ddserr.DDSArgumentError(message=f"There is no active MOTD with ID '{motd_id}'.")

        # Create email content
        # put motd_obj.message etc in there etc
        subject: str = "DDS Important Information"
        body: str = flask.render_template(f"mail/motd.txt", motd=motd_obj.message)
        html = flask.render_template(f"mail/motd.html", motd=motd_obj.message)

        # Setup email connection
        import threading

        start_time = process_time_ns()
        with mail.connect() as conn:
            # Email users
            user_emails = (
                db.session.query(models.Email)
                .filter(models.Email.primary == True)
                .with_entities(models.Email.email)
            )
            for email in utils.page_query(user_emails):
                msg = flask_mail.Message(
                    subject=subject, recipients=[email[0]], body=body, html=html
                )
                msg.attach(
                    "scilifelab_logo.png",
                    "image/png",
                    open(
                        os.path.join(flask.current_app.static_folder, "img/scilifelab_logo.png"),
                        "rb",
                    ).read(),
                    "inline",
                    headers=[
                        ["Content-ID", "<Logo>"],
                    ],
                )
                # Send email
                utils.send_email_with_retry(msg=msg, obj=conn)

        end_time = process_time_ns()

        # 184261050
        # 255691735

        flask.current_app.logger.info(f"Time taken: {end_time-start_time}")
        return {"message": f"MOTD '{motd_id}' has been sent to the users."}


class FindUser(flask_restful.Resource):
    """Get all users or check if there a specific user in the database."""

    @auth.login_required(role=["Super Admin"])
    @logging_bind_request
    @json_required
    @handle_db_error
    def get(self):
        """Return users or a confirmation on if one exists."""
        user_to_find = flask.request.json.get("username")
        if not user_to_find:
            raise ddserr.DDSArgumentError(
                message="Username required to check existence of account."
            )

        return {
            "exists": models.User.query.filter_by(username=user_to_find).one_or_none() is not None
        }


class ResetTwoFactor(flask_restful.Resource):
    """Deactivate TOTP and activate HOTP for other user, e.g. if phone lost."""

    @auth.login_required(role=["Super Admin"])
    @logging_bind_request
    @json_required
    @handle_db_error
    def put(self):
        """Change totp to hotp."""
        # Check that username is specified
        username: str = flask.request.json.get("username")
        if not username:
            raise ddserr.DDSArgumentError(message="Username required to reset 2FA to HOTP")

        # Verify valid user
        user: models.User = models.User.query.filter_by(username=username).one_or_none()
        if not user:
            raise ddserr.DDSArgumentError(message=f"The user doesn't exist: {username}")

        # TOTP needs to be active in order to deactivate
        if not user.totp_enabled:
            raise ddserr.DDSArgumentError(message="TOTP is already deactivated for this user.")

        user.deactivate_totp()

        return {
            "message": f"TOTP has been deactivated for user: {user.username}. They can now use 2FA via email during authentication."
        }


class SetMaintenance(flask_restful.Resource):
    """Change the maintenance mode of the system."""

    @auth.login_required(role=["Super Admin"])
    @logging_bind_request
    @json_required
    @handle_db_error
    def put(self):
        """Change the Maintenance mode."""
        # Get desired maintenance mode
        json_input = flask.request.json
        setting = json_input.get("state")
        if not setting:
            raise ddserr.DDSArgumentError(message="Please, specify an argument: on or off")

        # Get maintenance row from db
        current_mode = models.Maintenance.query.first()
        if not current_mode:
            raise ddserr.DDSArgumentError(message="There's no row in the Maintenance table.")

        # Activate maintenance if currently inactive
        if setting not in ["on", "off"]:
            raise ddserr.DDSArgumentError(message="Please, specify the correct argument: on or off")

        current_mode.active = setting == "on"
        db.session.commit()

        return {"message": f"Maintenance set to: {setting.upper()}"}


class AnyProjectsBusy(flask_restful.Resource):
    """Check if any projects are busy."""

    @auth.login_required(role=["Super Admin"])
    @logging_bind_request
    @handle_db_error
    def get(self):
        """Check if any projects are busy."""
        # Get busy projects
        projects_busy: typing.List = models.Project.query.filter_by(busy=True).all()
        num_busy: int = len(projects_busy)

        # Set info to always return nu
        return_info: typing.Dict = {"num": num_busy}

        # Return 0 if none are busy
        if num_busy == 0:
            return return_info

        # Check if user listing busy projects
        json_input = flask.request.json
        if json_input and json_input.get("list") is True:
            return_info.update({"projects": {p.public_id: p.date_updated for p in projects_busy}})

        return return_info
