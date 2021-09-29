"""Database table models."""

####################################################################################################
# IMPORTS ################################################################################ IMPORTS #
####################################################################################################

# Standard library
import datetime

# Installed
import pytz

# Own modules
from dds_web import db, C_TZ
import dds_web.utils

####################################################################################################
# MODELS ################################################################################## MODELS #
####################################################################################################


class Unit(db.Model):
    """Data model for unit accounts."""

    # Table setup
    __tablename__ = "units"
    __table_args__ = {"extend_existing": True}

    # Columns
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    public_id = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255), unique=True, nullable=False)
    internal_ref = db.Column(db.String(50), unique=True, nullable=False)
    safespring = db.Column(db.String(255), unique=False, nullable=False)  # unique=True later
    days_to_expire = db.Column(db.Integer, unique=False, nullable=False, default=30)
    counter = db.Column(db.Integer, unique=False, nullable=True)

    # Relationships
    # One unit can have many users
    users = db.relationship("User", backref="unit")
    # One unit can have many projects
    projects = db.relationship("Project", backref="responsible_unit")

    def __repr__(self):
        """Called by print, creates representation of object"""

        return f"<Unit {self.public_id}>"


class ProjectUsers(db.Model):
    __tablename__ = "projectusers"

    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), primary_key=True)
    user_id = db.Column(db.String(50), db.ForeignKey("users.username"), primary_key=True)

    owner = db.Column(db.Boolean, nullable=False, default=False)

    project = db.relationship("Project", back_populates="users")
    user = db.relationship("User", back_populates="projects")


# project_users = db.Table(
#     "project_users",
#     db.Column("project_id", db.Integer, db.ForeignKey("projects.id")),
#     db.Column("user", db.String(50), db.ForeignKey("users.username")),
# )


class Project(db.Model):
    """Data model for projects."""

    # Table setup
    __tablename__ = "projects"
    __table_args__ = {"extend_existing": True}

    # Columns
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # Foreign key -- One unit can have many projects
    unit_id = db.Column(db.Integer, db.ForeignKey("units.id"))

    public_id = db.Column(db.String(255), unique=True, nullable=False)
    title = db.Column(db.Text, unique=False, nullable=False)
    date_created = db.Column(
        db.DateTime(),
        nullable=False,
        default=dds_web.utils.current_time(),
    )
    date_updated = db.Column(db.DateTime(), nullable=True)
    status = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    pi = db.Column(db.String(255), unique=False, nullable=False)
    size = db.Column(db.BigInteger, unique=False, nullable=False)
    bucket = db.Column(db.String(255), unique=True, nullable=False)
    public_key = db.Column(db.String(64), nullable=False)
    private_key = db.Column(db.String(255), nullable=False)
    privkey_salt = db.Column(db.String(32), nullable=False)
    privkey_nonce = db.Column(db.String(24), nullable=False)

    # Relationships
    # One project can have many files
    files = db.relationship("File", backref="project")
    expired_files = db.relationship("ExpiredFile", backref="assigned_project")

    # One project can have many file versions
    file_versions = db.relationship("Version", backref="responsible_project")

    users = db.relationship("ProjectUsers", back_populates="project")

    def __repr__(self):
        """Called by print, creates representation of object"""

        return f"<Project {self.public_id}>"


class User(db.Model):
    """Data model for user accounts - base user model for all user types."""

    # Table setup
    __tablename__ = "users"
    __table_args__ = {"extend_existing": True}

    # Columns
    username = db.Column(db.String(50), primary_key=True, autoincrement=False)

    # Foreign keys - One unit can have many users
    unit_id = db.Column(db.Integer, db.ForeignKey("units.id"))

    password = db.Column(db.String(98), unique=False, nullable=False)
    role = db.Column(db.String(20), unique=False, nullable=False)
    name = db.Column(db.String(255), unique=False, nullable=True)

    type = db.Column(db.String(20), unique=False, nullable=False)

    # Relationships
    # One user can have many projects, and one projects can have many users
    # projects = db.relationship(
    #     "Project", secondary=project_users, backref=db.backref("users", lazy="dynamic")
    # )
    projects = db.relationship("ProjectUsers", back_populates="user")

    # One user can have many identifiers
    identifiers = db.relationship("Identifier", back_populates="user", cascade="all, delete-orphan")

    # One user can have many email addresses
    emails = db.relationship("Email", backref="users", lazy="dynamic", cascade="all, delete-orphan")

    __mapper_args__ = {"polymorphic_on": type}

    def __repr__(self):
        """Called by print, creates representation of object"""

        return f"<User {self.username}>"


class ResearchUser(User):
    """Data model for research user accounts."""

    __mapper_args__ = {"polymorphic_identity": "researchuser"}


