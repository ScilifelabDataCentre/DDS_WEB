"""User related endpoints e.g. authentication."""

####################################################################################################
# IMPORTS ################################################################################ IMPORTS #
####################################################################################################

# Standard library

# Installed
import flask_restful
import flask
import structlog

# Own modules
from dds_web import auth, db
from dds_web.database import models
from dds_web.api.dds_decorators import json_required, logging_bind_request, handle_db_error
from dds_web import utils
import dds_web.errors as ddserr


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

        json_input = flask.request.json
        motd = json_input.get("message")
        if not motd:
            raise ddserr.DDSArgumentError(message="No MOTD specified.")

        flask.current_app.logger.debug(motd)
        new_motd = models.MOTD(message=motd)
        db.session.add(new_motd)
        db.session.commit()

        return {"message": "The MOTD was successfully added to the database."}

    @auth.login_required(role=["Super Admin"])
    @logging_bind_request
    @handle_db_error
    def get(self):
        """Return list of all active MOTDs to super admin."""
        active_motds = models.MOTD.query.filter_by(active=True).all()
        motd_info = [
            {
                "MOTD ID": m.id,
                "Message": m.message,
                "Created": m.date_created,
            }
            for m in active_motds
        ]

        return {
            "motds": motd_info,
            "keys": [
                "MOTD ID",
                "Message",
                "Created",
            ],
        }

    @auth.login_required(role=["Super Admin"])
    @logging_bind_request
    @json_required
    @handle_db_error
    def put(self):
        """Deactivate MOTDs."""

        json_input = flask.request.json
        motd_id = json_input.get("motd_id")
        if not motd_id:
            raise ddserr.DDSArgumentError(message="No MOTD for deactivation specified.")

        motd_to_deactivate = models.MOTD.query.filter_by(id=motd_id).first()
        if motd_to_deactivate.active == True:
            motd_to_deactivate.active = 0
            db.session.commit()

            return {"message": "The MOTD was successfully deactivated the database."}
        else:
            raise ddserr.DDSArgumentError(message=f"MOTD with id {motd_id} is not active.")
