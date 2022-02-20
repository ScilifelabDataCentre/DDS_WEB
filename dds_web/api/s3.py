"""S3 module"""

####################################################################################################
# IMPORTS ################################################################################ IMPORTS #
####################################################################################################

# Standard library

# Installed
import flask_restful
import flask
import sqlalchemy

# Own modules
from dds_web import auth
from dds_web.api.api_s3_connector import ApiS3Connector
from dds_web.api.dds_decorators import logging_bind_request
from dds_web.errors import S3ProjectNotFoundError, DatabaseError, DDSArgumentError
from dds_web.api.schemas import project_schemas

####################################################################################################
# ENDPOINTS ############################################################################ ENDPOINTS #
####################################################################################################


class S3Info(flask_restful.Resource):
    """Gets the projects S3 keys"""

    @auth.login_required
    @logging_bind_request
    def get(self):
        """Get the safespring project"""
        args = flask.request.args
        if not args:
            raise DDSArgumentError(message="Missing information required!")

        project = project_schemas.ProjectRequiredSchema().load(flask.request.args)

        try:
            sfsp_proj, keys, url, bucketname = ApiS3Connector(project=project).get_s3_info()
        except sqlalchemy.exc.SQLAlchemyError as sqlerr:
            raise DatabaseError(message=str(sqlerr))

        if any(x is None for x in [url, keys, bucketname]):
            raise S3ProjectNotFoundError("No s3 info returned!")

        return {
            "safespring_project": sfsp_proj,
            "url": url,
            "keys": keys,
            "bucket": bucketname,
        }
