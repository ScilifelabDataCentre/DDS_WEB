"""API DB Connector module"""

###############################################################################
# IMPORTS ########################################################### IMPORTS #
###############################################################################

# Standard library
import traceback

# Installed
import flask
import sqlalchemy

# Own modules
from code_dds.api.errors import BucketNameNotFoundError, ProjectSizeError, \
    DBFileError, FolderSizeError, FileDeletionError, FileRetrievalError
from code_dds.common.db_code import models
from code_dds import db
from code_dds.api.dds_decorators import token_required

###############################################################################
# CLASSES ########################################################### CLASSES #
###############################################################################


@token_required
class DBConnector:
    """Class for performing database actions."""

    def __init__(self, *args, **kwargs):

        try:
            self.current_user, self.project = args
        except ValueError as err:
            flask.abort(500, str(err))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, tb):
        if exc_type is not None:
            traceback.print_exception(exc_type, exc_value, tb)
            return False  # uncomment to pass exception through

        return True

    def get_bucket_name(self):
        """Get bucket name from database"""

        bucketname, error = (None, "")
        try:
            bucket = models.Project.query.filter_by(
                id=self.project["id"]
            ).with_entities(
                models.Project.bucket
            ).first()
        except sqlalchemy.exc.SQLAlchemyError as err:
            error = str(err)
        else:
            bucketname = bucket[0]

        return bucketname, error

    def filename_in_bucket(self, filename):
        """Get filename in bucket."""

        print(f"File in db: {filename}", flush=True)
        name_in_bucket, error = (None, "")
        try:
            file = models.File.query.filter_by(
                project_id=self.project["id"]
            ).all()
        except sqlalchemy.exc.SQLAlchemyError as err:
            error = str(err)
            print(error, flush=True)
        else:
            name_in_bucket = file[0]

        return name_in_bucket, error

    def project_size(self):
        """Get size of project"""

        num_proj_files, error = (0, "")
        try:
            num_proj_files = models.Project.query.filter_by(
                id=self.project["id"]
            ).with_entities(models.Project.project_files).count()
        except sqlalchemy.exc.SQLAlchemyError as err:
            error = str(err)

        return num_proj_files, error

    def items_in_subpath(self, folder="."):
        """Get all items in root folder of project"""

        distinct_files, distinct_folders, error = ([], [], "")
        # Get everything in root:
        # Files have subpath "." and folders do not have child folders
        # Get everything in folder:
        # Files have subpath == folder and folders have child folders (regexp)
        try:
            # All files in project
            files = models.File.query.filter_by(
                project_id=self.project["id"]
            )

            # File names in root
            distinct_files = files.filter(
                models.File.subpath == folder
            ).with_entities(
                models.File.name, models.File.size
            ).all()

            # Folder names in folder (or root)
            distinct_folders = files.filter(
                sqlalchemy.and_(
                    (~models.File.subpath.contains(["/"]) if folder == "."
                     else
                     models.File.subpath.op("regexp")(f"^{folder}(\/[^\/]+)?$")),
                    models.File.subpath != folder
                )
            ).with_entities(models.File.subpath).distinct().all()
        except sqlalchemy.exc.SQLAlchemyError as err:
            error = str(err)

        return distinct_files, distinct_folders, error

    def folder_size(self, folder_name="."):
        """Get total size of folder"""

        tot_file_size, error = (None, "")
        try:
            file_info = models.File.query.with_entities(
                sqlalchemy.func.sum(models.File.size).label("sizeSum")
            ).filter(
                sqlalchemy.and_(
                    models.File.project_id == self.project["id"],
                    models.File.subpath.like(f"{folder_name}%")
                )
            ).first()
        except sqlalchemy.exc.SQLAlchemyError as err:
            error = str(err)
        else:
            tot_file_size = file_info.sizeSum

        return tot_file_size, error

    def delete_all(self):
        """Delete all files in project."""

        deleted, error = (False, "")
        try:
            models.File.query.filter_by(project_id=self.project["id"]).delete()
        except sqlalchemy.exc.SQLAlchemyError as err:
            db.session.rollback()
            error = str(err)
        else:
            deleted = True

        return deleted, error

    def delete_one(self, filename):
        """Delete all files in project."""

        exists, deleted, name_in_bucket, error = (False, False, None, "")
        try:
            file = models.File.query.filter_by(
                name=filename,
                project_id=self.project["id"]
            ).first()
        except sqlalchemy.exc.SQLAlchemyError as err:
            error = str(err)
        
        if file and file is not None:
            exists, name_in_bucket = (True, file.name_in_bucket)
            try:
                db.session.delete(file)
            except sqlalchemy.exc.SQLAlchemyError as err:
                db.session.rollback()
                error = str(err)
            else:
                deleted = True

        return exists, deleted, name_in_bucket, error
