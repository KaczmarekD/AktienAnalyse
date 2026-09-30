# Scoring-Profile im UI

> **Status:** Plan (30.09.2026). Tabellen in Phase 2b, Editor mit Vorschau ab Phase 3, siehe
> [Roadmap](roadmap.md). Entscheidung: [ADR-0009](../adr/0009-scoring-profile-in-der-db.md).

## Ziel

Die Gewichtung und die Schwellen des Scorings sollen im UI anpassbar sein, ohne Deployment. Jede
Änderung muss nachvollziehbar und umkehrbar sein, und jedes Ranking muss sich später mit genau
den Parametern reproduzieren lassen, mit denen es entstanden ist.

## Datenmodell

- Profile gehören dem `scoring`-Service.
- Jedes Speichern erzeugt eine **neue, unveränderliche Version**. Genau eine Version ist aktiv,
  und zwar die jüngste Zeile der Aktivierungs-Tabelle ([datenhaltung.md](datenhaltung.md)).
- Jeder Bewertungslauf speichert, mit welcher Profil-Version er gerechnet wurde. Zurückrollen
  heißt: eine ältere Version aktivieren.
- Die heutigen ENV-Werte (`VALUE_WEIGHT`, `QUALITY_WEIGHT`, `MIN_MARKET_CAP`) legen einmalig das
  Profil „Standard“ an. Danach gilt, was in der Datenbank steht.
- Die Mail nennt im Footer Profil und Version.

## Parameter

Die Standardwerte entsprechen dem heutigen `ScoringConfig`:

| Parameter | Standard | Regel |
|---|---|---|
| `value_weight` | 0.6 | 0–1. Die Quality-Gewichtung ist `1 − value_weight`, im UI ein einziger Schieberegler. Die Normierung in `Settings` entfällt damit. |
| `min_market_cap` | 300 000 000 | ≥ 0 (EUR) |
| `min_value_factor_share` | 0.5 | 0–1: Mindestanteil vorhandener Value-Faktoren |
| `min_quality_factor_share` | 0.5 | 0–1: Mindestanteil vorhandener Quality-Faktoren |
| `value_trap_value_threshold` | 0.70 | 0–1 |
| `value_trap_quality_threshold` | 0.30 | 0–1 |
| `drop_negative_value_metrics` | an | negative Multiples aus dem Value-Ranking ausschließen |
| `value_factors` | EV/EBIT, P/B, P/FCF, Shareholder Yield | Teilmenge des Katalogs, mindestens 2 aktiv |
| `quality_factors` | ROIC, FCF-Marge, Operating Margin, Net Debt/EBITDA, Earnings Stability | Teilmenge des Katalogs, mindestens 2 aktiv |

**Bewusst nicht änderbar** sind der Faktor-Katalog selbst und die Richtung jedes Faktors (ob ein
hoher oder niedriger Wert besser ist). Neue Faktoren bleiben Code-Änderungen nach dem Ablauf in
[CLAUDE.md](../../CLAUDE.md). Das UI zeigt zu jedem Faktor Methodik-Hinweise an, etwa warum das
KGV fehlt oder warum negative Multiples ausgeschlossen werden.

```python
ValueFactor = Literal["ev_ebit", "pb", "p_fcf", "shareholder_yield"]
QualityFactor = Literal[
    "roic", "fcf_margin", "operating_margin", "net_debt_ebitda", "earnings_stability"
]


class ScoringProfileParams(BaseModel):
    value_weight: float = Field(0.6, ge=0, le=1)
    min_market_cap: float = Field(300_000_000, ge=0)
    min_value_factor_share: float = Field(0.5, ge=0, le=1)
    min_quality_factor_share: float = Field(0.5, ge=0, le=1)
    value_trap_value_threshold: float = Field(0.70, ge=0, le=1)
    value_trap_quality_threshold: float = Field(0.30, ge=0, le=1)
    drop_negative_value_metrics: bool = True
    value_factors: set[ValueFactor] = Field(default_factory=lambda: set(get_args(ValueFactor)))
    quality_factors: set[QualityFactor] = Field(
        default_factory=lambda: set(get_args(QualityFactor))
    )

    @property
    def quality_weight(self) -> float:
        return 1.0 - self.value_weight

    @model_validator(mode="after")
    def _min_two_factors(self) -> Self:
        # _composite_mean braucht mindestens 2 vorhandene Faktoren je Gruppe
        if len(self.value_factors) < 2 or len(self.quality_factors) < 2:
            raise ValueError("je Gruppe mindestens 2 aktive Faktoren")
        return self
```

## Ablauf im UI

1. **Bearbeiten mit Live-Vorschau:** Jede Änderung im Formular geht nach 300 ms Pause als
   `POST /api/v1/scoring/preview` an das web-api und von dort als `rpc.va.scoring.preview` an
   `scoring`. Zurück kommt das Ranking samt Vergleich mit dem aktiven Profil: Rangänderungen,
   neue oder weggefallene Titel in den Top 20, geänderte Value-Trap-Markierungen. Dabei wird
   nichts gespeichert.
2. **Speichern:** Es entsteht eine neue Version. Das UI sendet per `If-Match` mit, auf welcher
   Version die Änderung beruht. Hat ein anderer Tab inzwischen gespeichert, antwortet der Server
   mit `409`, und das UI bietet Neuladen an.
3. **Aktivieren:** `scoring` hängt eine Aktivierung an und sendet
   `va.scoring.profile.activated`. Der Eventmanager verteilt das per WebSocket an alle offenen
   Tabs. Danach bewertet `scoring` den letzten Snapshot neu (`trigger=rescore`), und das Ranking
   im UI aktualisiert sich live. `notification` ignoriert solche Rescores, es gibt also keine
   zusätzliche Mail.

**Performance:** `score()` braucht für 110 Werte auf einem Ryzen (Zen 3) 8,5 ms (gemessen am
30.09.2026). Auf dem J4125 sind etwa 25–35 ms zu erwarten, die Vorschau wirkt also sofort.

## Validierung aus einer Quelle

Die Regeln stehen genau einmal in Pydantic. Daraus entsteht die Prüfung im Browser automatisch:

```
Pydantic (Field(ge=0, le=1), Literal-Faktoren)
  → OpenAPI (minimum/maximum, enum)
  → @hey-api/openapi-ts mit Zod-v4-Plugin
  → validateStandardSchema() in Angular Signal Forms
```

Browser und Server prüfen damit identisch. Regeln über mehrere Felder hinweg (z. B. „mindestens
2 aktive Faktoren je Gruppe“) stehen im `model_validator` und landen nicht in der
OpenAPI-Beschreibung. Die Vorschau meldet sie als `422`, und das Formular zeigt sie am
passenden Feld an.

## Auswirkungen auf die Konventionen

- „Konfiguration kommt aus Pydantic Settings“ gilt weiter für alles, was vom Deployment abhängt
  (Verbindungen, Secrets, Zeitplan). Die fachlichen Scoring-Parameter wandern in die Profile.
- „Magic Numbers in `scoring.py` gehören in `ScoringConfig`“ wird zu „… gehören in
  `ScoringProfileParams`“. Neue Schwellen bekommen dort einen Standardwert, und bestehende Profile
  erhalten ihn per Migration.
