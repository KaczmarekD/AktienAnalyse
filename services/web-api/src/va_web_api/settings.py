"""Settings des web-api: nur was das web-api braucht, mit eigenem Praefix ``WEB_API_``.

Die Zugangsdaten des Batches (``DATABASE_URL``, SMTP) sieht das web-api nie. Es liest mit der
Rolle ``va_read`` (U4, docs/architecture/umgebungen.md) und speichert Scoring-Profile mit der
Rolle ``va_profiles`` (P3.3), die nur in die Profil-Tabellen anfuegen darf. Die Projektionen
(P4.4) schreibt es mit der Rolle ``va_web`` ins Schema ``web``, gespeist aus NATS. Mit derselben
Rolle legt es seit P4.7 Runs in ``batch.run`` an (Start aus dem UI, Scheduler, Watchdog). Konten
und Sitzungen (D1.1) liegen im Schema ``identity`` und gehen nur ueber die Rolle ``va_identity``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from va_platform.tracing import Exporter

from .identity.domain import SessionPolicy
from .runs import Schedule, WatchdogLimits


class WebApiSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WEB_API_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # postgresql+psycopg://va_read:<pw>@db:5432/value_analyzer
    database_url: SecretStr = Field(min_length=1)
    # postgresql+psycopg://va_profiles:<pw>@db:5432/value_analyzer - ohne: Speichern ergibt 503
    profiles_database_url: SecretStr | None = None
    # P4.4: Event-Consumer fuer die Projektionen. Nur mit beidem, sonst laeuft die App ohne.
    # nats://nats:4222
    nats_url: str | None = None
    # postgresql+psycopg://va_web:<pw>@db:5432/value_analyzer
    projections_database_url: SecretStr | None = None
    # P4.5: erlaubte Herkunft fuer den WebSocket, durch Komma getrennt (kein JSON), etwa
    # "http://nas:8080, http://nas.fritz.box:8080". Leer: nur dieselbe Herkunft wie der Host.
    allowed_origins: str = ""
    # P4.7: Cron-Ausdruck fuer geplante Runs, ausgewertet in schedule_timezone. Leer: aus. Bis
    # P5.4 startet der Cron im Batch-Container die Wochenlaeufe; beides zugleich gaebe zwei Runs.
    schedule: str = ""
    schedule_timezone: str = "Europe/Berlin"
    # P4.7: So lange darf eine Stufe dauern, dann meldet der Watchdog den Run als gescheitert
    watchdog_fetch_minutes: float = Field(default=45, gt=0)
    watchdog_scoring_minutes: float = Field(default=5, gt=0)
    watchdog_report_minutes: float = Field(default=5, gt=0)
    # P5.5: "console" schreibt die Spans der Runs ins Log; die Services haben dasselbe Feld
    otel_traces_exporter: Exporter = "none"
    # D1.1: Konten und Sitzungen (Schema identity, Rolle va_identity). Ohne: Anmelden ergibt 503
    # postgresql+psycopg://va_identity:<pw>@db:5432/value_analyzer
    identity_database_url: SecretStr | None = None
    # D1.1: Sitzungs-Cookie nur ueber HTTPS (Name __Host-va_session). False nur lokal und im
    # E2E-Stack, die HTTP sprechen; dann heisst es va_session
    cookie_secure: bool = True
    # D1.1: Sitzung endet nach so vielen Stunden ohne Aktivitaet, spaetestens nach so vielen Tagen
    session_idle_hours: float = Field(default=12, gt=0)
    session_max_days: float = Field(default=30, gt=0)

    @model_validator(mode="after")
    def _schedule_is_valid(self) -> Self:
        _ = self.run_schedule  # ungueltiger Ausdruck oder Zeitzone: ValueError beim Start
        return self

    @property
    def run_schedule(self) -> Schedule | None:
        expression = self.schedule.strip()
        return Schedule(expression, self.schedule_timezone) if expression else None

    @property
    def watchdog_limits(self) -> WatchdogLimits:
        return WatchdogLimits(
            fetch=timedelta(minutes=self.watchdog_fetch_minutes),
            scoring=timedelta(minutes=self.watchdog_scoring_minutes),
            report=timedelta(minutes=self.watchdog_report_minutes),
        )

    @property
    def session_policy(self) -> SessionPolicy:
        return SessionPolicy(
            idle=timedelta(hours=self.session_idle_hours),
            absolute=timedelta(days=self.session_max_days),
        )

    @property
    def cookie_name(self) -> str:
        # __Host-: nur mit Secure, Pfad / und ohne Domain; der Browser bindet es an genau diesen Host
        return "__Host-va_session" if self.cookie_secure else "va_session"

    @property
    def origins(self) -> frozenset[str]:
        return frozenset(
            part.strip().rstrip("/").lower()
            for part in self.allowed_origins.split(",")
            if part.strip()
        )
