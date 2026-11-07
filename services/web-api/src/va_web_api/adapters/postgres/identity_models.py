"""Schema ``identity``: Konten, Anmeldungen und Sitzungen des web-api (D1.1, ADR-0012).

Persoenliche Daten: Nur die Rolle ``va_identity`` liest und schreibt hier, ``va_read`` und
``va_app`` bekommen nichts (``identity`` steht nicht in ``SCHEMAS`` von ``va_platform.db.ddl``).
Alles nur zum Anfuegen: Name, Mail und Status aendern sich als neue Zeile, gueltig ist die
juengste. Von einer Sitzung steht nur der SHA-256 ihrer ID hier, nie der Wert aus dem Cookie.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Identity, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from va_platform.db import Base, in_values
from va_platform.messaging import InboxMixin, OutboxMixin, outbox_table_args

from ...identity.domain import LOGIN_REASONS, REVOKE_REASONS, ROLES, STATUSES

SCHEMA = "identity"


class UserAccount(Base):
    __tablename__ = "user_account"
    __table_args__ = (
        CheckConstraint(in_values("role", ROLES), name="role"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    username: Mapped[str] = mapped_column(Text, unique=True)
    role: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class UserProfileVersion(Base):
    __tablename__ = "user_profile_version"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.user_account.id"), index=True)
    display_name: Mapped[str | None]
    email: Mapped[str | None]
    email_confirmed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class UserStatus(Base):
    __tablename__ = "user_status"
    __table_args__ = (
        CheckConstraint(in_values("status", STATUSES), name="status"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.user_account.id"), index=True)
    status: Mapped[str]
    reason: Mapped[str | None]
    at: Mapped[datetime] = mapped_column(server_default=func.now())


class PasswordCredential(Base):
    __tablename__ = "password_credential"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.user_account.id"), index=True)
    hash: Mapped[str]  # scrypt$n$r$p$salt$hash
    must_change: Mapped[bool] = mapped_column(server_default="false")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Session(Base):
    __tablename__ = "session"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id_hash: Mapped[str] = mapped_column(Text, primary_key=True)  # SHA-256 der Cookie-ID
    user_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.user_account.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]  # absolutes Ende
    user_agent: Mapped[str | None]
    ip: Mapped[str | None]


class SessionSeen(Base):
    """Aktivitaet einer Sitzung, hoechstens alle 10 Minuten eine Zeile."""

    __tablename__ = "session_seen"
    __table_args__ = (
        Index("ix_session_seen_id_hash_seen_at", "id_hash", "seen_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    id_hash: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.session.id_hash"))
    seen_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SessionRevocation(Base):
    __tablename__ = "session_revocation"
    __table_args__ = (
        CheckConstraint(in_values("reason", REVOKE_REASONS), name="reason"),
        {"schema": SCHEMA},
    )

    id_hash: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.session.id_hash"), primary_key=True)
    reason: Mapped[str]
    at: Mapped[datetime] = mapped_column(server_default=func.now())


class LoginEvent(Base):
    """Jeder Anmeldeversuch, ohne Passwort. Grundlage der Sperre (NUT-06)."""

    __tablename__ = "login_event"
    __table_args__ = (
        CheckConstraint(in_values("reason", LOGIN_REASONS), name="reason"),
        Index("ix_login_event_username_at", "username", "at"),
        Index("ix_login_event_ip_at", "ip", "at"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    username: Mapped[str]
    user_id: Mapped[int | None]  # bewusst ohne Fremdschluessel: auch unbekannte Namen
    ip: Mapped[str | None]
    ok: Mapped[bool]
    reason: Mapped[str]
    at: Mapped[datetime] = mapped_column(server_default=func.now())


class IdentityInbox(InboxMixin, Base):
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012


class IdentityOutbox(OutboxMixin, Base):
    """Ab D1.6 die Bestaetigungsmail (``priv.va.identity.email_confirmation.requested``)."""

    __table_args__ = outbox_table_args(SCHEMA)


class EmailConfirmation(Base):
    """D1.6 (NUT-10): Anfrage, eine neue Adresse zu bestaetigen. Nur der SHA-256 des Tokens."""

    __tablename__ = "email_confirmation"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.user_account.id"), index=True)
    email: Mapped[str]
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class EmailConfirmationUsed(Base):
    """D1.6: Der Link wurde benutzt; einmalig, deshalb ist das Token der Schluessel."""

    __tablename__ = "email_confirmation_used"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    token_hash: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA}.email_confirmation.token_hash"), primary_key=True
    )
    at: Mapped[datetime] = mapped_column(server_default=func.now())


class ErasureLog(Base):
    """D1.6 (ADR-0012): Das Loeschkommando lief. Ohne Inhalte: nur der Hash der Nutzer-ID, wer
    loeschte und wie viele Zeilen je Tabelle."""

    __tablename__ = "erasure_log"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    user_key: Mapped[str]  # SHA-256 der Nutzer-ID
    by_admin: Mapped[str]
    rows: Mapped[dict[str, int]] = mapped_column(JSONB)
    at: Mapped[datetime] = mapped_column(server_default=func.now())