class Identifier(db.Model):
    """
    Data model for user identifiers for login.

    Elixir identifiers consists of 58 characters (40 hex + "@elixir-europe.org").
    """

    # Table setup
    __tablename__ = "identifiers"
    __table_args__ = {"extend_existing": True}

    # Columns
    # Foreign keys
    username = db.Column(db.String(50), db.ForeignKey("users.username"), primary_key=True)
    identifier = db.Column(db.String(58), primary_key=True, unique=True, nullable=False)
    user = db.relationship("User", back_populates="identifiers")

    def __repr__(self):
        """Called by print, creates representation of object"""

        return f"<Identifier {self.identifier}>"


class Email(db.Model):
    """
    Data model for user email addresses.
    """

    # Table setup
    __tablename__ = "emails"
    __table_args__ = {"extend_existing": True}

    # Columns
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # Foreign key: One user can have multiple email addresses.
    user = db.Column(db.String(50), db.ForeignKey("users.username"))

    email = db.Column(db.String(255), unique=True, nullable=False)
    primary = db.Column(db.Boolean, unique=False, nullable=False, default=False)

    def __repr__(self):
        """Called by print, creates representation of object"""

        return f"<Email {self.email}>"


class File(db.Model):
    """Data model for files."""

    # Table setup
    __tablename__ = "files"
    __table_args__ = {"extend_existing": True}

    # Columns
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # Foreign keys: One project can have many files
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), index=True)

    public_id = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.Text, unique=False, nullable=False)
    name_in_bucket = db.Column(db.Text, unique=False, nullable=False)
    subpath = db.Column(db.Text, unique=False, nullable=False)
    size_original = db.Column(db.BigInteger, unique=False, nullable=False)
    size_stored = db.Column(db.BigInteger, unique=False, nullable=False)
    compressed = db.Column(db.Boolean, nullable=False)
    public_key = db.Column(db.String(64), unique=False, nullable=False)
    salt = db.Column(db.String(16), unique=False, nullable=False)
    checksum = db.Column(db.String(64), unique=False, nullable=False)
    time_latest_download = db.Column(db.DateTime(), unique=False, nullable=True)
    expires = db.Column(
        db.DateTime(),
        unique=False,
        nullable=False,
        default=dds_web.utils.current_time() + datetime.timedelta(days=30),
    )

    # Relationships
    versions = db.relationship("Version", backref="file")

    def __repr__(self):
        """Called by print, creates representation of object"""

        return f"<File {self.public_id}>"


class ExpiredFile(db.Model):
    """Data model for expired files. Moved here when in system for more than a month."""

    # Table setup
    __tablename__ = "expired_files"
    __table_args__ = {"extend_existing": True}

    # Columns
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    public_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.Text, unique=False, nullable=False)
    name_in_bucket = db.Column(db.Text, unique=False, nullable=False)
    subpath = db.Column(db.Text, unique=False, nullable=False)
    size_original = db.Column(db.BigInteger, unique=False, nullable=False)
    size_stored = db.Column(db.BigInteger, unique=False, nullable=False)
    compressed = db.Column(db.Boolean, nullable=False)
    public_key = db.Column(db.String(64), unique=False, nullable=False)
    salt = db.Column(db.String(50), unique=False, nullable=False)
    checksum = db.Column(db.String(64), unique=False, nullable=False)
    time_latest_download = db.Column(db.DateTime(), unique=False, nullable=True)
    expired = db.Column(
        db.DateTime(),
        unique=False,
        nullable=False,
        default=dds_web.utils.current_time(),
    )

    # Foreign keys
    # One project can have many files
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"))

    def __repr__(self):
        """Called by print, creates representation of object"""

        return f"<ExpiredFile {self.public_id}>"


class Version(db.Model):
    """Data model for keeping track of all active and non active files. Used for invoicing."""

    # Table setup
    __tablename__ = "versions"
    __table_args__ = {"extend_existing": True}

    # Columns
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # Foreign key - One project can have many files
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"))

    # Foreign key - One file can have many rows in invoicing
    active_file = db.Column(
        db.Integer, db.ForeignKey("files.id", ondelete="SET NULL"), nullable=True
    )

    size_stored = db.Column(db.BigInteger, unique=False, nullable=False)
    time_uploaded = db.Column(
        db.DateTime(), unique=False, nullable=False, default=dds_web.utils.current_time()
    )
    time_deleted = db.Column(db.DateTime(), unique=False, nullable=True, default=None)
    time_invoiced = db.Column(db.DateTime(), unique=False, nullable=True, default=None)

    def __repr__(self):
        """Called by print, creates representation of object"""

        return f"<File Version {self.id}>"
