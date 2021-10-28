"""File related schemas."""

####################################################################################################
# IMPORTS ################################################################################ IMPORTS #
####################################################################################################

# Standard Library

# Installed
import marshmallow
import sqlalchemy

# Own modules
from dds_web.database import models
import dds_web.utils
from dds_web.api.schemas import project_schemas

####################################################################################################
# SCHEMAS ################################################################################ SCHEMAS #
####################################################################################################


class NewFileSchema(project_schemas.ProjectRequiredSchema):
    """Validates and creates a new file object."""

    # Length minimum 1 required, required=True accepts empty string
    name = marshmallow.fields.String(required=True, validate=marshmallow.validate.Length(min=1))
    name_in_bucket = marshmallow.fields.String(
        required=True, validate=marshmallow.validate.Length(min=1)
    )
    subpath = marshmallow.fields.String(required=True, validate=marshmallow.validate.Length(min=1))
    size = marshmallow.fields.Integer(required=True)  # Accepts BigInt
    size_processed = marshmallow.fields.Integer(required=True)  # Accepts BigInt
    compressed = marshmallow.fields.Boolean(required=True)  # Accepts all truthy
    public_key = marshmallow.fields.String(
        required=True, validate=marshmallow.validate.Length(equal=64)
    )
    salt = marshmallow.fields.String(required=True, validate=marshmallow.validate.Length(equal=32))
    checksum = marshmallow.fields.String(
        required=True, validate=marshmallow.validate.Length(equal=64)
    )

    @marshmallow.validates_schema(skip_on_field_errors=True)
    def verify_file_not_exists(self, data, **kwargs):
        """Check that the file does not match anything already in the database."""

        # Check that there is no such file in the database
        project = data.get("project_row")
        try:
            file = (
                models.File.query.filter(
                    sqlalchemy.and_(
                        models.File.name == sqlalchemy.func.binary(data.get("name")),
                        models.File.project_id == sqlalchemy.func.binary(project.id),
                    )
                )
                .with_entities(models.File.id)
                .one_or_none()
            )
        except sqlalchemy.exc.SQLAlchemyError:
            raise

        if file:
            raise FileExistsError

    @marshmallow.post_load
    def return_items(self, data, **kwargs):
        """Create file object."""

        new_file = models.File(
            name=data.get("name"),
            name_in_bucket=data.get("name_in_bucket"),
            subpath=data.get("subpath"),
            size_original=data.get("size"),
            size_stored=data.get("size_processed"),
            compressed=data.get("compressed"),
            salt=data.get("salt"),
            public_key=data.get("public_key"),
            checksum=data.get("checksum"),
        )

        new_version = models.Version(
            size_stored=new_file.size_stored, time_uploaded=dds_web.utils.current_time()
        )

        project = data.get("project_row")
        # Update foreign keys
        project.file_versions.append(new_version)
        project.files.append(new_file)
        new_file.versions.append(new_version)

        return new_file
